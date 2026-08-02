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
from job_heartbeat import start_job, finish_job, JOB_CURATED   # QA F-01
from products_config import (
    ALL_PRODUCTS,
    CPU_ENTERPRISE_PRODUCTS,
    CPU_PRODUCTS,
    CURATED_FAB_METRICS,
    CURATED_DEMAND_INDICATORS,
    CURATED_DRAM_SPOT,
    CURATED_RETAIL_PRICES,
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

        -- Fab / manufacturer metrics — ONLY figures a company actually publishes
        -- (BACKLOG SC-11). Replaced sc_capacity, whose per-node capacity_kwpm and
        -- utilisation_pct were cited to earnings releases that never contained
        -- them. Generic (metric_key, detail) shape so a new disclosure is a new
        -- row, not a schema change.
        --
        -- metric_key vocabulary (extend deliberately):
        --   revenue_usd_b        quarterly net revenue          detail=''
        --   gross_margin_pct     quarterly gross margin         detail=''
        --   operating_margin_pct quarterly operating margin     detail=''
        --   wafer_shipments_kpcs 12-inch-equivalent wafers      detail=''
        --   node_revenue_pct     % of wafer revenue by node     detail='3nm'
        --   capex_usd_b          quarterly capital expenditure  detail=''
        --   utilisation_pct      ONLY where a company states it detail=''
        CREATE TABLE IF NOT EXISTS sc_fab_metrics (
            company         TEXT    NOT NULL,
            metric_key      TEXT    NOT NULL,
            detail          TEXT    NOT NULL DEFAULT '',
            period          TEXT    NOT NULL,   -- YYYY-Qn
            value           REAL,
            unit            TEXT,
            source          TEXT,               -- must NAME a document containing the figure
            notes           TEXT,
            PRIMARY KEY (company, metric_key, detail, period)
        );

        -- sc_semi_btb was DROPPED 2026-08-02 (BACKLOG SC-10) — see the drop
        -- statement after this script. Do not re-create it: the SEMI NA
        -- Book-to-Bill report was discontinued after Dec-2016 and the
        -- replacement is sc_demand_indicators[semi_wwsems_billings].

        -- DRAM / HBM spot prices
        CREATE TABLE IF NOT EXISTS sc_dram_spot (
            product_type    TEXT    NOT NULL,   -- DDR4 | DDR5 | HBM3E | ...
            spec_label      TEXT    NOT NULL,
            period          TEXT    NOT NULL,   -- YYYY-MM
            price_usd       REAL,
            source          TEXT,
            PRIMARY KEY (product_type, spec_label, period)
        );

        -- sc_capacity was DROPPED 2026-08-02 (BACKLOG SC-11) — see the drop
        -- statement after this script. Do not re-create it: per-node
        -- capacity_kwpm / utilisation_pct are published by no foundry, so the
        -- columns themselves invited the misattribution. Use sc_fab_metrics.

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

    # BACKLOG SC-10 — drop the retired SEMI NA Book-to-Bill table.
    #
    # SC-00 removed its panel and relabelled its 41 rows as modeled estimates, but
    # the rows kept loading on every deploy and kept appearing as a sheet in every
    # /api/export-xlsx workbook — a decade-dead indicator handed to readers with no
    # disclaimer attached to the file. Nothing in dashboard.py reads this table
    # (verified by grep before dropping), and it is deliberately absent from
    # _FRESHNESS_SPEC, so it was also unmonitored.
    #
    # Safe to drop rather than deprecate: every row originated in CURATED_SEMI_BTB,
    # which lives in git history, so this is fully reproducible — unlike the scraped
    # sc_prices / options_iv_history series, which are not (CLAUDE.md §5.1).
    # Idempotent: a no-op once the table is gone.
    _btb = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='sc_semi_btb'"
    ).fetchone()[0]
    if _btb:
        n = conn.execute("SELECT COUNT(*) FROM sc_semi_btb").fetchone()[0]
        conn.execute("DROP TABLE sc_semi_btb")
        log.warning(
            "Dropped retired table sc_semi_btb (%d rows) — SEMI discontinued the NA "
            "Book-to-Bill report after Dec-2016; replacement is "
            "sc_demand_indicators[semi_wwsems_billings]. See BACKLOG SC-10.", n
        )

    # BACKLOG SC-11 — drop sc_capacity, replaced by sc_fab_metrics.
    #
    # Every one of its 31 rows cited a named earnings release for per-NODE
    # capacity_kwpm and utilisation_pct. No foundry — TSMC, Samsung, Intel, SMIC —
    # discloses either at node granularity, so the citation named a document that
    # does not contain the figure. Same defect as SC-00, in a table SC-05 missed.
    #
    # Dropped rather than migrated: the columns themselves were the problem, so a
    # column rename (§7 rule 2) would have preserved the error in new clothing.
    # Reproducible from git like sc_semi_btb — the rows were 100 % curated.
    _cap = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='sc_capacity'"
    ).fetchone()[0]
    if _cap:
        n = conn.execute("SELECT COUNT(*) FROM sc_capacity").fetchone()[0]
        conn.execute("DROP TABLE sc_capacity")
        log.warning(
            "Dropped sc_capacity (%d rows) — per-node capacity/utilisation attributed to "
            "earnings releases that never published them. Replacement is sc_fab_metrics, "
            "which stores only figures companies actually disclose. See BACKLOG SC-11.", n
        )

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


