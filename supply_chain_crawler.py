"""
supply_chain_crawler.py — Semiconductor Supply Chain Data Crawler
=================================================================
Crawls and stores product-level supply chain metrics for GPU, CPU, and RAM:

  Data Source          Metric(s)                        Frequency
  ─────────────────────────────────────────────────────────────────
  PassMark (web)       Price Index, Perf Score           Weekly
  Newegg (web)         Price Index, Estimated Delivery   Weekly
  Steam HW Survey      Sales Volume proxy (GPU only)     Monthly
  SEMI website         Order Volume (B2B ratio)          Monthly
  Curated (earnings)   Mfr Capacity, Mfr Occupancy       Quarterly
  Curated (TrendForce) DRAM/HBM Spot Prices              Monthly

Run:
    python supply_chain_crawler.py           # all sources
    python supply_chain_crawler.py --quick   # skip slow PassMark/Newegg scraping
"""

import argparse
import json
import logging
import re
import sqlite3
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from config import DB_PATH, REQUEST_DELAY_SECONDS, now_hkt as _now_hkt
from products_config import (
    ALL_PRODUCTS,
    CPU_ENTERPRISE_PRODUCTS,
    CPU_PRODUCTS,
    CURATED_CAPACITY,
    CURATED_DEMAND_INDICATORS,
    CURATED_DRAM_SPOT,
    CURATED_RETAIL_PRICES,
    CURATED_SEMI_BTB,
    CURATED_STEAM_SURVEY,
    ENTERPRISE_PRODUCT_LAUNCHES,
    GPU_PRODUCTS,
    NEWEGG_PRODUCTS,
    RAM_PRODUCTS,
    SRC_PUBLISHED,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── HTTP session with browser-like headers ────────────────────────────────────
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})

TODAY = _now_hkt().strftime("%Y-%m-%d")
THIS_MONTH = _now_hkt().strftime("%Y-%m")


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE — supply-chain schema extension
# ══════════════════════════════════════════════════════════════════════════════

def init_supply_chain_db(conn: sqlite3.Connection) -> None:
    """Add supply-chain tables to the existing database (idempotent)."""
    conn.executescript("""
        PRAGMA journal_mode=WAL;

        -- Product master (GPU / CPU / RAM)
        CREATE TABLE IF NOT EXISTS sc_products (
            model_id        TEXT PRIMARY KEY,
            category        TEXT,           -- GPU | CPU | RAM
            name            TEXT,
            brand           TEXT,
            process_node    TEXT,
            manufacturer    TEXT,
            msrp_usd        REAL,
            specs_json      TEXT            -- full spec dict as JSON
        );

        -- Price Index (retail prices from Newegg / PassMark)
        CREATE TABLE IF NOT EXISTS sc_prices (
            model_id        TEXT    NOT NULL,
            date            TEXT    NOT NULL,
            source          TEXT    NOT NULL,   -- newegg | passmark
            price_usd       REAL,
            passmark_score  REAL,               -- performance score (PassMark only)
            price_perf      REAL,               -- score / USD (PassMark only)
            in_stock        INTEGER,            -- 1=yes 0=no NULL=unknown
            PRIMARY KEY (model_id, date, source)
        );

        -- Sales Volume proxy (GPU market share from Steam Hardware Survey)
        CREATE TABLE IF NOT EXISTS sc_market_share (
            model_name      TEXT    NOT NULL,   -- raw name from Steam survey
            period          TEXT    NOT NULL,   -- YYYY-MM
            share_pct       REAL,               -- % of Steam users
            source          TEXT    DEFAULT 'Steam HW Survey',
            PRIMARY KEY (model_name, period)
        );

        -- Order Volume indicator (SEMI NA Equipment Book-to-Bill)
        CREATE TABLE IF NOT EXISTS sc_semi_btb (
            period          TEXT    PRIMARY KEY,    -- YYYY-MM
            btb_ratio       REAL,
            source          TEXT
        );

        -- DRAM / HBM spot prices
        CREATE TABLE IF NOT EXISTS sc_dram_spot (
            product_type    TEXT    NOT NULL,   -- DDR4 | DDR5 | HBM3E | ...
            spec_label      TEXT    NOT NULL,
            period          TEXT    NOT NULL,   -- YYYY-MM
            price_usd       REAL,
            source          TEXT,
            PRIMARY KEY (product_type, spec_label, period)
        );

        -- Manufacturer capacity & utilisation
        CREATE TABLE IF NOT EXISTS sc_capacity (
            company         TEXT    NOT NULL,
            segment         TEXT    NOT NULL,   -- Foundry | Memory
            product_type    TEXT    NOT NULL,
            period          TEXT    NOT NULL,   -- YYYY-Qn
            capacity_kwpm   REAL,               -- 1000s of 300mm-eq wafers/month
            utilisation_pct REAL,
            source          TEXT,
            notes           TEXT,
            PRIMARY KEY (company, product_type, period)
        );

        -- Macro demand indicators (BACKLOG SC-06 / SC-00 fix B).
        -- Unified table for four free, authoritative series with different
        -- cadences/units rather than one bespoke table per source:
        --   tsmc_revenue / umc_revenue            monthly, NT$B  (live crawl)
        --   korea_chip_exports_20d                ~3x/month, USD B (curated)
        --   wsts_billings                         monthly, USD B (curated)
        --   semi_wwsems_billings                  quarterly, USD B (curated;
        --                                          replaces sc_semi_btb)
        CREATE TABLE IF NOT EXISTS sc_demand_indicators (
            indicator_key   TEXT    NOT NULL,   -- tsmc_revenue | umc_revenue | ...
            metric_label    TEXT    NOT NULL,
            period          TEXT    NOT NULL,   -- YYYY-MM or YYYY-Qn
            period_type     TEXT    NOT NULL,   -- month | quarter
            value           REAL,
            unit            TEXT,
            yoy_pct         REAL,
            seq_pct         REAL,               -- MoM (month) or QoQ (quarter)
            source          TEXT,
            notes           TEXT,
            PRIMARY KEY (indicator_key, period)
        );
    """)
    conn.commit()
    log.info("Supply-chain DB tables ready.")


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCT CATALOG LOADER
# ══════════════════════════════════════════════════════════════════════════════

