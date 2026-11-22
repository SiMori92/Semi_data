# CLAUDE.md — Semiconductor Industry Tracker

## Folder location & backup (updated 2026-11-21)

- **Project root:** `/Users/simpochiu/Projects/Invest-Industry Data Pj`. Paths under `~/Documents/...` or old names like `~/Projects/Claude - ...` in older notes, logs or handovers are stale.
- **In Cowork:** connect this project folder itself, not `~/Projects` as a whole, so it mounts at `$HOME/mnt/Invest-Industry Data Pj`.
- **Code backup:** this folder is not synced by Google Drive. rclone backs it up nightly to Google Drive at `Backup/Projects/Invest-Industry Data Pj`, skipping `node_modules`, `.venv*`, `.next`, `__pycache__`, caches, secrets and symlinks.
- **Documents copy:** every hour, documents are copied automatically from here to `/Users/simpochiu/Documents/Invest-Industry Data Pj/`, which syncs to Google Drive. That covers .md, .txt, .csv, PDF, Office files, .html, images, audio and video, in the same folder structure. Code, environments, `CLAUDE.md`/`AGENTS.md`, `_Working/` and secrets are not copied. Always create and edit files **here**. The Documents copy is one-way, so edits made there don't come back.
- **Never** put code, environments, build output or symlinks in `~/Documents`.
- **Paths in code:** resolve paths relative to the project root (e.g. `Path(__file__).resolve().parent`) instead of hard-coding absolute paths.
- **launchd backup job:** `~/Projects` isn't TCC-protected, so Full Disk Access is no longer needed. The installed `~/Library/LaunchAgents/com.simpo.semibackup.plist` must be re-copied from `Product/local/` and reloaded (it still points at the old `Claude - Industry Data Pj` path).


> **Read this file FIRST, in full, at the start of every session in this project.**
> It is the single source of truth for how this codebase is structured, how agents
> hand work to one another, and which mistakes have already cost us production incidents.
>
> Last structural rewrite: 2026-11-22 (GIT-01 — §5.0 git work tree + push only on explicit
> ask/approval, §7 rules 7/12–14). Before that: 2026-08-23 folder reorg (§2.1, rules 14–15)
> Open / in-progress work lives in **`BACKLOG.md`** — check it before claiming a task.

---

## 0. What This Project Is (30-second orientation)

An automated investment-analysis dashboard for a semiconductor industry analyst
(Simpo, schiu.develop@gmail.com). Three crawlers pull market, options, and
supply-chain data into a SQLite database; a 6-tab Next.js app renders it; everything
is hosted on Railway.app.

| Fact | Value |
|------|-------|
| Live URL | https://web-production-e3819.up.railway.app/ |
| Local folder | `/Users/simpochiu/Projects/Invest-Industry Data Pj` — four-folder layout, §2.1 |
| **Deploy set (local)** | **`Product/Git_Deploy/`** — this folder alone is the GitHub repo root. Nothing outside it reaches production (§2.1, §5.0) |
| Hosting | Railway.app — auto-deploys on every push to GitHub `main`, repo root. `Product/Git_Deploy/` is the git work tree; **agents commit/push only on Simpo's explicit ask or approval** (§5.0, §7 rule 12) |
| Datastore | SQLite on a Railway persistent volume at `/data/semiconductor_data.db` |
| UI framework | **Next.js** (`web/`, public on `$PORT`). Every endpoint is plain Flask in `api_server.py` on an internal port; Next proxies `/health` + `/api/*` to it (§3). The Dash UI was retired in WEB-01 Phase 5 (2026-11-16, archived) |
| Railway project / service / env IDs | `cee3a9a0-…63` / `ef9c4dc0-…bb` / `d4d8a81d-…e9` |

The product persona (analyst tone, strict sourcing, timestamps, zero-hallucination)
is defined in **§8 Output Persona** — apply it to any market-data *response*, not to
code or this doc.

---

## 1. Agent Onboarding Checklist (run every session, in order)

1. Read this entire file.
2. Read `BACKLOG.md` for open/in-progress work and any half-finished edits.
3. List the project files to get a current snapshot — the deploy set first:
   ```bash
   cd "/Users/simpochiu/Projects/Invest-Industry Data Pj"
   ls -la . Product Product/Git_Deploy
   ```
4. Read every file you intend to modify (Read tool) **before** editing. Never edit blind.
5. Check **§7 Hard Rules** and **§9 Known Issues** — the bug you're about to "fix" may
   already be documented with a known cause.
6. Confirm target environment. Develop and test **locally** first; most incidents are
   Railway-only and surface only after the change is uploaded and deployed.
7. **Ask Simpo before:** changing DB schema, editing `startup.sh`/`railway.toml`,
   adding a `requirements.txt` dependency, or removing/renaming a Flask endpoint.
8. Read **§5.0** before you touch a deployable file. `git status` / `git diff` in
   `Product/Git_Deploy/` show what you changed. You **commit and push only when Simpo explicitly
   asks or approves** (§7 rule 12) — a push to `main` is a production deploy. Otherwise finish
   with the file list ("ready to commit"), deletions included.

---

## 2. Component Index (where everything lives)

Use this as the routing table: find the *capability* in the left column, go straight
to the file(s) and the symbols noted.

### 2.1 Files at a glance

**Folder layout (reorganised 2026-08-23).** The project is four top-level folders and
**exactly one of them ships**. `Product/Git_Deploy/` *is* the GitHub repo root: every file
in it deploys, nothing outside it does. The deploy boundary is now the **folder**, not a
`.gitignore` rule — the folder is also the git work tree (§5.0).

```
<project root>/
  CLAUDE.md, BACKLOG.md   the agent contract. Kept at the project ROOT because agent
                          tooling loads them from there. The ONLY two files outside
                          Git_Deploy that go to the GitHub root — staged by
                          Product/local/git_stage_root_docs.sh (§5.0)
  Product/                everything that is "the product"
    Git_Deploy/           ★ THE DEPLOY SET + git work tree of SiMori92/Semi_data main (since
                          2026-11-22, GIT-01) — a flat 1:1 mirror of the GitHub repo root:
                          all .py, startup.sh, Procfile, railway.toml, Dockerfile,
                          requirements.txt, ibkr_config.json, .gitignore,
                          .env.example, and web/ (the Next.js UI — built in the
                          image) — the only subfolder
    next_rebuild/         WEB-01 parity harness for web/ (tests, fixtures, QA scripts)
                          — supplemental, does NOT deploy
    docs/                 reference material          — supplemental, does NOT deploy
    tests/                regression tests (§6.4)     — supplemental, does NOT deploy
    local/                LOCAL-ONLY scripts (backup agent, IBKR relay)
                          — supplemental; must never be invoked by startup.sh
  DB_Backup/              database exports pulled from the live site (§5.2). Production
                          data — NEVER commit, never name it in a git add (§7 r7)
  Semi_data/              SUPERSEDED stale clone (2026-10-30) of SiMori92/Semi_data (PUBLIC).
                          Use `git -C Product/Git_Deploy fetch` / `log origin/main` for "what is
                          on main" now. Never edit, commit or push from it (§9 RE-04, GIT-01)
  archive/                obsoleted product items and documents. Never imported, never
                          uploaded. `archive/_to_delete/` stages files for deletion,
                          because agents cannot delete files on this Mac
```

Four rules make that layout safe:

1. **Git_Deploy is flat — except `web/`.** (`assets/` went with the Dash UI in Phase 5.)
   `web/` is the Next.js app: its own `package.json`, built by the `Dockerfile`'s `web` stage,
   started by `startup.sh` — Python never imports from it and Node never imports outside it. Railway builds from the repo root; `startup.sh` invokes the
   crawlers by **bare relative filename** and `gunicorn api_server:server` resolves the
   module from CWD. A subfolder inside `Git_Deploy` — or a `.py` moved out of it — breaks
   boot *after* the old container is gone. §7 rule 11.
2. **"Supplemental" means it does not exist in production.** Nothing under `Product/docs`,
   `Product/tests`, or `Product/local` is uploaded, so deployed code can never import it.
   If the running app needs a file, that file belongs in `Git_Deploy`. A build-critical
   file filed as supplemental is the 2026-08-23 `requirements.txt` incident (§9).
3. **Supplemental also means this Mac is its only copy.** `docs/`, `tests/` and `local/`
   no longer reach GitHub, and they are outside the git work tree (§5.0). The copies still sitting in the
   GitHub repo from before the reorg are **frozen** — never read them as current, and never
   "resync" them by committing a folder.
4. **Every DB export goes to `DB_Backup/`**, enforced by `BACKUP_DIR` in the backup script
   and the launchd plist rather than by remembering (§5.2).

Paths in the table below are relative to **`Product/Git_Deploy/`** unless a folder is shown.