# Source tag for rows written by crawl_trendforce_spot(). Must be an EXACT,
# stable string: load_curated_dram_spot()'s reconcile uses equality on it to
# decide what not to delete. Changing this string without changing that query
# deletes every live row on the next deploy.
SRC_LIVE_SPOT = "TrendForce spot page (live)"

# Prefix for rows written by crawl_tsmc_quarterly(). Matched with LIKE 'prefix%'
# by load_curated_fab_metrics()'s reconcile so the per-quarter suffix still
# resolves. Change this without changing that query and every crawled quarter is
# deleted on the next deploy (SC-14).
SRC_LIVE_TSMC_Q = "TSMC Quarterly Results IR page (live)"


# ══════════════════════════════════════════════════════════════════════════════
# CURATED DATA LOADERS
# ══════════════════════════════════════════════════════════════════════════════

def load_curated_fab_metrics(conn: sqlite3.Connection) -> None:
    """
    Load CURATED_FAB_METRICS, then reconcile (SC-14), scoped to exclude live rows.

    Live writer is crawl_tsmc_quarterly(), which tags rows SRC_LIVE_TSMC_Q. Same
    scoping requirement as load_curated_dram_spot(): an unscoped delete would wipe
    every crawled quarter on the next deploy, because startup.sh runs
    --curated-only on every boot.
    """
    conn.executemany(
        "INSERT OR REPLACE INTO sc_fab_metrics VALUES (?,?,?,?,?,?,?,?)",
        CURATED_FAB_METRICS,
    )
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _fab_keep (c TEXT, m TEXT, d TEXT, p TEXT)")
    conn.execute("DELETE FROM _fab_keep")
    conn.executemany(
        "INSERT INTO _fab_keep VALUES (?,?,?,?)",
        [(r[0], r[1], r[2], r[3]) for r in CURATED_FAB_METRICS],
    )
    n = conn.execute(
        """
        DELETE FROM sc_fab_metrics
         WHERE COALESCE(source, '') NOT LIKE ?
           AND (company, metric_key, detail, period) NOT IN
               (SELECT c, m, d, p FROM _fab_keep)
        """,
        (SRC_LIVE_TSMC_Q + "%",),
    ).rowcount
    conn.commit()
    log.info("Fab metrics loaded — %d rows.", len(CURATED_FAB_METRICS))
    if n:
        log.warning("Reconciled sc_fab_metrics — deleted %d withdrawn row(s). "
                    "Live-crawled rows untouched.", n)