def load_product_catalog(conn: sqlite3.Connection) -> None:
    rows = []
    for model_id, p in ALL_PRODUCTS.items():
        rows.append((
            model_id,
            p.get("category", ""),
            p.get("name", model_id),
            p.get("brand", ""),
            p.get("node", p.get("process_node", "")),
            p.get("manufacturer", ""),
            p.get("msrp_usd"),
            json.dumps(p),
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO sc_products VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    log.info("Product catalog loaded — %d products.", len(rows))


# ══════════════════════════════════════════════════════════════════════════════
# CURATED DATA LOADERS
# ══════════════════════════════════════════════════════════════════════════════

def load_curated_capacity(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO sc_capacity VALUES (?,?,?,?,?,?,?,?)",
        CURATED_CAPACITY,
    )
    conn.commit()
    log.info("Capacity data loaded — %d rows.", len(CURATED_CAPACITY))


def load_curated_dram_spot(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO sc_dram_spot VALUES (?,?,?,?,?)",
        CURATED_DRAM_SPOT,
    )
    conn.commit()
    log.info("DRAM spot prices loaded — %d rows.", len(CURATED_DRAM_SPOT))


def load_curated_retail_prices(conn: sqlite3.Connection) -> None:
    """
    Load curated monthly retail price history for GPU, CPU, and RAM models into
    sc_prices with source='curated'.  These rows give the chart panels historical
    depth that PassMark/Newegg live crawls cannot provide (live crawls only record
    the current day's price).  Existing curated rows are replaced on each run so
    corrections in products_config.py propagate automatically.
    """
    conn.executemany(
        "INSERT OR REPLACE INTO sc_prices VALUES (?,?,?,?,?,?,?)",
        CURATED_RETAIL_PRICES,
    )
    conn.commit()
    log.info("Curated retail prices loaded — %d rows.", len(CURATED_RETAIL_PRICES))


def purge_null_price_rows(conn: sqlite3.Connection) -> None:
    """
    Delete contentless rows from sc_prices (BACKLOG SC-01).

    Before the write-guard in crawl_newegg(), a failed scrape still persisted a row
    with price_usd IS NULL. Those rows inflate COUNT(*) so /api/db-stats reports a
    dead scraper as healthy. Deleting them is safe: PK is (model_id, date, source)
    and every affected row carries no data.

    Idempotent — runs on every deploy via --curated-only; a no-op once clean.
    """
    n = conn.execute(
        "DELETE FROM sc_prices WHERE price_usd IS NULL AND passmark_score IS NULL"
    ).rowcount
    conn.commit()
    if n:
        log.warning("Purged %d contentless sc_prices rows (NULL price + NULL score).", n)


def load_curated_semi_btb(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO sc_semi_btb VALUES (?,?,?)",
        CURATED_SEMI_BTB,
    )
    conn.commit()
    log.info("B2B data loaded — %d rows (MODELLED ESTIMATES, not a SEMI publication; "
             "see BACKLOG SC-00).", len(CURATED_SEMI_BTB))


def load_curated_demand_indicators(conn: sqlite3.Connection) -> None:
    """Seed sc_demand_indicators (BACKLOG SC-06 / SC-00 fix B).

    All rows are SRC_PUBLISHED — transcribed from TSMC/UMC IR, Korea MOTIE,
    WSTS/SIA, and SEMI WWSEMS releases, not modeled. tsmc_revenue and
    umc_revenue get supplemented by a live crawl (crawl_tsmc_revenue /
    crawl_umc_revenue below); the other three are curated-only pending a
    stable source page — see the note in products_config.py.
    """
    conn.executemany(
        "INSERT OR REPLACE INTO sc_demand_indicators VALUES (?,?,?,?,?,?,?,?,?,?)",
        CURATED_DEMAND_INDICATORS,
    )
    conn.commit()
    log.info("Demand indicators loaded — %d rows.", len(CURATED_DEMAND_INDICATORS))


def load_curated_steam_survey(conn: sqlite3.Connection) -> None:
    """Seed sc_market_share with curated Steam HW Survey GPU share data.

    The Steam HW Survey page is JS-rendered, so a plain HTTP GET rarely returns
    the JSON payload.  This curated seed guarantees the GPU chart always has data;
    the live crawl in crawl_steam_survey() supplements with fresher data when it
    succeeds.
    """
    conn.executemany(
        "INSERT OR REPLACE INTO sc_market_share VALUES (?,?,?,?)",
        CURATED_STEAM_SURVEY,
    )
    conn.commit()
    log.info("Steam HW Survey curated seed loaded — %d GPU entries.", len(CURATED_STEAM_SURVEY))


# ══════════════════════════════════════════════════════════════════════════════
# LIVE SOURCE 1 — PassMark (Price Index + Performance Score)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_passmark_page(url: str) -> list[dict]:
    """
    Parse the PassMark benchmark list page.
    The data is embedded as a JavaScript array:
        var data = [["Name", score, price, ...], ...]
    Returns a list of dicts: {name, score, price_usd}
    """
    try:
        resp = SESSION.get(url, timeout=20)
        resp.raise_for_status()
        html = resp.text

        # Extract the JS data array (two common variable names)
        patterns = [
            r"var\s+cpuData\s*=\s*(\[.*?\]);",
            r"var\s+gpuData\s*=\s*(\[.*?\]);",
            r"var\s+data\s*=\s*(\[.*?\]);",
            r"var\s+chartData\s*=\s*(\[.*?\]);",
        ]
        raw = None
        for pat in patterns:
            m = re.search(pat, html, re.DOTALL)
            if m:
                raw = m.group(1)
                break

        if not raw:
            # Fallback: parse the <table> if present
            return _parse_passmark_table(html)

        entries = json.loads(raw)
        results = []
        for row in entries:
            if not isinstance(row, list) or len(row) < 2:
                continue
            name  = str(row[0]).strip()
            score = float(row[1]) if row[1] else None
            price = float(row[2]) if len(row) > 2 and row[2] and row[2] != "NA" else None
            results.append({"name": name, "score": score, "price_usd": price})
        return results

    except Exception as exc:
        log.warning("PassMark fetch failed (%s): %s", url, exc)
        return []


def _parse_passmark_table(html: str) -> list[dict]:
    """Fallback: scrape the HTML table on PassMark list pages."""
    results = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", {"id": "cputable"}) or soup.find("table", {"id": "gputTable"})
        if not table:
            return []
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            name  = cells[0].get_text(strip=True)
            score = None
            price = None
            for cell in cells[1:]:
                txt = cell.get_text(strip=True).replace(",", "").replace("$", "")
                try:
                    val = float(txt)
                    if score is None:
                        score = val
                    else:
                        price = val
                        break
                except ValueError:
                    continue
            results.append({"name": name, "score": score, "price_usd": price})
    except Exception as exc:
        log.warning("PassMark table parse failed: %s", exc)
    return results


def _match_passmark_entry(entries: list[dict], keyword: str) -> dict | None:
    """Find the best PassMark entry matching a product keyword."""
    kw = keyword.lower()
    # Exact substring match first
    for e in entries:
        if kw in e["name"].lower():
            return e
    # Looser word-by-word match
    kw_words = set(kw.split())
    best, best_count = None, 0
    for e in entries:
        words = set(e["name"].lower().split())
        count = len(kw_words & words)
        if count > best_count:
            best, best_count = e, count
    return best if best_count >= 2 else None


def crawl_passmark(conn: sqlite3.Connection) -> None:
    """Crawl PassMark GPU and CPU lists; store price + score per product."""
    GPU_URL = "https://www.videocardbenchmark.net/gpu_list.php"
    CPU_URL = "https://www.cpubenchmark.net/cpu_list.php"

    log.info("PassMark — fetching GPU list …")
    gpu_entries = _fetch_passmark_page(GPU_URL)
    log.info("PassMark — fetched %d GPU entries.", len(gpu_entries))
    time.sleep(REQUEST_DELAY_SECONDS * 2)

    log.info("PassMark — fetching CPU list …")
    cpu_entries = _fetch_passmark_page(CPU_URL)
    log.info("PassMark — fetched %d CPU entries.", len(cpu_entries))

    rows = []
    for model_id, prod in {**GPU_PRODUCTS, **CPU_PRODUCTS}.items():
        kw = prod.get("passmark_kw")
        if kw is None:
            continue   # archived/legacy product — skip live PassMark scraping
        pool    = gpu_entries if prod["category"] == "GPU" else cpu_entries
        match   = _match_passmark_entry(pool, kw)
        if not match:
            log.debug("  PassMark — no match for %s", model_id)
            continue
        score = match["score"]
        price = match["price_usd"]
        pp    = round(score / price, 2) if score and price and price > 0 else None
        rows.append((model_id, TODAY, "passmark", price, score, pp, None))
        log.info("  PassMark %-22s  score=%-7s  price=$%s", model_id, score, price)

    conn.executemany(
        "INSERT OR REPLACE INTO sc_prices VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    log.info("PassMark — %d products stored.", len(rows))


# ══════════════════════════════════════════════════════════════════════════════
# LIVE SOURCE 2 — Newegg (Retail Price + In-Stock Status)
# ══════════════════════════════════════════════════════════════════════════════

def _newegg_search_price(query: str) -> tuple:
    """
    Scrape Newegg search results for a product query.
    Returns (price_usd, in_stock) or (None, None) on failure.
    Targets the first listed price in search results.
    """
    url = f"https://www.newegg.com/p/pl?d={query}&N=4131"
    try:
        resp = SESSION.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # JSON-LD structured data (most reliable)
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in ("Product", "ItemList"):
                        offers = item.get("offers") or item.get("Offers", {})
                        if isinstance(offers, dict):
                            price = offers.get("price") or offers.get("lowPrice")
                            avail = offers.get("availability", "")
                            in_stock = 1 if "InStock" in avail else (0 if avail else None)
                            if price:
                                return float(price), in_stock
            except Exception:
                continue

        # HTML fallback: first price in listing
        price_el = soup.select_one(".price-current strong, .price-current-label")
        if price_el:
            txt = re.sub(r"[^\d.]", "", price_el.get_text())
            price = float(txt) if txt else None
            oos = bool(soup.select_one(".btn-message-disabled, .txt-oos"))
            return price, 0 if oos else 1

        return None, None
    except Exception as exc:
        log.debug("Newegg search failed for '%s': %s", query, exc)
        return None, None


def crawl_newegg(conn: sqlite3.Connection) -> None:
    """Crawl Newegg retail prices and in-stock status for all catalogued products."""
    log.info("Newegg — crawling %d products …", len(NEWEGG_PRODUCTS))
    rows    = []
    misses  = 0
    for i, (model_id, prod) in enumerate(NEWEGG_PRODUCTS.items(), 1):
        query = prod["newegg_q"]
        price, in_stock = _newegg_search_price(query)
        status = "✓ ${:.0f}".format(price) if price else "—"
        stk    = {1: "In Stock", 0: "OOS", None: "?"}[in_stock]
        log.info("  [%d/%d] %-22s  price=%-10s  stock=%s",
                 i, len(NEWEGG_PRODUCTS), model_id, status, stk)

        # A parse failure must NOT be persisted. Writing a NULL-price row keeps
        # COUNT(*) climbing while the table holds nothing — /api/db-stats then
        # reports the scraper as healthy. A missing row is honest; a NULL row
        # is a lie. (BACKLOG SC-01)
        if price is None:
            misses += 1
            log.warning("  Newegg — no price parsed for %s; row skipped", model_id)
        else:
            rows.append((model_id, TODAY, "newegg", price, None, None, in_stock))

        time.sleep(REQUEST_DELAY_SECONDS * 3)   # respect Newegg rate limits

    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO sc_prices VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()

    total    = len(NEWEGG_PRODUCTS)
    miss_pct = (misses / total * 100) if total else 0.0
    log.info("Newegg — %d/%d products stored (%d skipped, %.0f%% miss rate).",
             len(rows), total, misses, miss_pct)
    if total and miss_pct >= 50:
        log.error(
            "NEWEGG SCRAPER LIKELY BROKEN — %.0f%% of %d products returned no price. "
            "Newegg serves JS-rendered listings behind bot detection; both the JSON-LD "
            "and .price-current parse paths in _newegg_search_price() may need replacing. "
            "See BACKLOG SC-01 / SC-06.",
            miss_pct, total,
        )


# ══════════════════════════════════════════════════════════════════════════════
# LIVE SOURCE 3 — Steam Hardware Survey (GPU Sales Volume Proxy)
# ══════════════════════════════════════════════════════════════════════════════

_STEAM_URL = "https://store.steampowered.com/hwsurvey/videocard/"

# The survey page repeats every GPU in several tables: one overall table
# ("ALL VIDEO CARDS") and then one per DirectX class.  In the per-class tables
# the percentages are shares *within that class* — Intel HD Graphics 4000 shows
# ~28% under "DIRECTX 11 GPUS".  Scraping without respecting this boundary puts
# a decade-old iGPU at the top of the market-share chart.  (BACKLOG SC-02)
_STEAM_SECTION_START = "ALL VIDEO CARDS"
_STEAM_SECTION_END   = "DIRECTX 12 GPUS"

_STEAM_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june",
     "july", "august", "september", "october", "november", "december"], start=1)}