| File | Role | Key symbols / sections | ~Lines |
|------|------|------------------------|--------|
| `config.py` | 33-ticker map + env config | `TICKER_MAP`, `TICKER_TYPES`, `DB_PATH`, `PORT` | 107 |
| `crawler.py` | Market crawler (yfinance) | OHLCV, quarterly financials, sentiment, cycle detection | 577 |
| `supply_chain_crawler.py` | Supply-chain crawler | `crawl_supply_chain()`, `load_curated_*()`, `purge_null_price_rows()`, scrapers | 640 |
| `products_config.py` | Curated supply-chain seed data + catalog | `CURATED_RETAIL_PRICES`, `CURATED_DRAM_SPOT`, `CURATED_STEAM_SURVEY`, `CURATED_FAB_METRICS`, `CURATED_DEMAND_INDICATORS` | ~1620 |
| `ibkr_options_crawler.py` | IBKR IV crawler (ib_insync) | `reqHistoricalData`, IV metrics, DB store | 468 |
| `ibkr_config.json` | IBKR connection + 33 contract specs | `ticker_contracts`, `enabled` | 101 |
| `Product/local/ibkr_relay.py` | **LOCAL** script: TWS → cloud `/api/upload-iv` | relay loop | 235 |
| `iv_crawler.py` | **Cloud** IV crawler — replaces the IBKR path | `fetch_iv30_yahoo()`, `fetch_dvol_history()`, `compute_metrics()`, `crawl_iv()` | ~460 |
| `api_server.py` | **Every HTTP endpoint** (§6.3) — plain Flask, no Dash; `server` for gunicorn (internal 127.0.0.1:8051). Extracted verbatim from the retired `dashboard.py` (WEB-01 Phase 5) with the helpers the routes use | `_freshness_report`, `_consistency_report`, `_stale_sources`, `_build_export_workbook`, `_snapshot_db` (§2.3) | ~1000 |
| `job_heartbeat.py` | **The schedule + run heartbeats** — one definition read by both the scheduler and the UI | `JOB_SPECS`, `ensure_schema()`, `start_job()`, `finish_job()`, `run_source()` (per-scraper outcome → `crawl_source_runs`, catches the scraper's exception — DH-01), `job_report()`, `retry_backoff_hours()`; **run lock** `acquire_run_lock()` / `start_manual_run()` / `crawl_running()` — one flock (`.crawl_run.lock` beside the DB) taken by BOTH the scheduler and manual runs, so they never overlap (WEB-01c) | ~400 |
| `scheduler.py` | In-container crawl watchdog (F-01). Cannot be a Railway cron service — §3 | `due_jobs()`, `run_job()`, `tick()`, `acquire_singleton_lock()` | ~230 |
| `startup.sh` | Railway entrypoint: volume guard → curated reload → purges → seed-if-empty → watchdog → gunicorn | volume guard (§5.1), row-count check | 130 |
| `Product/local/backup_local.sh` | **LOCAL** daily script: pulls `/api/export-db` (the real backup) + `/api/export-xlsx` (reading copy) to this Mac. **The only backup on the Hobby plan — §5.2** | `PRAGMA integrity_check` + `MIN_PRICE_ROWS` floor, gzip, prune-to-`$KEEP`, ephemeral/crawl warnings, size-regression guard (`SAFE_TO_PRUNE`), restore recipe in the footer | ~210 |
| `Product/local/com.simpo.semibackup.plist` | launchd agent driving the above, daily 09:15. **Replaces the old crontab line — delete it** (cron skips while asleep, §9) | `StartCalendarInterval`, logs to `DB_Backup/backup.log` | 75 |
| `Product/local/git_stage_root_docs.sh` | **LOCAL** helper: stages project-root `CLAUDE.md`/`BACKLOG.md` at the repo root of the `Product/Git_Deploy` work tree (sparse-checkout keeps them out of the folder). `--check` = dry run. Only inside an approved commit (§5.0) | — | ~45 |
| `Product/local/.backup_env.example` | Template for `Product/local/.backup_env` (gitignored): `RELAY_API_KEY` for `/api/export-db` | — | 12 |
| `requirements.txt` | Python deps + gunicorn. **Pinned per Python version** (environment markers) to exactly what prod's 2026-10-29 build resolved — prod runs **Python 3.11** (`Dockerfile`, confirmed 2026-11-16), and a flat pin of numpy/scipy/pandas fails on Python ≤3.11. Bump deliberately, then re-run the golden parity suite (WEB-01b) | — | ~30 |
| `Procfile` | `web: sh startup.sh` | — | 1 |
| `railway.toml` | startCommand, healthcheckPath `/health`, timeout 300 | — | 8 |
| `Dockerfile` | **Prod's actual build** — Railway builds from it despite `railway.toml`'s `builder = "NIXPACKS"` (WEB-01e). Stage `web` (node:22) runs `export_web_config.py` + `npm ci` + `next build`; the `python:3.11-slim` runtime gets the `node` binary + `web/.next/standalone`. Railway's `startCommand` overrides `CMD` | `web` stage | ~60 |
| `.env.example` | Template: `DB_PATH`, `PORT`, `RELAY_API_KEY` | — | 20 |
| `Product/docs/PROJECT_INSTRUCTIONS.md` | **Canonical source of the Claude project's Instructions field** — §0 folder governance + the §8 analyst persona. Edit here, then re-paste into the field; the two drift silently otherwise (§12.2) | paste block below the marker line | ~95 |
| `Product/docs/SETUP_GUIDE.md` | 12-section setup + deployment guide | — | 280 |
| `Product/docs/Handover_Document.docx` | Prior human-readable handover | — | — |
| `Product/docs/Industry Data - Data Schema.xlsx` | Schema reference workbook | — | — |
| `Product/docs/QA_Review_Investor_Fitness_2026-08-02.md` | Investor-fitness QA review | — | — |
| `Product/tests/test_qa05_passmark.py` | QA-05/QA-05c regression test: PassMark parser / per-class inversion gate / purge. Reads its subject out of `supply_chain_crawler.py` by text, so it needs only `bs4` — run it after ANY edit to the PassMark path | 23 assertions across parser, layout-refusal, `_passmark_inversion_check`, `_passmark_class_rhos` (incl. the real pooled Simpson's-paradox prod pattern), `purge_rank_as_price_rows` | ~150 |
| `Product/tests/test_run_lock.py` | WEB-01c regression test: run lock (no overlap, scheduler waits) + `POST /api/run-crawl` (401/400/202/409). Fake 2-s crawlers, throwaway DB | 20 assertions | ~120 |
| `Product/tests/test_source_runs.py` | DH-01 regression test: fake scrapers (raise / write / write nothing) → `crawl_source_runs` rows, later scrapers still run after an error, job `failed` only when no source wrote, CLI exit 1. Needs `requests`+`bs4` and **Python ≥3.10** (`supply_chain_crawler.py` has a 3.10 annotation) | 13 assertions | ~140 |
| `Product/tests/test_api_contract.py` | WEB-01 Phase 5 contract test: every route of `api_server:server` vs the archived `dashboard:server` on the same DB (JSON deep-equal; exports by integrity + per-table content hash). `dump` per server, then `compare`. Re-run after any `api_server.py` change | 21 checks | ~230 |
| `archive/dashboard_phase5_20261116/` | The retired Dash UI (`dashboard.py`, `assets/`), the pre-Phase-5 `startup.sh`/`requirements.txt`/`Dockerfile` (= the rollback), `golden_dump.py`, `test_responsive_smoke.py`, Dash-vs-Next QA scripts. `next_rebuild/fixtures/golden.json` is now the **frozen** parity reference | README.md | — |
| `web/` | **The public UI** (Next.js 16 / React 19 / Zod, App Router). Read-only on the DB (`better-sqlite3` `readonly`+`fileMustExist`). `lib/` = TS ports of the §2.3 helpers; `next.config.ts` proxies `/health` + `/api/*` to gunicorn (`CLASSIC_ORIGIN`) | `lib/schemas.ts`, `lib/db.ts`, `lib/plotly/figure.ts`, `lib/tabs/*`, `app/ui-api/run-crawl` | — |
| `web/components/` + `web/app/{tokens,globals}.css` | UI-01 shared shell, page identity/artwork, filters, badges, metric cards, panels, alerts and accessible tables. Colours use theme tokens; artwork is local under `web/public/art/` | `Shell`, `PageHeading`, `ArtworkHeader`, `FilterPanel`, `Badge`, `MetricCard`, `DashTable`, `DashTabs`, `PlotlyChart` | — |
| `Product/docs/UI_HANDBOOK.md` + `UI_REFRESH_PLAN.md` | Supplemental UI reference, departures and acceptance record. Repeatable browser QA: `Product/next_rebuild/scripts/qa-phase5.cjs` | UI-01 | — |
| `web/lib/generated/products-config.json` | **Generated** — never hand-edit. Rebuilt from `products_config.py` on every Railway build | — | — |
| `export_web_config.py` | Build step: writes the JSON above, and **fails the build** if `web/lib/config.ts` ticker groups / colours drift from `config.py` | `PC_KEYS`, `KNOWN_UNGROUPED` | ~110 |
| `Product/next_rebuild/` | WEB-01 **parity harness** (supplemental): `npm test` runs the golden suite against `Git_Deploy/web` via the `@web` alias; `npm run stage` builds the deploy copy locally in `.stage/` | `tests/`, `scripts/qa-*.cjs`, `fixtures/` | — |
| `archive/old/` | Archived prior versions — **do not import from here** | — | — |

### 2.2 Capability → location map

| I need to… | Go to |
|------------|-------|
| Add/remove a ticker | `config.py` (`TICKER_MAP` + `TICKER_TYPES`) → `ibkr_config.json` (`ticker_contracts`) → re-run `crawler.py` |
| Change what market data is crawled | `crawler.py` |
| Change supply-chain scraping logic | `supply_chain_crawler.py` |
| Update monthly curated numbers (DRAM, capacity, retail, Steam, demand) | `products_config.py` (`CURATED_*` lists) → re-run `supply_chain_crawler.py`. **Removing a row only propagates for the two lists whose loader reconciles** — `CURATED_DRAM_SPOT` and `CURATED_RETAIL_PRICES` (§9, SC-14) |
| Change a UI colour, or the light/dark theme | `web/app/tokens.css` (both themes) **and** `TOKENS` in `web/lib/theme.ts` — `tests/theme.test.ts` fails if they differ or a pair drops below WCAG AA. UI code uses `var(--token)` via the `lib/config.ts` constants; charts may too (`PlotlyChart` resolves them per theme). Series colours are fixed hex, ≥3:1 on both chart surfaces; `CHART_COLORS` must also change in `config.py` (build drift check). Plan + handbook: `Product/docs/UI_REFRESH_PLAN.md`, `UI_HANDBOOK.md` (UI-01) |
| Add/modify a dashboard tab | **`web/`** (`lib/tabs/*`, `components/`) — §6.2. `npm test` + `npm run stage` in `Product/next_rebuild` |
| Touch IV / options data | `iv_crawler.py` (**default, cloud-native**); `ibkr_options_crawler.py`, `Product/local/ibkr_relay.py`, `ibkr_config.json` (dormant IBKR path — see §11) |
| Show P/E, market cap, or any valuation figure | `ticker_valuation_history` via `valuationSnapshot()` in `web/lib/valuation.ts` + the Financials tab (`web/lib/tabs/financials.ts`). **Never** from `quarterly_financials` — §9 F-02 |
| Run the PassMark regression tests | `python3 Product/tests/test_qa05_passmark.py` (works from any CWD) — mandatory after touching `_parse_passmark_table`, `crawl_passmark`, or `purge_rank_as_price_rows` (§9 QA-05) |
| Add a deploy-time data-integrity cleanup | `crawler.py` `purge_contaminated_valuation_cols()` pattern → call it from the `--purge-only` branch; `startup.sh` already runs that on every boot |
| Change how often a crawler runs, or add a scheduled job | `JOB_SPECS` in `job_heartbeat.py` — **the only place**. `scheduler.py` and the `/health` + navbar reporting both read it, so editing one dict moves both. A crawler not listed there is unscheduled AND unmonitored (§9 F-01) |
| Check whether the crawlers are actually running | `/health` → `jobs` / `overdue_jobs` / `crawl_ok`, the navbar `crawl-status-badge`, or `python3 scheduler.py --status` |
| See every data source's status, its crawl history, and which charts it feeds | **🩺 Data Health tab** (`?tab=health`, `web/lib/tabs/health.ts`). Per-source status = `freshnessReport()` + the feeding scraper's last `crawl_source_runs` result (or the job's `crawl_runs` outcome); source → chart map = `EXACT`, scraper → source map = `SCRAPER_SOURCES` in that file. **Adding a scraper:** add it to the `steps` list in `crawl_supply_chain()` AND to `SCRAPER_SOURCES` (DH-01) |
| Change how an IV source is labelled in the UI | `IV_SOURCE_META` / `ivSourceMeta()` in `web/lib/iv-source.ts` — §2.3 |
| Add an HTTP endpoint | `api_server.py` Flask `@server.route` — see §6.3; add a contract check to `Product/tests/test_api_contract.py` |
| Export the full dataset | `GET /api/export-bundle` (⬇️ Download Data navbar button) → zip of xlsx + db; or `/api/export-xlsx` / `/api/export-db` for one file — see §6.3 |
| **Back up / restore the database** | `GET /api/export-db` + `Product/local/backup_local.sh` — see §5.2. Never treat the xlsx as a backup |
| Change deploy/seed behavior | `startup.sh`, `railway.toml`, `Procfile` (**ask first**) |
| Decide whether a new file deploys | §2.1 — if production runs it, it goes in `Product/Git_Deploy/`; everything else is supplemental and never uploaded |
| Change the Claude project's Instructions field | `Product/docs/PROJECT_INSTRUCTIONS.md` → re-paste into the field. Never edit the field alone (§12.2) |
| Check whether prod data is actually persistent | `/health` → `volume_ok`; see §5.1 |
| Check whether a data source has gone quiet | `/api/db-stats` → `freshness` / `stale_sources` / `data_ok`, or the navbar badge; see §6.5 |
| Add a table (and keep it monitored) | `_FRESHNESS_SPEC` in `api_server.py` (feeds `/api/db-stats`) **and** `FRESHNESS_SPEC` in `web/lib/freshness.ts` (feeds the navbar chip) — two copies since Phase 5; change both in one edit or the badge and the API disagree (§6.5). Then add its row (label, producer job, affected charts) to `EXACT` in `web/lib/tabs/health.ts` — `tests/health.test.ts` fails on an unmapped fixture key |

### 2.3 Shared helpers (do NOT redefine inline)

Originally module-level in `dashboard.py` (retired in Phase 5). Each now lives as a **TypeScript
port in `web/lib/`** under the camelCase form of the name below (`_mem_yoy` → `memYoy` in
`mem.ts`, `_trace_style` → `traceStyle` in `plotly/figure.ts`, `_IV_SOURCE_META` →
`IV_SOURCE_META` in `iv-source.ts`, …), parity-tested against the frozen `golden.json`. The
freshness/consistency helpers and the two export helpers ALSO exist in Python in
`api_server.py`, because `/api/db-stats` and the exports need them — keep both copies in step.

```text
_CAT_ORDER        dict: category → list of ticker display names
_SHORT_CAT        dict: long cat name → short label (Semi / ETF / Macro / Tech)
_cat_rank         dict: ticker → (cat_index, ticker_index) for sorting
_ticker_cat(t)    → category name for a ticker
_ticker_label(t)  → "TICKER (Category)" label
_compute_hv30(ts) → DataFrame of 30-day historical volatility from daily_prices
_time_rangeselector(active_index) → 1Y/3Y/5Y button dict, pinned above the plot
_apply_rangeselector_layout(fig, legend_bottom=True, extra_height=70)
                  → mandatory partner of the above; see §7.2
_CYCLE_WINDOW=15  argrelextrema order for cycle detection
_build_cycle_chart(ticker) → go.Figure with up/down cycle shading
_sc_dram_inline() → DRAM chart + YoY table embedded in the RAM sub-tab

_trace_style(is_modeled, color, width) → Plotly kwargs for ONE sc_prices trace.
                  Observed = solid line + filled marker; modeled = open marker on
                  a thin dotted connector. Use at EVERY sc_prices plot site (SC-16)
_MODELED_SUFFIX   "  (modeled)" — legend suffix partner of the above
_modeled_note(what) → the standard yellow in-panel disclosure for a modeled chart

_MEM_DIE_GB       dict: product_type → benchmark die capacity in GB (DDR4=1, DDR5=2)
_MEM_COLORS       dict: product_type → line colour, shared by BOTH RAM charts
_MEM_UNIT_LABEL   dict: product_type → native price unit ("$/die" | "$/GB")
_MEM_SPECS        dict: product_type → bandwidth_gbs / capacity_gb / config /
                  bw_basis / class ("Commodity DRAM" | "HBM"). bandwidth bases
                  differ by class (DIMM vs stack) — never show without bw_basis
_MEM_ORDER        list: canonical series order (DRAM first, then HBM gens)
_mem_normalize_usd_per_gb(df) → sc_dram_spot frame + price_usd_gb + period_dt
_mem_yoy(grp, price_col)      → (latest_row, price_1y_ago, yoy_pct); anchored on
                  the SERIES' own latest period, not today, with a 12–15 month
                  lookback floor — see §7.3
_mem_break_gaps(grp, gap_months=3) → inserts a NaN row wherever a series skips
                  more than `gap_months`, so Plotly lifts the pen instead of
                  drawing a straight line across missing data. Apply at EVERY
                  sc_dram_spot plot site; the DDR series has a real 17-month hole

_IV_SOURCE_META   dict: options_iv.source PREFIX → (short label, description,
                  is_published). Matched by prefix because iv_crawler.py appends
                  "(proxy:GLD)" etc. Unknown values pass through unrelabelled
_iv_source_meta(s)    → (short, description, is_published) for one source string
_iv_source_summary(df) → (joined description, all_published) for a whole frame.
                  Drives the Sentiment banner, the Vol Source column, and the
                  navbar IV badge — all three read this, so they cannot disagree.
                  NEVER hardcode a producer name in the UI (see §9 IV-01)

_build_export_workbook() → the multi-sheet .xlsx as a BytesIO. Shared by
                  /api/export-xlsx and /api/export-bundle
_snapshot_db(tmp) → consistent byte-exact DB copy via VACUUM INTO, with a
                  conn.backup() fallback for SQLite < 3.27. Shared by
                  /api/export-db and /api/export-bundle. Both helpers exist so
                  the bundle and the single-file routes cannot drift — do NOT
                  inline a second copy of either (§6.3)

_FRESHNESS_SPEC   dict: table → (date column, granularity, SLA days). Add a row
                  here whenever you add a table — an unlisted table is unmonitored
_SC_PRICE_SLA     dict: sc_prices `source` value → SLA days (live 7 / curated 45)
_SC_DRAM_SLA      dict: sc_dram_spot `product_type` → SLA days. sc_dram_spot is NOT
                  in _FRESHNESS_SPEC — a table-level entry let one fresh series
                  certify a dead one (§9 SC-08)
_SC_DEMAND_SLA    dict: sc_demand_indicators `indicator_key` → SLA days — same
                  per-key pattern as _SC_PRICE_SLA (tsmc/umc 40, nanya 70,
                  korea 20, wsts 75, semi_wwsems 160/quarterly). Each is calibrated
                  to that publisher's OBSERVED lag, not its statutory one
valuation_snapshot_data(tickers) → newest ticker_valuation_history row per ticker
                  (MAX(snapshot_date) self-join). Returns EMPTY, never raises, on
                  a DB predating the table
_valuation_snapshot_panel(tickers) → the Financials tab's point-in-time valuation
                  card. Stamps every row with its "Observed On" date, yellow
                  banner past 4 days, and renders an explanatory blank rather
                  than nothing when the series is empty. Valuation figures go
                  HERE, never in a table headed by a fiscal quarter (§9 F-02)

_sc_demand_panel() → Macro Demand Indicators section (TSMC/UMC revenue, Korea
                  chip exports, WSTS billings, SEMI WWSEMS) — replaced the
                  retired sc_semi_btb panel, see §9 SC-00/SC-06
_period_end_date(v, kind) → the calendar date a period stops describing
                  ("2026-05"→31 May; "2025-Q1"→31 Mar). Month/quarter ages are
                  measured from period END, never start
_freshness_report()  → per-source {rows, max_period, days_stale, sla_days, stale,
                  null_price_pct, empty, unhealthy}. Never raises
_CONSISTENCY_SPEC dict: table → (series key col, period col, value col, source col)
                  for the SC-12 shape checks. Add a row when you add a series
                  table, or its shape is unchecked
_shape_severity(src) → "expected" if the source string says modeled/curated/
                  estimate, else "high". A disclosed estimate with an estimate's
                  shape is not a defect; a *published*-labelled series with one is
_consistency_report() → {flags, high, expected, checked, ok}. Four shape rules:
                  frozen · synthetic_glide (constant Δ) · geometric_glide
                  (constant ratio) · divergence (falls while WSTS YoY > +20 %).
                  Advisory — it flags, it never deletes. Never raises. `ok`
                  tracks HIGH only, and is reported as `shape_ok`, SEPARATE from
                  `data_ok` — see §6.5
_stale_sources(rep)  → sources where `unhealthy` (SLA breach OR ≥50 % empty rows),
                  worst first. Backs both /api/db-stats and the navbar badge —
                  keep them on this one helper so they cannot disagree
```

---

## 3. Architecture

```
crawler.py             ──┐
supply_chain_crawler.py ─┼──► SQLite DB (/data/semiconductor_data.db on Railway volume)
Product/local/ibkr_relay.py (LOCAL) ┘         │
                                    ▼
                    web/ — Next.js (public $PORT, read-only DB)
                               │  proxies /health, /api/*
                               ▼
                 api_server.py (gunicorn, 127.0.0.1:8051 — Flask, no UI)
                               │
                  ┌────────────┼─────────────┐
                POST /api/run-crawl  GET /health   POST /api/upload-iv
                (⚡, keyed)    (uptime)      (IBKR relay receiver)
                                          GET /api/db-stats (auth)
                                          GET /api/export-xlsx (public)
                                          GET /api/export-bundle (public) ◄─ ⬇️ button
                                          GET /api/export-db (public) ──► Product/local/backup_local.sh
```

Design decisions that constrain future work:

- **SQLite, not Postgres** — deliberately simple; one persistent Railway volume at `/data/`.
- **IV is derived in-cloud, not brokered.** `iv_crawler.py` builds a 30-day ATM
  constant-maturity IV from Yahoo option chains (equities/ETFs/indices) and reads Deribit's
  published DVOL index (BTC/ETH). No broker, no subscription, no daemon — it runs in the
  same container as every other crawler. **This is the default IV path.**
- **The IBKR path is dormant, not deleted.** `Product/local/ibkr_relay.py` / `ibkr_options_crawler.py` /
  `/api/upload-iv` still work and write the same schema; they are kept for the case where
  IBKR's own IV model is specifically required (§11). TWS/IB Gateway cannot run in the
  cloud, so that path always needs a local always-on machine — which is exactly why it is
  no longer the default.
- **`startup.sh` is the seed gate.** On boot it counts rows in `daily_prices`; if 0 it
  runs the crawlers, then `exec gunicorn`. This is why the DB survives redeploys only if
  the volume is mounted (see §9).
- **The schedule runs inside the web container, and has to.** `scheduler.py` is launched
  once from `startup.sh` before `exec gunicorn` (before, so `--workers 2` cannot double-fire
  it; backgrounded, so it stays outside the healthcheck window). It **cannot** be a Railway
  cron service: a Railway volume attaches to exactly **one** service, so a sibling service
  cannot reach `/data/`, and putting `cronSchedule` in `railway.toml` would turn *this*
  service into a cron job — Railway skips executions while the process is still running, and
  gunicorn never exits. It is a **watchdog, not a clock**: it asks "is any job past its
  interval?" rather than firing at wall-clock times, so a deploy landing mid-window recovers
  the missed run instead of skipping the day. See §9 F-01.
- **Next.js in front, Flask behind, one container (WEB-01).** A volume attaches to one service,
  so Next runs beside the crawlers and reads `/data/…` directly. `startup.sh` supervises both
  processes and exits non-zero if either dies (Railway restarts the container). Next never writes
  the DB; ⚡ Run Crawl goes Next `/ui-api/run-crawl` → Flask `POST /api/run-crawl` with the key
  server-side. Since Phase 5 there is no Dash fallback: a missing `node` or web build makes
  `startup.sh` exit 1, so a bad build fails its healthcheck and Railway keeps the previous deploy.
  Endpoints stay in Python permanently (pandas/openpyxl workbook, `VACUUM INTO`, the run lock).
- **`healthcheckTimeout=300`** in `railway.toml` gives the first-boot crawl time to finish
  before Railway declares the deploy failed. Do not lower it.

---

## 4. Data Model (SQLite)

**Journal mode is WAL** — every crawler runs `PRAGMA journal_mode=WAL` (readers never block on
a commit). `VACUUM INTO` (i.e. every `/api/export-db` backup) always writes a **DELETE-mode** copy,
so a backup file is not evidence of prod's journal mode (§9, WEB-01 QA).

Created by `crawler.py`:
`daily_prices` (ticker,date PK; OHLCV only — **no** market_cap column) ·
`quarterly_financials` (ticker,period_end PK; income + balance sheet + margins.
`pe_ratio`/`market_cap` are retained-but-always-NULL — they are snapshot figures with no
point-in-time history and live in `ticker_valuation_history`; **never write to them**, F-02) ·
`ticker_valuation_history` (ticker,snapshot_date PK; trailing/forward P/E, TTM EPS, market cap,
shares out, P/B, close. Keyed to the **last trading date**, so weekend re-runs collapse onto one
row. Observed-only, **not backfillable** — same contract as the IV series, §11/IV-03) ·
`market_sentiment` (ticker,snapshot_date PK; iv_current, perf_5d/10d/1m, days_since_large_drop) ·
`cycle_analysis` (ticker,snapshot_date PK; up/down magnitude, duration, vol_diff) ·
`company_info` (ticker PK) ·
`crawl_runs` (audit log; `job` + `note` columns added 2026-08-02 by `job_heartbeat.ensure_schema()`.
`job` DEFAULTs to `'market'`, so pre-existing rows backfill to what they in fact were.
One row per crawler run — this is the heartbeat the schedule and `/health` key on, F-01) ·
`crawl_source_runs` (DH-01, created by `job_heartbeat.ensure_schema()`; one row per **scraper** inside a
`supply_chain` run: `run_id`→`crawl_runs.id`, `source`, `status` `ok`/`no_data`/`error`, `rows_written` =
`total_changes` delta, `error`. Written by `run_source()`; read by the Data Health tab).

Created by `supply_chain_crawler.py`:
`sc_products` · `sc_prices` (product_id,date,source) · `sc_market_share` (Steam GPU share) ·
(`sc_semi_btb` DROPPED 2026-08-02, SC-10 — do not re-create; use `sc_demand_indicators[semi_wwsems_billings]`) ·
`sc_dram_spot` (DDR4/DDR5 monthly; HBM3/HBM3E withdrawn 2026-08-02, keys still registered in `_MEM_*`.
**Mixed curated + live** since SC-15: `crawl_trendforce_spot()` writes rows tagged `SRC_LIVE_SPOT`,
and `load_curated_dram_spot()`'s reconcile excludes that exact string — change one without the other
and every live row is deleted on the next deploy) ·
`sc_fab_metrics` (company,metric_key,detail,period PK; **only figures a company actually
publishes** — revenue, margins, wafer shipments, revenue-mix-by-node, capex, and utilisation
ONLY where stated. Replaced `sc_capacity`, DROPPED 2026-08-02 SC-11 — do not re-create it;
per-node capacity/utilisation is published by nobody. Live writer: `crawl_tsmc_quarterly()`) ·
`sc_demand_indicators` (indicator_key,period PK; TSMC/UMC/**Nanya** revenue, Korea chip exports,
WSTS billings, SEMI WWSEMS billings — genuinely published macro demand series, see §2.3,
SC-06/SC-13. Live crawlers: TSMC, UMC, Nanya).

Created by `ibkr_options_crawler.py` **and written by `iv_crawler.py`** (identical schema,
two producers, distinguished only by `source`):
`options_iv` (latest IV snapshot per ticker) · `options_iv_history` (ticker,date daily IV).
`source` values: `derived-yfinance-atm30[ (proxy:SYM)]` (derived — **not** published),
`Deribit DVOL (published)`, `IBKR`/`relay`. The equity series **cannot be backfilled**
(option chains are point-in-time), so rolling averages are NULL until snapshots accumulate.

**Tickers (33):** 14 semis, 7 ETFs (incl. VIX, A50=ASHR, USD=DXY proxy), 8 tech/mixed,
4 macro (Gold, ^TNX, BTC, ETH). Full list in `config.py`.

---

## 5. Environment & Deployment

| Variable | Set where | Value / note |
|----------|-----------|--------------|
| `DB_PATH` | Railway Variables | `/data/semiconductor_data.db` |
| `RELAY_API_KEY` | Railway Variables | **Never write the value in this file** — it is uploaded to GitHub (§5.0). Read it from Railway → Variables, or `Product/local/.backup_env` |
| `PORT` | auto-injected by Railway | **never set manually** (§7 rule 8) |
| `CLOUD_URL` | local `ibkr_relay_config.json` | the live Railway URL |

**Deploy:** see **§5.0** — `Product/Git_Deploy/` is a git working tree of `main`; agents commit
and push **only** when Simpo explicitly asks, or after asking and getting approval (§7 rule 12).

**Force a fresh crawl:** temporarily rename `DB_PATH` in Railway Variables to a new path
→ redeploy (crawlers run because new DB has 0 rows) → rename back. Railway SSH is
unreliable (closes immediately) — do not depend on it.

### 5.0 Deployment workflow — git, push only on explicit ask or approval (read before you finish any task)

```
Product/Git_Deploy/ (Mac, git work tree) ─[ agent: commit + push — ONLY on explicit ask/approval ]─►
        GitHub SiMori92/Semi_data  main, repo root  ─[ Railway auto-deploys every push ]─►  live URL
```

Since **2026-11-22 (GIT-01)** `Product/Git_Deploy/` is a real git working tree of
`https://github.com/SiMori92/Semi_data` (`origin`, branch `main`). Facts every agent works from:

1. **A push to `main` IS a production deploy.** Railway redeploys on every push. There is no
   staging branch, no CI and no PR gate (§6.4) — the local §6.4 loop is the only check.
2. **When an agent may write to git** (§7 rule 12):
   - *Read-only git is always allowed* in `Product/Git_Deploy/`: `status`, `diff`, `log`, `show`,
     `fetch`, `ls-files` — use them to derive what changed instead of reconstructing it by hand.
   - *Commit and push* happen **only** when Simpo explicitly asks for it in the current
     conversation ("commit and push", "deploy it"), **or** after the agent asks — naming the files
     and the commit message — and Simpo approves. Approval covers that one commit/push only; it
     does not carry over to the next change or the next session. When unsure, ask.
   - Never: `git init`, `--force`/`--force-with-lease` push, history rewrites (`rebase -i`,
     `reset --hard` on pushed commits, `commit --amend` after push), new branches/tags pushed
     without a request, or edits to `.git/config`/credentials.
3. **`Product/Git_Deploy/` is the repo root**, flat and 1:1 (§2.1). `CLAUDE.md` / `BACKLOG.md`
   are the exception: on GitHub they sit at the repo root, here they live at the **project root**.
   The work tree excludes them by **sparse-checkout** (`git sparse-checkout list` →
   `!/CLAUDE.md`, `!/BACKLOG.md`), so there is no second copy inside the deploy folder; stage the
   project-root copies with `sh Product/local/git_stage_root_docs.sh` (`--check` = dry run).
   Never copy the docs into `Product/Git_Deploy/` by hand.
4. **`Semi_data/` (project root) is superseded** by this work tree — a stale 2026-10-30 clone.
   Never edit, commit or push from it.

**The approved commit procedure** (run from `Product/Git_Deploy/`):

```bash
git fetch origin && git status -sb          # must be on main; if behind: git pull --ff-only
                                            # (never merge/rebase over someone else's work without asking)
# run the §6.4 checks on these exact files first
git add <each file by path>                 # NEVER `git add -A` / `git add .` — name every file
git rm  <each retired file by path>         # deletions are now real: they leave production too
sh ../local/git_stage_root_docs.sh          # if CLAUDE.md / BACKLOG.md changed
git diff --cached --stat                    # re-read: exactly the approved set, nothing else
git commit -m "<what + why>"                # end with the session's attribution line, if any
git push origin main                        # = deploy
git log origin/main --oneline -1            # confirm the push landed; report the SHA
```

**Still true from the manual-upload era:** an agent's report names every file added, modified
and deleted (now = `git diff --cached --stat` / the commit SHA, not a hand-typed manifest).
`.gitignore` is now enforced by git, but a `git add` of an explicit path can still override it —
so never name a `DB_Backup/` file, a `*.db`, `.env`, or anything under `archive/` (§7 rule 7).
Simpo may still upload through the GitHub web UI; that is why every procedure starts with
`git fetch` and refuses to proceed when `main` has moved unexpectedly.

**Verification is split across two people.** §12's "deploy is not done until verified" still holds:

| Step | Who | Check |
|------|-----|-------|
| Local test | agent | §6.4 loop — every tab, no page errors, row counts > 0 |
| Approval | Simpo | explicit ask, or "yes" to the agent's named file list + message |
| Commit + push | agent | named files only; `git diff --cached --stat` re-read before commit; report the pushed SHA |
| Build | agent or Simpo | Railway → service → Deployments → latest → build + deploy logs |
| Prod | agent or Simpo | `/health` (`volume_ok`, `crawl_ok`), `/api/db-stats`, click through the changed tabs |

Without an explicit ask or approval, the honest terminal state is still **"ready to commit —
files below"**. An agent that reports "deployed" means it pushed and saw the SHA on `origin/main`.

### 5.1 Durability: the volume guard (read before touching `DB_PATH` or `startup.sh`)

SQLite on a Railway volume has exactly one catastrophic failure mode, and it is silent.
If `DB_PATH` does not resolve inside the mounted volume, `mkdir -p` happily creates the
directory on the container's ephemeral layer; the crawlers re-seed, `/health` returns ok,
and every accumulated row vanishes on the next redeploy with **no visible symptom**.
Railway confirms this: *"having the wrong mount path for your volume would cause data to
be written to ephemeral storage instead of the volume."*

`startup.sh` therefore guards on boot, using `RAILWAY_VOLUME_MOUNT_PATH` (injected at
runtime whenever a volume is attached) plus a device-ID backstop (`stat -c %d`) for the
case where the path looks right but nothing is actually mounted. On failure it **skips the
seed crawl** — a seeded dashboard looks normal, which is precisely what hid the bug — and
exports `SEMI_VOLUME_OK=0` / `SEMI_VOLUME_REASON` to both servers. `api_server.py` reports
it in `/health` + `/api/db-stats`; the Next UI shows it as a red navbar banner (`web/lib/env.ts`).

The deploy stays **up** on failure (200 from `/health`) by design: the dashboard is
read-mostly and still useful, and an outage is a worse trade than a loud banner.

| Variable | Set by | Meaning |
|----------|--------|---------|
| `RAILWAY_VOLUME_MOUNT_PATH` | Railway, at runtime | Mount path; absent ⇒ no volume attached |
| `SEMI_VOLUME_OK` | `startup.sh` | `0` ⇒ ephemeral storage detected |
| `SEMI_VOLUME_REASON` | `startup.sh` | Human-readable cause, shown in the banner |
| `SEMI_ALLOW_EPHEMERAL_SEED` | you, optional | `1` ⇒ seed anyway (throwaway/preview envs only) |
| `SEMI_DISABLE_SCHEDULER` | you, optional | `1` ⇒ do not start the watchdog. Use only if an external Railway Cron drives the crawlers and you want exactly one driver |
| `SEMI_SCHEDULER_TICK_SEC` | you, optional | Watchdog re-evaluation interval; default 900 (15 min) |
| `SEMI_CRAWL_RUN_LOCK` | you, optional | Path of the shared crawl run lock; default `.crawl_run.lock` beside the DB (on the volume) |

**Not all data is equally at risk.** Prices/financials re-crawl from yfinance in ~3 min and
curated supply-chain data re-seeds from `products_config.py` (git). What is *unrecoverable*
is `sc_prices` scraped history, `options_iv_history`, and the per-day `market_sentiment` /
`cycle_analysis` snapshot series.

### 5.2 Backups: `Product/local/backup_local.sh` is the ONLY copy (Hobby plan)

Railway's managed volume backups (service → Settings → Volumes → Backups) are a **Pro-plan
feature**. This project is on **Hobby**, so that control does not exist — there is no second
line of defence behind the local script, and a failure there is an incident, not a chore.

Backups land in **`DB_Backup/`** at the project root. That is the folder contract (§2.1
rule 4), and it is enforced by `BACKUP_DIR` in both `Product/local/backup_local.sh` and the
launchd plist — not by remembering to file the download afterwards. `DB_Backup/` is
production data and never enters a commit (§7 rule 7).

| Layer | What | Restorable? |
|-------|------|-------------|
| `GET /api/export-db` → `*.db.gz` | **The backup.** `VACUUM INTO` snapshot: byte-exact, consistent under concurrent writes | ✅ yes |
| `GET /api/export-xlsx` → `*.xlsx` | Reading copy only. No import path; Excel coerces NULL/int/date on the way out | ❌ **no** |
| `GET /api/export-bundle` → `*.zip` | Both of the above in one archive + a README. What the ⬇️ Download Data button serves | ✅ yes (the `.db` member) |
| Railway volume backups | Pro-only — **not available** | n/a |

**All three export routes are public**, and that is deliberate rather than an oversight:
`/api/export-xlsx` already dumps every table discovered from `sqlite_master`, so the row data
was public regardless. Gating only `/api/export-db` protected schema DDL and indexes while
the contents they describe stayed open — the appearance of a boundary, not a boundary, and
worse than none because it invites the assumption that the data is protected. **If this
dataset ever needs to be private, gate all three; never re-gate just one.**

Cadence is **daily**, matching the un-backfillable snapshot series above, and scheduled with
**launchd** (`Product/local/com.simpo.semibackup.plist`), never cron — cron does not fire while the
Mac is asleep and never catches up (§9). No API key is required; the script still *sends*
`RELAY_API_KEY` if `Product/local/.backup_env` (gitignored) defines one, so it keeps working unchanged
on the day the exports are gated.

The script refuses to keep a download that fails `PRAGMA integrity_check` or falls under a
`daily_prices` row floor, and refuses to *prune* on a >50 % size regression. **Run the
restore drill once** (command block at the foot of the script) — an untested backup is a
hypothesis. There is deliberately **no** `/api/restore-db`: a public route that overwrites
the whole DB behind one static key is a worse risk than the one it mitigates.

**Verify production:**
```bash
curl https://web-production-e3819.up.railway.app/health        # → {"status":"ok","db":true}
curl https://web-production-e3819.up.railway.app/api/db-stats \
  -H "X-API-Key: $RELAY_API_KEY"        # value from Railway → Variables, never hardcoded here
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

### 6.2 Next.js tab pattern (WEB-01; the Dash callback pattern retired in Phase 5)
- Layout (UI-01 Phase 2): `components/Shell.tsx` = sidebar navigation + topbar (`NavStatus`) + one `<main id="main">`; filters live in `components/FilterPanel.tsx`. No Bootstrap — every class is defined in `app/globals.css` (colours only via `tokens.css` variables).
- Page identity (UI-01 Phase 3): `PageHeading.tsx` + `lib/page-headings.ts` supplies one H1 per tab, before filters. `ArtworkHeader.tsx` + `lib/artwork.ts` shuffles local `public/art/` images per tab visit/reload, never per filter or status poll (`semi-artwork-shuffle-v1` session storage). Dockerfile and staging copy `public/` into standalone output.
- Presentation (UI-01 Phase 4): `Badge.tsx` + `lib/presentation.ts` render labelled states; `MetricCard.tsx` is shared by Overview and Health (the latter through `DashTree`’s `semi_ui` node). `Card`/`card()` use `.panel`; section titles, alerts and source footers share classes in `globals.css`. `DashTable` supplies focusable labelled scroll regions and keyboard sort buttons (`aria-sort`).
- Acceptance details (UI-01 Phase 5): Supply Chain tabs use roving keyboard focus and linked tabpanels; Cycles has a named selector. `PlotlyChart` reserves chart height while loading and reports failures with a page-reload action. Artwork fallback is preloaded before its caption appears; total image failure shows an unavailable state.
- Tabs are routed by `?tab=<id>` (`web/lib/params.ts` `TABS`); `app/page.tsx` queries the DB
  server-side and passes plain data to client components (`components/`). Charts are Plotly
  figures built by `lib/plotly/figure.ts` and rendered by `PlotlyChart.tsx`.
- Reuse the §2.3 ports in `web/lib/`; never re-derive a helper inline. URL state is parsed with
  Zod (`parseView`), so a bad query string falls back to a default instead of crashing.
- The UI is **read-only** on the DB (`lib/db.ts`). Anything that writes goes through an
  `api_server.py` route (e.g. ⚡: `/ui-api/run-crawl` → `POST /api/run-crawl` with the key server-side).
- **Add a tab:** a `TABS` entry (`label`, and `tickers: true` if it reads the ticker/date filters — that is what shows the filter panel) + an icon in `ICONS` (`components/Shell.tsx`) + a `PAGE_HEADINGS` entry (`lib/page-headings.ts`) + a `lib/tabs/<name>.ts` builder + a `case` in `page.tsx`; then
  `npm test` and `npm run stage` (§6.4), and click through it in the staged build.

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
are public but must return JSON. Existing routes: `/health`, `/api/upload-iv`, `/api/db-stats`,
`/api/export-xlsx`, `/api/export-bundle`, `/api/export-db`, `/api/run-crawl`. **`POST /api/run-crawl`**
(WEB-01c) is write-class: `X-API-Key` REQUIRED and compared with `hmac.compare_digest`; an UNSET
`RELAY_API_KEY` refuses everything (the older `!= os.environ.get(..., "")` pattern would accept an
empty header). Body `{"jobs": [...]}` (default market + supply_chain) → 202 started · 409 a crawl is
running · 400 unknown job · 401. The ⚡ button is public by nature (BK-02) — the run LOCK, not the key,
is what stops overlap. `/api/db-stats` also reports
per-source data freshness — see §6.5. All three export routes are public; §5.2 explains why
gating only the raw-DB one was security theatre, and why they must be gated together or not
at all.

**`/api/export-bundle`** is what the ⬇️ Download Data button serves: a zip holding the
workbook, the `.db` snapshot, and a README naming which is restorable. It exists because a
single click can only produce **one** download — browsers suppress the second as a popup —
so a bundle is the only way to deliver both. It shares `_build_export_workbook()` and
`_snapshot_db()` with the two single-file routes; **never inline a second copy of either**,
or the bundle and the direct download will silently drift apart.

**`/api/export-xlsx`** streams the whole DB as a multi-sheet workbook (sheet 1 = README with
export timestamp + per-table row counts). Tables are discovered from `sqlite_master`, so a new
table is exported automatically — only add a `_EXPORT_SHEET_NAMES` entry if you want a prettier
sheet label. The ⬇️ button is a plain anchor to `/api/export-bundle` — keep it an anchor;
never buffer a workbook through a client-side fetch/JSON response (the gunicorn `--timeout 120`).

### 6.4 Local dev loop
```bash
# Run from INSIDE the deploy folder: Git_Deploy is what the cloud sees as CWD.
cd "/Users/simpochiu/Projects/Invest-Industry Data Pj/Product/Git_Deploy"
pip3 install -r requirements.txt
python3 crawler.py --quick          # prices + financials (~2 min)
python3 supply_chain_crawler.py
python3 api_server.py               # API → http://127.0.0.1:8051 (UI: npm run stage, below)
python3 ../tests/test_api_contract.py --help   # after any api_server.py change (§2.1 row)
python3 ../tests/test_qa05_passmark.py # regression tests — expect "23 passed, 0 failed"
cd ../next_rebuild && npm test         # web/ parity suite vs the frozen golden.json — expect all passed
npm run stage                          # build the deploy copy of web/ like Railway does
```
Then click through **every tab**, exercise dropdowns/date-pickers/buttons, watch for Next's red
"Application error" overlay and for 500s from `/health` / `/api/*` in the staged build. Validate DB row
counts (all expected tables > 0) before asking to commit, or committing on an explicit ask (§5.0).

Tests live in `Product/tests/` — supplemental, so since 2026-08-23 they no longer ship to
GitHub either — and are **never invoked by `startup.sh`** — the deploy does not run
them, so a failing test cannot block a deploy. That is a deliberate trade (a boot-time test
run would put a scraper regression in the healthcheck window), and its cost is that running
them is on you. Nothing between your edit and production runs a check: there is no CI, no
PR review, and no commit hook — this local loop is the **only** gate. Run it before any
handoff touching the PassMark path.

### 6.5 Data freshness — row counts are not a health signal

Three separate outages (§9: Newegg NULL rows, Steam frozen 17 months, retired SEMI B2B) all
ran with `COUNT(*)` steady or climbing and every status surface green. `_FRESHNESS_SPEC` +
`_freshness_report()` (§2.3) exist so a source that stopped producing is distinguishable from
one that is working. Two independent failures are tracked:

| Flag | Means | Example |
|------|-------|---------|
| `stale` | newest observation older than the table's SLA | Steam survey frozen at 2025-03 |
| `empty` | ≥50 % of rows carry no value (`null_price_pct`) | Newegg writing a NULL row per product per day |
| `unhealthy` | `stale OR empty` — what the badge and `stale_sources` select on | — |

Surfaced in `/api/db-stats` (`freshness`, `stale_sources`, `stale_count`, `data_ok`) and as
the navbar `data-freshness-badge`. Both read the **same** helper — never compute freshness
inline, or the two surfaces will eventually disagree and the badge stops being believed.

### Freshness answers "is it still producing?" — not "is it believable?"

Every data bug found in this project (SC-01 NULL rows, SC-02 frozen Steam, SC-04 falsified
DDR, SC-09 modeled HBM, SC-00 retired B2B) was found by a **human reading the numbers**. On
2026-08-02 the DB simultaneously held WSTS billings at +104 % YoY and a DRAM spot series flat
since 2024-12 — mutually impossible, both individually "healthy", nothing on screen.

`_consistency_report()` (§2.3, SC-12) adds the third leg: shape plausibility. It is **advisory
and severity-split** — a series labelled modeled that looks modeled is disclosed (`expected`);
a series claiming a publisher that looks fabricated is `high`. Reported as `shape_ok`,
deliberately **not** folded into `data_ok`: freshness is a fact, shape is a suspicion, and one
boolean cannot honestly mean both. Adding a series table without a `_CONSISTENCY_SPEC` row
leaves its shape unchecked, exactly as an unlisted table is unmonitored.

Month/quarter periods age from the period **END** (`_period_end_date`), so a May figure is not
"30 days late" on 1 June. When you add a table, add a `_FRESHNESS_SPEC` row: **an unlisted
table is an unmonitored table.** Where a panel shows its own "As of" staleness marker, keep its
threshold and the SLA here in agreement (e.g. Steam: 120 d ↔ 4 months).

---

## 7. 🔴 Hard Rules (each one caused a prior incident — no exceptions)

| # | Rule | Why |
|---|------|-----|
| 1 | Never `ALTER TABLE … ADD COLUMN` without `DEFAULT`/`NULL` | SQLite rejects NOT NULL on non-empty tables → crawler crash on Railway boot |
| 2 | Never rename a DB column/table without a migration script | Callbacks read columns by name → silent NoneType errors across all tabs |
| 3 | *(retired with the Dash UI, Phase 5 — kept so numbering stays stable)* Never register two Dash callbacks with the same Output ID+property | `DuplicateCallbackException` at import → app won't start |
| 4 | *(retired, Phase 5)* Never nest a callback Output inside another callback's Output | Dash 4.x circular-dependency / tab-render conflicts |
| 5 | Never use `python` on macOS — use `python3` | macOS `python` is v2; Railway uses `python` |
| 6 | Never use `X \| Y` union syntax in signatures | Railway may run older Python; use `Optional[X]` |
| 7 | Never put `.env`, `ibkr_relay_config.json`, `*.db`, `DB_Backup/`, `archive/`, or a `semiconductor_data_*/` snapshot in a commit or upload — and never write a secret's **value** into a tracked file, including this one | They are gitignored, but an explicit `git add <path>` overrides `.gitignore`, and the GitHub web uploader ignores it entirely (§5.0) — so name files deliberately. The repo is **PUBLIC**. `RELAY_API_KEY` sat in plaintext in §5 of this file and shipped to GitHub with every upload — redaction does not undo history, so a leak means **rotate** |
| 8 | Never set `PORT` as a Railway Variable | Railway injects it; a manual value crashes gunicorn |
| 9 | Never use `[ ! -s "$DB_PATH" ]` to decide on seeding | A schema-only DB is non-empty (~68 KB) but has 0 rows; use a row-count check |
| 10 | *(retired, Phase 5)* Never put `/` in a Dash component ID | Slashes break Dash's internal URL routing |
| 11 | Never move a `.py`, `startup.sh`, `Procfile`, `railway.toml`, `Dockerfile`, or `requirements.txt` out of `Product/Git_Deploy/`, and never create a subfolder inside it other than **`web/`** (the Next.js app: its own `package.json`, built in the image, started by `startup.sh` after gunicorn moves to an internal port). Nothing under `web/` is imported by Python, nothing outside `web/` is imported by Node, and `web/node_modules`/`.next` never exist locally inside Git_Deploy (build them via `npm run stage`) | Railway builds from the repo root; `startup.sh` invokes crawlers by bare filename and `gunicorn api_server:server` resolves the module from CWD. A move that looks purely cosmetic fails at container boot — *after* the old container is gone. `Product/docs`, `Product/tests`, `Product/local` and `archive/` are safe precisely because nothing at boot references them and nothing in them ships (§2.1) |
| 12 | Never commit or push unless Simpo explicitly asked for it, or approved the named files + message when you asked — and never `git init`, force-push, rewrite pushed history, `git add -A`/`.`, or run git anywhere but `Product/Git_Deploy/` | A push to `main` is a production deploy (Railway), with no CI or review in between (§5.0). Approval covers one commit/push, not the next. Until 2026-11-22 agents ran no git at all; a second history (`git init`) or a stray whole-folder add is how `DB_Backup/` dumps or a stale tree reach the public repo |
| 13 | Never let a file removal ship as a local delete alone | Delete with `git rm <path>` in the approved commit (or, for a GitHub web upload, delete it **in GitHub**). A file removed only from the folder keeps deploying forever — the file-level form of SC-14 (§9). List every `D`/`R` in the file list you ask approval for |
| 14 | Never commit a file from outside `Product/Git_Deploy/` — the only exceptions are `CLAUDE.md` and `BACKLOG.md`, staged by `Product/local/git_stage_root_docs.sh` | The deploy boundary is the folder (§2.1). Uploading a supplemental file puts a second copy of it in production's source of truth, where the next agent reads it as live. The inverse is the sharper edge: a file you *edited* outside `Git_Deploy` did **not** ship, however finished it looks locally |
| 15 | Never move a file without updating every absolute path that names it — launchd plists, cron lines, `_ROOT`/`__file__` lookups, script headers | The 2026-08-23 reorg silently killed both the daily backup (plist pointed at the old `local/backup_local.sh`) and the entire PassMark suite (`_ROOT` resolved to `Product/`, not the deploy folder). Neither raised; both looked filed-away and correct. A move is a **config change**, and the failure surfaces at 09:15 tomorrow, not now (§9) |

### 7.1 The Plotly template anti-pattern (read before touching any chart)

UI-01 charts are light by default, with dark values resolved from the same CSS tokens by
`PlotlyChart`; the template/layout ownership rule below applies in both themes.

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

### 7.2 The rangeselector overlay anti-pattern

Plotly's default `rangeselector` position is *inside* the top-left of the plot area, and the
template's `margin.t=40` leaves no headroom. The 1Y/3Y/5Y buttons therefore render on top of
the series lines, the chart title, and any top-anchored horizontal legend — the bug seen on
the Enterprise CPU chart, where the buttons sat over the legend row.

`_time_rangeselector()` now pins the buttons to `x=0, y=1.03, yanchor="bottom"` (above the
plot). That only works if the figure also reserves the space:

```python
fig.update_xaxes(rangeselector=_time_rangeselector(0), ...)
_apply_rangeselector_layout(fig)                       # ✅ always pair the two
_apply_rangeselector_layout(fig, legend_bottom=False)  # ✅ keep right-hand legend
fig.update_xaxes(rangeselector=_time_rangeselector(0)) # ❌ alone → buttons overlay chart
```

The helper grows `height`, opens `margin.t=95` (title line + button line), and by default
moves the legend below the x-axis so it can never collide. Never re-add a
`legend=dict(orientation="h", y=1.02, …)` next to a rangeselector — that is exactly the
collision this replaced.

---

### 7.3 The retired-series anti-pattern (read before touching any time-series panel)

Some curated series stop being quoted when a product is superseded — `CURATED_DRAM_SPOT`
HBM3 ends 2023-12. Two independent failures follow, and **both render as plausible output**:

1. **Invisible line.** A default x-range of "newest data − 1 year" excludes the whole series.
   Plotly still draws the legend entry, so the chart looks complete and merely appears to be
   missing data. Anchor the default window to cover the *oldest* series you intend to show.
2. **Fabricated 0.0% YoY.** A "1Y ago" lookup filtered on `period <= today − 12 months`
   matches every row of a retired series, so `.last()` returns the latest row itself and the
   delta is a value compared against itself.

```python
_mem_yoy(grp)                                     # ✅ anchors on series' own latest period
df[df.period <= today_minus_12mo].last()          # ❌ retired series matches itself → +0.0%
range=[end - 1y, end]                             # ❌ silently hides any series ending earlier
```

Always surface the observation date (an "As of" column) next to any price so a stale figure
cannot be read as current, and return `"—"` rather than a number when no genuine 12-month
anchor exists. This is the §8 zero-hallucination rule applied to derived metrics.

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
| Data silently stops accumulating; every health signal green | `DB_PATH` outside the volume mount → `mkdir -p` writes to the ephemeral layer; `startup.sh` re-seeds and `/health` `db:true` only checks file existence, so the wipe is invisible | Volume guard in `startup.sh` + `volume_ok` on `/health`/`/api/db-stats` + red navbar banner; seed skipped on ephemeral (§5.1) |
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
| 1Y/3Y/5Y buttons drawn on top of the legend / chart lines | Plotly puts `rangeselector` inside the plot's top-left and `margin.t=40` leaves no headroom; several charts also anchored an `orientation="h"` legend at `y=1.02` in the same spot | Pinned buttons above the plot in `_time_rangeselector()` + new `_apply_rangeselector_layout()` applied at all 10 rangeselector sites (§7.2) |
| Enterprise CPU sub-tab: scatter empty, price chart showed RAM series | `sc_prices_query()` had no `"CPU-Enterprise"` branch — the chained ternary fell through to `RAM_PRODUCTS`, so RAM model_ids were queried; `CPU_ENTERPRISE_PRODUCTS.get(ram_id)` returned `{}` → `cores=None` → every scatter point skipped | Added the `CPU-Enterprise` branch (`dashboard.py` ~L1830). When adding a product category, update **both** `products_config.py` and this dispatcher — the fallback fails silently |
| RAM tab: HBM3 in the legend but no line drawn | `CURATED_DRAM_SPOT` HBM3 ends 2023-12 (superseded by HBM3E), but both RAM charts defaulted to a **trailing-12-month** x-range anchored on the newest data — the whole HBM3 series fell outside the view. Not a data bug; a viewport bug that looks exactly like one | Default range widened to 5Y in `_sc_enterprise_ram_section()` and `_sc_dram_inline()`, `active_index` aligned to the 5Y button. When a series is retired, **always check the default window still covers it** (§7.3) |
| RAM tab: HBM3 YoY reported a false `+0.0%` | The 1Y-ago lookup filtered on `period <= today − 12mo`. For a series whose data stops years ago, every row passes that filter, so `.last()` returned the series' own latest row — comparing a value against itself | `_mem_yoy()` anchors on the series' own latest period with a 12–15 month lookback floor and returns `None` → "—" when no genuine anchor exists (§7.3) |
| DDR4/DDR5 spot series ran ~18x low with the sign inverted, labelled `SRC_PUBLISHED` | 34 rows (2025-01 → 2026-05) decayed in lockstep −1 % to −2 % every month for 17 consecutive months while TrendForce reported conventional DRAM contract prices **+93–98 % QoQ** in 1Q26 and DDR4 1Gx8 3200 spot at **US$36.00** (2026-06-30) vs the US$2.02 the table claimed. A smooth monotonic glide is the fingerprint of extrapolated filler — no spot market moves that way | Rows deleted, not relabelled (a wrong number is worse than no number, §8); one dated TrendForce anchor added. `_mem_break_gaps()` inserts a NaN so Plotly cannot draw a line across the hole, and the panel states the withdrawal. **Check a curated series' month-to-month deltas before trusting it: unnatural regularity is the tell** |
| YoY table printed "+1258.5 %" after the DDR purge | With the fabricated rows gone, DDR4's nearest anchor to 2026-06 was 2024-12 — exactly 18 months back, which the old floor admitted, so an 18-month move was labelled year-on-year | `_mem_yoy()` floor tightened 18 → 15 months; still admits the bi-monthly HBM series. **Widening a lookback to tolerate sparse data silently redefines the metric** |
| RAM tab: DDR4/DDR5 not comparable to HBM | `sc_dram_spot.price_usd` holds two units in one column (USD/**die** for DDR, USD/**GB** for HBM) | `_mem_normalize_usd_per_gb()` divides die prices by `_MEM_DIE_GB` so all series share one USD/GB axis. Any new memory type **must** get a `_MEM_DIE_GB` entry — a missing key silently falls back to 1.0 GB and understates $/GB |
| Capacity bar chart titled "Latest Quarter" but bars spanned two quarters | `groupby(["company","product_type"]).last()` takes each series' own newest row; companies report on different schedules, so `CURATED_CAPACITY` yields a 2024-Q4/2025-Q1 mix presented as one quarter | Per-bar period stamped on x-label, bar text, and hover (+`source`); title shows the actual span; footer states bars are not all the same period (`_sc_capacity_panel`). Any chart built from a per-series `.last()` must show the period per series, never a single global one |
| Steam GPU share frozen at 2025-03 for 17 months; panel looked normal | `crawl_steam_survey()` searched for a `"hardware":"…"` JSON blob the page does not contain (it is server-rendered HTML), found nothing, and wrote 0 rows **without raising**. The HTML fallback would have been worse — it scraped the per-DirectX-class tables, whose percentages are shares *within* a class (Intel HD 4000 ≈ 28 % under DX11) | Section-aware text parser `_parse_steam_survey()` bounded to the "ALL VIDEO CARDS" table; takes the second-to-last column (last is the MoM delta); reads the survey's own month from the heading. **Validation gate** (≥15 entries, shares sum 40–105 %, month parsed) rejects a bad parse and keeps the curated seed rather than writing garbage. "As of" badge on the panel, red at 4+ months (§7.3) |
| Newegg rows accumulated daily but every `price_usd` was NULL; `/api/db-stats` looked healthy | Newegg serves JS-rendered listings behind bot detection, so both parse paths in `_newegg_search_price()` return `None` — and `crawl_newegg()` appended the row anyway. Row count is not a data-quality signal | Write-guard: skip the row when `price is None`; ERROR log when the miss rate ≥50 %; `purge_null_price_rows()` runs each deploy. **Never persist a row when the parse failed — a missing row is honest, a NULL row hides the outage** |
| B2B chart plotted 41 monthly values sourced to "SEMI NA Equipment B2B" | SEMI discontinued the NA Book-to-Bill report after the **Dec-2016** report (NA billings press release ceased Feb-2022); `crawl_semi_btb()` scraped semi.org for a release that hadn't existed in ~9 years, failed silently, and left hand-modelled curated rows looking live | Crawler retired to a no-op stub; all 41 `CURATED_SEMI_BTB` labels → `"Modeled estimate — NOT a SEMI publication"`; yellow in-panel disclaimer. Fix B done: `_sc_btb_panel()` removed, replaced by `_sc_demand_panel()` with real SEMI WWSEMS billings (BACKLOG SC-00/SC-06). **Before trusting a curated series, verify the cited publication still exists** |
| Price chart shows a cliff at a split date | `daily_prices` used `INSERT OR IGNORE`; yfinance re-adjusts *all* history after a split, but IGNORE preserved the stale pre-split rows | Changed to `INSERT OR REPLACE` (`crawler.py` ~L240). Still idempotent — PK is (ticker, date) |
| Chart footers cited "TrendForce"/"Goldman Sachs"/ODP as flat `[Source: …]` for numbers that are actually hand-modeled | Curated tables had no vocabulary distinguishing a genuinely published figure from a derived estimate; footer text named the institution either way | `products_config.py` defines `SRC_PUBLISHED` / `SRC_MODELED`; every `_source_footer()` in the Supply Chain tab states which portion is primary vs. modeled (`§8` zero-hallucination). No `source_url` column added — a fabricated URL for a modeled number is the same violation in a different shape |
| `sc_dram_spot` reported `unhealthy: false` while DDR5 had no observation for 20 months | A table-level `_FRESHNESS_SPEC` entry evaluates `MAX(period)` over every series at once, so it answers "is ANY series fresh?" — one DDR4 anchor certified the whole table. Same defect the per-source `_SC_PRICE_SLA` was built to fix, one level down | Per-`product_type` `_SC_DRAM_SLA`, reported as `sc_dram_spot[ddr5]`. **A table-level SLA is only valid when the table holds one series** — if a table mixes independent series under a type/source/key column, the SLA must be keyed on that column |
| One modeled series appeared twice — as `sc_dram_spot` USD/GB and as `sc_prices` USD/stack — and the second copy read as corroboration | `CURATED_RETAIL_PRICES` HBM rows were `CURATED_DRAM_SPOT`'s per-GB estimate × stack capacity (11.80×48=566, 18.40×96=1766 reproduce them exactly); the retired header said so. Purging only the per-GB series would have left the rescaled twin driving the Enterprise price-index chart | Both deleted together (SC-09). **Before deleting a modeled series, grep for a rescaled restatement of it elsewhere** — a derived copy in different units is not a second source, and unit conversion is enough to hide the shared origin. Era-shading bands are now drawn only for a `product_type` that has data, so a withdrawn series cannot leave a labelled empty band |
| A backup retention policy that could delete the last good copy | `backup_local.sh` validated HTTP 200 + zip magic, but not *content*. If prod re-seeds onto ephemeral storage the export is a well-formed workbook holding a fraction of the history; since pruning keeps the N most **recent** files, N degraded runs evict every good copy — the retention policy becomes the data-loss mechanism | Size-regression guard: new file <50 % of the previous one ⇒ warn and **skip pruning**. **A backup is not verified by its exit code** — check that what it contains is plausible, and never let an automated deletion outrank an unverified write |
| 25 of 26 curated retail series were formula-generated, correctly labelled, and still misleading | `Xeon-8490H` ran 40 consecutive steps at a constant ratio, `R9-7950X` fell exactly −$5.00/month for 12 months. All were honestly tagged `SRC_MODELED`, so no labelling rule was broken — but they were drawn as smooth solid lines beside real ETF and PassMark data, and a reader takes direction and rate-of-change from a line regardless of its footnote | `_trace_style()` (§2.3) renders modeled series as open markers on a dotted connector at every plot site, plus `_modeled_note()` on each chart; consumer charts now overlay curated + PassMark instead of picking one, so where observation begins is visible (SC-16). **A correct provenance label is necessary but not sufficient — the rendering has to carry the same information**, and a chart that picks one of two sources hides the one it drops |
| A whole table's COLUMNS encoded a figure nobody publishes | `sc_capacity.capacity_kwpm` / `utilisation_pct` were per-NODE, and no foundry discloses either at node granularity — so all 31 rows cited earnings releases that did not contain them. SC-05 fixed provenance labels but never reached this table | Table dropped and replaced by `sc_fab_metrics`, a generic `(company, metric_key, detail, period)` shape holding only published figures (SC-11). **Renaming the columns would have preserved the error** — when the schema itself presumes a disclosure that does not exist, migrate the shape, not the labels. Companies whose filings were not opened are left blank on purpose, and the panel says so |
| Deleting falsified rows from `products_config.py` left them live in prod; git said 53 rows, `/api/db-stats` said 87 | The curated loaders are `INSERT OR REPLACE` only. That propagates *corrections* but never *withdrawals* — a row removed from the seed list simply survives on the Railway volume forever. SC-04's retraction of 34 fabricated DDR rows was therefore a no-op in production while reading as complete in the repo | `load_curated_dram_spot()` now **reconciles**: insert, then delete any `(product_type, spec_label, period)` not in `CURATED_DRAM_SPOT`. Safe because no live writer targets `sc_dram_spot`. **A curated table is only truly curated if the loader deletes as well as inserts** — and any table with live writers (`sc_prices`) must scope that delete to `source='curated'` |
| Drafted `CURATED_DEMAND_INDICATORS` rows with `source=SRC_PUBLISHED` for TSMC/UMC/MOTIE/WSTS/SEMI data, caught before shipping | `SRC_PUBLISHED` (`products_config.py`) is a **string constant hardcoded to `"TrendForce (public release)"`** for SC-05's DRAM series — reusing it for unrelated orgs would have mislabeled every TSMC row as TrendForce data. A generic-sounding constant name invites exactly this reuse | Every row now cites the actual org name as a plain string (`"TSMC IR"`, `"UMC IR"`, `"Korea MOTIE / KITA"`, `"WSTS / SIA"`, `"SEMI WWSEMS"`). **`SRC_PUBLISHED`/`SRC_MODELED` are DRAM-specific despite the generic name — never reuse a provenance constant across sources without reading what string it actually contains** |
| **IV-01** Sentiment tab titled panels "Options IV — Snapshot Table (IBKR Real-Time)" and the navbar chip read "⚫ IBKR: disabled" while a perfectly good derived IV series was populating those very panels | The UI hardcoded a *producer* name at ~6 sites and the badge answered "is IBKR enabled?" rather than "does an IV series exist, and where is it from?". Once `options_iv` had two writers with one schema, every hardcoded label became a potential mislabel — the same class as reusing `SRC_PUBLISHED` for non-TrendForce rows | All labels now derive from the row's own `source` via `_IV_SOURCE_META`/`_iv_source_meta()` (§2.3), matched by **prefix** so `(proxy:GLD)` suffixes still resolve; unknown sources pass through unrelabelled rather than being coerced into a known bucket. **A status badge must describe the data, not one possible producer of it** |
| **IV-02** A proxy substitution (Gold→GLD, BRK.A→BRK-B, 10YTreasury→TLT, USD→UUP) was visible only in the crawler's console log | `resolved[display] = (iv, SRC_YF_DERIVED, note)` dropped the proxy symbol, so `options_iv` said "Gold, 22.25%" with no indication the number is GLD's vol. A reader querying the table — or the XLSX export — could not know | Proxy written into the `source` string itself: `derived-yfinance-atm30 (proxy:GLD)`. **A proxy that is only disclosed in a log is an undisclosed proxy** (§8) |
| **IV-03** Nearly wrote IV rolling averages on day one by seeding history from HV30 | `options_iv` has `iv_1m_avg` … `iv_1y_avg` columns, and empty columns look broken, which creates pressure to fill them. But an option chain is point-in-time — Yahoo exposes no historical chains — so the equity IV series genuinely cannot be backfilled | `compute_metrics()` returns `None` until a window has enough real observations; the panel states blanks accumulate daily. Crypto (DVOL) has 400+ days of published history and populates immediately, which makes the contrast visible. **An empty column that says why is honest; a filled one built from a proxy is §7.3 all over again** |
| **F-02** Every historical quarter reported the same P/E and market cap; valuation "history" was a flat line at today's multiple | `crawler.py` fetched `yf.Ticker().info` **once** per ticker and wrote `trailingPE` / `marketCap` into every row of the per-quarter loop, plus an `eps or trailingEps` fallback that put a **TTM** figure into a single quarter (~4x overstatement). The newest row was approximately right, which is precisely what hid it. `_CONSISTENCY_SPEC`'s `frozen` rule — written to catch exactly this shape — covered five supply-chain tables and had never been aimed at `quarterly_financials` | Columns retained but always NULL (Hard Rule 2: `dashboard.py` + `/api/export-xlsx` read this shape by name); snapshot moved to `ticker_valuation_history` keyed on the **observation** date; `eps` now carries the quarter's own Diluted EPS or NULL; `purge_contaminated_valuation_cols()` runs every deploy from `startup.sh` because the writer-side fix alone never reaches rows already on the volume (SC-14 again); `fin_valuation`/`fin_revenue` added to `_CONSISTENCY_SPEC` as a regression trip-wire. **A figure whose only available value is "now" cannot be stored in a table keyed by a fiscal period** — put it in a table keyed by when it was observed, or leave it out |
| **F-01** Data could stop refreshing entirely with every status surface green; the crawl cadence existed only in this file | `startup.sh` runs the full crawlers **only when `daily_prices` is empty** — i.e. once, ever, on a healthy volume. Everything after that depended on a Railway Cron present in **no file in the repo**: invisible to review, unreconstructible from git, and unverifiable. `crawl_runs` could not detect it either — it logged only `crawler.py`, and `last_crawl` returned the newest run of *any* job, so one curated reload per deploy kept it looking recent | `job_heartbeat.py` (`JOB_SPECS` + per-job `crawl_runs.job` heartbeats, all three crawlers now record) and `scheduler.py`, an in-container **watchdog** launched once from `startup.sh` before `exec gunicorn`. It cannot be a Railway cron service (§3: one volume ⇒ one service; `cronSchedule` would convert the web service into a cron job). Keyed on job-run recency, **not** data freshness — driving it off `_FRESHNESS_SPEC` would re-crawl forever whenever a *publisher* went quiet. Exponential retry backoff (1 h→2 h→4 h, capped at the interval) so a broken scraper is not re-launched every tick. Surfaced as `/health.crawl_ok`, `/api/db-stats.overdue_jobs`, and a navbar chip **separate** from the freshness chip — "we stopped crawling" and "they stopped publishing" have different fixes. **A schedule that lives only in a hosting console is not a schedule, it is an assumption** |
| **BK-02** An auth gate that protected nothing, on a button that could not have used it anyway | `/api/export-db` shipped auth-gated on the reasoning that a raw DB is "strictly larger disclosure" than the workbook. It is not: `/api/export-xlsx` is **public** and dumps every table discovered from `sqlite_master`, so the rows were already open — the gate covered schema DDL and indexes and nothing else. The inconsistency was the defect, because a partial gate implies a protection that does not exist. It surfaced only when the ⬇️ Download Data button was asked to serve both files: a plain `<a href>` cannot send `X-API-Key`, and the "fix" of embedding `RELAY_API_KEY` in publicly-served HTML would have leaked the key for `/api/upload-iv`, a **write** endpoint | Gate removed; all three export routes public, with §5.2 stating they must be gated together or not at all. Button repointed at the new `/api/export-bundle` (a zip — one click can only produce one download; browsers suppress the second as a popup). `_build_export_workbook()` + `_snapshot_db()` extracted so bundle and single-file routes share one implementation. `backup_local.sh` now sends the key only when present, so it survives a future gating unchanged. **An inconsistent access control is worse than none — it buys no protection and sells false confidence; and if a public UI element must reach an endpoint, that endpoint cannot be key-authenticated, because the only place to put the key is where everyone can read it** |
| **BK-01** The documented backup strategy named two layers; one was Pro-only and the other was not restorable, so the real count was **zero** | §5.1 called Railway volume backups "the first line of defence" — they are a **Pro-plan** feature and this project is on Hobby, so that layer never existed. The "second" layer pulled `/api/export-xlsx`, and a workbook has no import path: restoring means hand-writing a sheet→SQLite converter that guesses types back (NULL vs `""`, int→float, TEXT dates) against composite PKs, during an outage. Both layers read as controls in the doc; neither could return the database. Compounding it, the schedule was **cron on a laptop** — cron does not fire while the Mac is asleep and never catches up, so the job stops with no error, no mail, no log line (F-01's class again) | `GET /api/export-db` added: auth-gated `VACUUM INTO` snapshot (consistent under concurrent writes, unlike a file copy, which can capture a torn page + unmerged WAL and produce a file that opens fine and is subtly corrupt). `backup_local.sh` now pulls `.db.gz`, verifies `PRAGMA integrity_check` **and** a `daily_prices` row floor before keeping it, and prints the un-backfillable snapshot-table counts. Schedule moved cron → **launchd** `StartCalendarInterval`, weekly → **daily** (matching `options_iv_history`/`market_sentiment`/`cycle_analysis`, which cannot be re-crawled). `backups/`, `*.db.gz`, `Product/local/.backup_env` gitignored — the old xlsx backups were landing in a tracked directory. **A backup format you cannot restore from is an archive, and a plan whose layers you have never exercised is a list of assumptions** — check that the platform feature you are relying on exists on the plan you are actually paying for |
| A repo reorg moved a LOCAL script and silently broke its cron | `Product/local/backup_local.sh` documents its own crontab line as `cd "<project root>" && ./backup_local.sh`. Moving the file into `local/` leaves that cron entry pointing at a path that no longer holds the script; cron's failure goes to local mail nobody reads, so the off-platform backup stops with no signal — the same silent-stop class as F-01 | Path updated in the script header and §2.1, with an explicit "update your crontab" note. **A script that documents its own scheduling is a config file too** — moving it is a config change, and any scheduler referencing it by absolute path must be updated in the same pass |
| **QA-05** Every PassMark price ever stored was PassMark's **Rank** column — RTX-4090 at "$3", RX-7800-XT at "$52" — drawn on the consumer charts in the SOLID *observed* style SC-16 reserves for real measurements | `_parse_passmark_table()` walked cells left-to-right and took the **first** numeric as score and the **second** as price. The real table is `Name │ G3D Mark │ Rank │ Value │ Price (USD)`, so "the second number" is Rank. Undetectable by every existing control: ranks 3–151 sit inside any plausible GPU price band, the rows were never NULL, never stale, and never frozen — `_consistency_report()` caught exactly ONE series (`RX-7800-XT`, whose rank happened to repeat 6 times) out of 126 contaminated rows. PassMark was also the only live scraper with no validation gate | Parser re-addressed **by header text**, so a column insertion is a parse *failure* rather than a silent unit swap, and an unrecognised layout returns `[]` instead of guessing positionally. Five gates in `crawl_passmark()` (catalogue size · never persist a NULL price · price range + 5x drift vs last stored · ≥50 % coverage · **score↔price rank correlation ≤ −0.90**). The correlation gate is the one that actually catches this class: real street prices correlate loosely *positively* with performance, while a rank column is by construction a perfect inverse — it is the **relationship** that is impossible, not the magnitude. `purge_rank_as_price_rows()` condemns whole scrape dates on the same shared test and runs every deploy (SC-14 — the writer-side fix never reaches rows already on the volume). **A range check cannot catch a wrong column whose values happen to be plausible numbers; check the relationship between columns, and address columns by name** |
| **QA-05c** The QA-05 inversion gate + purge shipped, ran on two boots, and deleted nothing — the real prod contamination passed the exact check built to catch it | Both checks pooled GPU and CPU rows. Within each class the rank-as-price data is perfectly inverse (rho −1.0), but PassMark's CPU list is longer, so CPU ranks (134–496) all exceed GPU ranks (3–151) while CPU Mark scores (38k–67k) also exceed G3D scores (16k–38k) — Simpson's paradox lifted the pooled rho to **+0.121**, above the −0.90 trigger. The 18-test suite passed because every fixture was single-class | `_passmark_class_rhos()` — inversion computed per catalogue class at both sites (purge joins `sc_products.category`; Gate 5 uses the product's own category); condemn/reject if ANY class with ≥`_PM_INV_MIN_N`(4) rows breaches. The real pooled 14-model prod pattern is now itself a fixture. **A relationship check is only valid within the population that defines the relationship — ranks are inverse to score only inside the list that assigned them; and a regression fixture must be the real prod shape, not a synthetic simplification of it** |
| Supply chain reasoned about a datacenter-driven market using only consumer-retail proxies (Newegg/PassMark/Steam) | No industry-standard demand series was tracked | Added `sc_demand_indicators` (TSMC/UMC monthly revenue, Korea MOTIE 20-day chip exports, WSTS/SIA billings, SEMI WWSEMS billings). Live crawl only for TSMC/UMC — both IR pages were fetched and confirmed plain server-rendered tables before writing a parser. Korea/WSTS/SEMI are curated-only **by design**: their sources publish as one-off articles or a members-only portal, not a stable per-period table — scraping any of them would repeat the Steam/SEMI-BTB mistake. **Confirm a page is actually a stable table before writing a scraper for it; don't assume "the ticket says start with X" means X is scrapable** (BACKLOG SC-06) |
| **RE-01** The 2026-08-23 folder reorg silently killed the daily backup and the entire regression suite | Two absolute paths were left behind by a move that looked purely cosmetic. `com.simpo.semibackup.plist` hardcodes `.../Claude - Industry Data Pj/local/backup_local.sh`; the script had moved to `Product/local/`, so launchd exec'd a missing file — and its `StandardOutPath` pointed at a directory that no longer existed, so the failure could not even reach the log. `test_qa05_passmark.py` resolved its subject as `dirname(dirname(__file__))/supply_chain_crawler.py`, i.e. `Product/`, while the crawler now lives in `Product/Git_Deploy/` — every QA-05 gate stopped running. Neither raised anything a person would see; the same class as the earlier cron-vs-reorg row, one folder deeper | Plist repointed at `Product/local/` with logs and `BACKUP_DIR` in `DB_Backup/`; the test resolves the deploy folder from a **candidate list** and exits with the paths it tried instead of a bare `FileNotFoundError`. §7 rule 15 added. **Moving a file is a config change** — grep the whole project for its old path, including plists, cron lines, and `__file__`-relative lookups, before calling the move done |
| **RE-02** `requirements.txt` was filed one folder above the deploy set, where the new folder rules classified it "supplemental — no deployment needed" | The reorg put every `.py` in `Product/Git_Deploy/` but left `requirements.txt` at `Product/`. Nothing broke immediately, and that is the trap: manual upload never deletes, so the GitHub copy kept building fine while the local layout said the file did not deploy. The first agent to trust the folder rules would have dropped a dependency change on the floor, or a clean re-upload would have produced a container with no dependencies at all | `Git_Deploy` redefined as an exact 1:1 mirror of the GitHub repo root (§2.1) — `requirements.txt`, `.gitignore`, `.env.example` moved in. **A filing decision is a deployment decision here.** If production runs it, it lives in `Git_Deploy`; the test is "would Railway's build fail without it?", not "is it code?" |
| **WEB-01a** Every chart rendered at 450 px from 2026-10-30 | `_responsive_graph()` set `responsive=True`, so Plotly sized to the `dcc.Graph` container — whose default height is 450 px — and ignored `layout.height`: the 660-px price chart, `_apply_rangeselector_layout()`'s headroom and the per-ticker heatmap height were all squashed. Found only by a pixel-measuring side-by-side | `_responsive_graph()` sets `style.height` from the figure's own `layout.height`. **`responsive=True` makes the container, not the figure, own the height** — always give the container one |
| **WEB-01 QA** Overview tab crashed (`TypeError`) whenever a selected ticker's latest perf value was NULL | Under pandas 3, `DataFrame.astype(str)` keeps NaN as a float, so `... .values + "%"` raised; the KPI path printed `nan%`. No fixture row had a NULL, so it never showed — found by a NULL-injected golden variant | Heatmap text `"—"` for NaN; KPI treats NaN as missing (no delta). **Test with injected NULLs: a fixture with no gaps cannot exercise missing-data rules**, and a dependency major (pandas 2→3) can turn a cosmetic `nan%` into a crash |
| **WEB-01 QA** "Prod SQLite is in DELETE journal mode" — a wrong finding, briefly written into the rebuild prompt | Read from `PRAGMA journal_mode` on a `/api/export-db` backup; `VACUUM INTO` always writes DELETE mode. All crawlers set WAL | Corrected (§4). **A copy made by `VACUUM INTO` is not evidence of the source's journal mode** — check the writer code |
| **WEB-01b** A "pin to what prod runs" `requirements.txt` would have failed the build | The newest numpy/scipy (and pandas 3) need Python ≥3.12/≥3.11; prod's Python version was recorded nowhere (it is 3.11 — the `Dockerfile`, WEB-01e). Caught only by installing on a Python 3.10 machine | Pins per Python version via environment markers, each = what pip resolved at the 2026-10-29 build for that Python; verified installable on 3.9–3.13. **A dependency pin is only reproducible together with the interpreter version it was resolved for** |
| **RE-04** `Git_Deploy` was ~350 lines behind production for 10 days, and `BACKLOG` still listed already-deployed work as "PENDING UPLOAD" | On 2026-10-30 a responsive redesign was committed and pushed from a separate git clone (`Semi_data/`), bypassing `Git_Deploy` entirely. Prod `/health` (scheduler on, heartbeats) proved the 2026-08-09 upload had landed, but nothing recorded it. Meanwhile the backup launchd agent (RE-03 step 1) was never reloaded: **no backup from 2026-08-09 to 2026-11-09**, 92 days of un-backfillable series with no second copy | `Git_Deploy` re-synced to `main@c9db2e4`; `assets/` permitted by rule 11; `Semi_data/` declared read-only reference; fresh verified backup pulled 2026-11-09. **Before trusting a folder as "what's in prod", compare it to `main` — and check the newest file in `DB_Backup/`, not the backup script** |
| **WEB-01d** The cutover's first staged build would have failed its Railway healthcheck: `/health` → **500** through Next | Next.js resolves `rewrites()` at **build** time into `routes-manifest.json`, so `CLASSIC_ORIGIN` set by `startup.sh` at runtime was ignored and the proxy targeted the build-time default `:8050` while gunicorn listened on `:8051`. Found by running the staged standalone server, not by the 84-test parity suite, which never exercises the proxy | One internal port, pinned in three places that say so (`web/next.config.ts`, `web/lib/env.ts`, `startup.sh` `CLASSIC_PORT=8051`, no override); `$PORT=8051` falls back to classic. **A Next.js env var read in `next.config.ts` is a build input, not a runtime setting** — check `routes-manifest.json` for the value you expect |
| **WEB-01e** The first cutover deploy served the classic Dash UI: `!!! node not found — falling back …` | `nixpacks.toml` added Node and the web build, but Railway builds this service from the root **`Dockerfile`** (`python:3.11-slim`, no Node) — `railway.toml`'s `builder = "NIXPACKS"` notwithstanding. The build log's first line says which: "load build definition from Dockerfile". The startup.sh fallback kept the site up, as designed | Web build moved into a `web` stage of the `Dockerfile`; `nixpacks.toml` deleted. Also settled the WEB-01b unknown: prod Python = **3.11**. **Read the build log's first lines before assuming which builder runs — a config file the builder never reads fails silently** |
| **WEB-01f** The Dockerfile `web` stage failed in 8 s at `npm ci` | `better-sqlite3`'s install script is `node-gyp rebuild`. npm 11 (this Mac) skips unapproved install scripts, so every local build ran without it; npm 10 (the `node:22` image) runs it, and `node:22-bookworm-slim` has no compiler. The package ships N-API prebuilds (`prebuilds/linux-x64.node`), which are what actually loads | `npm ci --ignore-scripts` in the Dockerfile, reproducing the tested configuration. **A lockfile's `hasInstallScript` is not the whole story — check `npm install-scripts ls`, and match the npm major the build image uses** |
| **WEB-01g** (Phase 5 QA, local) The staged Next proxy answered `/health` and every `/api/*` with **500** while gunicorn answered directly | Not a code bug: a leftover `next-server` from an earlier test still held `127.0.0.1:3100`; a specific-address bind wins over the new `*:3100` one, so requests went to the stale server, whose rewrite target was a gunicorn that no longer existed. Prod is unaffected — one container, fresh ports | Retested on a free port: all green. **Before reading an e2e failure as a regression, `lsof -nP -iTCP:<port> -sTCP:LISTEN` — two listeners on one port means you are testing the wrong process** |
| **DH-01** A single scraper exception silently cancelled every scraper after it, and per-source failures were invisible | `crawl_supply_chain()` ran 8 scrapers in one `try`: PassMark raising meant Steam, TrendForce and all IR scrapers never ran that week, and `crawl_runs` (one row per JOB) could only say "failed" for the lot — or "completed" when a scraper swallowed its own error and wrote nothing | Each scraper runs through `job_heartbeat.run_source()`: exception caught + rolled back, outcome (`ok`/`no_data`/`error`, rows written) recorded in `crawl_source_runs`, the rest continue. Job = `failed` only when **no** scraper wrote (`finish_job` contract), with the per-source tally in `note`; shown on the 🩺 Data Health tab. **Isolate independent sources inside a job, and log at the granularity you need to diagnose** |
| **RE-05** The daily backup agent was "reloaded" in RE-03 on paper but was never installed; once installed (2026-11-16) launchd exited **126** on its first run | `~/Library/LaunchAgents` had no `com.simpo.semibackup.plist` at all. Installed, its first run failed with `Operation not permitted`: macOS privacy (TCC) blocks launchd's `/bin/bash` from reading `~/Documents`, where the script and `DB_Backup/` live. launchd itself could still write `backup.log`, so the log existing proved nothing | Agent installed; **Simpo must grant `/bin/bash` Full Disk Access** (System Settings → Privacy & Security → Full Disk Access → `+` → ⌘⇧G `/bin/bash`), then `launchctl start com.simpo.semibackup`. **A scheduled job on macOS is not verified until it has written its own output — check exit status (`launchctl list`, column 2) and a new `.db.gz`, not the log file** |

| **GIT-01** `BACKLOG` said WEB-01 Phase 5 was "NOT in prod" a week after it had shipped | Manual web uploads left no trace on this Mac: on 2026-11-16 the Phase 5 files were uploaded and `dashboard.py`/`assets/responsive.css` deleted on `main` (`92e22f4`, `8d95baf`), but nothing recorded it locally — the same blind spot as RE-04 | `Product/Git_Deploy/` became a git work tree of `main` (sparse-checkout excludes the root docs); `git fetch` + `log origin/main` is now the source of truth for what shipped. Agents push only on explicit ask/approval (§5.0, §7 rule 12). **If deploys can happen outside the tool that records them, the record will drift — make the deploy path itself the record** |
| **UI-01 QA** A failed artwork load could display the fallback caption even when its image also failed | Error handling selected the fallback metadata without preloading its image | Preload the fallback before showing its caption; if both fail, show neutral “Artwork unavailable”. Test both selected-image and total-image failure, alongside chart loading/error states |

---

## 10. Maintenance Calendar

| Cadence | Task | Where |
|---------|------|-------|
| **Automatic** | Price + financials crawl (24 h), IV crawl (24 h), supply-chain scrape (7 d) | `scheduler.py` watchdog, driven by `JOB_SPECS` — **no external cron required**. Verify with `/health` → `crawl_ok` or the navbar chip |
| Daily (automated) | Off-platform database backup — **the only backup on Hobby** | launchd → `Product/local/backup_local.sh` (§5.2). Railway volume backups are Pro-only and unavailable |
| Weekly | Glance at `DB_Backup/backup.log` — no new `.db.gz` means the agent stopped | `launchctl list \| grep semibackup` (col 2 = last exit code) |
| Quarterly | **Restore drill** — gunzip the newest backup, `PRAGMA integrity_check`, run the dashboard off it | recipe at the foot of `Product/local/backup_local.sh` |
| Weekly | Glance at the navbar `crawl:` chip — 🔴 means a job stopped succeeding | any page |
| Monthly | Update `CURATED_DRAM_SPOT`, `CURATED_FAB_METRICS`, retail, Steam, demand | `products_config.py` → re-run crawler → commit/push on approval (§5.0) |
| Monthly | Re-verify PassMark/Newegg scraper selectors (DOM drift) | run `supply_chain_crawler.py` locally |
| Quarterly | Review ticker list | `config.py` → re-crawl → commit/push on approval (§5.0) |
| Monthly | Spot-check IV plausibility vs a public quote (e.g. VIX ≈ SPY IV30) | `python3 iv_crawler.py --dry-run` |
| On demand | Enable the dormant IBKR IV feed once TWS configured | §11 |
| On demand | Force full DB rebuild after schema change | rename `DB_PATH` in Railway → redeploy → rename back |

---

## 11. Implied Volatility

### 11.1 Default path — `iv_crawler.py` (cloud-native, no broker)

```bash
python3 iv_crawler.py --dry-run          # compute + print, write nothing
python3 iv_crawler.py --tickers NVDA MU  # subset
python3 iv_crawler.py                    # all tickers (~90 s)
```

- **Equities / ETFs / indices** → 30-day ATM constant-maturity IV interpolated in *total
  variance* across the two expiries bracketing 30 DTE, from Yahoo option chains. **Derived,
  not published** — label accordingly (§8).
- **BTC / ETH** → Deribit DVOL, a genuinely published index, backfilled ~400 days.
- Four tickers have no listed options and use a proxy recorded in `source`:
  `USD→UUP`, `Gold→GLD`, `10YTreasury→TLT`, `BRK.A→BRK-B`.
- **Validation gate:** per-ticker values outside 5–400 % are dropped; if under 60 % of
  tickers resolve the run writes **nothing** and exits 1 (a partial snapshot reads as a
  market event, not an outage). Widening `NEAR_STRIKES` or `SANE_IV_RANGE` poisons the
  series — deep-wing Yahoo quotes carry 200–300 % solver artefacts.
- Boot runs it backgrounded from `startup.sh` (outside the healthcheck window); the real
  cadence is Railway Cron (§10).

### 11.2 Dormant path — IBKR (only if IBKR's own IV model is specifically required)

Requires an always-on local machine running TWS/IB Gateway plus a paid OPRA subscription;
historical IV carries the same entitlement requirement as streaming top-of-book, and paper
accounts return nothing unless market data is explicitly shared to them.

Set `"enabled": true` in `ibkr_config.json`. Requires TWS/IB Gateway locally on port 7497
(paper) or 7496 (live). Test with `python3 ibkr_options_crawler.py --test-connection`. Create
`ibkr_relay_config.json` (gitignored) with `cloud_url`, `relay_api_key`, `tickers`, then run
`python3 Product/local/ibkr_relay.py` after market open (or cron it). Rows land in the same `options_iv`
schema with `source='relay'`, so the UI picks them up with no code change.

The navbar chip (`ibkr-status-badge` — ID kept to avoid a rename, §7 rule 2) no longer
reports IBKR enablement; it reports whichever IV source actually populated the table:
⚫ none / 🟡 derived / 🟢 published, with per-source ticker counts in the tooltip.

---

## 12. Working Agreement Between Agents

Many sessions touch this repo. To hand work off cleanly:

- **Before starting:** read this file + `BACKLOG.md`; claim a backlog item by noting it.
- **While working:** keep edits scoped to one feature/fix; reuse §2.3 helpers; obey §7.
- **After finishing:** if you discover a new failure mode, add a row to §9. If you defer
  work, record it in `BACKLOG.md` with enough detail (file, line, exact change) that the
  next agent doesn't re-derive it. Never leave an edit undocumented — uncommitted work in
  `Product/Git_Deploy/` and anything outside it (docs, tests) is invisible to git history.
- **End with the file list, and push only on an explicit ask or approval** (§5.0, §7 rule 12).
  Finish with the local §6.4 checks plus the changed/added/**deleted** files (`git status`), then
  either commit + push because Simpo asked, or ask for approval naming the files and message.
- **Deploy is not done until verified:** push → watch Railway logs → hit
  `/health` and `/api/db-stats` (§5.0 table).

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
DELIVER:      edited files + file list; commit/push only on explicit ask or approval (§5.0).
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
- A change to the folder contract, the deploy boundary, or the analyst persona → also update
  `Product/docs/PROJECT_INSTRUCTIONS.md` **and tell Simpo to re-paste it** into the Claude
  project's Instructions field. That field is a copy, not a link: it cannot be edited by an
  agent, so an un-flagged change to it is a permanent drift between what the doc says and
  what every future session is actually told.
- A new hard constraint that, if violated, breaks prod → **§7** (reserve for real incidents).
- The architecture or a design decision changed → **§3**.

**Do NOT update when:**

- The change is internal to one function and contradicts nothing already written.
- You'd only be restating what an existing section already covers — link to it (`see §X`) instead.
- You're tempted to add narrative, status notes, or "what I did this session" — that belongs
  in `BACKLOG.md`, not here. (There is no commit message to put it in — §5.0.)

**Rules for the edit itself:**

1. **Smallest correct diff.** Edit the existing line/row; don't append a near-duplicate.
2. **Prefer tables and one-liners** over prose; match the surrounding section's format.
3. **Single source of truth** — a fact lives in exactly one section; cross-reference (`§X`)
   rather than copy.
4. **No churn** — don't reword, reorder, or "tidy" sections you didn't functionally change.
5. **Bump** the "Last structural rewrite" date at the top only for structural changes
   (new/removed/reorganized sections), not for routine row additions.
6. **Treat this file like code:** read before editing, keep the edit scoped, and list
   `CLAUDE.md` in the **same commit** as the code change it documents (§5.0) —
   a doc edit left out of the commit never ships, and the next agent reads the stale copy
   from GitHub as authoritative.

If your task changed nothing this file asserts, leave it untouched — that is the correct
outcome, not a missed step.