def load_curated_dram_spot(conn: sqlite3.Connection) -> None:
    """
    Load CURATED_DRAM_SPOT, then RECONCILE — delete any sc_dram_spot row whose
    (product_type, spec_label, period) key is no longer in the curated list.

    Why the delete is mandatory (BACKLOG SC-14):
    INSERT OR REPLACE propagates *corrections* but never *withdrawals*. SC-04
    deleted 34 falsified DDR rows from products_config.py on 2026-08-02; because
    this loader only inserted, those rows survived on the Railway volume — prod
    reported 87 sc_dram_spot rows against 53 defined in git. The retraction was a
    no-op in production while reading as done in the repo, which is the worst
    possible combination: the falsified series stayed on the chart.

    SCOPE (changed by SC-15 — read before editing): sc_dram_spot is no longer
    100 % curated. crawl_trendforce_spot() writes live rows tagged SRC_LIVE_SPOT,
    and those keys are deliberately absent from CURATED_DRAM_SPOT. The delete is
    therefore scoped to exclude them — an unscoped reconcile would wipe every
    live observation on the next deploy, because startup.sh runs --curated-only
    on every boot. This is the same scoping `load_curated_retail_prices()` needs
    for its PassMark/Newegg writers.
    """
    conn.executemany(
        "INSERT OR REPLACE INTO sc_dram_spot VALUES (?,?,?,?,?)",
        CURATED_DRAM_SPOT,
    )
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _dram_keep (pt TEXT, sl TEXT, pd TEXT)")
    conn.execute("DELETE FROM _dram_keep")
    conn.executemany(
        "INSERT INTO _dram_keep VALUES (?,?,?)",
        [(r[0], r[1], r[2]) for r in CURATED_DRAM_SPOT],
    )
    n = conn.execute(
        """
        DELETE FROM sc_dram_spot
         WHERE COALESCE(source, '') <> ?
           AND (product_type, spec_label, period) NOT IN
               (SELECT pt, sl, pd FROM _dram_keep)
        """,
        (SRC_LIVE_SPOT,),
    ).rowcount
    conn.commit()
    log.info("DRAM spot prices loaded — %d rows.", len(CURATED_DRAM_SPOT))
    if n:
        log.warning(
            "Reconciled sc_dram_spot — deleted %d withdrawn row(s) no longer in "
            "CURATED_DRAM_SPOT (see BACKLOG SC-14).", n
        )


def load_curated_retail_prices(conn: sqlite3.Connection) -> None:
    """
    Load curated monthly retail price history for GPU, CPU, and RAM models into
    sc_prices with source='curated'.  These rows give the chart panels historical
    depth that PassMark/Newegg live crawls cannot provide (live crawls only record
    the current day's price).  Existing curated rows are replaced on each run so
    corrections in products_config.py propagate automatically.

    Then RECONCILE, scoped to source='curated' (BACKLOG SC-14 / SC-09):
    INSERT OR REPLACE propagates corrections but not withdrawals, so a row deleted
    from CURATED_RETAIL_PRICES would otherwise survive on the Railway volume
    forever — which is exactly how SC-04's DRAM retraction became a no-op in prod.

    The source='curated' scope is MANDATORY and not a stylistic choice. Unlike
    sc_dram_spot, this table has live writers: crawl_passmark() and crawl_newegg()
    insert rows that appear nowhere in products_config.py. An unscoped reconcile
    here would delete every live-scraped price on the next deploy.
    """
    conn.executemany(
        "INSERT OR REPLACE INTO sc_prices VALUES (?,?,?,?,?,?,?)",
        CURATED_RETAIL_PRICES,
    )
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _retail_keep (mid TEXT, dt TEXT)")
    conn.execute("DELETE FROM _retail_keep")
    conn.executemany(
        "INSERT INTO _retail_keep VALUES (?,?)",
        [(r[0], r[1]) for r in CURATED_RETAIL_PRICES],
    )
    n = conn.execute(
        """
        DELETE FROM sc_prices
         WHERE source = 'curated'
           AND (model_id, date) NOT IN (SELECT mid, dt FROM _retail_keep)
        """
    ).rowcount
    conn.commit()
    log.info("Curated retail prices loaded — %d rows.", len(CURATED_RETAIL_PRICES))
    if n:
        log.warning(
            "Reconciled sc_prices[curated] — deleted %d withdrawn row(s) no longer in "
            "CURATED_RETAIL_PRICES (see BACKLOG SC-14). Live scraped rows untouched.", n
        )


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