_PCT_RE   = re.compile(r"^[+-]?\d+(?:\.\d+)?%$")
_TITLE_RE = re.compile(r"Survey:\s*([A-Za-z]+)\s+(\d{4})")


def _parse_steam_survey(text: str) -> tuple:
    """
    Parse the visible text of the Steam HW Survey video-card page.

    Returns (period, [(model_name, share_pct), ...]).  `period` is the survey's
    OWN month ("YYYY-MM") taken from the page heading — never today's date, so a
    stale page can never be stamped as current (CLAUDE.md §7.3).

    Row shape on the page is:  NAME, <5 monthly values>, <MoM change>.
    The current month is therefore the SECOND-TO-LAST value in the run, not the
    last — the last column is the delta.
    """
    period = None
    m = _TITLE_RE.search(text)
    if m:
        mon = _STEAM_MONTHS.get(m.group(1).strip().lower())
        if mon:
            period = f"{int(m.group(2)):04d}-{mon:02d}"

    lines = [ln.strip().strip("*").strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    # Restrict to the overall table.
    try:
        i0 = next(i for i, ln in enumerate(lines) if _STEAM_SECTION_START in ln.upper())
    except StopIteration:
        return period, []
    i1 = next((i for i, ln in enumerate(lines[i0 + 1:], i0 + 1)
               if _STEAM_SECTION_END in ln.upper()), len(lines))
    lines = lines[i0 + 1:i1]

    out, name, run = [], None, []

    def _flush():
        # run = [JAN, FEB, MAR, APR, CURRENT, CHANGE]; take CURRENT.
        if name and len(run) >= 2:
            raw = run[-2].rstrip("%")
            try:
                pct = float(raw)
            except ValueError:
                return
            if 0 < pct <= 100 and name.upper() not in ("OTHER",):
                out.append((name, pct))

    for ln in lines:
        if _PCT_RE.match(ln) or ln == "-":
            run.append(ln)
        else:
            _flush()
            name, run = (ln if not ln.isupper() else None), []
    _flush()
    return period, out


def crawl_steam_survey(conn: sqlite3.Connection) -> None:
    """
    Fetch the Steam Hardware Survey GPU page and store model → % share.

    Validates before writing: a partial or mis-shaped parse must never overwrite
    the curated seed with garbage, and must never be silently accepted (the old
    version searched for a `"hardware":"…"` JSON blob the page does not contain,
    found nothing, and wrote zero rows without raising — the table then sat
    frozen for 17 months).  See BACKLOG SC-02.
    """
    log.info("Steam HW Survey — fetching GPU market share …")
    try:
        resp = SESSION.get(_STEAM_URL, timeout=25)
        resp.raise_for_status()
        text = BeautifulSoup(resp.text, "html.parser").get_text("\n")
    except Exception as exc:
        log.error("STEAM SURVEY FETCH FAILED: %s — curated seed retained.", exc)
        return

    period, entries = _parse_steam_survey(text)

    # ── Validation gates ──────────────────────────────────────────────────────
    problems = []
    if not period:
        problems.append("survey month not found in page heading")
    if len(entries) < 15:
        problems.append(f"only {len(entries)} GPU entries parsed (expected 15+)")
    total = sum(p for _, p in entries)
    if entries and not (40 <= total <= 105):
        problems.append(f"shares sum to {total:.1f}% (expected 40–105%)")

    if problems:
        log.error(
            "STEAM SURVEY PARSE REJECTED (%s) — page layout has likely changed. "
            "Curated seed retained; refresh CURATED_STEAM_SURVEY by hand and see "
            "BACKLOG SC-02.", "; ".join(problems),
        )
        return

    conn.executemany(
        "INSERT OR REPLACE INTO sc_market_share VALUES (?,?,?,?)",
        [(n, period, p, "Steam HW Survey") for n, p in entries],
    )
    conn.commit()
    log.info("Steam HW Survey — %d GPU entries stored for %s (shares sum %.1f%%).",
             len(entries), period, total)


# ══════════════════════════════════════════════════════════════════════════════
# LIVE SOURCE 4 — TSMC / UMC monthly revenue (BACKLOG SC-06)
# ══════════════════════════════════════════════════════════════════════════════
#
# Both IR pages were fetched and confirmed server-rendered plain HTML tables —
# not JS-only shells like Steam (SC-02) or a discontinued article search like
# SEMI B2B (SC-00). That confirmation is why these two get a live crawler while
# korea_chip_exports_20d / wsts_billings / semi_wwsems_billings do not: those
# three publish as one-off press articles or a members-only portal, with no
# stable per-period table to point a parser at.

_TSMC_MONTH_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?\s*\n+"
    r"\s*([\d,]{5,10})\s*\n+\s*([\-\d.]+)\s*%",
)
_TSMC_MONTH_NUM = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                    "Jul": 7, "Aug": 8, "Sept": 9, "Sep": 9, "Oct": 10,
                    "Nov": 11, "Dec": 12}


