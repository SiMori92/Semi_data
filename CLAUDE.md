# CLAUDE.md — Semiconductor Industry Tracker

> **Read this file FIRST, in full, at the start of every session in this project.**
> It is the single source of truth for how this codebase is structured, how agents
> hand work to one another, and which mistakes have already cost us production incidents.
>
> Last structural rewrite: 2026-05-31
> Open / in-progress work lives in **`BACKLOG.md`** — check it before claiming a task.

---

## 0. What This Project Is (30-second orientation)

An automated investment-analysis dashboard for a semiconductor industry analyst
(Simpo, schiu.develop@gmail.com). Three crawlers pull market, options, and
supply-chain data into a SQLite database; a 6-tab Dash app renders it; everything
is hosted on Railway.app.

| Fact | Value |
|------|-------|
| Live URL | https://web-production-e3819.up.railway.app/ |
| Local folder | `/Users/simpochiu/Documents/Claude - Industry Data Pj` |
| Hosting | Railway.app (auto-deploys on `git push origin main`) |
| Datastore | SQLite on a Railway persistent volume at `/data/semiconductor_data.db` |
| UI framework | Dash (Plotly) served by gunicorn |
| Railway project / service / env IDs | `cee3a9a0-…63` / `ef9c4dc0-…bb` / `d4d8a81d-…e9` |

The product persona (analyst tone, strict sourcing, timestamps, zero-hallucination)
is defined in **§8 Output Persona** — apply it to any market-data *response*, not to
code or this doc.

---

## 1. Agent Onboarding Checklist (run every session, in order)

1. Read this entire file.
2. Read `BACKLOG.md` for open/in-progress work and any half-finished edits.
3. List the project files to get a current snapshot:
   ```bash
   ls -la "/Users/simpochiu/Documents/Claude - Industry Data Pj/"
   ```
4. Read every file you intend to modify (Read tool) **before** editing. Never edit blind.
5. Check **§7 Hard Rules** and **§9 Known Issues** — the bug you're about to "fix" may
   already be documented with a known cause.
6. Confirm target environment. Develop and test **locally** first; most incidents are
   Railway-only and surface after push.
7. **Ask Simpo before:** changing DB schema, editing `startup.sh`/`railway.toml`,
   adding a `requirements.txt` dependency, or removing/renaming a Flask endpoint.

---

## 2. Component Index (where everything lives)

Use this as the routing table: find the *capability* in the left column, go straight
to the file(s) and the symbols noted.

### 2.1 Files at a glance

| File | Role | Key symbols / sections | ~Lines |
|------|------|------------------------|--------|
| `config.py` | 33-ticker map + env config | `TICKER_MAP`, `TICKER_TYPES`, `DB_PATH`, `PORT` | 107 |
| `crawler.py` | Market crawler (yfinance) | OHLCV, quarterly financials, sentiment, cycle detection | 577 |
| `supply_chain_crawler.py` | Supply-chain crawler | `crawl_supply_chain()`, `load_curated_*()`, scrapers | 629 |
| `products_config.py` | Curated supply-chain seed data + catalog | `CURATED_RETAIL_PRICES`, `CURATED_DRAM_SPOT`, `CURATED_SEMI_BTB`, `CURATED_STEAM_SURVEY`, `CURATED_CAPACITY` | 779 |
| `ibkr_options_crawler.py` | IBKR IV crawler (ib_insync) | `reqHistoricalData`, IV metrics, DB store | 468 |
| `ibkr_config.json` | IBKR connection + 33 contract specs | `ticker_contracts`, `enabled` | 101 |
| `ibkr_relay.py` | **LOCAL** script: TWS → cloud `/api/upload-iv` | relay loop | 235 |
| `dashboard.py` | 6-tab Dash app + Flask endpoints; `server` for gunicorn | tab fns + module helpers (§2.3) | 3125 |
| `startup.sh` | Railway entrypoint: seed-if-empty then gunicorn | row-count check | 48 |
| `requirements.txt` | Python deps + gunicorn | — | 11 |
| `Procfile` | `web: sh startup.sh` | — | 1 |
| `railway.toml` | startCommand, healthcheckPath `/health`, timeout 300 | — | 8 |
| `Dockerfile` | Alt deploy (Fly.io / manual Docker) | — | 30 |
| `.env.example` | Template: `DB_PATH`, `PORT`, `RELAY_API_KEY` | — | 20 |
| `SETUP_GUIDE.md` | 12-section setup + deployment guide | — | 280 |
| `Handover_Document.docx` | Prior human-readable handover | — | — |
| `Industry Data - Data Schema.xlsx` | Schema reference workbook | — | — |
| `old/` | Archived prior versions — **do not import from here** | — | — |