# ── TSMC quarterly actuals (BACKLOG SC-11) ────────────────────────────────────
#
# Precondition checked 2026-08-02: investor.tsmc.com/english/quarterly-results/
# {year}/q{n} is server-rendered and carries a "Guidance" table whose first
# numeric column is that quarter's ACTUAL (2Q26: revenue 40.20, GM 67.7%,
# OM 60.3%). Confirmed by fetching the page, not assumed.
#
# Scope note: only revenue and the two margins are crawled. Wafer shipments and
# revenue-mix-by-node live in the linked Management Report PDF, which is a
# different parsing problem — they stay curated, transcribed by hand from a
# document someone actually opened. Crawling what is easy and hand-checking what
# is not is the correct split; inventing the hard half is what SC-11 fixed.
_TSMC_Q_URL = "https://investor.tsmc.com/english/quarterly-results/{year}/q{q}"

# "Net Revenue   (US$ billion)\n40.20\n39.0-40.2\n44.6-45.8" — first number after
# the label is the actual; the ranges that follow are guidance and must not match
# (they contain a hyphen, so a bare [\d.]+ anchored to the first cell is enough).
_TSMC_Q_METRICS = [
    (r"Net Revenue[^\n]*\n+\s*([\d.]+)\s*\n",  "revenue_usd_b",        "US$B", (1.0, 200.0)),
    (r"Gross Margin\s*\n+\s*([\d.]+)\s*%",     "gross_margin_pct",     "%",    (0.0, 100.0)),
    (r"Operating Margin\s*\n+\s*([\d.]+)\s*%", "operating_margin_pct", "%",    (0.0, 100.0)),
]


def _parse_tsmc_quarterly(text: str) -> list:
    """Return [(metric_key, value, unit), ...] from one quarterly-results page."""
    out = []
    for pattern, key, unit, (lo, hi) in _TSMC_Q_METRICS:
        m = re.search(pattern, text)
        if not m:
            continue
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        if lo <= v <= hi:                 # implausible values are dropped, not stored
            out.append((key, v, unit))
    return out


def crawl_tsmc_quarterly(conn: sqlite3.Connection, quarters: int = 6) -> None:
    """
    Walk back `quarters` quarters of TSMC results pages and store the actuals.

    Per-quarter try/except (§6.1): a future quarter has no page and an older one
    may render differently — neither may abort the run. A quarter that yields
    fewer than all three metrics is skipped entirely rather than written partially,
    so a layout change cannot leave a half-populated quarter looking complete.
    """
    now = _now_hkt()
    y, q = now.year, (now.month - 1) // 3 + 1
    stored = 0
    for _ in range(quarters):
        q -= 1
        if q == 0:
            y, q = y - 1, 4
        period = f"{y}-Q{q}"
        try:
            resp = SESSION.get(_TSMC_Q_URL.format(year=y, q=q), timeout=25)
            if resp.status_code != 200:
                continue
            text = BeautifulSoup(resp.text, "html.parser").get_text("\n")
            rows = _parse_tsmc_quarterly(text)
            if len(rows) < len(_TSMC_Q_METRICS):
                log.warning("TSMC %s — only %d/%d metrics parsed; quarter skipped.",
                            period, len(rows), len(_TSMC_Q_METRICS))
                continue
            conn.executemany(
                "INSERT OR REPLACE INTO sc_fab_metrics VALUES (?,?,?,?,?,?,?,?)",
                [("TSMC", key, "", period, val, unit,
                  f"{SRC_LIVE_TSMC_Q} — {period}", "Guidance table, actual column")
                 for key, val, unit in rows],
            )
            conn.commit()
            stored += 1
        except Exception as exc:
            log.warning("TSMC %s quarterly fetch failed: %s", period, exc)
            continue
        time.sleep(REQUEST_DELAY_SECONDS)

    if stored:
        log.info("TSMC quarterly actuals — %d quarter(s) stored.", stored)
    else:
        log.error("TSMC QUARTERLY PARSE REJECTED — no quarter yielded a full metric "
                  "set; page layout has likely changed. Curated seed retained. "
                  "See BACKLOG SC-11.")