def _parse_tsmc_revenue(text: str, year: int) -> list:
    """
    Parse TSMC's monthly-revenue IR page (get_text("\n") linearization).

    Row shape per month is "Jan.\n401,255\n36.8%" (month, NT$ millions, YoY%);
    future months in the same-year table render as blank cells and simply
    don't match. Returns [(period, value_ntb, yoy_pct), ...] sorted by month,
    MoM ("seq_pct") computed here from consecutive rows since the page only
    publishes YoY.
    """
    rows = []
    for mon_abbr, raw_millions, yoy in _TSMC_MONTH_RE.findall(text):
        mon = _TSMC_MONTH_NUM.get(mon_abbr)
        if mon is None:
            continue
        try:
            value_ntb = float(raw_millions.replace(",", "")) / 1000.0
            yoy_pct = float(yoy)
        except ValueError:
            continue
        rows.append((mon, f"{year:04d}-{mon:02d}", value_ntb, yoy_pct))
    rows.sort(key=lambda r: r[0])
    out = []
    prev_value = None
    for _, period, value_ntb, yoy_pct in rows:
        seq_pct = ((value_ntb / prev_value - 1) * 100) if prev_value else None
        out.append((period, value_ntb, yoy_pct, seq_pct))
        prev_value = value_ntb
    return out


