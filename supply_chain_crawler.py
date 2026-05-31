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
    CURATED_DRAM_SPOT,
    CURATED_RETAIL_PRICES,
    CURATED_SEMI_BTB,
    CURATED_STEAM_SURVEY,
    ENTERPRISE_PRODUCT_LAUNCHES,
    GPU_PRODUCTS,
    NEWEGG_PRODUCTS,
    RAM_PRODUCTS,
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


def load_curated_semi_btb(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO sc_semi_btb VALUES (?,?,?)",
        CURATED_SEMI_BTB,
    )
    conn.commit()
    log.info("SEMI B2B data loaded — %d rows.", len(CURATED_SEMI_BTB))


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
    rows = []
    for i, (model_id, prod) in enumerate(NEWEGG_PRODUCTS.items(), 1):
        query = prod["newegg_q"]
        price, in_stock = _newegg_search_price(query)
        status = "✓ ${:.0f}".format(price) if price else "—"
        stk    = {1: "In Stock", 0: "OOS", None: "?"}[in_stock]
        log.info("  [%d/%d] %-22s  price=%-10s  stock=%s",
                 i, len(NEWEGG_PRODUCTS), model_id, status, stk)
        rows.append((model_id, TODAY, "newegg", price, None, None, in_stock))
        time.sleep(REQUEST_DELAY_SECONDS * 3)   # respect Newegg rate limits

    conn.executemany(
        "INSERT OR REPLACE INTO sc_prices VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    log.info("Newegg — %d products stored.", len(rows))


# ══════════════════════════════════════════════════════════════════════════════
# LIVE SOURCE 3 — Steam Hardware Survey (GPU Sales Volume Proxy)
# ══════════════════════════════════════════════════════════════════════════════

def crawl_steam_survey(conn: sqlite3.Connection) -> None:
    """
    Fetch the Steam Hardware Survey GPU page.
    Extracts GPU model → % share (proxy for relative sales volume / installed base).
    """
    url = "https://store.steampowered.com/hwsurvey/videocard/"
    log.info("Steam HW Survey — fetching GPU market share …")
    try:
        resp = SESSION.get(url, timeout=25)
        resp.raise_for_status()
        html = resp.text

        # Data is embedded in JS: each entry has "hardware":"..." and "percentage":"..."
        # Use re.DOTALL so the pattern spans newlines inside JS objects.
        matches = re.findall(
            r'"hardware"\s*:\s*"([^"]+)"[\s\S]*?"percentage"\s*:\s*"([\d.]+)"',
            html, re.DOTALL,
        )
        if not matches:
            # Fallback: parse HTML rows
            soup  = BeautifulSoup(html, "html.parser")
            rows_html = soup.select("table tr, .survey_area tr")
            matches = []
            for row in rows_html:
                cells = row.find_all("td")
                if len(cells) >= 2:
                    name = cells[0].get_text(strip=True)
                    pct  = cells[-1].get_text(strip=True).replace("%", "").strip()
                    if name and pct:
                        matches.append((name, pct))

        rows = []
        for name, pct_str in matches:
            try:
                pct = float(str(pct_str).replace("%", "").strip())
                rows.append((name, THIS_MONTH, pct, "Steam HW Survey"))
            except ValueError:
                continue

        conn.executemany(
            "INSERT OR REPLACE INTO sc_market_share VALUES (?,?,?,?)",
            rows,
        )
        conn.commit()
        log.info("Steam HW Survey — %d GPU entries stored for %s.", len(rows), THIS_MONTH)

    except Exception as exc:
        log.warning("Steam HW Survey failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
# LIVE SOURCE 4 — SEMI Book-to-Bill (Order Volume Indicator)
# ══════════════════════════════════════════════════════════════════════════════

def crawl_semi_btb(conn: sqlite3.Connection) -> None:
    """
    Attempt to fetch the latest SEMI NA Equipment Book-to-Bill ratio.
    SEMI publishes monthly press releases at semi.org.
    Falls back gracefully if the page structure changes.
    """
    url  = "https://www.semi.org/en/news-media-press-releases?combine=book+to+bill&field_article_type_tid=All"
    log.info("SEMI B2B — fetching latest press release …")
    try:
        resp = SESSION.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Find the first result link that looks like a B2B report
        links = soup.select("a[href*='book'], a[href*='billing'], h3 a, .views-field-title a")
        for link in links[:5]:
            href = link.get("href", "")
            text = link.get_text(strip=True).lower()
            if "book" in text or "billing" in text or "b2b" in text:
                article_url = href if href.startswith("http") else "https://www.semi.org" + href
                _parse_semi_btb_article(conn, article_url)
                return

        log.info("SEMI B2B — no new article found; curated data already loaded.")
    except Exception as exc:
        log.warning("SEMI B2B fetch failed: %s", exc)


def _parse_semi_btb_article(conn: sqlite3.Connection, url: str) -> None:
    """Extract the B2B ratio from a SEMI press release article."""
    try:
        resp = SESSION.get(url, timeout=20)
        resp.raise_for_status()
        text = BeautifulSoup(resp.text, "html.parser").get_text(" ")

        # Look for patterns like "ratio was 1.23" or "book-to-bill of 1.23"
        m = re.search(r"(?:ratio|book-to-bill)[^\d]{0,30}(\d+\.\d+)", text, re.IGNORECASE)
        if not m:
            m = re.search(r"(\d\.\d{2})\s*(?:ratio|book|billing)", text, re.IGNORECASE)
        if not m:
            log.info("SEMI B2B — could not extract ratio from article.")
            return

        ratio = float(m.group(1))
        # Determine month from article text
        month_m = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+(\d{4})", text, re.IGNORECASE,
        )
        if month_m:
            from datetime import datetime as _dt
            dt = _dt.strptime(f"{month_m.group(1)} {month_m.group(2)}", "%B %Y")
            period = dt.strftime("%Y-%m")
        else:
            period = THIS_MONTH

        conn.execute(
            "INSERT OR REPLACE INTO sc_semi_btb VALUES (?,?,?)",
            (period, ratio, "SEMI NA Equipment B2B (live)"),
        )
        conn.commit()
        log.info("SEMI B2B — period=%s  ratio=%.2f  stored.", period, ratio)

    except Exception as exc:
        log.warning("SEMI B2B article parse failed (%s): %s", url, exc)


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