# ── Nanya Technology monthly revenue (BACKLOG SC-13) ──────────────────────────
#
# Precondition checked 2026-08-02 before writing this parser (the SC-06 rule):
# nanya.com/en/IR/36?Year=YYYY returns a SERVER-RENDERED HTML table
# (Month | Consolidated Net Revenue | MoM Change | YoY Change) with a plain year
# query parameter. Confirmed, not assumed.
#
# Column order differs from TSMC and UMC: Nanya prints MoM BEFORE YoY. Reading
# them positionally without checking would silently swap two published figures —
# the sort of error that produces a plausible-looking number, which is the whole
# class this project keeps getting bitten by.
_NANYA_URL = "https://www.nanya.com/en/IR/36?Year={year}"

_NANYA_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                 "August", "September", "October", "November", "December"]

# "January\n15,309,988\n27.4%\n608.0%" — future months render as blank cells and
# simply do not match. The month name is anchored so the "Accumulated Revenue"
# summary row (which has no month and a meaningless MoM) can never be captured.
_NANYA_ROW_RE = re.compile(
    r"\b(" + "|".join(_NANYA_MONTHS) + r")\s*\n+"
    r"\s*([\d,]{4,15})\s*\n+"
    r"\s*(-?[\d.]+)\s*%\s*\n+"
    r"\s*(-?[\d.]+)\s*%"
)


def _parse_nanya_revenue(text: str, year: int) -> list:
    """
    Parse Nanya's monthly-revenue IR page.

    Returns [(period, value_ntb, yoy_pct, seq_pct), ...] — matching the tuple
    order used by _parse_tsmc_revenue/_parse_umc_revenue, NOT the page's column
    order. Nanya publishes both MoM and YoY, so neither is derived here.
    """
    rows = []
    for mon_name, raw_thousands, mom, yoy in _NANYA_ROW_RE.findall(text):
        mon = _NANYA_MONTHS.index(mon_name) + 1
        try:
            value_ntb = float(raw_thousands.replace(",", "")) / 1_000_000.0
            yoy_pct, seq_pct = float(yoy), float(mom)
        except ValueError:
            continue
        rows.append((mon, f"{year:04d}-{mon:02d}", value_ntb, yoy_pct, seq_pct))
    rows.sort(key=lambda r: r[0])
    return [(p, v, y, s) for _, p, v, y, s in rows]