def crawl_tsmc_revenue(conn: sqlite3.Connection) -> None:
    """
    Fetch TSMC's IR monthly-revenue page for the current year and store it.

    Validates before writing (BACKLOG SC-01/SC-02 lesson): requires at least
    one parsed month with a revenue figure in TSMC's normal order of magnitude
    (NT$100B–NT$1000B) — a parse that finds nothing, or finds implausible
    numbers, must never overwrite the curated seed and must never fail
    silently.
    """
    year = int(_now_hkt().strftime("%Y"))
    url = f"https://investor.tsmc.com/english/monthly-revenue/{year}"
    log.info("TSMC monthly revenue — fetching %s …", url)
    try:
        resp = SESSION.get(url, timeout=25)
        resp.raise_for_status()
        text = BeautifulSoup(resp.text, "html.parser").get_text("\n")
    except Exception as exc:
        log.error("TSMC REVENUE FETCH FAILED: %s — curated seed retained.", exc)
        return

    parsed = _parse_tsmc_revenue(text, year)
    bad = [p for p in parsed if not (100 <= p[1] <= 1000)]
    if not parsed or bad:
        log.error(
            "TSMC REVENUE PARSE REJECTED (%s) — page layout has likely changed. "
            "Curated seed retained; refresh CURATED_DEMAND_INDICATORS by hand "
            "and see BACKLOG SC-06.",
            "no rows parsed" if not parsed else f"{len(bad)} implausible value(s)",
        )
        return

    conn.executemany(
        "INSERT OR REPLACE INTO sc_demand_indicators VALUES (?,?,?,?,?,?,?,?,?,?)",
        [("tsmc_revenue", "TSMC Monthly Revenue", period, "month", value, "NT$B",
          yoy, seq, SRC_PUBLISHED, "TSMC IR (live crawl)")
         for period, value, yoy, seq in parsed],
    )
    conn.commit()
    log.info("TSMC monthly revenue — %d month(s) stored, latest %s = NT$%.1fB.",
              len(parsed), parsed[-1][0], parsed[-1][1])


