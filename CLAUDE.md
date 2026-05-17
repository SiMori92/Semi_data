# CLAUDE.md — Semiconductor Industry Tracker
# Read this file first at the start of every session in this project.
# Last updated: May 2026

---

## Project Summary

An automated investment-analysis dashboard for a semiconductor industry analyst (Simpo, schiu.develop@gmail.com).
Crawls market + supply-chain data, stores to SQLite, serves a 6-tab Dash dashboard hosted on Railway.app.

- **Live URL:** https://web-production-e3819.up.railway.app/
- **GitHub repo:** private repo owned by schiu.develop@gmail.com
- **Local folder:** `/Users/simpochiu/Documents/Claude - Industry Data Pj`
- **Railway project ID:** cee3a9a0-a0da-4abe-a505-8b61bbaecd63
- **Railway service ID:** ef9c4dc0-2172-4546-8f7a-d77a4a0ff2bb
- **Railway environment ID:** d4d8a81d-7afb-4cff-9025-3834c5dbeee9

---

## Architecture

```
crawler.py            ──┐
supply_chain_crawler.py ─┼──► SQLite DB (/data/semiconductor_data.db on Railway volume)
ibkr_relay.py (LOCAL) ──┘         │
                                   ▼
                         dashboard.py (gunicorn)
                               │
                    ┌──────────┼──────────┐
                    GET /      GET /health POST /api/upload-iv
                  (Dash UI)  (uptime)   (IBKR relay receiver)
```

**Key decisions:**
- SQLite (not PostgreSQL) — kept simple; Railway persistent volume at `/data/`
- IBKR TWS runs locally only → `ibkr_relay.py` POSTs IV to cloud via `/api/upload-iv`
- `startup.sh` is the Railway entry point: checks `daily_prices` row count, runs crawlers if 0, then starts gunicorn
- `healthcheckTimeout = 300` in `railway.toml` — gives crawlers time to complete before Railway declares deploy failed

---

## All Files

| File | Purpose | ~Lines |
|------|---------|--------|
| `config.py` | 33 ticker map (display name → Yahoo Finance symbol), DB_PATH + PORT read from env vars | 95 |
| `crawler.py` | yfinance crawler: OHLCV prices, quarterly financials, sentiment, cycle detection → SQLite | 547 |
| `supply_chain_crawler.py` | PassMark + Newegg + Steam HW Survey + SEMI.org scraping + curated data → SQLite | 581 |
| `products_config.py` | GPU/CPU/RAM product catalog; curated capacity, DRAM spot, SEMI BTB data | 387 |
| `ibkr_options_crawler.py` | ib_insync IBKR IV crawler: reqHistoricalData, IV metrics, DB storage | 468 |
| `ibkr_config.json` | IBKR connection config + 33 contract specs (user-editable) | 101 |
| `ibkr_relay.py` | LOCAL script: fetches IV from TWS, POSTs to cloud `/api/upload-iv` | 180 |
| `dashboard.py` | 6-tab Dash app + Flask `/health` + `/api/upload-iv` relay endpoint; exposes `server` for gunicorn | 1800 |
| `startup.sh` | Railway entrypoint: mkdir /data, check row count, run crawlers if empty, exec gunicorn | 30 |
| `requirements.txt` | All Python deps + gunicorn | 11 |
| `Procfile` | `web: sh startup.sh` | 1 |
| `railway.toml` | startCommand, healthcheckPath=/health, healthcheckTimeout=300 | 8 |
| `Dockerfile` | Alternative for Fly.io / manual Docker | 30 |
| `.env.example` | Template for DB_PATH, PORT, RELAY_API_KEY | 20 |
| `.gitignore` | Ignores *.db, .env, ibkr_relay_config.json, old/, __pycache__ | 20 |
| `SETUP_GUIDE.md` | 12-section full setup + deployment guide | 280 |
| `Handover_Document.docx` | AI agent handover document | — |

---

## Tickers (33 total)

```python
# Semiconductor companies (14)
SEMI_COMPANIES = ["NVDA","AMD","ASML","AVGO","QCOM","MU","ARM","LRCX","AMAT","MRVL","TSM","TXN","NXPI","INTC"]

# ETFs (7)  — includes VIX, A50 (=ASHR), USD (=UUP/DXY proxy)
SEMI_ETFS = ["SOXL","SOXS","SMH","TQQQ","VIX","A50","USD"]

# Tech/Mixed (8)
["MSFT","GOOG","META","AAPL","TSLA","AMZN","ORCL","BRK.A"]

# Macro (4)
["Gold (GC=F)", "10YTreasury (^TNX)", "BTC-USD", "ETH-USD"]
```