def crawl_nanya_revenue(conn: sqlite3.Connection) -> None:
    """
    Fetch Nanya's monthly revenue and store it as sc_demand_indicators.

    Validation gate (SC-01/SC-02): reject the whole run unless every parsed month
    is inside Nanya's plausible range. NT$0.5B–NT$100B is deliberately wide — it
    spans the 2023 trough and leaves headroom above the 2026 spike, so it catches
    a unit error (thousands read as units would be ~1000x out) without pretending
    to know what the next print should be.
    """
    year = int(_now_hkt().strftime("%Y"))
    url = _NANYA_URL.format(year=year)
    log.info("Nanya monthly revenue — fetching %s …", url)
    try:
        resp = SESSION.get(url, timeout=25)
        resp.raise_for_status()
        text = BeautifulSoup(resp.text, "html.parser").get_text("\n")
    except Exception as exc:
        log.error("NANYA REVENUE FETCH FAILED: %s — curated seed retained.", exc)
        return

    parsed = _parse_nanya_revenue(text, year)
    bad = [p for p in parsed if not (0.5 <= p[1] <= 100)]
    if not parsed or bad:
        log.error(
            "NANYA REVENUE PARSE REJECTED (%s) — page layout has likely changed. "
            "Curated seed retained; see BACKLOG SC-13.",
            "no rows parsed" if not parsed else f"{len(bad)} implausible value(s)",
        )
        return

    conn.executemany(
        "INSERT OR REPLACE INTO sc_demand_indicators VALUES (?,?,?,?,?,?,?,?,?,?)",
        [("nanya_revenue", "Nanya Monthly Revenue", period, "month", value, "NT$B",
          yoy, seq, "Nanya IR", "Nanya IR (live crawl)")
         for period, value, yoy, seq in parsed],
    )
    conn.commit()
    log.info("Nanya monthly revenue — %d month(s) stored, latest %s = NT$%.1fB (%+.1f%% YoY).",
             len(parsed), parsed[-1][0], parsed[-1][1], parsed[-1][2])


# ══════════════════════════════════════════════════════════════════════════════
# LIVE SOURCE 6 — TrendForce DRAM spot price page (BACKLOG SC-15)
# ══════════════════════════════════════════════════════════════════════════════
#
# Precondition checked on 2026-08-02 before a line of this was written (the SC-06
# rule): trendforce.com/price/dram/dram_spot returns a SERVER-RENDERED HTML table
# — Item / Daily High / Daily Low / Session High / Session Low / Session Average /
# Session Change — with its own "Last Update YYYY-MM-DD HH:MM (GMT+8)" stamp. No
# JS execution needed, unlike Steam (SC-02) or Newegg (SC-01).
#
# Why this matters: TrendForce's free weekly [Insights] articles quote ONLY the
# DDR4 mainstream chip, which is why SC-08 could not close the DDR5 hole from
# them. This page carries DDR5 too, so it is the source that actually fixes the
# coverage gap rather than reporting it.
#
# The page also carries DDR4 16Gb, both eTT grades, DDR3, contract, module, GDDR
# and LPDDR tables. Only the two series that already exist in CURATED_DRAM_SPOT
# are captured — adding a new product_type means new _MEM_DIE_GB / _MEM_SPECS /
# _MEM_COLORS / _MEM_ORDER / _SC_DRAM_SLA entries in dashboard.py, and a missing
# _MEM_DIE_GB key silently understates $/GB (CLAUDE.md §9). Extend deliberately.

_SPOT_URL = "https://www.trendforce.com/price/dram/dram_spot"

# Page label → (product_type, spec_label). The spec_label MUST match the curated
# rows exactly or the live data forks into a parallel series that shares a chart
# with its own history and looks like two products.
_SPOT_ITEMS = {
    "DDR5 16Gb (2Gx8) 4800/5600": ("DDR5", "16Gb 2Gx8 die (spot)"),
    "DDR4 8Gb (1Gx8) 3200":       ("DDR4", "8Gb 1Gx8 die (spot)"),
}

# "Last Update 2026-07-31 18:10 (GMT+8)" — the page's own timestamp, never
# datetime.now(). A crawler that stamps rows with the time it ran reports itself
# as fresh even when the publisher has gone quiet; that is precisely how the
# Steam survey sat frozen for 17 months (SC-02).
_SPOT_ASOF_RE = re.compile(r"Last Update\s+(\d{4})-(\d{2})-(\d{2})\s+[\d:]+")

# Row shape after get_text("\n"): label, then 5 numeric cells, the 6th being the
# Session Average we want. Session Average is the same figure the weekly
# [Insights] articles quote as "the average spot price of mainstream chips", so
# the live series and the curated 2026 anchors are one series (verified: the
# 2026-06-30 article's US$36.00 equals this column on that date).
_SPOT_NUM = r"\s*[\d,]+\.?\d*\s*\n+"