_UMC_ROW_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s*\n+"
    r"\s*([\d,]{5,12})\s*\n+\s*[\d,]{5,12}\s*\n+\s*[\-\d,]+\s*\n+\s*([\-\d.]+)\s*%",
)


def _parse_umc_revenue(text: str, year: int) -> list:
    """
    Parse UMC's monthly-sales-revenue IR page.

    Row shape per month is "Jan.\n<NT$'000 2026>\n<NT$'000 2025>\n<YoY change>\n
    <YoY %>" — five cells; UMC publishes YoY% itself so no MoM computation is
    needed for accuracy, but seq_pct (MoM) is still derived for consistency
    with tsmc_revenue.
    """
    rows = []
    for mon_abbr, raw_thousands, yoy in _UMC_ROW_RE.findall(text):
        mon = _TSMC_MONTH_NUM.get(mon_abbr)
        if mon is None:
            continue
        try:
            value_ntb = float(raw_thousands.replace(",", "")) / 1_000_000.0
            yoy_pct = float(yoy)
        except ValueError:
            continue
        rows.append((mon, f"{year:04d}-{mon:02d}", value_ntb, yoy_pct))
    rows.sort(key=lambda r: r[0])
    out = []
    prev_value = None
    for _, period, value_ntb, yoy_pct in rows:
        seq_pct = ((value_ntb / prev_value - 1) * 100) if prev_value else None
        out.append((period, value_ntb, yoy_pct, seq_pct))
        prev_value = value_ntb
    return out