### 2.2 Capability → location map

| I need to… | Go to |
|------------|-------|
| Add/remove a ticker | `config.py` (`TICKER_MAP` + `TICKER_TYPES`) → `ibkr_config.json` (`ticker_contracts`) → re-run `crawler.py` |
| Change what market data is crawled | `crawler.py` |
| Change supply-chain scraping logic | `supply_chain_crawler.py` |
| Update monthly curated numbers (DRAM, capacity, BTB, retail, Steam) | `products_config.py` (`CURATED_*` lists) → re-run `supply_chain_crawler.py` |
| Add/modify a dashboard tab | `dashboard.py` — see §6.2 |
| Touch IV / options data | `ibkr_options_crawler.py`, `ibkr_relay.py`, `ibkr_config.json` |
| Add an HTTP endpoint | `dashboard.py` Flask `@server.route` — see §6.3 |
| Change deploy/seed behavior | `startup.sh`, `railway.toml`, `Procfile` (**ask first**) |

### 2.3 Module-level helpers in `dashboard.py` (shared across tabs — do NOT redefine inline)

These were lifted out of `tab_overview()` and are now module-wide. `tab_sentiment()`,
`tab_cycles()`, and `tab_supply_chain()` depend on them:

```text
_CAT_ORDER        dict: category → list of ticker display names
_SHORT_CAT        dict: long cat name → short label (Semi / ETF / Macro / Tech)
_cat_rank         dict: ticker → (cat_index, ticker_index) for sorting
_ticker_cat(t)    → category name for a ticker
_ticker_label(t)  → "TICKER (Category)" label
_compute_hv30(ts) → DataFrame of 30-day historical volatility from daily_prices
_CYCLE_WINDOW=15  argrelextrema order for cycle detection
_build_cycle_chart(ticker) → go.Figure with up/down cycle shading
_sc_dram_inline() → DRAM chart + YoY table embedded in the RAM sub-tab
```

---

## 3. Architecture

```
crawler.py             ──┐
supply_chain_crawler.py ─┼──► SQLite DB (/data/semiconductor_data.db on Railway volume)
ibkr_relay.py (LOCAL)  ──┘         │
                                    ▼
                         dashboard.py (gunicorn)
                               │
                  ┌────────────┼─────────────┐
                GET /       GET /health   POST /api/upload-iv
              (Dash UI)     (uptime)      (IBKR relay receiver)
                                          GET /api/db-stats (auth)
```

Design decisions that constrain future work:

- **SQLite, not Postgres** — deliberately simple; one persistent Railway volume at `/data/`.
- **IBKR runs locally only.** TWS can't run in the cloud, so `ibkr_relay.py` POSTs IV
  snapshots to the cloud `/api/upload-iv` endpoint. Anything IBKR-related that must run
  in-cloud is a non-starter.
- **`startup.sh` is the seed gate.** On boot it counts rows in `daily_prices`; if 0 it
  runs the crawlers, then `exec gunicorn`. This is why the DB survives redeploys only if
  the volume is mounted (see §9).
- **`healthcheckTimeout=300`** in `railway.toml` gives the first-boot crawl time to finish
  before Railway declares the deploy failed. Do not lower it.

