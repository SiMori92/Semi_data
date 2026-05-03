# Semiconductor Industry Tracker — Complete Setup Guide

A full walkthrough: install, configure, run locally, and deploy to the cloud.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [File Reference](#2-file-reference)
3. [Prerequisites](#3-prerequisites)
4. [Local Installation](#4-local-installation)
5. [Running Locally](#5-running-locally)
6. [Configuration Reference](#6-configuration-reference)
7. [Dashboard Tour](#7-dashboard-tour)
8. [IBKR Options IV Integration](#8-ibkr-options-iv-integration)
9. [Cloud Deployment](#9-cloud-deployment)
10. [IBKR Relay (local → cloud)](#10-ibkr-relay-local--cloud)
11. [Scheduling Automatic Crawls](#11-scheduling-automatic-crawls)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  LOCAL MACHINE                                                  │
│                                                                 │
│  crawler.py ──────────────────────────────────────────────┐    │
│  supply_chain_crawler.py ─────────────────────────────────┤    │
│                                                           ▼    │
│  ibkr_relay.py ◄── TWS / IB Gateway              semiconductor │
│       │                                            _data.db    │
│       │ POST /api/upload-iv                           ▲        │
│       │                                               │        │
└───────┼───────────────────────────────────────────────┼────────┘
        │                                               │ (local run)
        │                                               │
        ▼ (cloud run)                           dashboard.py
  ┌───────────────────────────────────────────────────────────┐
  │  CLOUD HOST  (Railway / Render / Fly.io)                  │
  │                                                           │
  │  gunicorn dashboard:server                                │
  │      │                                                    │
  │      ├── GET  /          → Dash web app (browser UI)      │
  │      ├── GET  /health    → uptime probe                   │
  │      └── POST /api/upload-iv  ← ibkr_relay.py             │
  │                                                           │
  │  /data/semiconductor_data.db  (persistent volume)        │
  └───────────────────────────────────────────────────────────┘
```

**Data sources:**
- Yahoo Finance (`yfinance`) — price, volume, financials, basic IV
- Interactive Brokers API (`ib_insync`) — high-quality real-time IV with history
- PassMark — GPU & CPU benchmark prices and scores
- Newegg — retail GPU/CPU/RAM prices
- Steam Hardware Survey — GPU market share
- SEMI.org press releases — equipment book-to-bill ratio
- Curated earnings-call data — manufacturer capacity & utilization
- Curated TrendForce data — DRAM/HBM3E spot prices

---

## 2. File Reference

| File | Purpose |
|------|---------|
| `config.py` | Ticker definitions, Yahoo Finance symbol map, DB path, thresholds |
| `products_config.py` | GPU/CPU/RAM product catalog + curated capacity/DRAM/BTB data |
| `crawler.py` | Main yfinance crawler — pulls prices, financials, sentiment, cycles |
| `supply_chain_crawler.py` | Supply-chain crawler — PassMark, Newegg, Steam, SEMI.org |
| `ibkr_options_crawler.py` | IBKR options IV crawler — uses `ib_insync` |
| `ibkr_config.json` | IBKR connection settings + contract definitions (user-editable) |
| `ibkr_relay.py` | **Local script** — fetches IV from TWS and POSTs to cloud app |
| `ibkr_relay_config.json` | Relay settings: cloud URL and API key (user-created, git-ignored) |
| `dashboard.py` | Dash web app — 6-tab interactive dashboard |
| `requirements.txt` | Python dependencies |
| `Procfile` | Gunicorn start command (used by Railway/Render) |
| `railway.toml` | Railway-specific deploy config |
| `Dockerfile` | Container definition (used by Fly.io or manual Docker deploys) |
| `.env.example` | Template for environment variables |
| `semiconductor_data.db` | SQLite database (created on first crawl) |

---

## 3. Prerequisites

- **Python 3.10+** (3.11 recommended)
- **pip** (comes with Python)
- **Git** (for pushing to cloud platforms)
- For IBKR IV: **TWS or IB Gateway** installed and running locally

---

## 4. Local Installation

### 4.1 Clone / download the project

Place all project files in a folder, e.g. `~/semiconductor-tracker/`.

### 4.2 Create a virtual environment (recommended)

```bash
cd ~/semiconductor-tracker
python3 -m venv .venv
source .venv/bin/activate      # macOS/Linux
# .venv\Scripts\activate       # Windows
```

### 4.3 Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `ib_insync` is included but only used if you enable IBKR.
> If you don't plan to use IBKR, it installs harmlessly and does nothing.

### 4.4 Copy the environment template

```bash
cp .env.example .env
# Edit .env as needed — see Section 6 for all variables
```

---

## 5. Running Locally

### 5.1 Fetch data (first run)

```bash
# Full crawl — all 33 tickers + supply-chain scraping (~5–8 min)
python crawler.py
python supply_chain_crawler.py

# Quick crawl — skips slow IV fetch (~2 min)
python crawler.py --quick

# Crawl specific tickers only
python crawler.py --tickers NVDA AMD ASML TSM
```

### 5.2 Launch the dashboard

```bash
python dashboard.py
```

Then open **http://127.0.0.1:8050** in your browser.

---

## 6. Configuration Reference

### config.py

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `semiconductor_data.db` | SQLite file path. Set `DB_PATH` env var to override (e.g. cloud persistent volume). |
| `DASHBOARD_PORT` | `8050` | Web server port. Set `PORT` env var to override. |
| `DASHBOARD_HOST` | `127.0.0.1` | Bind address. Set `HOST` env var to override. Cloud sets this automatically via gunicorn. |
| `PRICE_HISTORY_PERIOD` | `2y` | How far back to pull price history from Yahoo Finance. |
| `LARGE_DROP_THRESHOLD` | `-0.05` | Threshold for "large single-day drop" (-5%). |
| `CYCLE_DETECTION_WINDOW` | `15` | Rolling window (trading days) for peak/trough detection. |

### ibkr_config.json

| Field | Description |
|-------|-------------|
| `enabled` | Set to `true` to activate IBKR IV fetching. |
| `connection.port` | `7496` TWS Live · `7497` TWS Paper · `4001` Gateway Live · `4002` Gateway Paper |
| `connection.client_id` | Unique ID per simultaneous API connection (1–999). |
| `crawl_settings.history_duration` | IBKR history window, e.g. `"1 Y"`. |
| `crawl_settings.delay_between_requests_s` | Throttle between IBKR requests. |
| `ticker_contracts` | Per-ticker contract spec (type, symbol, exchange, currency). |

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_PATH` | No | SQLite path. Defaults to `semiconductor_data.db`. |
| `PORT` | No (cloud injects) | Web server port. |
| `RELAY_API_KEY` | Recommended | Shared secret for `/api/upload-iv`. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. |

---

## 7. Dashboard Tour

| Tab | What you see |
|-----|-------------|
| **Overview** | KPI cards, normalised price chart, volume bars, return heatmap |
| **Financials** | Revenue, Gross/Op/Net Profit, R&D, margins, AR & Inventory turnover — all quarterly |
| **Sentiment** | Implied volatility (IBKR or yfinance), days since large drop, 5d/10d/1m performance |
| **Cycles** | Up/down cycle magnitude & duration, volume change vs prior cycle |
| **Period Compare** | Pick any two date ranges → side-by-side return & financials comparison |
| **Supply Chain** | GPU/CPU/RAM retail prices, PassMark scores, Steam GPU share, SEMI B2B, fab utilization, DRAM spot |

The **IBKR status badge** in the top nav shows:
- ⚫ Disabled — `ibkr_config.json` has `enabled: false`
- 🟡 Enabled / no data — IBKR is on but no IV snapshot in DB yet
- 🟢 Live — IV data found in DB

---

## 8. IBKR Options IV Integration

### 8.1 Install TWS or IB Gateway

Download from: https://www.interactivebrokers.com/en/trading/tws.php

### 8.2 Configure TWS API access

In TWS: **Edit → Global Configuration → API → Settings**
- ✅ Enable ActiveX and Socket Clients
- ✅ Add `127.0.0.1` to Trusted IP Addresses
- ✅ Read-Only API (tick for safety — we only read data)
- Set Socket port to match `ibkr_config.json → connection.port` (default: 7497 paper trading)

### 8.3 Enable in ibkr_config.json

```json
{
  "enabled": true,
  "connection": {
    "port": 7497
  }
}
```

### 8.4 Run the IBKR crawler

```bash
# Test connection first
python ibkr_options_crawler.py --test-connection

# Crawl all tickers
python ibkr_options_crawler.py

# Crawl specific tickers
python ibkr_options_crawler.py --tickers NVDA AMD ASML
```

IV data is written to `options_iv` and `options_iv_history` tables in the DB,
and the Sentiment tab will automatically show the full IV term-structure charts.

---

## 9. Cloud Deployment

The application is designed for **Railway.app** (simplest) but also works on
Render.com, Fly.io, or any Docker-capable host.

### 9.1 Deploy to Railway (recommended)

1. Push your project to a GitHub repository.
2. Go to https://railway.app → **New Project → Deploy from GitHub repo**.
3. Select your repo. Railway auto-detects the `Procfile` and `railway.toml`.
4. **Add a Volume** (Volumes tab → New Volume → mount at `/data`).
5. **Set environment variables** (Variables tab):
   - `DB_PATH` = `/data/semiconductor_data.db`
   - `RELAY_API_KEY` = your secret key
6. Deploy. Railway provides a public URL (e.g. `https://your-app.railway.app`).
7. Run the initial crawl via Railway's shell console:
   ```bash
   python crawler.py --quick
   python supply_chain_crawler.py --quick
   ```

### 9.2 Deploy to Render.com

1. Push to GitHub. Go to https://render.com → **New Web Service**.
2. Connect your repo. Build command: `pip install -r requirements.txt`.
3. Start command: `gunicorn dashboard:server --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
4. Add a **Disk** (persistent storage) mounted at `/data`, size ≥ 1 GB.
5. Set environment variables: `DB_PATH=/data/semiconductor_data.db` + `RELAY_API_KEY`.

### 9.3 Deploy to Fly.io

```bash
fly launch          # auto-detects Dockerfile, creates fly.toml
fly volumes create semiconductor_data --size 1
# Edit fly.toml: add [mounts] section pointing /data to the volume
fly secrets set RELAY_API_KEY=your-secret-key DB_PATH=/data/semiconductor_data.db
fly deploy
```

### 9.4 Keep data fresh on the cloud

After deployment, schedule the crawler to run periodically using the platform's
scheduler (Railway Cron, Render Cron Jobs, or Fly.io Machines) or via the
local cron approach described in Section 11.

---

## 10. IBKR Relay (local → cloud)

Since your IBKR TWS/IB Gateway runs on your **local machine**, and the dashboard
is now on the cloud, `ibkr_relay.py` bridges the gap:

```
Your machine (TWS running)  →  ibkr_relay.py  →  POST /api/upload-iv  →  cloud DB
```

### 10.1 Create relay config

```bash
python ibkr_relay.py --init-config
```

This creates `ibkr_relay_config.json`. Edit it:

```json
{
  "cloud_url":     "https://your-app.railway.app",
  "relay_api_key": "your-secret-key-here",
  "tickers":       []
}
```

> `tickers: []` = relay all tickers from `ibkr_config.json`.

### 10.2 Run the relay

```bash
# Fetch IV and push to cloud (requires TWS / IB Gateway running)
python ibkr_relay.py

# Relay specific tickers only
python ibkr_relay.py --tickers NVDA AMD ASML TSM
```

### 10.3 Schedule the relay (optional)

Add to your local crontab (macOS/Linux) to run every weekday at market open:

```bash
crontab -e
# Add:
30 9 * * 1-5 cd ~/semiconductor-tracker && python ibkr_relay.py >> ibkr_relay.log 2>&1
```

---

## 11. Scheduling Automatic Crawls

### Local cron (macOS/Linux)

```bash
crontab -e
```

Add:
```bash
# Full supply-chain crawl every Sunday at 6:00 AM
0 6 * * 0 cd ~/semiconductor-tracker && python crawler.py && python supply_chain_crawler.py >> crawl.log 2>&1

# Quick price + financials crawl every weekday at 6:00 AM
0 6 * * 1-5 cd ~/semiconductor-tracker && python crawler.py --quick >> crawl.log 2>&1
```

### Cloud scheduler (Railway / Render)

Use your platform's built-in cron feature and run:
```bash
python crawler.py --quick
```

---

## 12. Troubleshooting

### "Database not found" on startup

Run the crawler first:
```bash
python crawler.py --quick
```

### Dashboard shows no data

1. Check the DB was created: `ls -lh semiconductor_data.db`
2. Verify the crawl completed without errors: check the terminal output or `crawl.log`

### IBKR "Cannot connect"

1. Confirm TWS or IB Gateway is running.
2. Check the port in `ibkr_config.json` matches the API port in TWS.
3. Verify `127.0.0.1` is in TWS's Trusted IP Addresses.
4. Run `python ibkr_options_crawler.py --test-connection` to see the specific error.

### Cloud relay returns 401 Unauthorized

The `RELAY_API_KEY` in `ibkr_relay_config.json` must exactly match the `RELAY_API_KEY`
environment variable set on the cloud host. Both are case-sensitive.

### Cloud app crashes on startup

1. Check platform logs for Python errors.
2. Confirm `DB_PATH` env var points to a writable location (inside the persistent volume).
3. Confirm `gunicorn` is listed in `requirements.txt` (it is — see the file).

### PassMark / Newegg / Steam scraping fails

These scrapers are resilient to failures — they log warnings and continue.
Curated static data in `products_config.py` is always loaded as a baseline.
If a scraper fails repeatedly, check the target website's structure hasn't changed
and update the CSS selectors in `supply_chain_crawler.py`.

### yfinance rate-limiting / empty data

Yahoo Finance occasionally throttles requests. Use `--quick` mode to skip the
slower option-chain IV fetch, and add a longer `REQUEST_DELAY_SECONDS` in
`config.py` if you hit rate limits frequently.

---

## Quick-reference command summary

```bash
# ── Local setup ───────────────────────────────────────────────────────────────
pip install -r requirements.txt

# ── Data crawl ────────────────────────────────────────────────────────────────
python crawler.py --quick           # Prices + financials (~2 min)
python crawler.py                   # Full crawl incl. yfinance IV (~5–8 min)
python supply_chain_crawler.py      # GPU/CPU/RAM + SEMI BTB + DRAM

# ── Dashboard ─────────────────────────────────────────────────────────────────
python dashboard.py                 # → http://127.0.0.1:8050

# ── IBKR ──────────────────────────────────────────────────────────────────────
python ibkr_options_crawler.py --test-connection
python ibkr_options_crawler.py      # Write IV to local DB
python ibkr_relay.py                # Push IV to cloud dashboard

# ── Cloud (gunicorn) ──────────────────────────────────────────────────────────
gunicorn dashboard:server --bind 0.0.0.0:8050 --workers 2 --timeout 120
```