def crawl_umc_revenue(conn: sqlite3.Connection) -> None:
    """
    Fetch UMC's IR monthly-sales-revenue page for the current year and store it.

    Same validation discipline as crawl_tsmc_revenue: UMC's monthly revenue
    runs roughly NT$15B–NT$30B; anything outside that band rejects the whole
    batch rather than writing a bad number.
    """
    year = int(_now_hkt().strftime("%Y"))
    url = "https://www.umc.com/en/IR_Financial/monthly_sales_revenue"
    log.info("UMC monthly revenue — fetching %s …", url)
    try:
        resp = SESSION.get(url, timeout=25)
        resp.raise_for_status()
        text = BeautifulSoup(resp.text, "html.parser").get_text("\n")
    except Exception as exc:
        log.error("UMC REVENUE FETCH FAILED: %s — curated seed retained.", exc)
        return

    parsed = _parse_umc_revenue(text, year)
    bad = [p for p in parsed if not (10 <= p[1] <= 50)]
    if not parsed or bad:
        log.error(
            "UMC REVENUE PARSE REJECTED (%s) — page layout has likely changed. "
            "Curated seed retained; refresh CURATED_DEMAND_INDICATORS by hand "
            "and see BACKLOG SC-06.",
            "no rows parsed" if not parsed else f"{len(bad)} implausible value(s)",
        )
        return

    conn.executemany(
        "INSERT OR REPLACE INTO sc_demand_indicators VALUES (?,?,?,?,?,?,?,?,?,?)",
        [("umc_revenue", "UMC Monthly Revenue", period, "month", value, "NT$B",
          yoy, seq, SRC_PUBLISHED, "UMC IR (live crawl)")
         for period, value, yoy, seq in parsed],
    )
    conn.commit()
    log.info("UMC monthly revenue — %d month(s) stored, latest %s = NT$%.1fB.",
              len(parsed), parsed[-1][0], parsed[-1][1])


