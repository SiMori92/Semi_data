# config.py — Semiconductor Industry Data Tracker
# Central configuration: tickers, Yahoo Finance symbol mapping, DB path, thresholds

import os

# ── Ticker definitions from schema (Targets sheet) ───────────────────────────
# Maps the display name used in the schema to the Yahoo Finance symbol
TICKER_MAP = {
    # ETFs
    "SOXX":         "SOXX",          # iShares Semiconductor ETF — supply chain benchmark
    "SOXL":         "SOXL",
    "SOXS":         "SOXS",
    "SMH":          "SMH",
    "TQQQ":         "TQQQ",
    "VIX":          "^VIX",
    "A50":          "ASHR",        # FTSE China A50 — best free proxy
    "USD":          "DX-Y.NYB",   # USD Index (DXY)
    # Companies
    "AMD":          "AMD",
    "AVGO":         "AVGO",
    "ASML":         "ASML",
    "NVDA":         "NVDA",
    "QCOM":         "QCOM",
    "MU":           "MU",
    "ARM":          "ARM",
    "LRCX":         "LRCX",
    "AMAT":         "AMAT",
    "MRVL":         "MRVL",
    "TSM":          "TSM",
    "TXN":          "TXN",
    "NXPI":         "NXPI",
    "INTC":         "INTC",
    "BRK.A":        "BRK-A",
    "ORCL":         "ORCL",
    "MSFT":         "MSFT",
    "GOOG":         "GOOG",
    "META":         "META",
    "AAPL":         "AAPL",
    "TSLA":         "TSLA",
    "AMZN":         "AMZN",
    # Commodity
    "Gold":         "GC=F",       # Gold Futures
    # Bond
    "10YTreasury":  "^TNX",       # 10-Year Treasury Yield
    # Crypto
    "BTC":          "BTC-USD",
    "ETH":          "ETH-USD",
}

# Ticker type (for grouping in UI)
TICKER_TYPES = {
    "SOXX": "ETF",
    "SOXL": "ETF", "SOXS": "ETF", "SMH": "ETF", "TQQQ": "ETF",
    "VIX": "ETF", "A50": "ETF", "USD": "ETF",
    "AMD": "Company", "AVGO": "Company", "ASML": "Company", "NVDA": "Company",
    "QCOM": "Company", "MU": "Company", "ARM": "Company", "LRCX": "Company",
    "AMAT": "Company", "MRVL": "Company", "TSM": "Company", "TXN": "Company",
    "NXPI": "Company", "INTC": "Company", "BRK.A": "Company", "ORCL": "Company",
    "MSFT": "Company", "GOOG": "Company", "META": "Company", "AAPL": "Company",
    "TSLA": "Company", "AMZN": "Company",
    "Gold": "Commodity",
    "10YTreasury": "Bond",
    "BTC": "Crypto", "ETH": "Crypto",
}

# Core semiconductor companies (highlighted in dashboard)
SEMI_COMPANIES = [
    "NVDA", "AMD", "ASML", "AVGO", "QCOM", "MU", "ARM",
    "LRCX", "AMAT", "MRVL", "TSM", "TXN", "NXPI", "INTC",
]

# Semi-focused ETFs
SEMI_ETFS = ["SOXL", "SOXS", "SMH"]

# ── Database ──────────────────────────────────────────────────────────────────
# On cloud: set DB_PATH env var to point at a persistent-volume mount, e.g.
#   DB_PATH=/data/semiconductor_data.db
DB_PATH = os.environ.get("DB_PATH", "semiconductor_data.db")

# ── Crawler settings ──────────────────────────────────────────────────────────
PRICE_HISTORY_PERIOD = "2y"          # How far back to pull price history
LARGE_DROP_THRESHOLD = -0.05         # -5% = "large single-day drop"
CYCLE_DETECTION_WINDOW = 15          # Rolling window (trading days) for peak/trough detection
REQUEST_DELAY_SECONDS = 0.5          # Polite delay between Yahoo Finance calls

# ── Dashboard settings ────────────────────────────────────────────────────────
# On cloud the PORT env var is injected by the platform (Railway, Render, Fly.io).
# Locally it defaults to 8050 on 127.0.0.1.
DASHBOARD_PORT = int(os.environ.get("PORT", 8050))
DASHBOARD_HOST = os.environ.get("HOST", "127.0.0.1")
DARK_THEME = True

# Chart colour palette (one per ticker group)
CHART_COLORS = [
    "#00D4FF", "#FF6B6B", "#51CF66", "#FFD43B", "#CC5DE8",
    "#FF922B", "#74C0FC", "#F06595", "#A9E34B", "#63E6BE",
    "#4DABF7", "#FFA94D", "#DA77F2", "#E599F7", "#96F2D7",
]