---

## Database Schema (SQLite)

**Tables created by `crawler.py`:**
- `daily_prices` — (ticker, date) PK, OHLCV, market_cap
- `financials` — (ticker, period_end) PK, quarterly income + balance sheet, computed margins
- `sentiment` — (ticker) PK, iv_current, days_since_large_drop, perf_5d/10d/1m
- `cycles` — (ticker, cycle_start) PK, type(up/down), magnitude, duration, volume_change
- `company_info` — (ticker) PK, name, sector, pe_ratio, etc.
- `crawl_runs` — audit log of each crawl

**Tables created by `supply_chain_crawler.py`:**
- `sc_products` — product catalog (GPU/CPU/RAM)
- `sc_prices` — (product_id, date, source) — retail prices from Newegg + PassMark
- `sc_market_share` — Steam GPU share %
- `sc_semi_btb` — SEMI equipment book-to-bill monthly
- `sc_dram_spot` — DDR4/DDR5/HBM3E monthly spot prices
- `sc_capacity` — fab utilisation % per company/quarter

**Tables created by `ibkr_options_crawler.py`:**
- `options_iv` — (ticker) latest IV snapshot: iv_current, iv_1m/1q/6m/1y_avg, iv_pct_vs_1y, 52w high/low
- `options_iv_history` — (ticker, date) daily IV history

---

## Environment Variables

| Variable | Where set | Value |
|----------|-----------|-------|
| `DB_PATH` | Railway Variables | `/data/semiconductor_data.db` |
| `RELAY_API_KEY` | Railway Variables | `4f890dbeaee2840a5b53e45cc5a370595ee2687c0f0958530a2d4efc6f9d3229` |
| `PORT` | Auto-injected by Railway | do not set manually |
| `CLOUD_URL` | ibkr_relay_config.json (local) | `https://web-production-e3819.up.railway.app` |

---

## Dashboard Tabs

| Tab | Key components |
|-----|----------------|
| **Overview** | KPI cards, normalised price chart, volume bars, return heatmap |
| **Financials** | Revenue, gross/op/net profit, R&D, margins, AR+inventory turnover (quarterly, all tickers) |
| **Sentiment** | IBKR: IV term structure bar, IV percentile, IV history line; fallback: yfinance ATM IV + yellow warning |
| **Cycles** | Up/down cycle magnitude & duration via scipy.signal.argrelextrema (CYCLE_DETECTION_WINDOW=15) |
| **Period Compare** | Custom date range picker → side-by-side return % + financials |
| **Supply Chain** | GPU/CPU/RAM prices, PassMark scores, Steam share, SEMI BTB, fab capacity gauges, DRAM spot |

**UI constants (dark theme):**
```python
BG="#0d1117"  BG2="#161b22"  BG3="#21262d"
ACCENT="#58a6ff"  GREEN="#3fb950"  RED="#f85149"  YELLOW="#d29922"
```

**IBKR status badge:** `ibkr-status-badge` span in navbar — ⚫ disabled / 🟡 enabled-no-data / 🟢 live

---

## Cloud Deployment (Railway)

**Entry point:** `startup.sh`
```bash
mkdir -p "$(dirname "$DB_PATH")"
ROW_COUNT=$(python3 -c "SELECT COUNT(*) FROM daily_prices ...")  # 0 if empty
if [ "$ROW_COUNT" -eq 0 ]; then
    python crawler.py --quick
    python supply_chain_crawler.py
fi
exec gunicorn dashboard:server --bind "0.0.0.0:$PORT" --workers 2 --timeout 120
```

**To deploy changes:** upload changed files to GitHub repo → Railway auto-redeploys on push.

**To check deploy logs:** Railway → service → Deployments → click latest → view live logs.

**To force a fresh crawl:** In Railway Variables, temporarily rename DB_PATH to a new path (e.g. `/data/semi_v2.db`) → redeploy → crawlers run → rename back. OR delete the DB file via Railway shell if SSH is working.

**Railway shell SSH (if needed):**
```bash
railway ssh --project=cee3a9a0-a0da-4abe-a505-8b61bbaecd63 \
            --environment=d4d8a81d-7afb-4cff-9025-3834c5dbeee9 \
            --service=ef9c4dc0-2172-4546-8f7a-d77a4a0ff2bb
```
Note: Railway SSH has been unreliable — closes immediately. Use startup.sh auto-crawl approach instead.