# ══════════════════════════════════════════════════════════════════════════════
# LIVE SOURCE 5 — RETIRED: SEMI NA Book-to-Bill (see BACKLOG SC-00)
# ══════════════════════════════════════════════════════════════════════════════
#
# SEMI discontinued the North American Semiconductor Equipment Book-to-Bill
# report after the DECEMBER 2016 report; the NA billings press release also
# ceased in Feb-2022.  The former scraper here searched semi.org for a monthly
# "book to bill" press release that has not existed for ~9 years, failed
# silently every run, and left the hand-modelled CURATED_SEMI_BTB rows in place
# looking like live data.
#
# The live capex/order signal that DOES exist is the SEMI/SEAJ Worldwide
# Semiconductor Equipment Market Statistics (WWSEMS) QUARTERLY billings report
# (e.g. Q1 2026: $36.55B, +14% YoY).  Wiring that up is BACKLOG SC-00 fix B and
# needs a new `sc_equipment_billings` table — a schema change, which requires
# sign-off per CLAUDE.md §1 step 7.  Until then this is a no-op stub: better an
# empty series than an invented one.


def crawl_semi_btb(conn: sqlite3.Connection) -> None:
    """No-op. The source report was discontinued in 2016 — see the note above."""
    log.info(
        "SEMI B2B — crawler retired: the NA Book-to-Bill report was discontinued "
        "after Dec-2016. Existing sc_semi_btb rows are MODELLED ESTIMATES, not SEMI "
        "data. Replacement = SEMI WWSEMS quarterly billings (BACKLOG SC-00)."
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

def crawl_supply_chain(quick: bool = False, curated_only: bool = False) -> None:
    """
    Main entry point for supply-chain data collection.
    curated_only=True  loads only in-memory curated data — no network calls at all.
                       Idempotent (INSERT OR REPLACE); safe to run on every deploy.
    quick=True         skips PassMark + Newegg but still hits Steam / SEMI BTB.
    """
    conn = get_conn()
    init_supply_chain_db(conn)

    log.info("─── Step 1: Load product catalog ───────────────────────────")
    load_product_catalog(conn)

    log.info("─── Step 2: Load curated capacity & DRAM data ──────────────")
    load_curated_capacity(conn)
    load_curated_dram_spot(conn)
    load_curated_semi_btb(conn)
    load_curated_retail_prices(conn)
    load_curated_steam_survey(conn)   # seed Steam data; live crawl may overwrite
    load_curated_demand_indicators(conn)  # seed demand data; TSMC/UMC live crawl may overwrite
    purge_null_price_rows(conn)       # BACKLOG SC-01 — idempotent cleanup

    if curated_only:
        conn.close()
        log.info("✅  Curated data load complete (--curated-only; no network calls).")
        return

    log.info("─── Step 3: Live sources ────────────────────────────────────")
    if not quick:
        crawl_passmark(conn)
        time.sleep(REQUEST_DELAY_SECONDS * 2)
        crawl_newegg(conn)
        time.sleep(REQUEST_DELAY_SECONDS)
    else:
        log.info("  [--quick] Skipping PassMark + Newegg scraping.")

    crawl_steam_survey(conn)
    time.sleep(REQUEST_DELAY_SECONDS)
    crawl_semi_btb(conn)
    time.sleep(REQUEST_DELAY_SECONDS)
    crawl_tsmc_revenue(conn)
    time.sleep(REQUEST_DELAY_SECONDS)
    crawl_umc_revenue(conn)

    conn.close()
    log.info("✅  Supply chain crawl complete.")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Semiconductor Supply Chain Crawler")
    parser.add_argument(
        "--quick", action="store_true",
        help="Skip PassMark/Newegg scraping; still runs Steam + SEMI BTB network calls.",
    )
    parser.add_argument(
        "--curated-only", action="store_true",
        help="Load only in-memory curated data (zero network calls). "
             "Safe to run on every deploy — idempotent via INSERT OR REPLACE.",
    )
    args = parser.parse_args()
    crawl_supply_chain(quick=args.quick, curated_only=args.curated_only)