---

## 4. Data Model (SQLite)

Created by `crawler.py`:
`daily_prices` (ticker,date PK; OHLCV, market_cap) ·
`quarterly_financials` (ticker,period_end PK; income + balance sheet + margins) ·
`market_sentiment` (ticker,snapshot_date PK; iv_current, perf_5d/10d/1m, days_since_large_drop) ·
`cycle_analysis` (ticker,snapshot_date PK; up/down magnitude, duration, vol_diff) ·
`company_info` (ticker PK) ·
`crawl_runs` (audit log).

Created by `supply_chain_crawler.py`:
`sc_products` · `sc_prices` (product_id,date,source) · `sc_market_share` (Steam GPU share) ·
`sc_semi_btb` (monthly book-to-bill) · `sc_dram_spot` (DDR4/DDR5/HBM3E monthly) ·
`sc_capacity` (fab utilisation per company/quarter).

Created by `ibkr_options_crawler.py`:
`options_iv` (latest IV snapshot per ticker) · `options_iv_history` (ticker,date daily IV).

**Tickers (33):** 14 semis, 7 ETFs (incl. VIX, A50=ASHR, USD=DXY proxy), 8 tech/mixed,
4 macro (Gold, ^TNX, BTC, ETH). Full list in `config.py`.

---

## 5. Environment & Deployment

| Variable | Set where | Value / note |
|----------|-----------|--------------|
| `DB_PATH` | Railway Variables | `/data/semiconductor_data.db` |
| `RELAY_API_KEY` | Railway Variables | `4f890dbeaee2840a5b53e45cc5a370595ee2687c0f0958530a2d4efc6f9d3229` |
| `PORT` | auto-injected by Railway | **never set manually** (§7 rule 8) |
| `CLOUD_URL` | local `ibkr_relay_config.json` | the live Railway URL |

**Deploy:** `git add -A && git commit -m "…" && git push origin main` → Railway auto-redeploys.
Monitor at Railway → service → Deployments → latest → live logs.

**Force a fresh crawl:** temporarily rename `DB_PATH` in Railway Variables to a new path
→ redeploy (crawlers run because new DB has 0 rows) → rename back. Railway SSH is
unreliable (closes immediately) — do not depend on it.

**Verify production:**
```bash
curl https://web-production-e3819.up.railway.app/health        # → {"status":"ok","db":true}
curl https://web-production-e3819.up.railway.app/api/db-stats \
  -H "X-API-Key: 4f890dbeaee2840a5b53e45cc5a370595ee2687c0f0958530a2d4efc6f9d3229"
```

---

## 6. Conventions & Patterns

### 6.1 Python style
- Target **Python 3.9-compatible**: no `X | Y` union types (use `Optional[X]`), no walrus
  in complex contexts.
- On macOS use `python3`; the Railway Linux container uses `python`. Keep scripts context-aware (§7 rule 5).
- Imports: stdlib → third-party → local, blank-line separated.
- DB access: always `with sqlite3.connect(DB_PATH) as conn:`.
- Crawlers: wrap each ticker in `try/except`; one bad ticker must never abort the run.
  Commit after each ticker batch (partial progress survives a crash). Use `INSERT OR REPLACE`
  for idempotency.
- Logging: `print(f"[{datetime.utcnow():%Y-%m-%d %H:%M:%S}] …")`.

### 6.2 Dash callback pattern
```python
@app.callback(
    Output("component-id", "property"),
    Input("trigger-id", "property"),
    State("state-id", "value"),
    prevent_initial_call=True,   # for user-triggered callbacks
)
def cb(trigger_val, state_val):
    if trigger_val is None:
        raise PreventUpdate
    ...
    return result
```
- Every `Output` ID must be **globally unique** across `dashboard.py` — grep before adding.
- Use `raise PreventUpdate` (not `dash.no_update`) for None/invalid input.
- For sub-tabs, use `dbc.Tabs` with pre-rendered content + CSS show/hide. **Never** drive a
  parent tab container from a nested callback (see §9 Supply Chain history).