def _spot_row_re(label: str):
    """Regex for one spot row: label, 4 skipped numeric cells, then the 5th
    (Session Average) captured. Built as an explicit concatenation — writing this
    as `r"..." r"..." * 4` silently repeats the LABEL instead of the numeric cell,
    because implicit string concatenation binds tighter than `*`."""
    return re.compile(
        re.escape(label) + r"\s*\n+" + (_SPOT_NUM * 4) + r"\s*([\d,]+\.?\d*)\s*\n"
    )


def _parse_trendforce_spot(text: str) -> tuple:
    """
    Parse the DRAM Spot Price table. Returns (period, asof, [(pt, spec, price)]).

    Bounded to the spot section: the page renders four tables (spot, contract,
    module, GDDR) and EACH has its own "Last Update" line, so an unbounded search
    can pair spot prices with the contract table's timestamp. Same class of bug as
    reading Steam's per-DirectX tables instead of "ALL VIDEO CARDS" (SC-02).
    """
    start = text.find("DRAM Spot Price")
    end   = text.find("DRAM Contract Price", start + 1) if start >= 0 else -1
    if start < 0:
        return None, None, []
    section = text[start:end] if end > start else text[start:]

    m = _SPOT_ASOF_RE.search(section)
    if not m:
        return None, None, []
    y, mo, d = m.group(1), m.group(2), m.group(3)
    period, asof = f"{y}-{mo}", f"{y}-{mo}-{d}"

    out = []
    for label, (ptype, spec) in _SPOT_ITEMS.items():
        hit = _spot_row_re(label).search(section)
        if not hit:
            continue
        try:
            price = float(hit.group(1).replace(",", ""))
        except ValueError:
            continue
        if price > 0:                      # never persist a contentless row (SC-01)
            out.append((ptype, spec, price))
    return period, asof, out


def crawl_trendforce_spot(conn: sqlite3.Connection) -> None:
    """
    Store the current DRAM spot session averages for the series we already track.

    Validation gate before writing (SC-01/SC-02 lesson): a parse that finds
    nothing, cannot read the page's timestamp, or returns a price wildly off the
    last stored value for that series must NEVER overwrite good data and must
    never fail silently. Rejection keeps existing rows and logs ERROR.
    """
    try:
        r = requests.get(_SPOT_URL, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; semi-tracker/1.0)"})
        r.raise_for_status()
        text = BeautifulSoup(r.text, "html.parser").get_text("\n")
    except Exception as exc:
        log.error("TrendForce spot page fetch FAILED (%s) — no rows written.", exc)
        return

    period, asof, rows = _parse_trendforce_spot(text)

    problems = []
    if not period:
        problems.append("'Last Update' timestamp not found in the spot section")
    if len(rows) < len(_SPOT_ITEMS):
        problems.append(f"only {len(rows)}/{len(_SPOT_ITEMS)} tracked series parsed")

    # Magnitude check against the last stored value per series. The falsified DDR
    # rows (SC-04) ran ~18x off the real market for 17 months with every status
    # surface green; a bounds check is cheap and would have caught it on day one.
    for ptype, spec, price in rows:
        prev = conn.execute(
            "SELECT price_usd FROM sc_dram_spot WHERE product_type=? AND spec_label=? "
            "AND price_usd IS NOT NULL ORDER BY period DESC LIMIT 1",
            (ptype, spec),
        ).fetchone()
        if prev and prev[0] and not (prev[0] / 10.0 <= price <= prev[0] * 10.0):
            problems.append(f"{ptype} {price} is >10x from last stored {prev[0]}")

    if problems:
        log.error(
            "TRENDFORCE SPOT PARSE REJECTED (%s) — page layout has likely changed. "
            "Existing rows retained; see BACKLOG SC-15.", "; ".join(problems),
        )
        return

    conn.executemany(
        "INSERT OR REPLACE INTO sc_dram_spot VALUES (?,?,?,?,?)",
        [(pt, spec, period, price, SRC_LIVE_SPOT) for pt, spec, price in rows],
    )
    conn.commit()
    log.info("TrendForce spot — %d series stored for %s (as of %s): %s",
             len(rows), period, asof,
             ", ".join(f"{pt} ${p:.2f}" for pt, _, p in rows))