---

## Known Issues & Fixes (History)

| Issue | Root cause | Fix |
|-------|-----------|-----|
| `$PORT` literal in start command | Railway exec-form doesn't expand shell vars | `startCommand = 'sh -c "gunicorn ... --bind 0.0.0.0:$PORT ..."'` in railway.toml |
| Dashboard "No price data" after deploy | Volume not attached → DB written to ephemeral container, wiped on redeploy | Fixed volume mount; startup.sh uses row-count check not file-size check |
| 68 KB empty database skipped re-crawl | `[ ! -s "$DB_PATH" ]` passes for non-empty file even if schema-only | Changed to `SELECT COUNT(*) FROM daily_prices` via Python |
| Railway SSH closes immediately | Container not accepting SSH in that state | Abandoned SSH; use startup.sh approach |
| `python` not found on macOS | macOS uses `python3`; Railway Linux container uses `python` | Clarified context; no code change needed |
| `dict | None` type annotation | Python 3.10+ only syntax | Changed to `def crawl(tickers=None, ...)` |
| Dash IDs with `/` characters | Slash caused routing conflicts | `.replace('/', '')` in ID generation lambda; updated callback Input refs |

---

## Key Code Locations

**How to add a new ticker:**
1. Add to `TICKER_MAP` in `config.py` (display_name → Yahoo Finance symbol)
2. Add to `TICKER_TYPES` in `config.py`
3. Add contract spec to `ibkr_config.json → ticker_contracts`
4. Re-run `crawler.py` to fetch its data

**How to add a new dashboard tab:**
1. Add `tab_yourname()` function in `dashboard.py` (returns `dbc.Tab`)
2. Add to the `dbc.Tabs` children list in `app.layout`
3. Add callback `update_yourname_tab` with `Input("tabs", "active_tab")`

**How to update curated supply-chain data:**
- DRAM spot prices: edit `CURATED_DRAM_SPOT` list in `products_config.py`
- Fab capacity: edit `CURATED_CAPACITY` list in `products_config.py`
- SEMI BTB: edit `CURATED_SEMI_BTB` list in `products_config.py`
- Then re-run `python supply_chain_crawler.py` locally and push DB, or redeploy on Railway

**Flask endpoints in dashboard.py:**
```python
@server.route("/health")          # GET — returns {"status":"ok","db":bool}
@server.route("/api/upload-iv")   # POST — receives IV snapshots from ibkr_relay.py
```

---

## IBKR Integration (not yet enabled)

- Set `"enabled": true` in `ibkr_config.json`
- Requires TWS/IB Gateway running locally on port 7497 (paper) or 7496 (live)
- Run `python ibkr_options_crawler.py --test-connection` first
- Create `ibkr_relay_config.json`:
  ```json
  { "cloud_url": "https://web-production-e3819.up.railway.app",
    "relay_api_key": "4f890dbeaee2840a5b53e45cc5a370595ee2687c0f0958530a2d4efc6f9d3229",
    "tickers": [] }
  ```
- Run `python ibkr_relay.py` after market open each day (or schedule via cron)

---

## Recommended Next Steps

1. **Confirm crawl works** — watch Railway deploy logs; look for "Crawl complete" after latest startup.sh push
2. **Set up Railway Cron** — schedule `python crawler.py --quick` weekdays at 06:00 UTC
3. **Update curated data monthly** — DRAM spot + fab capacity in `products_config.py`
4. **Enable IBKR IV** — follow IBKR section above once TWS is configured
5. **Add /run-crawl endpoint** — protected by RELAY_API_KEY, triggers fresh crawl from browser

---

## Quick Commands

```bash
# Local
pip install -r requirements.txt
python crawler.py --quick                    # prices + financials (~2 min)
python supply_chain_crawler.py               # supply chain data
python dashboard.py                          # → http://127.0.0.1:8050

# IBKR relay (local → cloud)
python ibkr_relay.py --init-config           # create ibkr_relay_config.json
python ibkr_relay.py                         # push IV data to cloud

# Check DB row count (Railway shell or local)
python3 -c "import sqlite3,os; db=os.environ.get('DB_PATH','semiconductor_data.db'); c=sqlite3.connect(db); print('prices:', c.execute('SELECT COUNT(*) FROM daily_prices').fetchone()[0])"
```