**Add a tab:** write `tab_yourname()` returning a `dbc.Tab` → add to `dbc.Tabs` children in
`app.layout` → add `update_yourname_tab` callback keyed on `Input("tabs","active_tab")` →
confirm all new component IDs are unique. Reuse §2.3 helpers; don't redefine them.

### 6.3 Flask endpoint pattern
```python
@server.route("/api/your-endpoint", methods=["POST"])
def your_endpoint():
    if request.headers.get("X-API-Key", "") != os.environ.get("RELAY_API_KEY", ""):
        return jsonify({"error": "unauthorized"}), 401
    ...
    return jsonify({"status": "ok"})
```
All write endpoints check `RELAY_API_KEY`. Read/status endpoints (`/health`, `/api/db-stats`)
are public but must return JSON. Existing routes: `/health`, `/api/upload-iv`, `/api/db-stats`.

### 6.4 Local dev loop
```bash
cd "/Users/simpochiu/Documents/Claude - Industry Data Pj"
pip3 install -r requirements.txt
python3 crawler.py --quick          # prices + financials (~2 min)
python3 supply_chain_crawler.py
python3 dashboard.py                # → http://127.0.0.1:8050
```
Then click through **every tab**, exercise dropdowns/date-pickers/buttons, watch for red
`Callback error` banners and for `DuplicateCallbackException` on startup. Validate DB row
counts (all expected tables > 0) before pushing.

---

## 7. 🔴 Hard Rules (each one caused a prior incident — no exceptions)

| # | Rule | Why |
|---|------|-----|
| 1 | Never `ALTER TABLE … ADD COLUMN` without `DEFAULT`/`NULL` | SQLite rejects NOT NULL on non-empty tables → crawler crash on Railway boot |
| 2 | Never rename a DB column/table without a migration script | Callbacks read columns by name → silent NoneType errors across all tabs |
| 3 | Never register two Dash callbacks with the same Output ID+property | `DuplicateCallbackException` at import → app won't start |
| 4 | Never nest a callback Output inside another callback's Output | Dash 4.x circular-dependency / tab-render conflicts |
| 5 | Never use `python` on macOS — use `python3` | macOS `python` is v2; Railway uses `python` |
| 6 | Never use `X \| Y` union syntax in signatures | Railway may run older Python; use `Optional[X]` |
| 7 | Never commit `.env`, `ibkr_relay_config.json`, or `*.db` | Secrets + local DB are gitignored; committing exposes credentials |
| 8 | Never set `PORT` as a Railway Variable | Railway injects it; a manual value crashes gunicorn |
| 9 | Never use `[ ! -s "$DB_PATH" ]` to decide on seeding | A schema-only DB is non-empty (~68 KB) but has 0 rows; use a row-count check |
| 10 | Never put `/` in a Dash component ID | Slashes break Dash's internal URL routing |

### 7.1 The Plotly template anti-pattern (read before touching any chart)

`PLOTLY_TEMPLATE["layout"]` (spread as `_base_layout`) **already contains** `font=`, `xaxis=`,
and `yaxis=` keys. Passing any of those again as explicit kwargs to `update_layout()` throws
`TypeError: got multiple values for keyword argument …`. Two separate production crashes came
from exactly this.

```python
fig.update_layout(**_base_layout, height=500)        # ✅ 'height' not in template
fig.update_xaxes(rangeselector=dict(...))             # ✅ axis extras go here
fig.update_yaxes(title_text="USD")                    # ✅
fig.update_layout(**_base_layout, xaxis=dict(...))    # ❌ crashes
fig.update_layout(**_base_layout, font=dict(...))     # ❌ crashes
```

---

## 8. Output Persona (apply to market-data *responses*, not code)

When responding to a request for a market update or interpreting crawled data, act as a
**Semiconductor Industry Data Analyst**:

1. **Executive Summary (TL;DR)** — bulleted, < 150 words, signal over noise.
2. **Visualize** — Markdown tables or Mermaid; never dense paragraphs for numbers.
3. **Strict sourcing** — every figure carries an inline `[Source: Organization]` (SIA, SEMI,
   TrendForce, Gartner, foundry releases). End with a Data Sources Glossary.
4. **Timestamps** — next to every visual and in the glossary:
   `[Data Last Crawled/Updated: YYYY-MM-DD HH:MM UTC]`.
5. **Zero hallucination** — if a figure isn't in the latest crawl, write
   *"Data not available in the latest crawl."* Never estimate or fall back to training data.

Tone: professional, objective, financial, analytical.

---

## 9. Known Issues & Fixes (history — check before re-debugging)

| Symptom | Root cause | Fix applied |
|---------|-----------|-------------|
| `$PORT` literal in start command | Railway exec-form doesn't expand shell vars | `startCommand = 'sh -c "gunicorn … --bind 0.0.0.0:$PORT …"'` |
| "No price data" after deploy | Volume not mounted → DB on ephemeral container, wiped | Fixed volume mount; row-count seed check |
| 68 KB empty DB skipped re-crawl | `[ ! -s ]` passes for schema-only file | Row-count check via Python |
| Railway SSH closes immediately | Container state | Abandoned SSH; use startup.sh seed approach |
| `python` not found on macOS | v2 vs v3 | Use `python3` locally |
| `dict \| None` annotation error | 3.10+-only syntax | Default-value / `Optional` patterns |
| Dash IDs with `/` | Routing conflict | `.replace('/', '')` in ID generation |
| Supply Chain tab shows previous tab | `sc-price-panel` callback nested in `tab-content` output (Dash 4.1) | Replaced with `dbc.Tabs` sub-tabs (GPU/CPU/RAM), CSS show/hide |
| Refresh button "no response" | Not wired; no visual feedback | Wired `Input("btn-refresh")` to render_tab; added `reload-stamp` confirmation |
| Select All / Clear All inert | No callback registered | Added `select_clear_all` populating all four checklists |
| `/api/upload-iv` relay fails | INSERT used `as_of`; schema column is `snapshot_date` | Fixed column name; added `source='relay'` |
| Overview `update_layout() … 'font'` | Template already has `font=` | Removed duplicate kwarg (see §7.1) |
| Supply Chain `update_layout() … 'xaxis'` | Template already has `xaxis=` | Moved to `update_xaxes(rangeselector=…)` (see §7.1) |
| Steam GPU chart empty | JS-rendered page; raw GET returns shell; regex lacked `re.DOTALL` | Added `CURATED_STEAM_SURVEY` seed; fixed regex with `re.DOTALL` |
| `vol_diff_last_cycle` only for MU & Gold | Condition `len(prev_peaks) >= 2` needed 3+ peaks | Changed to `>= 1`, `prev_peak = prev_peaks[-1]` |
| Sentiment IV all NULL | `--quick` skips IV; yfinance returns NULL for ETFs/crypto/bonds | `_compute_hv30()` fallback + yellow "HV30" badge |

---

## 10. Maintenance Calendar

| Cadence | Task | Where |
|---------|------|-------|
| Daily (automate) | Price + financials crawl, weekdays 06:00 UTC | Railway Cron → `crawler.py --quick` |
| Monthly | Update `CURATED_DRAM_SPOT`, `CURATED_CAPACITY`, `CURATED_SEMI_BTB`, retail, Steam | `products_config.py` → re-run crawler → push |
| Monthly | Re-verify PassMark/Newegg scraper selectors (DOM drift) | run `supply_chain_crawler.py` locally |
| Quarterly | Review ticker list | `config.py` → re-crawl → push |
| On demand | Enable IBKR IV feed once TWS configured | §11 |
| On demand | Force full DB rebuild after schema change | rename `DB_PATH` in Railway → redeploy → rename back |