# ══════════════════════════════════════════════════════════════════════════════
# REMOVED — SEMI NA Book-to-Bill (BACKLOG SC-00 → SC-10)
# ══════════════════════════════════════════════════════════════════════════════
#
# SEMI discontinued the North American Semiconductor Equipment Book-to-Bill report
# after the DECEMBER 2016 report; the NA billings press release ceased Feb-2022.
# The former scraper searched semi.org for a release that had not existed for ~9
# years, failed silently every run, and left hand-modelled rows looking live.
#
# SC-00 retired the scraper to a no-op stub; SC-10 removed the stub, the loader,
# CURATED_SEMI_BTB, and the table itself (dropped in init_supply_chain_db()).
#
# The replacement is LIVE: sc_demand_indicators[semi_wwsems_billings] carries real
# SEMI WWSEMS quarterly equipment billings. Do not re-add a Book-to-Bill series —
# there is no publication behind it.


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
    load_curated_fab_metrics(conn)
    load_curated_dram_spot(conn)
    load_curated_retail_prices(conn)
    load_curated_steam_survey(conn)   # seed Steam data; live crawl may overwrite
    load_curated_demand_indicators(conn)  # seed demand data; TSMC/UMC live crawl may overwrite
    purge_null_price_rows(conn)       # BACKLOG SC-01 — idempotent cleanup

    if curated_only:
        # Recorded under a DISTINCT job name (QA F-01). This path makes zero
        # network calls, so it must never satisfy the live-scrape SLA — a
        # container that only ever reboots would otherwise look exactly like a
        # container that is actually crawling.
        _cur_id = start_job(conn, JOB_CURATED)
        finish_job(conn, _cur_id, "completed", note="curated reload only; no network calls")
        conn.close()
        log.info("✅  Curated data load complete (--curated-only; no network calls).")
        return

    run_id = start_job(conn, "supply_chain")
    try:
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
        crawl_trendforce_spot(conn)
        time.sleep(REQUEST_DELAY_SECONDS)
        crawl_tsmc_revenue(conn)
        time.sleep(REQUEST_DELAY_SECONDS)
        crawl_umc_revenue(conn)
        time.sleep(REQUEST_DELAY_SECONDS)
        crawl_nanya_revenue(conn)
        time.sleep(REQUEST_DELAY_SECONDS)
        crawl_tsmc_quarterly(conn)
    except Exception as exc:
        finish_job(conn, run_id, "failed", note=f"{type(exc).__name__}: {exc}")
        conn.close()
        raise

    finish_job(conn, run_id, "completed",
               note="quick (no PassMark/Newegg)" if quick else "full")
    conn.close()
    log.info("✅  Supply chain crawl complete.")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Semiconductor Supply Chain Crawler")
    parser.add_argument(
        "--quick", action="store_true",
        help="Skip PassMark/Newegg scraping; still runs Steam / TrendForce spot / "
             "TSMC / UMC network calls.",
    )
    parser.add_argument(
        "--spot-only", action="store_true",
        help="Run ONLY the TrendForce DRAM spot crawl (BACKLOG SC-15). Use this to "
             "verify the parser against the live page after a layout change without "
             "touching any other source.",
    )
    parser.add_argument(
        "--curated-only", action="store_true",
        help="Load only in-memory curated data (zero network calls). "
             "Safe to run on every deploy — idempotent via INSERT OR REPLACE.",
    )
    args = parser.parse_args()
    if args.spot_only:
        _conn = get_conn()
        init_supply_chain_db(_conn)
        crawl_trendforce_spot(_conn)
        _conn.close()
    else:
        crawl_supply_chain(quick=args.quick, curated_only=args.curated_only)