---

## 11. IBKR Integration (not yet enabled)

Set `"enabled": true` in `ibkr_config.json`. Requires TWS/IB Gateway locally on port 7497
(paper) or 7496 (live). Test with `python3 ibkr_options_crawler.py --test-connection`. Create
`ibkr_relay_config.json` (gitignored) with `cloud_url`, `relay_api_key`, `tickers`, then run
`python3 ibkr_relay.py` after market open (or cron it). The IBKR status badge in the navbar
(`ibkr-status-badge`) reads ⚫ disabled / 🟡 enabled-no-data / 🟢 live.

---

## 12. Working Agreement Between Agents

Many sessions touch this repo. To hand work off cleanly:

- **Before starting:** read this file + `BACKLOG.md`; claim a backlog item by noting it.
- **While working:** keep edits scoped to one feature/fix; reuse §2.3 helpers; obey §7.
- **After finishing:** if you discover a new failure mode, add a row to §9. If you defer
  work, record it in `BACKLOG.md` with enough detail (file, line, exact change) that the
  next agent doesn't re-derive it. Never leave uncommitted edits without a `BACKLOG.md` note.
- **Deploy is not done until verified:** push, watch Railway logs, then hit `/health` and
  `/api/db-stats`.

### 12.1 How to submit a feature/bug request (standard ticket)

Non-trivial requests should arrive in this shape — it maps onto §2.2, front-loads the §7
gates, and pre-commits the verify step:

```
TITLE: <imperative — "Fix flat-lining price index" / "Add Earnings-Calendar tab">
TYPE: bug | feature | data-refresh        PRIORITY: P0 blocker | P1 | P2

WHAT / WHY:   1–2 sentences. User-visible symptom or the goal.
WHERE:        files + symbols (or the §2.2 capability row); agent confirms.
DONE-WHEN:    one observable result.
CONSTRAINTS:  which §7 rules / ask-first gates this touches ("none" is valid).
VERIFY:       local (tabs/buttons to click) + prod (/health, /api/db-stats).
```

For genuinely one-line asks (e.g. "bump Financials window to 16 quarters"), a single
sentence naming the file is enough — skip the template.

### 12.2 Keeping this file current (mandatory workflow)

This file is the contract every agent relies on. Each agent **must** review it at the end
of a task and update it **only when the work changed something this file asserts.** The goal
is a doc that stays accurate *and* lean — update with intent, not reflex.

**Update when (and only when) your change makes the file wrong or incomplete:**

- A new failure mode + fix → add one row to **§9** (don't write a paragraph).
- A new file, tab, endpoint, helper, or capability → update the relevant table in **§2**.
- A new schema object/column → **§4**; a new env var or deploy step → **§5**.
- A new hard constraint that, if violated, breaks prod → **§7** (reserve for real incidents).
- The architecture or a design decision changed → **§3**.

**Do NOT update when:**

- The change is internal to one function and contradicts nothing already written.
- You'd only be restating what an existing section already covers — link to it (`see §X`) instead.
- You're tempted to add narrative, status notes, or "what I did this session" — that belongs
  in `BACKLOG.md` and the commit message, not here.

**Rules for the edit itself:**

1. **Smallest correct diff.** Edit the existing line/row; don't append a near-duplicate.
2. **Prefer tables and one-liners** over prose; match the surrounding section's format.
3. **Single source of truth** — a fact lives in exactly one section; cross-reference (`§X`)
   rather than copy.
4. **No churn** — don't reword, reorder, or "tidy" sections you didn't functionally change.
5. **Bump** the "Last structural rewrite" date at the top only for structural changes
   (new/removed/reorganized sections), not for routine row additions.
6. **Treat this file like code:** read before editing, keep the edit scoped, and include the
   doc change in the same commit as the code change it documents.

If your task changed nothing this file asserts, leave it untouched — that is the correct
outcome, not a missed step.
