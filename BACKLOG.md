# BACKLOG.md — Open & In-Progress Work

> Companion to `CLAUDE.md`. This file holds work that is **not yet done**: half-finished
> edits, deferred fixes, and prioritized next steps. `CLAUDE.md` stays timeless; anything
> with a "TODO" or "in progress" status lives here.
>
> Convention: when you finish a backlog item, delete its row/section and (if it produced a
> reusable lesson) add a row to `CLAUDE.md §9 Known Issues`.
>
> Last updated: 2026-11-16 (WEB-01 Phase 4 cutover prepared; WEB-01a/b/c confirmed in prod `main@0d1ae85`; backup agent installed but blocked by macOS TCC — RE-05) — earlier: 2026-11-09 11:15 (WEB-01 Phase 3 + QA) — (RE-04: Git_Deploy re-synced to prod `main@c9db2e4`; pending-upload
> table reconciled against live `/health`; fresh backup pulled; WEB-01 Next.js rebuild opened)

---

# 🟡 UPLOAD STATE — reconciled 2026-11-09 against prod

**The 2026-08-09 upload landed** (GitHub `main@89645d9`), and the responsive redesign is live
on top of it (`main@c9db2e4`, 2026-10-30, pushed from the `Semi_data/` clone — §9 RE-04).
Evidence `[Data Last Crawled/Updated: 2026-11-08 22:07 UTC]`: `/health` → `scheduler_on: true`,
`crawl_ok: true`, per-job heartbeats for market/iv/supply_chain; `/assets/responsive.css` → 200.

| Item | State |
|------|-------|
| SC-04/SC-07, F-02, F-01, QA-05, BK-01 code, §5.0/§7 r12–13 | **in prod** (`main@89645d9`). F-02 Financials panel + QA-05 coverage gate: not yet eyeballed in prod — click Financials once |
| RE-01/RE-02 docs + `.gitignore`, plist/test path fixes | local/doc-only; `.gitignore` + `CLAUDE.md`/`BACKLOG.md` **not on GitHub** (see RE-04 manifest) |
| RE-04 sync: `dashboard.py` = `main@c9db2e4`, `assets/responsive.css` | Git_Deploy matches prod — **nothing to upload for code** |

---

## WEB-01 — Next.js / TypeScript / Zod rebuild  (P2, opened 2026-11-09)

Prompt: `Product/docs/NEXTJS_REBUILD_PROMPT.md`. App: **`Product/Git_Deploy/web/`** (moved there
2026-11-16 for cutover). Harness: `Product/next_rebuild/` (supplemental). Findings: `Product/next_rebuild/PARITY_REPORT.md`.
Decisions: D-1…D-8 (2026-11-09); **cutover signed off by Simpo 2026-11-16** (Node in the image,
`startup.sh` change, `nixpacks.toml`, rule-11 `web/` amendment).

| Phase | State |
|---|---|
| 0–3 | done (84/84, 0 browser diffs — 2026-11-09) |
| WEB-01a/b/c + Overview NULL fix | **in prod** — GitHub `main@0d1ae85` (2026-11-15); `POST /api/run-crawl` → 401 unkeyed, confirmed 2026-11-16 |
| 4 — cutover | **in prod** 2026-11-16 (Dockerfile build — §9 WEB-01e/f). Post-deploy checks 1–4 passed (build, boot line, /health + tabs + auth + exports, ⚡ + ⬇️ by Simpo). **Open: check 5** (scheduled backup — blocked on RE-05 Full Disk Access) and **check 6** (Railway memory) |
| 5 — retirement | **prepared + verified locally 2026-11-16, ready to upload** (manifest below). Do NOT upload until Phase 4 check 5 passes — Phase 5 removes the `SEMI_UI=classic` rollback |

### Phase 4 — upload gate + post-deploy checks (Simpo)
**Do not upload until** the backup agent has produced two scheduled `.db.gz` (RE-03 / §9 RE-05:
grant `/bin/bash` Full Disk Access first). Then upload the 2026-11-16 manifest and check:
1. Railway build log: stage `FROM node:22-bookworm-slim AS web` runs; `export_web_config: … matches config.py`;
   `npm ci` + `next build` succeed. (Python = 3.11 from the Dockerfile — WEB-01b's unknown is closed.)
2. Deploy log: `=== UI: next (public :PORT) -> API: gunicorn (internal http://127.0.0.1:8051) ===`.
   If it says `falling back to the classic Dash UI`, the web build did not land — site still works.
3. `/health` → same JSON as before (`volume_ok`, `crawl_ok`); `/api/db-stats` with key → 200.
4. Open the site: every tab renders; ⚡ Run Crawl toast; ⬇️ Download Data zip downloads.
5. Next day: a scheduled `backup_local.sh` run succeeds against the new front door.
6. Railway → Metrics: memory headroom (expected ≈ 175 MB Node + ~416 MB × 2 gunicorn).
**Rollback (no upload needed):** Railway Variable `SEMI_UI=classic` → redeploy. Full rollback:
restore the pre-cutover `startup.sh` (`archive/_to_delete/…` not needed — the classic branch is the
old line verbatim) and restore the pre-cutover `Dockerfile` (single `python:3.11-slim` stage) + delete `web/` **in GitHub** (`D`).

### Phase 5 — retirement (done locally 2026-11-16; NOT in prod)
What changed: `api_server.py` (Flask only) holds every route, extracted verbatim from `dashboard.py`
with the helpers the routes use; `startup.sh` runs `gunicorn api_server:server` internally and has
**no classic branch** (missing node/web build or `PORT=8051` → exit 1); `requirements.txt` drops
dash / dash-bootstrap-components / plotly and pins flask 3.1.3 + werkzeug 3.1.9 directly;
`dashboard.py` + `assets/responsive.css` archived to `archive/dashboard_phase5_20261116/` together
with the exact pre-Phase-5 prod `startup.sh` / `requirements.txt` / `Dockerfile` (= the rollback).
`golden.json` frozen; `golden_dump.py`, `test_responsive_smoke.py` and the Dash-vs-Next QA scripts archived.

Verified: `Product/tests/test_api_contract.py` 21/21 on 4 DBs; Python 3.11 venv without dash/plotly
→ every module imports, test_run_lock 18/18, PassMark 23/23; `npm test` 84/84; staged real
`startup.sh` on a copy of the 2026-11-16 live bundle → /health identical via Next + gunicorn, all 6
tabs draw every chart in a browser, auth 401s, exports correct, ⚡ crawl ran (35/35 + full supply
chain) with "already in progress" on a 2nd click, `backup_local.sh` unedited → integrity ok, startup
exits 1 with no web build / on PORT=8051, clean SIGTERM teardown.

Intentional behaviour differences: GET `/api/run-crawl` → 405 (was Dash's catch-all 200 page —
neither starts a crawl); the bundle README's local-run hint names `api_server.py`.

**Upload gate:** Phase 4 check 5 (a scheduled `backup_local.sh` `.db.gz` from launchd). Then upload
the 2026-11-16 Phase 5 manifest and check: build log `pip install` has no dash/plotly; boot line
`=== UI: next (public :PORT) -> API: gunicorn api_server (internal http://127.0.0.1:8051) ===`;
`/health`, tabs, ⚡, ⬇️ as in Phase 4; Railway memory drops (no Dash/Plotly in the 2 workers).
**Rollback:** upload `archive/dashboard_phase5_20261116/Git_Deploy/{dashboard.py, assets/responsive.css,
startup.sh, requirements.txt, Dockerfile}` back to the GitHub root (README there). `api_server.py` can stay.

Follow-up (P3): freshness/consistency logic now exists twice — `api_server.py` (for `/api/db-stats`)
and `web/lib/freshness.ts` / `consistency.ts` (navbar chips). Either make the chips read
`/api/db-stats` through the proxy, or add a contract check that the two agree on the live DB.

### Resolved 2026-11-16: prod Python is 3.11
The Railway build log shows `FROM python:3.11-slim` (the `Dockerfile` — §9 WEB-01e), so prod runs
pandas 3 and the TS `_compute_hv30` port (pandas-3 semantics) matches it. Remaining nit: WEB-01b's
"verified installable on 3.9–3.13" is wrong for 3.9 (`yfinance==1.7.0` → `curl_cffi>=0.15` needs ≥3.10);
fix the `requirements.txt` header comment next time it is touched. Not a prod issue.

---

## RE-03 — folder reorg: manual steps Simpo must run  (P0, 2026-08-23 — STILL OPEN 2026-11-09)

> **2026-11-09:** confirmed step 1 never ran — `DB_Backup/` had nothing newer than 2026-08-09
> and no `backup.log`. A manual verified pull was taken (`semiconductor_data_20261108_1803.db.gz`,
> integrity ok, 48,524 `daily_prices` rows) but **the daily agent is still not running.**
> Also note: the GitHub repo is **public** (API returns 200 unauthenticated). No
> `RELAY_API_KEY` value was found in its history (checked 2026-11-09).

> **2026-11-16:** the plist had never been copied into `~/Library/LaunchAgents`. An agent installed and
> loaded it; the first run exited **126** (`Operation not permitted` — macOS TCC blocks launchd's `/bin/bash`
> from `~/Documents`). **Remaining for Simpo:** System Settings → Privacy & Security → Full Disk Access →
> `+` → ⌘⇧G `/bin/bash` → enable; then `launchctl start com.simpo.semibackup` and check
> `launchctl list | grep semibackup` shows `0` and a new `DB_Backup/*.db.gz` appears (CLAUDE.md §9 RE-05).

Code and docs are done on disk. These three cannot be done by an agent:

1. **Reload the launchd backup agent.** It has been exec'ing a path that no longer exists
   since the reorg, so the ONLY backup (Hobby plan, `CLAUDE.md §5.2`) has produced nothing.
   ```bash
   cd "/Users/simpochiu/Documents/Claude - Industry Data Pj"
   launchctl unload ~/Library/LaunchAgents/com.simpo.semibackup.plist 2>/dev/null
   cp Product/local/com.simpo.semibackup.plist ~/Library/LaunchAgents/
   launchctl load  ~/Library/LaunchAgents/com.simpo.semibackup.plist
   launchctl start com.simpo.semibackup          # don't wait for 09:15 to find out
   tail -f DB_Backup/backup.log
   ```
   Expect a new `DB_Backup/semiconductor_data_*.db.gz`. `launchctl list | grep semibackup`
   → column 2 is the last exit code; 0 is good.

2. **Decide what happens to `docs/`, `tests/`, `local/` in GitHub.** They are supplemental
   now (`§2.1`), so they no longer upload — but manual upload cannot delete, so the
   pre-reorg copies sit in the repo forever, looking authoritative to anyone who clones.
   Either delete those three folders **in GitHub** (flag as `D` in a manifest), or accept
   them as frozen. Until then this Mac is the only copy of `Product/tests` — the only
   regression gate there is (`§6.4`).

3. **Restore drill** — still open from BK-01. Recipe at the foot of
   `Product/local/backup_local.sh`. An untested backup is a hypothesis.

**Consequence:** the next upload is not an incremental change — it is the **first deploy of
every one of the above at once**. Deploy them in the order above and check `/health` and
`/api/db-stats` between batches if possible; a single combined upload means a boot failure
gives you six suspects instead of one. Delete a row here the moment it is confirmed in prod.

**`RELAY_API_KEY` was exposed.** It sat in plaintext in `CLAUDE.md §5` and shipped to GitHub
with every prior upload. Redacted 2026-08-09 — but redaction does not remove it from commit
history. **Rotate it** (Railway → Variables → redeploy → update `local/.backup_env`) if the
repo is or ever was public.

---

# 🔴 Data-Source Audit — 2026-08-02

Findings from a full review of every data source feeding the DB, verified against the live
export (`/api/export-xlsx`) rather than row counts alone. Row counts were green for all
three P0 items — **`/api/db-stats` cannot currently distinguish "175 rows of data" from
"175 rows of NULL"**. Same silent-green failure class as the volume bug (`CLAUDE.md §5.1`).

Evidence snapshot `[Data Last Crawled/Updated: 2026-08-01 23:25 UTC]`:

| Table / source | Rows | Latest date | State |
|---|---|---|---|
| `daily_prices` / `quarterly_financials` / `market_sentiment` | 46,045 / 154 / 209 | 2026-08-01 · 2026-06-30 · 2026-08-01 | ✅ current |
| `sc_prices` source=`passmark` | 98 | 2026-08-01 | ✅ 98/98 priced |
| `sc_prices` source=`newegg` | 175 | 2026-08-01 | 🔴 **0/175 priced** — SC-01 |
| `sc_prices` source=`curated` | 956 | 2026-05-01 | 🟠 3 months stale — SC-04 |
| `sc_market_share` (Steam) | 22 | **2025-03** | 🔴 17 months stale — SC-02 |
| `sc_semi_btb` | 41 | 2026-05 | 🔴 **source discontinued 2016** — SC-00 |
| `sc_capacity` | 31 | **2025-Q1** | 🔴 5 quarters stale — SC-04 |
| `sc_dram_spot` | 86 → **53** | 2026-05 → **2026-06** | 🔴→✅ **34 rows were falsified (~18x low, sign inverted) — deleted, real anchor added (SC-04)** |
| `sc_demand_indicators` (new, SC-06) | 19 | 2026-06 (TSMC/UMC) · 2026-Q1 (SEMI) | 🟢 all rows genuinely published; WSTS/SEMI show as stale — real gap, not a bug |

**Status 2026-08-02:** SC-01, SC-02, SC-03, SC-05, and SC-06 closed; SC-00 fully closed (fix A +
fix B — SEMI WWSEMS now live in the new demand-indicators panel, retired B2B panel removed).
SC-04 and SC-07 unclaimed. **Not yet pushed — the fixes above are on disk only.**

The three data bugs shared one root cause: a source that stops producing is indistinguishable,
in this codebase, from one that is working. SC-03 closed that class — per-source freshness and
empty-row rates now surface in `/api/db-stats` and the navbar. **Expect the badge to read 🔴 on
first deploy**; the backlog it names is SC-04.

---

# 🔴 Data-Source Audit Round 2 — 2026-08-02 (analyst review)

Second pass, reviewing the sources themselves rather than the pipeline. Round 1 asked
*"is the crawler writing rows?"*; round 2 asks *"is the number in the row the number the
industry publishes?"* — and cross-checked three series against their primary releases.

**Verified correct** `[Data Last Crawled/Updated: 2026-08-02 13:55 UTC]`:

| DB value | Primary source | Match |
|---|---|---|
| `wsts_billings` 2026-05 = $120.6 B (Apr $110.5 B) | SIA/WSTS: $120.6 B, +9.2 % MoM, +104.1 % YoY vs $59.1 B | ✅ exact |
| `korea_chip_exports_20d` 2026-07 = $22.1 B, +180 % | MOTIE/KITA via Korea Herald 2026-07-21: $22.113 B, +180 % | ✅ exact |
| `tsmc_revenue` / `umc_revenue` 2026-06 | TSMC IR (rel. 2026-07-13) / UMC IR (rel. 2026-07-06) | ✅ live scrape, on-cadence |

**The macro/demand layer is sound.** Everything below is the price and capacity layer, where
the DB currently contradicts the demand layer sitting in the same database: WSTS shows
+104 % YoY billings while `sc_dram_spot` shows DDR5 unchanged since 2024-12. Nothing in the
UI flags that contradiction. SC-08 → SC-13 close it.

Only P0/P1 items are ticketed here — P2 source-upgrade ideas (licensed market data to replace
yfinance, CBOE/ORATS EOD IV, SEMI SMG wafer shipments, retiring Newegg, demoting Steam to a
labelled consumer proxy) are deliberately left out; raise them after SC-08…SC-13 land.

---

# 🔴 Investor-Fitness QA Review — 2026-08-02 (round 3, external)

Third pass, from an investor's seat rather than the pipeline's: *does a decision-maker get an
accurate, current answer?* Rounds 1–2 audited the supply-chain tables. **Round 3 found the
equity side had never been audited at all** — and the shape checks built in SC-12 had never
been pointed at it. Full report: `QA_Review_Investor_Fitness_2026-08-02.md`.

| ID | Finding | Sev | Status |
|---|---|---|---|
| **F-02** | `quarterly_financials.pe_ratio` / `market_cap` held a snapshot of *today* in every historical quarter; `eps` fell back to a TTM figure | P0 | ✅ **DONE 2026-08-02** — see below |
| **F-01** | Full crawl runs only when `daily_prices` is empty; all ongoing refresh depends on a Railway Cron that **exists in no file in this repo** | P0 | ✅ **DONE 2026-08-02** — see below |
| **F-05** | `/api/export-xlsx` is public and its README carries only row counts — every SC-05/SC-16 provenance label is UI-only and dies on export | P1 | 🔴 OPEN — QA-02 |
| **F-06** | Financials footer claims "SEC EDGAR filings" (yfinance scrapes Yahoo, vendor-normalised) and "5 years" (actually ~5 quarters) | P1 | 🔴 OPEN — QA-03 |
| **F-07** | `ar_turnover` / `inventory_turnover` are un-annualised quarterly ratios on period-end balances — ~4x off convention, charted unqualified | P1 | 🔴 OPEN — QA-04 |
| **F-08** | `crawl_passmark()` is the only live scraper with no validation gate; scraper failure is loud in logs, invisible on screen | P2 | 🔴 OPEN — QA-05 |
| **F-03/F-04** | 24 of 26 curated retail series still formula-generated and 93 d stale; demand indicators hold 1–6 observations each | P1 | 🔴 OPEN — folds into SC-04 |

---

## ✅ QA-F02 — Snapshot valuation written into every historical quarter — **DONE 2026-08-02**

```
TITLE:        Stop writing snapshot P/E, market cap and TTM EPS into quarterly_financials
TYPE:         bug                                    PRIORITY: P0 blocker — CLOSED
```

**WHAT WAS WRONG:** `crawler.py` fetched `yf.Ticker().info` once per ticker, then wrote
`trailingPE` and `marketCap` from that single snapshot into **every row** of the per-quarter
loop, plus `eps or info["trailingEps"]` — injecting a trailing-twelve-month figure into a
single quarter. P/E and market-cap history were a flat line at today's value. The newest row
was approximately correct, which is why it survived every prior review.

**FIX APPLIED** (schema + destructive-write gates cleared with Simpo first, `CLAUDE.md §1`):

- New `ticker_valuation_history` (ticker, snapshot_date PK) — trailing/forward P/E, TTM EPS,
  market cap, shares outstanding, P/B, close. Written from the `info` dict
  `fetch_and_store_financials()` **already** holds, so zero extra network calls, and placed
  *before* the `income.empty` early return so ETFs/crypto get a snapshot too.
- Keyed on the **last trading date** (`_last_price_date()`), not wall clock: a Saturday and a
  Sunday run both describe Friday's close and collapse onto one row instead of manufacturing
  two "independent" observations of a shut market.
- All-NULL guard: nothing resolved ⇒ no row. A row of NULLs is the SC-01 shape — it inflates
  `COUNT(*)` and reads as a healthy crawl.
- `quarterly_financials.pe_ratio` / `market_cap` now written as NULL. **Columns retained, not
  dropped** (Hard Rule 2 — `dashboard.py` and `/api/export-xlsx` read this shape by name).
- `purge_contaminated_valuation_cols()` + `crawler.py --purge-only`, wired into `startup.sh`
  on every boot, **outside** the row-count gate. Necessary because the writer-side fix alone
  never reaches rows already on the volume — the exact SC-14 lesson. Updates only those two
  columns; the genuine revenue/margin figures in the same rows are untouched.
- `dashboard.py`: P/E and market cap removed from "Latest Quarter Summary"; new
  `_valuation_snapshot_panel()` renders them with an explicit **"Observed On"** column, a
  yellow banner past 4 days, and an explanatory blank (not silence) while the series is empty.
- Monitoring gap closed: `ticker_valuation_history` added to `_FRESHNESS_SPEC` (4 d, tracks
  `daily_prices`); `fin_valuation` + `fin_revenue` added to `_CONSISTENCY_SPEC`.

**KNOWN LIMIT, stated rather than overclaimed:** the `frozen` rule needs `_FLAT_MIN_POINTS`
(6) identical values and yfinance returns ~5 quarters, so on a freshly-seeded DB the new
trip-wire is *armed but cannot yet fire*. `quarterly_financials` accumulates across crawls, so
it becomes effective at 6+ quarters per ticker — it guards against reintroduction, it would
not have caught the original.

**VERIFIED:** fixture DB seeded with the exact contamination (pe=24.7 / cap=$198B across 5
quarters × 2 tickers). Purge NULLs 10/10 rows, is a no-op on second run, and leaves revenue
varying across all 5 quarters. Snapshot writer is idempotent (2 writes → 1 row), skips the
all-NULL case, and falls back correctly for a ticker with no price history. Partial-NULL rows
render "—" per field. `crawler.py`/`dashboard.py` byte-compile; `startup.sh` passes `sh -n`.
**Not yet deployed — local only. `dash` is unavailable in the review sandbox, so the
Financials tab has NOT been rendered; click it before pushing.**

---

## ✅ QA-01 — The refresh schedule existed only in documentation — **DONE 2026-08-02**

```
TITLE:        Put the crawl schedule in the repo and surface last-successful-crawl per crawler
TYPE:         bug                                    PRIORITY: P0 blocker — CLOSED
```

**WHAT WAS WRONG:** `startup.sh` runs the full crawlers only when `daily_prices` has 0 rows —
once, ever, on a healthy volume. Every subsequent refresh depended on a Railway Cron present in
**no file in this repo**. `crawl_runs` could not detect the gap either: only `crawler.py` wrote
to it, and `last_crawl` returned the newest run of *any* job, so one curated reload per deploy
kept it looking recent while nothing was being crawled.

**THE CONSTRAINT THAT SHAPED THE FIX** (verified against Railway's docs, not assumed):

- **A Railway volume attaches to exactly ONE service.** The textbook answer — a sibling cron
  service in the same repo — physically cannot reach `/data/semiconductor_data.db`.
- **`cronSchedule` in `railway.toml` applies to *this* service.** Adding it would convert the
  web service into a cron job; Railway requires a cron service to exit and skips executions
  while one is still running, so gunicorn would take the dashboard down *and* the schedule
  would never fire.

So the cadence has to run inside the container that holds the volume.

**FIX APPLIED** (schema + `startup.sh` gates cleared with Simpo first, `CLAUDE.md §1`):

- **`job_heartbeat.py`** — `JOB_SPECS` (market 24 h · iv 24 h · supply_chain 7 d) plus
  heartbeat read/write helpers. `crawl_runs` gains `job` (`DEFAULT 'market'`, so existing rows
  backfill to what they were — Hard Rule 1) and `note`. All three crawlers now record.
  `supply_chain_crawler.py --curated-only` records under a **distinct** job name so a container
  that only reboots can never look like one that is crawling.
- **`scheduler.py`** — watchdog launched once from `startup.sh` *before* `exec gunicorn`
  (before, so `--workers 2` cannot double-fire it; an flock backstops a manual second start).
- **Watchdog, not wall-clock cron.** It asks "is any job past its interval?", so a deploy
  landing at 06:05 recovers the missed 06:00 run instead of skipping the day — otherwise F-01's
  failure shape simply returns in a new costume, and this container restarts on every deploy.
- **Keyed on job runs, not data freshness.** Deliberate: `_FRESHNESS_SPEC` goes red when a
  *publisher* stops releasing, and driving the scheduler off it would re-crawl TrendForce
  forever the moment TrendForce went quiet. Freshness is about the world, heartbeats about us.
- **Retry backoff** (1 h → 2 h → 4 h, capped at the job's interval) — caught in testing: without
  it a permanently failing scraper is due on *every* tick and gets re-launched every 15 minutes
  against a source already refusing us.
- **Status is honest about partial success.** A market crawl resolving <50 % of tickers, and an
  IV run aborted by its coverage gate, both record `failed`. A heartbeat that goes green on a
  degraded run certifies the outage instead of reporting it.
- **Surfaced three ways:** `/health` → `jobs` / `overdue_jobs` / `crawl_ok` (unauthenticated, so
  an uptime probe can see it), `/api/db-stats` → same fields, and a navbar `crawl-status-badge`
  **separate** from the freshness chip — "we stopped crawling" and "they stopped publishing"
  have different fixes and must not share one light.
- `SEMI_DISABLE_SCHEDULER=1` kill-switch if you'd rather keep an external cron as sole driver.

**A TIMEZONE REGRESSION WAS CAUGHT IN TESTING AND FIXED:** the heartbeat first wrote UTC, but
`_crawl_timestamp()` reads `crawl_runs.finished_at` and stamps it "HKT" onto **every**
`[Data Last Crawled/Updated]` footer in the UI. That would have shifted every timestamp in the
product by 8 hours. `job_heartbeat._now()` now uses `config.now_hkt`, matching the storage
convention of every other table, with a comment saying why.

**VERIFIED:** fixture DB carrying a legacy pre-`job` `crawl_runs` — ALTER succeeds against
existing rows and backfills `job='market'`; `ensure_schema()` idempotent. A DB whose last crawl
was 2026-05-01 correctly reports market **2242 h overdue** (F-01 made visible). Dry-run writes
no heartbeats; a real tick runs jobs in dependency order (market first — sentiment, cycles and
valuation all derive from it); succeeded jobs drop out of `due` on the next tick; a failed run
never enters `last_success`; backoff suppresses retries and caps at 24 h; a success clears the
streak; flock rejects a second instance; kill-switch honoured; heartbeat clock drift vs
`now_hkt` = 0 s. All files byte-compile, `sh -n startup.sh` passes, no duplicate Dash Outputs.

**NOT YET DEPLOYED — local only.** `dash` is unavailable in the review sandbox, so the navbar
chip has not been rendered. On first deploy expect the chip to read **🔴 crawl: 3 overdue** and
the watchdog to immediately run all three jobs — that is correct behaviour against a database
that genuinely has not been crawled, not a fault.

**FOLLOW-UP (not blocking):** `_crawl_timestamp()` still returns the newest completed run of
any job, so a supply-chain run can stamp the footer on a price chart. Now that `job` exists it
should filter by the job that produced the data being footnoted.

---

## 🔴 QA-02 — Provenance dies at the export boundary

```
TITLE:        Carry provenance + freshness into /api/export-xlsx, and authenticate it
TYPE:         bug                                    PRIORITY: P1
```

**WHAT / WHY:** the README sheet carries table / rows / columns / truncation and nothing else.
The whole SC-05 + SC-16 apparatus — `SRC_MODELED` labels, dotted modeled traces, yellow
notices, "As of" badges — exists only in the Dash UI. The workbook is what gets emailed and
pasted into a model, and it arrives with 908 synthetic retail prices in the same visual
register as real OHLCV. The endpoint is also unauthenticated.

**WHERE:** `dashboard.py` `export_xlsx()` (~L4838-4900).

**FIX:** add a `PROVENANCE` sheet from `_freshness_report()` + `_consistency_report()` +
per-source published/modeled/derived status; prefix modeled sheets `MODELED_`; require
`X-API-Key`.

**DONE-WHEN:** a reader who opens only the workbook can tell which numbers are observed and
which are this project's estimate.

---

## 🔴 QA-03 — Financials tab misstates its own source and coverage

```
TITLE:        Correct the Financials footer — not EDGAR, not 5 years
TYPE:         bug                                    PRIORITY: P1
```

`dashboard.py` ~L1461 claims "sourced from SEC EDGAR filings via yfinance" (yfinance scrapes
Yahoo Finance; vendor-normalised, Refinitiv-lineage — no primary-filing chain of custody) and
"up to 5 years of quarterly data" (`quarterly_income_stmt` returns 4–5 columns; the audit
snapshot shows 154 rows ÷ ~31 tickers ≈ 5 quarters). This is SC-05 — naming an authority the
project does not source from — inside the project's own UI. One-line fix, both strings.

---

## 🔴 QA-04 — Turnover ratios are quarterly, labelled as turnover

```
TITLE:        Annualise AR / inventory turnover, or rename them
TYPE:         bug                                    PRIORITY: P1
```

`crawler.py` ~L305: `ar_turn = revenue / ar` and `inv_turn = cogs / inv`, both quarterly and
both on period-end rather than average balances — ~4x below the figure any analyst benchmarks
against, charted as "Accounts Receivable Turnover" / "Inventory Turnover" with no qualifier.
Inventory turns are a primary semiconductor cycle-turn signal. Either annualise with average
balances or rename to `*_turnover_quarterly`; silently non-standard is the one option that
isn't acceptable. Same block: `gm = gp/revenue if revenue and gp` discards a legitimate zero
gross profit as missing.

---

## 🟠 QA-05 — `crawl_passmark()` has no validation gate — **DEPLOYED & VERIFIED IN PROD 2026-08-09 (incl. QA-05c); alerting half still open**

```
TITLE:        Add a parse-validation gate to crawl_passmark(), and alert on crawler errors
TYPE:         bug                          PRIORITY: P2 → P0 (evidence, 2026-08-09)
```

> **Re-rated on evidence, then fixed. The ticket understated it: PassMark has never
> recorded a single real price.**
>
> `/api/db-stats` flagged one HIGH shape flag — `sc_prices[RX-7800-XT]` frozen at 52.
> Pulling the export showed the whole column is PassMark's **Rank**, on all 9 scrape
> dates, perfectly inverse to score:
>
> | Model | score | stored "price" | actual meaning |
> |---|---|---|---|
> | RTX-4090 | 38,042 | $3 | rank 3 |
> | RX-7800-XT | 24,428 | $52 | rank 52 |
> | Arc-B580 | 16,037 | $151 | rank 151 |
>
> Cause: `_parse_passmark_table()` took the first numeric as score and the second as
> price; the real table is `Name │ G3D Mark │ Rank │ Value │ Price (USD)`. Confirmed
> against the live page's header row on 2026-08-09.
>
> **Why nothing caught it:** ranks 3–151 are plausible GPU prices, the rows were never
> NULL (SC-01 clean), never stale (SC-03 clean), and never frozen (SC-12 saw 1 of 126).
> And PassMark is the **observed** series SC-16 overlays on the modeled curated curves —
> so the fabricated line was the one drawn solid.
>
> **Fixed in `supply_chain_crawler.py`:**
> - `_parse_passmark_table()` re-addressed **by header text**; unknown layout ⇒ `[]`,
>   never a positional guess. `_passmark_num()` maps `"NA"` → `None` rather than
>   skipping the cell (skipping slides the next column into the slot).
> - Five gates in `crawl_passmark()`: catalogue ≥200 entries · never persist a NULL
>   price · price in $20–20,000 and within 5x of that series' last stored value ·
>   ≥50 % of tracked products resolved · **score↔price rank correlation ≤ −0.90**.
> - `purge_rank_as_price_rows()` condemns whole scrape dates on the same shared
>   correlation test; wired into `--curated-only`, so it runs every deploy (SC-14).
>
> **Tested — 18/18 pass** (`tests/test_qa05_passmark.py` — promoted out of `/tmp` and into
> the repo on 2026-08-09; re-run it after any PassMark edit): parser returns $560 not rank 3;
> NA→None; rejects a removed Price column, a JS shell, renamed headers; survives a
> column *insertion*; correlation gate fires at −1.000 on the real prod pattern and
> stays quiet at +0.886 on noisy real prices; purge deletes exactly the 30 contaminated
> rows in a prod-shaped fixture, leaves a healthy date and curated rows untouched, and
> is idempotent. `supply_chain_crawler.py` byte-compiles.
>
> **⚠️ STILL OPEN — do not close this ticket yet:**
>
> 1. **Deploy LANDED but the purge is a no-op on real prod data — root-caused
>    2026-08-09 evening (P0, reopened as QA-05c).** The post-deploy DB export
>    (`DB backup/`, crawl_runs showing two `supply_chain_curated` boots 16:53 +
>    17:12 HKT, README from the new bundle route) proves the new code is live and
>    F-02's valuation purge works (0 non-NULL pe_ratio/market_cap). But all 126
>    rank-as-price rows survived both boots, and running the on-disk
>    `purge_rank_as_price_rows()` against a copy of that DB locally also deletes
>    nothing. Cause: **Simpson's paradox in `_passmark_inversion_check()`**. Each
>    class is perfectly inverse (GPU-only rho=−1.0, CPU-only rho=−1.0), but the
>    check pools both lists: CPU ranks (134–496, longer list) all exceed GPU ranks
>    (3–151) while CPU Mark scores (38k–67k) also exceed G3D scores (16k–38k), so
>    the pooled rho is **+0.121** and the −0.90 trigger can never fire on the real
>    14-model mix. The write-side gate in `crawl_passmark()` shares the same pooled
>    check and is equally blind — if rank-as-price recurred it would pass. The
>    18/18 tests missed it because every fixture was single-class.
>    **QA-05c CODE DONE 2026-08-09 evening — NOT DEPLOYED.** Inversion now
>    computed per catalogue class in BOTH sites via new `_passmark_class_rhos()`
>    (`_PM_INV_MIN_N=4` — the CPU class tracks exactly 4 models): the purge joins
>    `sc_prices` → `sc_products.category` (with a pooled `'?'` fallback if
>    `sc_products` is somehow absent, so boot can never crash), and Gate 5 in
>    `crawl_passmark()` partitions on the product's own category, rejecting if ANY
>    class breaches −0.90. Log line now shows per-class rho
>    (`rho CPU:+1.00 GPU:+1.00` on the live 2026-08-09 run — real prices pass).
>    **Verified:** tests **23/23** (new §3b fixture = the exact pooled prod
>    pattern at rho **+0.121**, GPU and CPU each −1.000 per class; purge fixture
>    now mixed-class, 42 rows; no-sc_products fallback covered) · new purge run
>    against a copy of the 2026-08-09 prod export condemns **all 9 dates at
>    −1.000 and deletes all 126 rows**, curated untouched, idempotent ·
>    byte-compiles.
>    **DEPLOYED & VERIFIED IN PROD 2026-08-09 ~18:30 HKT:** boot purge deleted all
>    126 contaminated rows; ⚡ Run Crawl rewrote 14 models with real street prices
>    (RTX-4090 $3,299.95, i9-285K $496; per-class rho GPU +1.0 / CPU +1.0);
>    `/api/db-stats` → `shape_ok: true`, 0 HIGH flags. PassMark history restarts
>    at 2026-08-09 by design — the condemned dates were deleted, not corrected
>    (§8). Confirmed against `DB backup/semiconductor_data_20260809_1041.db`.
>
> 2. ~~Coverage gate uncalibrated~~ — **CALIBRATED 2026-08-09 against the live page.**
>    Live run: `PassMark — 14/20 products stored (rho=+0.25)`, all prices real street
>    prices (RTX-4090 $3,299.95, i9-285K $496). **`_PM_MIN_RESOLVED` = 0.50 stays** —
>    resolution is 70 %, rho healthily positive, gate quiet. All 6 skips are `nomatch`
>    and all are AMD Ryzen CPUs — root-caused as a SOURCE limitation, not a matcher bug:
>    `cpu_list.php`'s server-rendered `cputable` (2,842 rows, 698 KB) contains **zero
>    AMD rows** (0×"7950X", 3×"Ryzen" in the whole document). Prod history agrees: all
>    9 scrape dates ever stored the same 14 Intel/GPU models, never a Ryzen. The CPU
>    panel is therefore Intel-only from PassMark — an honest gap, not a wrong number.
>    **Fix path (new work, do NOT rush):** `high_end_cpus.html` DOES carry AMD with
>    score+price (`<li>` chart items: `prdname` / `count` / `price-neww`, e.g. Ryzen 9
>    7950X3D → 62,302 / $465.62, verified live 2026-08-09). Needs a small dedicated
>    parser + the same five gates; ticket it as QA-05b rather than widening this one.
>
> **Still not done from the original ticket:** the alerting half — routing
> `_stale_sources()` and crawler `log.error` into a daily digest. A log nobody reads is
> still not a control; that remains open and is now the only unfinished part of QA-05.

`crawl_steam_survey`, `crawl_trendforce_spot`, `crawl_tsmc_revenue`, `crawl_umc_revenue` and
`crawl_nanya_revenue` all validate and refuse to write on a bad parse. `crawl_passmark()` does
none of this — no minimum-entry check, no miss-rate threshold, no `log.error` — and PassMark is
one of only two genuinely-live supply-chain sources. Separately: every gate's failure path is
`log.error(...); return`, and nobody reads Railway logs. Route `_stale_sources()` + any crawler
`log.error` into a daily digest — a log nobody reads is not a control.

---

## ✅ SC-08 — `sc_dram_spot` freshness carried by a single DDR4 row; DDR5 a 20-month void — **DONE 2026-08-02**

```
TITLE:        Per-product_type SLA on sc_dram_spot + backfill DDR5 from dated TrendForce releases
TYPE:         bug                                    PRIORITY: P0 blocker — CLOSED
```

> **Done 2026-08-02 — and the ticket's core assumption was wrong in our favour.**
>
> **Part 1 — per-`product_type` SLA.** `sc_dram_spot` removed from `_FRESHNESS_SPEC`
> (a table-level entry is what let one row certify the table) and replaced with
> `_SC_DRAM_SLA`, reported as `sc_dram_spot[ddr4]` / `[ddr5]` — the same key shape the badge
> already consumes for `sc_prices[...]` and `sc_demand[...]`, so no caller changed. HBM3/HBM3E
> keys retained at 75 d so a restored series is monitored from its first row.
>
> **Part 2 — the anchors, and a better source than the ticket assumed.** The ticket expected
> DDR5 to stay a documented hole, because TrendForce's free weekly *[Insights]* articles quote
> **only** the DDR4 mainstream chip. That is true of the articles — but
> **`trendforce.com/price/dram/dram_spot` publishes the full spot table as server-rendered
> HTML** with its own `Last Update` timestamp, including DDR5. Three primary dated anchors
> added, one row per citation:
>
> | Series | Period | Price | Observed | Source |
> |---|---|---|---|---|
> | DDR4 8Gb 1Gx8 3200 | 2026-05 | $32.00 | 2026-05-19 | [Insights] article |
> | DDR4 8Gb 1Gx8 3200 | 2026-06 | $36.00 | 2026-06-30 | [Insights] article (pre-existing) |
> | DDR4 8Gb 1Gx8 3200 | 2026-07 | $42.11 | 2026-07-31 | spot price page |
> | **DDR5 16Gb 2Gx8 4800/5600** | **2026-07** | **$50.97** | **2026-07-31** | **spot price page** |
>
> Cross-check that the two channels are one series, not two: the 2026-06-30 article quotes
> "US$36.00" for the mainstream chip and the price page's Session Average column is the same
> figure. Convention recorded in the file — Session Average, stamped with the observation date
> in `source`, latest observation within the month, never a month-end value inferred from a
> mid-month quote.
>
> **Verified:** DDR4 and DDR5 both now report `days_stale=2` — green **because they are
> genuinely current**, not because a sibling row is. `_mem_yoy()` returns `"—"` for both (no
> anchor inside the 12–15 month window), so nothing fabricated a YoY. `_mem_break_gaps()`
> still breaks the line across the 2025-01 → 2026-06 hole. Panel notice reworded: the 2026
> points are individually sourced observations, and **DDR5 has one 2026 anchor, so it is a
> level check, not a trend.**
>
> **Residual, deliberately not closed here:** freshness measures recency, not continuity.
> DDR5 is now green on one point covering 20 months. The honest fix is the live crawler —
> **SC-15**, filed below with the precondition already verified.

---

## ✅ SC-15 — Crawl the TrendForce DRAM spot page live — **DONE 2026-08-02**

```
TITLE:        Live-crawl trendforce.com/price/dram/dram_spot into sc_dram_spot
TYPE:         feature                                PRIORITY: P1 — CLOSED
```

> **Done 2026-08-02.** `crawl_trendforce_spot()` + pure `_parse_trendforce_spot()`, following
> the `_parse_tsmc_revenue()` / `_parse_steam_survey()` idiom (pure function on a
> `get_text("\n")` linearization, validation gate in the caller).
>
> **The reconcile re-scope was done FIRST**, before the writer existed — it is the step that
> silently destroys data if it lands second. `load_curated_dram_spot()` now excludes
> `source = SRC_LIVE_SPOT` from its delete. Regression-tested explicitly: with the scope
> removed, an unscoped delete removes the live rows on the next `--curated-only`, i.e. on the
> next deploy. `SRC_LIVE_SPOT` is an exact-match string in a `<>` comparison — **changing that
> constant without changing the query deletes every live row.** Noted at both sites.
>
> **Parser scope:** only the two series already in `CURATED_DRAM_SPOT` (DDR5 16Gb 2Gx8
> 4800/5600, DDR4 8Gb 1Gx8 3200), with `spec_label` matched exactly so live data continues the
> existing series instead of forking a parallel one. The page also offers DDR4 16Gb, both eTT
> grades, DDR3, and the contract/module/GDDR tables — deliberately left, because a new
> `product_type` needs `_MEM_DIE_GB` / `_MEM_SPECS` / `_MEM_COLORS` / `_MEM_ORDER` /
> `_SC_DRAM_SLA` entries and a missing `_MEM_DIE_GB` key silently understates $/GB (§9).
>
> **Validation gate** — rejects and keeps existing rows, logging ERROR, unless: the spot
> section's own `Last Update` stamp parses, **both** tracked series parse, and each price is
> within 10x of the last stored value for that series. Period comes from the page's timestamp,
> never `datetime.now()` — a crawler that stamps rows with its own run time reports itself
> fresh after the publisher goes quiet, which is exactly how Steam sat frozen 17 months.
>
> **Section bounding matters:** the page renders four tables (spot / contract / module / GDDR)
> and **each has its own `Last Update` line**. An unbounded search pairs spot prices with the
> contract table's older timestamp. Same defect class as reading Steam's per-DirectX tables
> instead of "ALL VIDEO CARDS". Parse is bounded between `DRAM Spot Price` and
> `DRAM Contract Price`, and there is a test asserting it picks 2026-07 and not 2026-06.
>
> **Tested against a fixture built from the real 2026-08-02 page text:**
>
> | Case | Result |
> |---|---|
> | Correct section, timestamp, Session Average column | ✅ DDR5 50.967 / DDR4 42.112, period 2026-07 |
> | eTT / DDR4-16Gb / DDR3 / contract / module decoy rows | ✅ none captured |
> | JS shell (Steam-style failure) | ✅ rejected |
> | Rows fine, timestamp renamed | ✅ rejected |
> | Timestamp fine, table gone | ✅ rejected |
> | Spot section heading changed | ✅ rejected |
> | 3 consecutive `--curated-only` deploys after a live crawl | ✅ live rows survive |
>
> A caught bug worth recording: the row regex was first written as
> `r"{label}..." r"\s*[\d,]+..." * 4` — implicit string concatenation binds tighter than `*`,
> so it repeated the **label** four times and matched nothing. The fixture test caught it;
> a live-only test would have reported "0 rows parsed" and looked like a site change.
>
> **Two honest limits, both left visible rather than papered over:**
> 1. **`_SC_DRAM_SLA` NOT tightened to 10d.** The full crawl runs only on an empty DB or a
>    manual ⚡ Run Crawl, so the live crawler fires rarely today; a tight SLA would breach
>    constantly and train the reader to ignore the badge (SC-04's calibration lesson).
>    **Tighten it in the same change that adds the Railway Cron schedule** — a crawler does not
>    make data fresh until something runs it. That is now the binding constraint, not the code.
> 2. **The 2026 curated anchors overwrite live rows for those same months** on every
>    `--curated-only`. Harmless while the values agree (42.11 vs 42.112), but treat SC-08's
>    curated 2026 rows as bootstrap: do not keep hand-adding curated rows for months the live
>    crawler now covers.
>
> **Could not be tested against the live site from this session** (no outbound fetch from the
> tooling that writes code). Run `python3 supply_chain_crawler.py --spot-only` locally — the
> new flag exists for exactly this — and confirm the log line before pushing.

<details><summary>Original ticket (kept for context)</summary>

**WHAT / WHY:** SC-08 closed the freshness *reporting* gap but left the coverage gap: DDR5
has one observation in 20 months, and the monthly curated refresh is the same manual step
that lapsed and produced SC-04. `trendforce.com/price/dram/dram_spot` carries the whole
table — DDR5 16Gb 2Gx8 4800/5600, DDR5 eTT, DDR4 16Gb/8Gb 3200 + eTT, DDR3 4Gb — with Daily
High/Low, Session High/Low/Average, Session Change, and a `Last Update … (GMT+8)` stamp. Same
page also carries DRAM **contract** prices, module, GDDR and LPDDR.

**The SC-06 precondition is already met and this is the reason the ticket is worth opening:**
the page was fetched on 2026-08-02 and returned a **plain server-rendered HTML table**, no JS
execution required — the opposite of the Steam survey (SC-02) and Newegg (SC-01). Do re-verify
before writing the parser; do not take this note as permission to skip the check.

**WHERE:** `supply_chain_crawler.py` — new `crawl_trendforce_spot()` beside
`crawl_tsmc_revenue()`; `dashboard.py` → `_SC_DRAM_SLA` (tighten DDR4/DDR5 45 → 10 d once
live), `_MEM_DIE_GB` / `_MEM_SPECS` entries for any newly tracked chip.

**FIX / CONSTRAINTS:**
- Parse the **Session Average** column, and read the page's own `Last Update` timestamp for
  the period — never `datetime.now()`. The Steam fix (SC-02) turned on exactly this point.
- **Validation gate before writing**, per SC-02: reject the parse unless ≥5 rows are found,
  the timestamp parses, and each price is within 10x of the last stored value for that
  series. On failure, log ERROR and keep existing rows — never write a partial parse.
- **Never write a NULL price row** (SC-01).
- `source` must record the observation date, matching the curated convention.
- Live rows and curated rows share `sc_dram_spot`, so `load_curated_dram_spot()`'s reconcile
  (SC-14) **must be re-scoped** before this ships — today it deletes anything not in
  `CURATED_DRAM_SPOT`, which would wipe every live row on the next deploy. Scope it to
  curated-sourced rows, exactly as `load_curated_retail_prices()` does. **This is the one
  step that will break production if missed.**

**DONE-WHEN:** DDR4 and DDR5 each gain a new observation per crawl without a code edit, and
`sc_dram_spot[ddr5]` shows a continuous series rather than a single anchor.

**VERIFY:** local crawl twice, confirm idempotency and that curated rows survive; then
`--curated-only` and confirm live rows still survive. Prod — `/api/db-stats` per-type keys.

</details>

---

## ✅ SC-08 — original ticket (kept for context)

<details><summary>Expand</summary>

**WHAT / WHY:** `/api/db-stats` reports `sc_dram_spot: {days_stale: 33, unhealthy: false}`.
That green reading rests entirely on the **one** row SC-04 added (DDR4 2026-06 = $36.00).
Behind it, **DDR5 has no observation after 2024-12 ($5.80/die)** while TrendForce DataTrack
listed DDR5 16Gb 2Gx8 4800/5600 at a **$61.00 daily high, session average mid-$40s** in early
July 2026 — roughly a 10x gap, spanning the largest DRAM upcycle on record. The table-level
SLA is structurally unable to see this: one fresh series masks every dead one beside it.

This is SC-03's own lesson re-appearing one level down. A per-`source` SLA was the fix for
`sc_prices`; `sc_dram_spot` needs the same treatment per `product_type`.

**WHERE:**
- `dashboard.py` → `_FRESHNESS_SPEC` / `_freshness_report()`; add a `_SC_DRAM_SLA`
  dict keyed on `product_type`, exactly mirroring the existing `_SC_PRICE_SLA` and
  `_SC_DEMAND_SLA` pattern (§2.3). Emit as `sc_dram_spot[ddr5]` etc., like
  `sc_demand[tsmc_revenue]` already does.
- `products_config.py` → `CURATED_DRAM_SPOT` for the backfill.

**FIX:**
1. Per-`product_type` SLA (DDR4/DDR5 45 d; HBM bi-monthly 75 d).
2. Backfill DDR5 **only** from dated TrendForce releases, one row per citation, source string
   carrying the release date (`"TrendForce spot (YYYY-MM-DD)"`) — the pattern SC-04 established.
   A third-party paraphrase ("mid-$40s") is **not** citable; leave the gap if that is all
   there is.

**DONE-WHEN:** `/api/db-stats` reports DDR4, DDR5 and HBM separately, and DDR5's staleness is
either < SLA or **visibly red**. Green-because-hidden is the failure being fixed.

**CONSTRAINTS:** §7.3 — new rows must sit inside the default 5Y window; `_mem_yoy()` must
return `"—"` not a fabricated `0.0 %`; `_mem_break_gaps()` must still break the 2024-12 →
2026-06 hole. Any new memory type needs a `_MEM_DIE_GB` entry (§2.3) or $/GB is understated.

**VERIFY:** local — RAM sub-tab, confirm no line crosses the gap and every "As of" is honest.
Prod — `/api/db-stats` shows the split keys; badge counts them independently.

</details>

---

## ✅ SC-09 — The entire HBM series is fabricated with the exact fingerprint SC-04 deleted — **DONE 2026-08-02**

```
TITLE:        Purge modeled HBM3/HBM3E rows from CURATED_DRAM_SPOT
TYPE:         bug                                    PRIORITY: P0 blocker — CLOSED
```

> **Done 2026-08-02 — and the ticket understated the blast radius.**
>
> **The series existed twice.** `CURATED_RETAIL_PRICES` held HBM3-48GB / HBM3E-96GB
> *per-stack* rows that were the same per-GB estimate multiplied by stack capacity —
> `11.80 × 48 = 566` and `18.40 × 96 = 1766` reproduce the last row of each block exactly,
> and the retired header said so in writing ("TrendForce contract price estimates × stack
> capacity"). That copy fed the **Enterprise AI Hardware Price Index vs SOXX** chart as a
> "RAM" line, where it read as a second, corroborating source. Purging only the per-GB
> series would have left the rescaled twin on a chart. **68 rows deleted, not 20.**
>
> | Removed | From | Rows |
> |---|---|---|
> | HBM3 / HBM3E per-GB | `CURATED_DRAM_SPOT` | 20 |
> | HBM3-48GB / HBM3E-96GB per-stack | `CURATED_RETAIL_PRICES` | 48 |
>
> - **Not backfilled.** No citable anchor exists. Available figures are third-party
>   aggregator paraphrases that contradict each other inside a single article (~$13–17/GB
>   vs "~$300 per 36 GB stack" ≈ $8.3/GB); TrendForce's 2026-06-02 release is directional
>   only. Same test that stopped SC-04 recording a "mid-$40s" DDR5 paraphrase. The modeled
>   *direction* was probably wrong too — public commentary has HBM3E falling from its
>   H1-2025 peak before a mid-2026 rebound, against this series' unbroken climb.
> - **Propagation:** `load_curated_retail_prices()` gained a reconcile **scoped to
>   `source='curated'`** (SC-14 pattern). The scope is mandatory — this table has live
>   PassMark/Newegg writers, and an unscoped delete would wipe every scraped price.
>   Verified: 910 → 908 curated rows, 2 withdrawn deleted, **live rows untouched**,
>   idempotent on re-run.
> - **UI:** withdrawal notice in the RAM sub-tab; HBM claims removed from the price-index
>   note, snapshot note, both source footers, and two docstrings. Era-shading bands now
>   draw only for a `product_type` that has data — otherwise a labelled "HBM3E Era" band
>   would sit over empty space and read as a rendering fault.
> - **`_MEM_*` keys deliberately retained** so the panel renders an empty group instead of
>   raising, per the ticket.
> - **Regression check:** longest constant-delta run across every surviving series is now
>   **2** (was 15). Nothing with the synthetic fingerprint survived. New `CLAUDE.md §9` row.
>
> **Verify in prod after deploy:** `sc_dram_spot` 53 → **33** rows (SC-14 reconcile does the
> DRAM half); `sc_prices[curated]` 956 → **908**; RAM sub-tab shows DDR only; the Enterprise
> index chart shows GPU + CPU with no RAM line.

**WHAT / WHY:** `CURATED_DRAM_SPOT` HBM3E runs 2024-01 → 2026-05 rising **+$0.20 every single
two-month step, 15 steps, never once deviating** ($12.00 → $18.40/GB); HBM3 before it glides the
same way. Source label is `"Modeled estimate"`.

This is the **identical monotonic-glide fingerprint** that SC-04 correctly identified as
extrapolated filler and deleted from the DDR rows on the same day. One was purged; the other
was left in the chart beside it. The `SRC_MODELED` label is not a sufficient defence — SC-04
established that a wrong number is worse than no number (§8), and that principle does not
weaken because the number is honestly labelled. HBM contract pricing over 2024–2026 was
anything but a smooth glide.

**WHERE:** `products_config.py` → `CURATED_DRAM_SPOT`, all `HBM3` and `HBM3E` tuples;
`dashboard.py` → `_MEM_ORDER`, `_MEM_SPECS`, `_MEM_COLORS`, `_MEM_DIE_GB`, `_sc_dram_inline()`,
`_sc_enterprise_ram_section()`.

**FIX:** delete the rows (do not relabel). Replace the header comment with the same withdrawal
note SC-04 wrote for DDR. If a genuine anchor exists (TrendForce HBM contract release, SK Hynix
or Micron earnings HBM ASP commentary), add it dated, one row per citation. Keep the series
registered in `_MEM_*` so the panel does not crash on an empty group; state the withdrawal in
the in-panel notice next to the existing DDR one.

**DONE-WHEN:** no series in the RAM panel carries a constant month-to-month delta, and the
panel states which series have been withdrawn and why.

**CONSTRAINTS:** §7.3 retired-series rules; `_mem_yoy()` must return `"—"`, never `+0.0 %`.

**VERIFY:** local — RAM sub-tab renders with DDR only, legend intact, no exception on the empty
HBM group. Compute month-to-month deltas of every remaining series; any perfectly constant run
> 4 periods is a red flag that survived the purge.

---

## ✅ SC-10 — `sc_semi_btb` rows still ship after the panel was removed — **DONE 2026-08-02**

```
TITLE:        Drop the sc_semi_btb table and its curated seed
TYPE:         bug                                    PRIORITY: P0 — CLOSED
```

> **Done 2026-08-02.** Grep first: no callback, query helper, or panel read the table —
> only the export map and the `/api/db-stats` table list, both of which listed it purely to
> report it. Removed in one pass:
>
> | Removed | File |
> |---|---|
> | `CURATED_SEMI_BTB` (41 rows) + module docstring line | `products_config.py` |
> | `load_curated_semi_btb()`, its orchestrator call, the `crawl_semi_btb()` no-op stub and its call, the `CREATE TABLE`, the import | `supply_chain_crawler.py` |
> | `_EXPORT_SHEET_NAMES["sc_semi_btb"]`, `/api/db-stats` table list entry | `dashboard.py` |
> | `DROP TABLE sc_semi_btb` added to `init_supply_chain_db()`, guarded on `sqlite_master` and logging the row count before dropping | `supply_chain_crawler.py` |
>
> **The "irreversible" caution in the ticket was overstated, and that mattered for
> sequencing.** Every row originated in `CURATED_SEMI_BTB`, which is in git history, so the
> table is fully reproducible — unlike scraped `sc_prices` / `options_iv_history`, which are
> not (CLAUDE.md §5.1). The drop did not need to wait on the Railway backup being enabled.
> Enabling backups is still #1 on the queue, on its own merits.
>
> **Verified** on a simulated prod DB seeded with 41 rows: dropped with the row count
> logged, idempotent on re-run, full curated load unaffected. The `/api/export-xlsx` sheet
> disappears automatically — sheets are discovered from `sqlite_master`, so no export code
> change was needed beyond deleting the cosmetic label.
>
> **Side effect worth noting:** `_FRESHNESS_SPEC` had a comment calling `sc_semi_btb` "the
> ONLY table for which unmonitored is correct". That exception is now gone — every remaining
> table is covered by either `_FRESHNESS_SPEC` or a per-key SLA dict. The rule no longer has
> a carve-out, which is a better invariant than the carve-out was.
>
> **Verify in prod after deploy:** `/api/db-stats` no longer lists `sc_semi_btb`; the deploy
> log shows `Dropped retired table sc_semi_btb (41 rows)`; the downloaded workbook has no
> Book-to-Bill sheet.

**WHAT / WHY:** SC-00 fix B removed `_sc_btb_panel()` and replaced it with
`_sc_demand_panel()`, but `/api/db-stats` still returns `sc_semi_btb: 41`. Those rows model a
series **SEMI discontinued after the Dec-2016 report**. They are unmonitored (SC-04 removed the
table from `_FRESHNESS_SPEC`, correctly, since its panel is gone) and they are **exported**:
`/api/export-xlsx` discovers tables from `sqlite_master`, so every workbook a reader downloads
still contains a sheet of a decade-dead indicator with no disclaimer around it.

**WHERE:** `products_config.py` → delete `CURATED_SEMI_BTB`; `supply_chain_crawler.py` →
delete the `crawl_semi_btb()` stub and its `load_curated_*` caller; `dashboard.py` →
`_EXPORT_SHEET_NAMES` entry if present; add a one-line `DROP TABLE IF EXISTS sc_semi_btb`
to the curated loader so prod actually loses the rows on next deploy.

**DONE-WHEN:** `/api/db-stats` no longer lists `sc_semi_btb`, and the exported workbook has no
such sheet.

**CONSTRAINTS:** §7 rule 2 — this is a table **removal**, not a rename, and no callback reads it
post-SC-00; grep to confirm before dropping. Dropping a table on a persistent volume is
irreversible — confirm the Railway volume backup (Durability follow-up #1) exists first.

**VERIFY:** grep `sc_semi_btb` across the repo returns only historical BACKLOG/CLAUDE text.
Prod — `/api/db-stats`, then download `/api/export-xlsx` and check the sheet list.

---

## ✅ SC-11 — `sc_capacity` cites earnings releases that do not contain the numbers — **DONE 2026-08-02**

```
TITLE:        Rebuild sc_capacity from what foundries actually disclose
TYPE:         bug                                    PRIORITY: P1 — CLOSED
```

> **Done 2026-08-02, option (a) — rebuild from real disclosures.** Schema change approved by
> Simpo before implementation (§1 step 7).
>
> **`sc_capacity` dropped, `sc_fab_metrics` created.** Dropped rather than migrated: the
> *columns* were the defect. `capacity_kwpm` and `utilisation_pct` at node granularity are
> published by no foundry, so renaming them (§7 rule 2) would have preserved the error in new
> clothing. All 31 rows deleted, not relabelled (§8) — reproducible from git like
> `sc_semi_btb`, since they were 100 % curated.
>
> New shape is generic `(company, metric_key, detail, period, value, unit, source, notes)`, so
> a new disclosure is a new row rather than a schema change. Vocabulary documented on the DDL:
> `revenue_usd_b`, `gross_margin_pct`, `operating_margin_pct`, `wafer_shipments_kpcs`,
> `node_revenue_pct` (detail = node), `capex_usd_b`, `utilisation_pct` **only where a company
> states it**.
>
> **Seeded with 7 rows, all TSMC, all verified against a document I opened:**
>
> | Metric | 2026-Q2 | Source |
> |---|---|---|
> | Net revenue | US$40.20B | Quarterly Results guidance table, actual column |
> | Gross margin | 67.7% | same |
> | Operating margin | 60.3% | same |
> | Wafer shipments | 4,336k 12-inch-eq | 2Q26 Management Report |
> | Revenue by node | 2nm 3% · 3nm 30% · 5nm 33% | 2Q26 Management Report |
>
> The US$40.20B was confirmed independently on the IR page this session, matching what SC-04
> had recorded — two reads, same number.
>
> **Samsung, SK Hynix, Micron and Intel are deliberately blank.** The old table carried 22 rows
> across those four. Their filings were not opened in this pass, so nothing was written for
> them — carrying the previous numbers across under a new column name is exactly the move this
> ticket exists to prevent. The panel says so on screen.
>
> **Live crawler added: `crawl_tsmc_quarterly()`.** Precondition checked first (SC-06 rule) —
> `investor.tsmc.com/english/quarterly-results/{year}/q{n}` is server-rendered and the Guidance
> table's first numeric column is that quarter's actual. Walks back 6 quarters. **A quarter is
> all-or-nothing**: fewer than 3 metrics parsed ⇒ the whole quarter is skipped, so a layout
> change cannot leave a half-populated quarter looking complete. Wafer shipments and node mix
> stay curated — they live in a PDF, and crawling what is easy while hand-checking what is not
> is the correct split.
>
> **Reconcile scoped to `SRC_LIVE_TSMC_Q` prefix** (SC-14). Verified: 3 live quarters survive
> three consecutive `--curated-only` deploys.
>
> **Tested:** old table with 31 rows → dropped on init, idempotent; parser captures the actual
> column and ignores the guidance ranges and the exchange-rate row; JS-shell, renamed labels,
> unit-slip (40200.0) and >100% margin all yield <3 metrics ⇒ quarter skipped. `_FRESHNESS_SPEC`
> and `_CONSISTENCY_SPEC` re-keyed to `sc_fab_metrics`; `_EXPORT_SHEET_NAMES` and the
> `/api/db-stats` table list updated; `sc_capacity_query()` deleted. No shape flags on the new
> series.
>
> **Verify in prod:** deploy log shows `Dropped sc_capacity (31 rows)`; `/api/db-stats` lists
> `sc_fab_metrics` and no `sc_capacity`; Supply Chain tab shows "Manufacturer Disclosures" with
> a Source Document column; exported workbook has an `SC Fab Metrics` sheet and no
> `SC Fab Capacity`.

<details><summary>Original ticket (kept for context)</summary>

**WHAT / WHY:** Every `CURATED_CAPACITY` row carries a `source` like `"TSMC Q4 2023 Earnings"`
against a `capacity_kwpm` and `utilisation_pct` **per technology node**. No foundry — TSMC,
Samsung, Intel, SMIC — discloses per-node capacity or per-node utilisation in any earnings
release. The citation names a document that does not contain the figure.

That is the same failure class as SC-00 (a real institution's name attached to a number it
never published), and it is the one SC-05 was written to eliminate — SC-05 fixed the DRAM
labels and did not reach this table. SC-04 flagged the staleness (2025-Q1, 489 days) and
correctly stopped short of backfilling; **the provenance defect is the more serious half and
is independent of the staleness.** A stale honest number is a maintenance item; a current
misattributed one is a §8 violation.

**WHERE:** `products_config.py` → `CURATED_CAPACITY`; `dashboard.py` → `_sc_capacity_panel()`.

**FIX:** option (a) from SC-04 — restructure to published fields: wafer shipments (TSMC reports
12-inch-equivalent, e.g. 4,336k in Q2-2026), revenue by node (2nm 3 % / 3nm 30 % / 5nm 33 %),
capex, and blended company-level utilisation **where a company states it**. Anything retained
that is genuinely derived must be labelled `SRC_MODELED` with an in-panel disclaimer, per the
B2B precedent. Schema change ⇒ **ask-first gate** (§1 step 7).

**DONE-WHEN:** every `sc_capacity` row's `source` names a document that actually contains that
figure, or the row reads as a modeled estimate in the UI.

**CONSTRAINTS:** §7 rule 1 (no NOT NULL adds), rule 2 (migration script if columns change);
per-bar period stamp must survive (§9); ask Simpo before the schema change.

**VERIFY:** pick three rows at random, open the cited release, find the number. If you cannot,
the row fails.

</details>

---

## ✅ SC-12 — No automated check that the price layer agrees with the demand layer — **DONE 2026-08-02**

```
TITLE:        Cross-source consistency check between sc_demand_indicators and sc_dram_spot
TYPE:         feature                                PRIORITY: P1 — CLOSED
```

> **Done 2026-08-02.** `_consistency_report()` beside `_freshness_report()`, same contract
> (never raises, one helper behind both surfaces). Four shape rules over every series in
> `_CONSISTENCY_SPEC` (sc_dram_spot, sc_prices, sc_market_share, sc_demand_indicators,
> sc_capacity):
>
> | Rule | Fires when | Catches |
> |---|---|---|
> | `frozen` | ≥6 identical consecutive values, still producing | a scraper stuck on one value |
> | `synthetic_glide` | ≥5 equal first-differences (±1%) | SC-09's HBM3E (+$0.20 × 15) |
> | `geometric_glide` | ≥5 equal ratios (±1%) | SC-04's DDR (−1.5%/mo × 17) |
> | `divergence` | fell 6+ periods while WSTS YoY > +20% | a price series contradicting the demand layer |
>
> **`geometric_glide` was added after the first test run.** SC-04's rows decayed by a constant
> *percentage*, so their absolute steps shrank every month and `synthetic_glide` missed them
> entirely — only `divergence` caught that series, and `divergence` needs WSTS to be present.
> A constant ratio is the other half of the same fingerprint and needs no demand-layer
> context, so it still works if WSTS goes quiet. Verified: with WSTS removed, SC-04 is still
> caught.
>
> **Severity split — the design decision that makes this usable.** The first run flagged
> **24 of 26 curated retail series**. Not a false positive: `R9-7950X` falls exactly −$5/month
> for 12 straight months, `RX-7900-XTX` −$10/month for 9. Those are hand-drawn decay curves.
> But they are already labelled `SRC_MODELED`, so alarming on them would fire 65 flags on day
> one and the badge would be ignored within a week (SC-04's calibration lesson).
>
> So severity depends on what a series **claims to be**: a modeled-labelled series with a
> modeled shape is self-consistent and disclosed → `expected` (reported, not alarmed). A
> series claiming a publisher while showing a fabricated shape → `high`. That is exactly
> SC-04, where 34 extrapolated rows carried `"TrendForce (public release)"`.
>
> **Verified against the DB's own history.** Re-injecting the historical bad rows *with their
> original published labels*:
>
> ```
> HIGH=3  expected=65  badge_green=False
> 🔴 sc_dram_spot[DDR4]   geometric_glide  18 steps of ~-1.50% ending 2026-05
> 🔴 sc_dram_spot[HBM3E]  geometric_glide   7 steps of ~+1.10% ending 2026-05
> 🔴 sc_dram_spot[HBM3E]  synthetic_glide   7 steps of ~+0.20 ending 2026-05
> ```
>
> Against the **current** seeds: `HIGH=0`, badge green — the fabricated series really are gone.
> No false positives on real DDR4/DDR5 spot, WSTS, TSMC, UMC, SEMI WWSEMS, or `sc_capacity`.
>
> **The DONE-WHEN was wrong about SC-01/SC-02 and I did not fudge it.** SC-02 (Steam frozen at
> 2025-03) wrote *one* period then stopped — a per-series shape check sees a single point and
> skips it. SC-01 (Newegg NULLs) has no values at all. Both are **freshness/emptiness**
> failures and are already caught by `stale` / `empty`; shape checks are the third leg, not a
> superset. The `frozen` rule is still worth having and was verified separately against a
> still-producing stuck scraper (fires) and a moving series (does not).
>
> **Surfacing:** `/api/db-stats` gains `consistency`, `consistency_flags`, `shape_ok`.
> `shape_ok` is deliberately **separate from `data_ok`** — freshness is a fact, shape is a
> suspicion, and merging them would make one green boolean mean two things. Badge: 🔴 stale
> (unchanged, wins) → 🟡 *n* shape flags → 🟢 fresh. Only `high` flags turn the badge amber.

<details><summary>Original ticket (kept for context)</summary>

**WHAT / WHY:** SC-03 made each source report its *own* health. It cannot detect the failure
that actually shipped: on 2026-08-02 the DB simultaneously held WSTS billings at **+104 % YoY**
and a DRAM spot series **flat since 2024-12** — mutually impossible, both individually
"healthy", no warning anywhere. Every data bug found in rounds 1 and 2 (Newegg NULLs, frozen
Steam, retired B2B, falsified DDR, modeled HBM) would have been caught earlier by one rule:
*does this series move when the market moves?*

**WHERE:** `dashboard.py` → new `_consistency_report()` beside `_freshness_report()`; surface
in `/api/db-stats` and fold into the navbar badge, reusing the single-helper discipline of §6.5
so the two surfaces cannot disagree.

**FIX:** start with three rules, each cheap and each mapped to a real prior incident:
1. **Flat-line:** any series with zero variance for > 6 periods while `wsts_billings` YoY
   is outside ±20 % → flag. (Catches frozen Steam, falsified DDR.)
2. **Synthetic glide:** any series whose month-to-month delta is constant to within 1 % for
   > 4 consecutive periods → flag. (Catches the modeled HBM and the deleted DDR rows.)
3. **Magnitude:** any curated price more than 5x from the nearest dated primary anchor → flag.

**DONE-WHEN:** running the check against the 2026-08-01 DB snapshot reproduces the SC-01,
SC-02 and SC-04 findings without being told what to look for.

**CONSTRAINTS:** must never raise (same contract as `_freshness_report()`); advisory only —
it flags, it does not delete.

**VERIFY:** unit-test each rule against the known-bad historical rows preserved in git.

</details>

---

## ✅ SC-16 — 24 of 26 curated retail price series are hand-drawn decay curves — **DONE 2026-08-02**

```
TITLE:        Decide what to do with the modeled CURATED_RETAIL_PRICES curves
TYPE:         data-refresh                           PRIORITY: P2 — CLOSED
```

> **Done 2026-08-02, split option — consumer gains live observations, enterprise loses the
> line.** Chosen by Simpo after the two classes were measured separately.
>
> **The measurement that drove the split:**
>
> | Class | Series | Flagged | Live source available? |
> |---|---|---|---|
> | Enterprise (A100/H100/H200/B200/MI300X, EPYC, Xeon) | 9 | **9 of 9** | ❌ none — no free source publishes accelerator contract ASPs |
> | Consumer (GPU/CPU/RAM) | 17 | **16 of 17** | ✅ PassMark, live and healthy (112 rows, 0 % null, current) |
>
> Worst offenders: `Xeon-8490H` runs **40 consecutive steps at a constant ratio**;
> `EPYC-9654` 42; `R9-7950X` falls exactly −$5.00/month for 12 months. These are formulas.
>
> **The fix is visual, and deliberately so.** The rows are correctly labelled `SRC_MODELED`,
> so this was never a mislabelling defect — it is the SC-09 argument: *a reader takes direction
> and rate-of-change from a LINE regardless of its footnote.* One shared helper now styles
> every `sc_prices` trace:
>
> - **Modeled** → open markers on a thin dotted connector, 85 % opacity, `(modeled)` legend suffix
> - **Observed** → solid line, filled marker
>
> Applied at all four plot sites: Enterprise GPU, Enterprise CPU, the consumer price section,
> and the Enterprise-vs-SOXX index. The last one mattered most — modeled indices were being
> drawn beside a real ETF series, and a dotted line alone had not made that asymmetry visible.
> A yellow `_modeled_note()` disclosure sits on each of the four charts.
>
> **Consumer charts now show BOTH sources instead of picking one.** `_sc_price_section()`
> previously did `df_pass if not df_pass.empty else df_curated`, which silently hid whichever
> it did not choose and made a modeled series indistinguishable from a measured one. It now
> plots the curated backbone (modeled style) and the PassMark observations (solid) on the same
> axes with a shared `legendgroup`, so **the point where real data begins is visible on the
> chart.** As PassMark accumulates, the solid segment grows and the modeled one recedes —
> the series self-corrects without another ticket.
>
> **Enterprise values were kept, not deleted.** Unlike SC-09's HBM series, there is no
> alternative source and no rescaled twin — deleting would remove the capability rather than
> qualify it. They keep their levels and lose the implied trend, which is the honest position:
> read the level, not the shape.
>
> **Not done — and worth knowing:** the underlying numbers are unchanged, so SC-12 still
> reports 65 `expected` shape flags. That is correct behaviour, not an oversight: the flags
> describe the data, and the data is still modeled. Replacing the enterprise levels with
> observations would need a paid channel-pricing source (TrendForce enterprise reports, or
> cloud GPU spot rates as a proxy) — a purchasing decision, not an engineering one.
>
> **Verify:** Supply Chain → GPU/CPU/RAM and the Enterprise sub-tabs — every modeled series
> renders as open markers on a dotted line with a `(modeled)` legend entry and a yellow notice
> above the chart; the SOXX line stays solid and visually distinct from the indices beside it.

<details><summary>Original ticket (kept for context)</summary>

**WHAT / WHY:** Surfaced by SC-12's shape checks, not by inspection. `R9-7950X` falls exactly
−$5.00 every month for 12 consecutive months; `RX-7900-XTX` −$10.00 for 9; most GPU/CPU series
decay at a constant percentage. 65 shape flags across the table.

These are **correctly labelled** `SRC_MODELED`, which is why SC-12 files them as `expected`
rather than alarming — this is not a mislabelling defect like SC-04. But it does mean the
Enterprise GPU/CPU price-index charts are drawing smooth author-drawn curves, and a reader
takes direction and rate-of-change from a line regardless of its footnote (the SC-09 argument).

**WHERE:** `products_config.py` → `CURATED_RETAIL_PRICES`; the enterprise index in
`_sc_vs_etf_panel()`; the existing "Enterprise GPU Price Data" item below overlaps this.

**OPTIONS (needs a decision, same shape as SC-11):** (a) replace with real observations —
PassMark already delivers live consumer pricing; enterprise GPU contract ASPs have no free
source, so those series may simply not be supportable; (b) keep as modeled but stop drawing
them as continuous lines (markers only, or a shaded band); (c) leave as-is — disclosed,
flagged, and understood.

**DONE-WHEN:** either the series carry observations, or the UI stops presenting a modeled
curve with the same visual weight as a measured one.

</details>

---

## ✅ SC-13 — Extend the Taiwan monthly-revenue scraper beyond TSMC/UMC — **DONE 2026-08-02 (1 of 6 shipped, deliberately)**

```
TITLE:        Add MOPS monthly revenue for ASE, MediaTek, Nanya, Winbond, Vanguard
TYPE:         feature                                PRIORITY: P1 — CLOSED
```

> **Done 2026-08-02 — one issuer added, four rejected, and the rejections are the point.**
>
> The ticket named five issuers. SC-06's rule is to **confirm each page is a stable
> server-rendered table before writing its parser**, so every candidate was fetched first.
> Only one passed. Shipping five speculative parsers would have reproduced SC-02 exactly:
> code that runs, finds nothing, and reports success.
>
> | Candidate | URL tried | Result |
> |---|---|---|
> | **Nanya** | `nanya.com/en/IR/36?Year=YYYY` | ✅ **server-rendered table**, plain year param — shipped |
> | MediaTek | `mediatek.com/about/investor-relations/monthly-sales-revenue` | ❌ empty body (JS-rendered) |
> | Winbond | `winbond.com/hq/investor-relations/.../monthly-revenue` | ❌ empty body |
> | ASE | `aselgroup.com/en/ir/revenue`, `aseglobal.com/en/investor/monthly-revenue` | ❌ empty body on both |
> | Vanguard | `vis.com.tw/en/investors/monthly-revenue` | ❌ redirects to homepage; real path is `ir_financials`, unverified |
> | MOPS (all issuers) | `mops.twse.com.tw/mops/web/t21sc03_e` | ❌ POST-form endpoint, not a GET table |
>
> **Nanya is the highest-signal one of the six anyway.** Pure-play commodity DRAM, monthly,
> statutory — it puts a *published revenue* series behind the memory layer that SC-04
> falsified and SC-08 could only partly rebuild. Its numbers independently corroborate the
> rest of the demand layer: **+730.1% YoY in May 2026**, alongside WSTS +104% and DDR4 spot
> $2.65 → $42.11.
>
> | Period | NT$B | YoY | MoM |
> |---|---|---|---|
> | 2026-01 | 15.310 | +608.0% | +27.4% |
> | 2026-05 | 27.670 | +730.1% | +8.6% |
>
> **A trap worth recording: Nanya prints MoM BEFORE YoY**, the opposite of TSMC and UMC.
> Reading positionally without checking would have silently swapped two published figures and
> produced a perfectly plausible wrong number. There is an explicit test asserting
> `YoY=608.0, MoM=27.4` and not the reverse.
>
> **Tested** against a fixture from the real page: 5 months parsed correctly; blank future
> months (June, July) not captured; the `Accumulated Revenue` summary row not captured (it has
> no month and a meaningless MoM); JS-shell and percent-stripped inputs rejected by the gate.
> Seeded into `CURATED_DEMAND_INDICATORS` so the panel is populated before the first crawl,
> and `_consistency_report()` raises no flag on the new series.
>
> **SLA set to 70d, not 40d, and this is a calibration not a fudge.** Nanya's English IR page
> carried Jan–May on 2026-08-02 while TSMC and UMC already showed June. That is publication
> lag, not a parse gap — the page's own accumulated-revenue total sums Jan–May exactly
> (102,247,696). A 40-day SLA would ship red on day one and train the reader to ignore the
> badge (SC-04). **Tighten to 40 once the live crawler has two or three months of evidence
> about this page's real cadence.**
>
> **Remaining four are NOT re-tickets by default.** MediaTek/Winbond/ASE are JS-rendered on
> the paths tried; the correct answer for them is a data source, not a cleverer scraper. Only
> Vanguard is worth one more look (`vis.com.tw/en/ir_financials`) since it was a wrong-URL
> failure rather than a rendering failure. If broader coverage is genuinely wanted, the right
> move is the MOPS POST endpoint for all issuers at once — a different ticket with a different
> risk profile, not an extension of this one.

<details><summary>Original ticket (kept for context)</summary>

**WHAT / WHY:** SC-06 established the highest-value live feed in the project: Taiwan-listed
issuers must publish monthly revenue by the 10th of the following month, and both IR pages
proved to be plain server-rendered tables. That statutory disclosure covers far more of the
chain than the two names currently scraped — **ASE** (OSAT / advanced packaging, the CoWoS
bottleneck the capacity panel keeps gesturing at), **MediaTek** (fabless demand), **Nanya**
and **Winbond** (memory — the layer with the largest data hole per SC-08), **Vanguard**
(mature-node). It is free, monthly, ~40-day fresher than WSTS, and needs no new schema:
`sc_demand_indicators` is keyed `(indicator_key, period)`.

**WHERE:** `supply_chain_crawler.py` → generalise `crawl_tsmc_revenue()` / `crawl_umc_revenue()`
into one issuer-parameterised function; `dashboard.py` → `_SC_DEMAND_SLA` entry per new key
(40 d, matching TSMC/UMC), and `_sc_demand_panel()` grouping.

**FIX:** **confirm each IR page is a stable server-rendered table before writing its parser** —
the explicit lesson of SC-06 and the Steam failure. Any issuer whose page is JS-rendered or
PDF-only is curated-only or dropped; do not scrape it. Cite the actual org per row
(`"ASE IR"`, `"MediaTek IR"`) — **never** reuse `SRC_PUBLISHED`, which is hardcoded to
`"TrendForce (public release)"` (§9).

**DONE-WHEN:** each added issuer has ≥ 3 months of live-crawled revenue and its own
`_SC_DEMAND_SLA` key showing green.

**CONSTRAINTS:** one `try/except` per issuer — one bad IR page must not abort the run (§6.1).
Add an SLA key per issuer or the series is unmonitored (§6.5).

**VERIFY:** local crawl, then reconcile each issuer's latest month against its IR page by hand.
Prod — `/api/db-stats` shows one `sc_demand[...]` key per issuer.

</details>

---

## ✅ SC-14 — Curated loaders never delete; retractions were a no-op in prod — **DONE 2026-08-02**

```
TITLE:        Make load_curated_dram_spot() reconcile (insert AND delete)
TYPE:         bug                                    PRIORITY: P0 blocker — CLOSED
```

**Found while preparing the round-1 push (#0).** Disk defined 53 `sc_dram_spot` rows;
`/api/db-stats` reported **87**. The 34-row difference is exactly SC-04's falsified DDR set.

Root cause: every `load_curated_*()` is `INSERT OR REPLACE` only. That propagates a *changed*
value but never a *withdrawn* one — a tuple removed from `products_config.py` survives on the
Railway volume indefinitely. **SC-04's headline fix — deleting falsified data rather than
relabelling it — was inert in production while reading as complete in git.** Pushing #0 without
this would have shipped the retraction and left the falsified series on the chart.

**FIXED:** `load_curated_dram_spot()` inserts, then deletes any
`(product_type, spec_label, period)` absent from `CURATED_DRAM_SPOT`, via a temp key table.
Verified on a simulated prod DB: 56 → 53 rows, correct 3 deleted, idempotent on re-run,
`MAX(period)` still 2026-06. Runs every deploy through `startup.sh --curated-only`.

**Scope deliberately limited to `sc_dram_spot`** — it has no live writer, so the curated list
is its complete intended contents. `sc_prices` has PassMark/Newegg writers; a reconcile there
**must** be scoped to `source='curated'` or it deletes live scraped history.

**Follow-through owed by other tickets:** SC-09 (HBM purge) and SC-10 (`sc_semi_btb` drop) are
both deletions and inherit this defect — SC-09 is now covered by this reconcile, SC-10 still
needs its explicit `DROP TABLE`. `CURATED_CAPACITY`, `CURATED_RETAIL_PRICES`,
`CURATED_STEAM_SURVEY`, `CURATED_DEMAND_INDICATORS` remain insert-only: **do not remove rows
from those lists expecting prod to follow.** New `CLAUDE.md §9` row added.

---

## ✅ SC-00 — `sc_semi_btb` publishes a series that no longer exists — **FULLY DONE 2026-08-02**

```
TITLE:        Replace the retired B2B series with SEMI WWSEMS quarterly billings
TYPE:         bug                                    PRIORITY: P0 → P1 — CLOSED
```

> **Done 2026-08-02 (fix A — the misattribution is closed):**
> - All 41 `CURATED_SEMI_BTB` source labels → `"Modeled estimate — NOT a SEMI publication"`.
> - `crawl_semi_btb()` retired to a documented no-op stub; `_parse_semi_btb_article()` deleted.
> - Yellow in-panel disclaimer + retitled chart/section/footer in `_sc_btb_panel()`;
>   Supply-Chain header text and top-level source footer updated.
> - Propagates to prod automatically — `startup.sh` L71 runs `--curated-only` every deploy
>   and `sc_semi_btb` PK is `period`, so `INSERT OR REPLACE` overwrites the old labels.
>
> **Done 2026-08-02 (fix B — done as part of SC-06):** SEMI WWSEMS quarterly billings (Q2/Q3
> 2025 + Q1 2026, all genuinely published) now live in `sc_demand_indicators`, rendered in the
> new `_sc_demand_panel()`. `_sc_btb_panel()` and its call site are removed — see SC-06 for the
> full writeup. `sc_semi_btb` the table/loader/crawler-stub are left in place (harmless, already
> a no-op) rather than renamed, per `CLAUDE.md §7` rule 2.

**WHAT / WHY:** `CURATED_SEMI_BTB` holds 41 monthly values (2023-01 → 2026-05) attributed to
`"SEMI NA Equipment B2B"`. SEMI discontinued the North American Book-to-Bill report after the
**December 2016** report; the NA billings *press release* also ceased Feb-2022
[Source: SEMI, *Historical Book-to-Bill Report (1991–2016)*]. These numbers therefore cannot
have come from SEMI — they are modeled estimates rendered with an authoritative label, which
is a direct violation of the zero-hallucination rule in `CLAUDE.md §8`.

`crawl_semi_btb()` compounds it: it scrapes semi.org for a "book to bill" press release that
has not been published in ~9 years, fails silently, logs a warning, and leaves the invented
curated rows in place — indistinguishable from live data in the UI.

**WHERE:**
- `products_config.py` → `CURATED_SEMI_BTB` (41 tuples, `('YYYY-MM', ratio, source)`)
- `supply_chain_crawler.py` L504–545 → `crawl_semi_btb()`, `_parse_semi_btb_article()`
- `dashboard.py` → the B2B panel in the Supply Chain tab (grep `sc_semi_btb`)

**FIX (pick A, prefer B):**
- **A — minimum, ~15 min:** rewrite every source string to
  `"Modeled estimate — NOT a SEMI publication"` and add a persistent caption under the chart.
  Honest, but the series still carries no information.
- **B — correct, ~2 h:** replace the metric entirely with **SEMI WWSEMS quarterly billings**,
  which is live and authoritative: Q1 2026 = **$36.55 B, +14 % YoY, +1 % QoQ**, released
  2026-06-04 [Source: SEMI WWSEMS]. Add `sc_equipment_billings` (period, billings_usd_bn,
  yoy_pct, qoq_pct, source, source_url); point the crawler at the quarterly press-release URL
  pattern; retire `crawl_semi_btb()` and drop the `sc_semi_btb` panel.

**DONE-WHEN:** no chart in the app attributes a number to a SEMI publication that did not
publish it; the B2B panel either shows WWSEMS billings or is gone.

**CONSTRAINTS:** New table ⇒ **ask Simpo first** (`CLAUDE.md §1` step 7, §4). `INSERT OR REPLACE`
for idempotency. Do not rename `sc_semi_btb` in place — `CLAUDE.md §7` rule 2 (migration script
required); add the new table and drop the panel instead.

**VERIFY:** local — Supply Chain tab renders with no callback error, no B2B chart or a WWSEMS
chart with a real "As of" date. Prod — `/api/db-stats` shows the new table; `/health` still ok.

---

## ✅ SC-01 — Newegg crawler writes NULL-price rows — **DONE 2026-08-02**

```
TITLE:        Stop persisting NULL-price rows from the Newegg scraper
TYPE:         bug                                    PRIORITY: P0 blocker — CLOSED
```

> **Done 2026-08-02.** `crawl_newegg()` now skips the row when `price is None` (WARNING per
> product), reports a miss rate, and logs `NEWEGG SCRAPER LIKELY BROKEN` at ERROR when ≥50 %
> of products return no price. `purge_null_price_rows()` (new, idempotent) deletes contentless
> rows and runs in Step 2 of `crawl_supply_chain()`, so prod self-cleans on the next deploy
> via `startup.sh` `--curated-only`.
>
> Tested against a scratch DB: total-failure run wrote **0** rows (was 25); partial run wrote
> **3/3 priced, no NULLs**; seeded NULL rows purged with curated + passmark rows untouched.
> Lesson recorded in `CLAUDE.md §9`.
>
> **Note:** the scraper itself is still broken (100 % miss rate) — it now fails *loudly*
> instead of silently. Deciding its fate is **SC-06**.

<details><summary>Original ticket (kept for context)</summary>

**WHAT / WHY:** Every `newegg` row in prod has `price_usd IS NULL` — 175 of 175. Newegg now
serves JS-rendered listings behind bot detection, so both parse paths in
`_newegg_search_price()` (the JSON-LD block and the `.price-current` CSS fallback) miss and
return `(None, None)`. `crawl_newegg()` then appends the row **regardless of outcome**, so the
row count climbs daily while the data is empty — and `/api/db-stats` reports it as healthy.

**WHERE:**
- `supply_chain_crawler.py` L435 — `rows.append((model_id, TODAY, "newegg", price, None, None, in_stock))`
  sits outside any `if price` guard
- `supply_chain_crawler.py` L381–422 — `_newegg_search_price()` parse paths

**FIX:**
1. Guard the write (2 lines, do this first — stops the bleeding):
   ```python
   if price is None:
       log.warning("  Newegg — no price for %s; row skipped", model_id)
       continue
   rows.append((model_id, TODAY, "newegg", price, None, None, in_stock))
   ```
   A missing row is honest; a NULL row is a lie that inflates the health endpoint.
2. Track a failure rate in the run: if >50 % of products yield no price, log
   `NEWEGG SCRAPER LIKELY BROKEN` at ERROR so it surfaces in Railway logs.
3. Then decide the source's fate — see **SC-06**. Retail consumer GPU price is low-signal for
   a portfolio now dominated by datacenter revenue; killing this scraper is a defensible outcome.

**DONE-WHEN:** a local `python3 supply_chain_crawler.py` run stores zero NULL-price rows, and
the existing NULL rows are deleted:
```sql
DELETE FROM sc_prices WHERE source='newegg' AND price_usd IS NULL;
```

**CONSTRAINTS:** None of the §7 hard rules. Deleting rows is safe — `sc_prices` PK is
(model_id, date, source) and every affected row is contentless.

**VERIFY:** local — run the crawler, then
`SELECT source, COUNT(*), COUNT(price_usd) FROM sc_prices GROUP BY source;` → counts must match.
Prod — after deploy, same query via `/api/export-xlsx`.

</details>

---

## ✅ SC-02 — Steam Hardware Survey frozen at 2025-03 — **DONE 2026-08-02**

```
TITLE:        Repair or retire the Steam HW Survey live crawl
TYPE:         bug                                    PRIORITY: P1 — CLOSED
```

> **Done 2026-08-02.** Diagnosis first, per the ticket: the page is **server-rendered**, not
> JS-only. The crawler was looking for a `"hardware":"…"/"percentage":"…"` JSON blob that the
> page has never contained, so it matched nothing and wrote zero rows without raising. The
> HTML fallback would have been *worse* than nothing — it scraped the per-DirectX-class
> tables, where percentages are shares **within** a class (Intel HD Graphics 4000 ≈ 28 %
> under "DIRECTX 11 GPUS"), which would have put a decade-old iGPU at the top of the chart.
>
> - New `_parse_steam_survey()` — bounded to the "ALL VIDEO CARDS" section, takes the
>   second-to-last column (the last is the MoM delta), reads the survey's own month from the
>   page heading so a stale page can never be stamped with today's date (§7.3).
> - **Validation gate before writing:** ≥15 entries, shares summing 40–105 %, month parsed.
>   On failure it logs `STEAM SURVEY PARSE REJECTED` at ERROR and keeps the curated seed —
>   a bad parse can no longer overwrite good data, and can no longer fail silently.
> - `CURATED_STEAM_SURVEY` replaced with **real May-2026 Valve data** (40 rows, verbatim from
>   the ALL VIDEO CARDS table). The old 2025-03 seed did not match Valve's published figures
>   — it had RTX 4060 at 9.24 % against ~4 % actual, apparently renormalised over a top-N
>   subset. Same disease as SC-00, so it was replaced wholesale rather than extended.
> - Panel now carries an "As of `<survey month>`" badge, red at 4+ months (Valve publishes
>   with a 1–3 month lag, so a 3-month threshold would cry wolf).
>
> Tested: parser against a live-page fixture — 17/17 rows correct, DX-class rows and the
> "Other" bucket excluded, gap rows (`-`) handled; gates reject a JS shell, a truncated
> table, and a missing section boundary while leaving the seed at 22 rows intact; panel
> renders "current" at 2026-05 and flags stale when forced back to 2025-03.
>
> **Residual:** the live path is verified against a fixture, not against Valve's DOM (no
> browser in this environment). First real run will either store ~40 rows or log
> `STEAM SURVEY PARSE REJECTED` — check the Railway log after deploy and adjust the parser
> if rejected. It cannot corrupt data either way.

<details><summary>Original ticket (kept for context)</summary>

**WHAT / WHY:** `sc_market_share` contains exactly the 22 rows of `CURATED_STEAM_SURVEY`, all
stamped `2025-03`. The live crawl has produced nothing since. The `re.DOTALL` fix logged in
`CLAUDE.md §9` addressed the regex but did not restore the data path — Valve serves the survey
via a JS-rendered page, so `SESSION.get()` returns a shell and both the regex and the
BeautifulSoup table fallback come back empty. The GPU share chart therefore presents a
17-month-old snapshot with no visual indication it is stale.

**WHERE:** `supply_chain_crawler.py` L450–500 → `crawl_steam_survey()`

**FIX:**
1. Confirm the failure mode first — `curl` the URL and check whether `"percentage"` appears in
   the raw HTML at all. Do not re-tune the regex before confirming the payload is present.
2. If the payload is JS-only: Valve exposes the survey data as a JSON endpoint used by the
   page; fetch that directly. Do **not** escalate to a headless browser — that is not
   deployable on Railway within the current footprint.
3. If no stable endpoint exists: retire the live crawl, keep the curated seed, and stamp the
   panel with the observation date per `CLAUDE.md §7.3` ("As of 2025-03") so a stale figure
   cannot read as current.
4. Either way, refresh `CURATED_STEAM_SURVEY` to the latest published month.

**DONE-WHEN:** the GPU share chart either carries data ≤ 2 months old, or visibly states the
snapshot month next to every figure.

**CONSTRAINTS:** `CLAUDE.md §7.3` — surface the observation date; never let a retired series
read as live. No new dependencies without asking (`§1` step 7).

**VERIFY:** local — Supply Chain → GPU sub-tab; confirm the "As of" label matches
`SELECT MAX(period) FROM sc_market_share`.

</details>

---

## ✅ SC-03 — `/api/db-stats` reports row counts, not freshness — **DONE 2026-08-02**

```
TITLE:        Add per-table freshness + null-rate to /api/db-stats and a staleness badge
TYPE:         feature                                PRIORITY: P1 — CLOSED
```

> **Done 2026-08-02.** New freshness module in `dashboard.py` (`_FRESHNESS_SPEC`,
> `_period_end_date`, `_freshness_report`, `_stale_sources` — documented in `CLAUDE.md`
> §2.3 / §6.5).
>
> - Tracks **two** independent failures, not one: `stale` (observation older than SLA) and
>   `empty` (≥50 % of rows carry no value). `unhealthy = stale OR empty`. Without the second,
>   the badge would have missed SC-01 entirely — those Newegg rows were dated *today*.
> - Month/quarter periods age from the period **end**, so a May figure isn't "30 days late"
>   on 1 June.
> - `/api/db-stats` gains `freshness`, `stale_sources`, `stale_count`, `data_ok`; existing
>   flat row counts kept for backward compatibility. Auth unchanged (401 without the key).
> - Navbar `data-freshness-badge` — 🟢 "data: fresh" or 🔴 "N stale/empty sources" with a
>   per-source hover breakdown. Mirrors the proven `ibkr-status-badge` pattern (navbar-level
>   Output on `status-interval`, never nested in tab-content → §7 rules 3 & 4 clear).
> - `sc_market_share` SLA set to 120 d to agree with the panel's own 4-month "As of" marker.
>   Two surfaces disagreeing about the same table is how a real signal gets ignored.
>
> Tested against a DB reproducing prod: correctly flags 5 unhealthy sources (`sc_capacity`
> 489 d, `sc_prices[curated]` 93 d, `sc_dram_spot` / `sc_semi_btb` 63 d, `sc_prices[newegg]`
> 100 % empty-but-fresh); returns 🟢 and `data_ok: true` on an all-current DB; endpoint 200
> with key / 401 without; layout builds with no `DuplicateCallbackException`.
>
> **On first deploy the badge will read 🔴 — that is correct**, and it is SC-04's queue.

<details><summary>Original ticket (kept for context)</summary>

**WHAT / WHY:** Root cause that let SC-00 → SC-02 run undetected. `/api/db-stats` returns
`COUNT(*)` per table only, so a table frozen 17 months ago and a table refreshed this morning
look identical. This is the same lesson as the volume guard: the system must be **loud** about
silent decay, not merely up.

**WHERE:** `dashboard.py` L4210–4250 → `db_stats()`; navbar badge area (grep `ibkr-status-badge`
for the existing pattern to copy).

**FIX:**
1. Extend `db_stats()` with, per table, `max_date` (the table's own date column),
   `days_stale`, and — for `sc_prices` — `null_price_pct` by source.
2. Define an SLA per table and return `stale: true` when breached:

   | Table | Date column | SLA |
   |---|---|---|
   | `daily_prices`, `market_sentiment`, `cycle_analysis` | `date` / `snapshot_date` | 4 days |
   | `quarterly_financials` | `period_end` | 120 days |
   | `sc_prices` (live sources) | `date` | 7 days |
   | `sc_prices` (curated), `sc_dram_spot` | `date` / `period` | 45 days |
   | `sc_market_share` | `period` | 60 days |
   | `sc_capacity` | `period` | 150 days |

3. Add a yellow navbar badge — "⚠ N stale sources" — mirroring the red volume banner, linking
   to a tooltip listing the offenders.

**DONE-WHEN:** `curl /api/db-stats` returns `max_date` + `days_stale` for every table, and the
badge appears today (it should — at least four tables are currently breaching).

**CONSTRAINTS:** `CLAUDE.md §7` rule 3 (unique Output ID — grep before adding the badge ID) and
rule 10 (no `/` in component IDs). `/api/db-stats` stays authenticated; do not widen it.

**VERIFY:** local — badge renders and lists SC-02/SC-04 tables. Prod — `/api/db-stats` includes
the new fields; `/health` unchanged.

</details>

---

## 🟠 SC-04 — Curated data stale — **DRAM FIXED 2026-08-02; CAPACITY + RETAIL STILL OPEN**

> **Done 2026-08-02 — and the ticket was wrong about the problem.** `sc_dram_spot` was not
> merely stale, it was **falsified and inverted**:
>
> | | DB claimed (2026-05) | Actually published |
> |---|---|---|
> | DDR4 8Gb 1Gx8 spot | $2.02, drifting **down** | **$36.00** (2026-06-30) [TrendForce] |
> | Conventional DRAM contract | — | **+93–98 % QoQ** in 1Q26 [TrendForce, 2026-06-01] |
> | DRAM industry revenue | — | **+81 % QoQ to $97 B** in 1Q26 [TrendForce] |
>
> 34 DDR4/DDR5 rows (2025-01 → 2026-05) decayed −1 % to −2 % **every month for 17
> consecutive months, never once reversing**, through the largest DRAM upcycle on record —
> all labelled `SRC_PUBLISHED "TrendForce (public release)"`. That shape is extrapolated
> filler; SC-05 certified it as published in error.
>
> - **Deleted, not relabelled.** A wrong number is worse than no number (§8). The
>   2025-01 → 2026-05 hole is deliberate and documented in the `CURATED_DRAM_SPOT` header.
> - Added the one genuinely citable anchor: DDR4 2026-06 = **$36.00**, source
>   `"TrendForce spot (2026-06-30)"`. **No DDR5 row** — the only figures found were a
>   third-party "mid-$40s" paraphrase, not precise enough to write down.
> - `_mem_break_gaps()` (new, §2.3) inserts a NaN so Plotly cannot draw a line from
>   2024-12 ($2.65) to 2026-06 ($36.00) — that line would have shown an 18-month climb
>   that never happened. Applied at both RAM plot sites.
> - `_mem_yoy()` floor tightened 18 → 15 months: post-purge it was reporting **"+1258.5 %
>   YoY"** for an 18-month move. DDR4 now correctly returns "—".
> - Yellow in-panel notice explains the gap is withdrawn data, not a rendering fault.
> - **SLA calibration** (SC-03 follow-through): `wsts_billings` 45 → 75 d and
>   `semi_wwsems_billings` 110 → 160 d, matching real publication lag (Q1-2026 WWSEMS
>   landed Q+65 d, so Q2 isn't due until ~September). `sc_semi_btb` removed from
>   `_FRESHNESS_SPEC` — its panel is gone, so monitoring it would fire forever.
>   Badge went 5 unhealthy → **2**, both genuine.
>
> **STILL OPEN — needs your decision, both blocked on the same question:**
>
> | Source | State | Why I stopped |
> |---|---|---|
> | `sc_capacity` | 2025-Q1, **489 d** stale | TSMC Q2-2026 actuals *are* published (rev $40.20 B, 4,336k 12-inch-equiv wafers, 2nm 3 % / 3nm 30 % / 5nm 33 % of wafer revenue), but **per-node `capacity_kwpm` and `utilisation_pct` are disclosed by no foundry**. Filling them means modeling — the exact act that produced this ticket |
> | `sc_prices[curated]` | 2026-05, **93 d** stale | Already `SRC_MODELED`; extending it means generating three more months of modeled retail prices |
>
> Pick one per source: **(a)** restructure to what foundries actually publish (wafer
> shipments, revenue by node, capex — schema change, ask-first gate); **(b)** backfill as
> explicit `SRC_MODELED` with a visible disclaimer like the old B2B panel; or **(c)** leave
> stale and let the badge report it honestly. I did not choose for you — every option
> writes numbers into a chart you may show someone.

<details><summary>Original ticket (kept for context)</summary>

### SC-04 — Curated data 3 months to 5 quarters behind

```
TITLE:        Backfill curated retail, DRAM, and fab-capacity series to current
TYPE:         data-refresh                           PRIORITY: P1
```

**WHAT / WHY:** The monthly refresh in `CLAUDE.md §10` has not been run. Gaps:
`CURATED_RETAIL_PRICES` and `CURATED_DRAM_SPOT` stop **2026-05** (3 months); `CURATED_CAPACITY`
stops **2025-Q1** (5 quarters) — the fab-utilisation panel is effectively a historical exhibit.

**WHERE:** `products_config.py` → `CURATED_RETAIL_PRICES`, `CURATED_DRAM_SPOT`,
`CURATED_CAPACITY`; re-run `python3 supply_chain_crawler.py --curated-only`.

**FIX:** add rows through 2026-07 / 2026-Q2. Capacity rows come from company earnings decks
(TSMC, Intel, Micron, SK Hynix, Samsung) — already the pattern in the existing `source` column.
While in the file, **automate the trigger**: SC-03's staleness badge should make the next lapse
self-reporting.

**DONE-WHEN:** every curated series' `MAX(period)` is within its SC-03 SLA.

**CONSTRAINTS:** `CLAUDE.md §7.3` — any newly retired series must still fall inside the chart's
default x-window, and `_mem_yoy()` must return `"—"` rather than a fake `0.0 %`. New memory
types need a `_MEM_DIE_GB` entry (`§2.3`) or $/GB is silently understated. Capacity bars must
keep the per-bar period stamp (`§9`).

**VERIFY:** local — RAM, GPU, CPU, and Capacity sub-tabs; confirm every "As of" is current and
no YoY reads exactly `+0.0 %`.

</details>

---

## ✅ SC-05 — Sourcing labels overstate provenance (fixed 2026-08-02)

```
TITLE:        Distinguish licensed data from hand-entered estimates in every source label
TYPE:         bug                                    PRIORITY: P2
```

**WHAT WAS WRONG:** `CURATED_DRAM_SPOT` rows were labelled `"TrendForce"` and `"TrendForce est."`.
TrendForce/DRAMeXchange **is** the industry-standard DRAM spot source, but the project holds no
licence — these are numbers transcribed or inferred from public commentary. The label implied a
data feed that does not exist. Same issue in every `_source_footer()` call across the Supply
Chain tab (Enterprise GPU, Enterprise CPU, RAM, GPU/CPU/RAM overview, consumer price history) —
each cited "TrendForce", ODP, Gartner/IDC, or Goldman/Wells Fargo as flat `[Source: ...]`
citations for numbers that are actually this project's own estimate.

**FIX applied:**
- `products_config.py` now defines `SRC_PUBLISHED = "TrendForce (public release)"` and
  `SRC_MODELED = "Modeled estimate"` — the two-tier vocabulary (earnings-sourced rows keep their
  existing `"<Company> Q<n> <YYYY> earnings"` format, already correct).
- `CURATED_DRAM_SPOT`: DDR4/DDR5 rows (genuinely transcribed from TrendForce's free weekly spot
  articles) relabeled `SRC_PUBLISHED`; HBM3/HBM3E rows (contract prices never publicly quoted)
  relabeled `SRC_MODELED`.
- `CURATED_RETAIL_PRICES` has no per-row provenance field (its `source` column is DB routing:
  `"curated"` vs. live `"newegg"`/`"passmark"`) — added `CURATED_RETAIL_PROVENANCE = SRC_MODELED`
  at the catalog level and surfaced it in `dashboard.py`'s footer instead of migrating ~1,000 rows.
- `dashboard.py`: every `_source_footer()` in the Supply Chain tab (RAM/DRAM ×2, Enterprise GPU,
  Enterprise CPU, GPU/CPU/RAM overview, consumer price history, Overview snapshot) now separates
  the genuine primary source (official specs, launch ODP, earnings transcripts) from the modeled
  portion, and states plainly that TrendForce/Gartner/Goldman/Wells Fargo citations are
  *informed by*, not a licensed feed of. The DRAM YoY table's per-row `Source` column is
  color-coded (green = published, yellow = modeled) and its zero-hallucination default fallback
  changed from `"TrendForce"` to `SRC_MODELED`.

**Deliberately NOT done — `source_url` column:** the ticket suggested adding a `source_url`
column. Skipped: every `SRC_MODELED` row has no genuine URL to attach (that's what makes it
modeled), and fabricating one would violate the same zero-hallucination rule this fix enforces.
`SRC_PUBLISHED` rows (TrendForce DRAMeXchange weekly articles) don't have stable per-week URLs
either. If a real per-source landing page shows up worth linking, add it then — don't build
unused schema now.

**VERIFIED:** local — loaded `CURATED_DRAM_SPOT`/`CURATED_RETAIL_PRICES`/`CURATED_CAPACITY` into
a scratch DB and rendered `_sc_dram_inline`, `_sc_enterprise_gpu_section`,
`_sc_enterprise_cpu_section`, `_sc_enterprise_ram_section` — no callback errors; DRAM YoY table
confirmed `DDR4/DDR5 → "TrendForce (public release)"`, `HBM3/HBM3E → "Modeled estimate"`.
Prod verification (`/health`, visual check of Supply Chain tab) still pending next deploy.

---

## ✅ SC-06 — Source mix is consumer-weighted; no authoritative demand series (fixed 2026-08-02)

```
TITLE:        Add free authoritative semiconductor demand indicators
TYPE:         feature                                PRIORITY: P2 — CLOSED
```

**WHAT WAS WRONG:** The supply-chain layer reasoned about a datacenter-driven market using
consumer-retail proxies (Newegg, PassMark, Steam). None of the four industry-standard demand
series was tracked.

**FIX applied — all four series added, one unified table:**
- New `sc_demand_indicators` table (`indicator_key, metric_label, period, period_type, value,
  unit, yoy_pct, seq_pct, source, notes`) in `supply_chain_crawler.py`, rather than four bespoke
  tables — the series share the same shape (period → value), just different cadence/units.
- `CURATED_DEMAND_INDICATORS` in `products_config.py`, 19 rows, every one **genuinely published**
  (verified by fetching each source directly on 2026-08-02, not carried over from training data):
  TSMC monthly revenue Jan–Jun 2026 [TSMC IR], UMC monthly revenue Jan–Jun 2026 [UMC IR], Korea
  chip exports Jul 1–20 2026 = $22.1B (+180% YoY) [Korea MOTIE/KITA], WSTS global sales Mar–May
  2026 [WSTS/SIA], SEMI WWSEMS billings Q2/Q3 2025 + Q1 2026 [SEMI]. `source` is the actual org
  name per row, **not** the `SRC_PUBLISHED` constant — that string is hardcoded to `"TrendForce
  (public release)"` for SC-05's DRAM series specifically and would have misattributed this data
  (caught and fixed before shipping — same class of bug SC-05 exists to prevent).
- **Live crawlers for TSMC + UMC only** (`crawl_tsmc_revenue()` / `crawl_umc_revenue()`): both IR
  pages were fetched and confirmed plain server-rendered HTML tables (not JS shells). Regex-based
  parser validated against the real page content, gated by a plausibility check (TSMC
  NT$100–1000B, UMC NT$10–50B) before writing — a bad parse keeps the curated seed and logs
  `TSMC/UMC REVENUE PARSE REJECTED`, never a silent or partial write (SC-01/SC-02 lesson).
- **Korea MOTIE, WSTS, and SEMI WWSEMS stay curated-only** — deliberately, not deferred. WSTS's
  monthly data sits behind a members-only login; Korea MOTIE and SEMI publish one-off press
  articles, not a stable per-period table. Scraping any of these would repeat the exact SC-02/
  SEMI-BTB mistake (parsing a page shape that isn't actually there). Update by hand as each
  source releases new data — same maintenance pattern as `CURATED_DRAM_SPOT`/`CURATED_CAPACITY`.
- **Also closes SC-00 fix B**: the retired `sc_semi_btb` panel (`_sc_btb_panel()`) is replaced by
  `_sc_demand_panel()`, which includes SEMI WWSEMS billings as one of its four charts. The
  `sc_semi_btb` table/loader/crawler stub are left as-is (harmless, already a documented no-op)
  since `CLAUDE.md §7` rule 2 rules out renaming — only the UI panel and its call site were
  removed, per the original SC-00 plan ("add the new table and drop the panel instead").
- `dashboard.py`: 2×2 subplot (TSMC/UMC revenue, Korea exports, WSTS billings, SEMI WWSEMS) +
  latest-value/YoY table + `_source_footer` naming each org directly. Per-indicator freshness
  SLA added to `_freshness_report()` (`_SC_DEMAND_SLA`), same per-key pattern as `_SC_PRICE_SLA`.
  `sc_demand_indicators` added to `/api/db-stats` and the export-sheet name map.

**VERIFIED:** local — loaded all 19 curated rows into a scratch DB; `_sc_demand_panel()` and the
full `tab_supply_chain()` render with no callback error; `_freshness_report()` correctly flags
`sc_demand[wsts_billings]` and `sc_demand[semi_wwsems_billings]` as stale (their sources genuinely
haven't published June/Q2 data yet) while `tsmc_revenue`/`umc_revenue`/`korea_chip_exports_20d`
report healthy — the monitor reflects real gaps, doesn't paper over them. `_parse_tsmc_revenue` /
`_parse_umc_revenue` unit-tested against simulated page text matching the real fetched tables
(exact value/YoY/MoM match) and against garbage input (returns `[]`, triggers the reject path,
row count unchanged). Prod verification (`/api/db-stats`, visual check of the new panel, whether
the live TSMC/UMC crawl actually succeeds against the real DOM) pending next deploy.

---

## 🟡 SC-07 — `yfinance` is a prototype-grade source; make its limits explicit

```
TITLE:        Document yfinance limitations; move fundamentals to SEC EDGAR
TYPE:         feature                                PRIORITY: P2
```

**WHAT / WHY:** `crawler.py` sources prices, fundamentals, and IV from `yfinance` — an
unlicensed scrape of Yahoo with no SLA, no redistribution right, and known-unreliable `.info`
fields (already the root cause of the all-NULL IV issue in `CLAUDE.md §9`). Acceptable for
charting; not a basis for an investment decision, and the dashboard does not say so anywhere.

**FIX:**
1. Add a one-line data-provenance note in the app footer: prices/fundamentals are Yahoo-sourced
   and unofficial.
2. Move `quarterly_financials` to the **SEC EDGAR `companyfacts` API** — free, authoritative,
   XBRL, restatement-aware. Covers the US names; keep yfinance for TSM/ASML/foreign filers.
3. Finish the IBKR IV path (`CLAUDE.md §11`) — it is the correct source for implied vol and is
   already scaffolded. Do the durability items below **first**: `options_iv_history` will exist
   nowhere else.

**CONSTRAINTS:** EDGAR requires a declared `User-Agent` with contact email or requests are
throttled. Do not change `quarterly_financials` column names (`§7` rule 2).

---

## 🟠 Open — Enterprise GPU Price Data Requires Monthly Curated Updates

The GPU (Enterprise) tab in Supply Chain now tracks A100/H100/H200/B200/MI300X contract prices.
These are modeled estimates, not live scraped data (no Newegg/PassMark for enterprise GPUs).

**Update monthly:** extend `CURATED_RETAIL_PRICES` enterprise rows in `products_config.py`
using TrendForce enterprise GPU channel reports, cloud GPU spot pricing (CoreWeave/Lambda),
and analyst research (Goldman/WF semiconductor team).

Format: `("MODEL-ID","YYYY-MM-01","curated",price_usd,None,None,None)`.

When a new flagship GPU ships (e.g. B300, MI400), add it to `GPU_ENTERPRISE_PRODUCTS` and
add a corresponding entry to `FLAGSHIP_ERAS` and `GA_MARKERS` inside `_sc_enterprise_gpu_section()`.

---

---

## 🟠 BK-01 — Restorable backup path — **CODE DONE 2026-08-09; NOT DEPLOYED; 3 MANUAL STEPS OPEN**

Replaces Durability Follow-up #1 (below), which turned out to be un-doable: Railway volume
backups are Pro-only and this project is on Hobby. Lesson row added to `CLAUDE.md §9` (BK-01);
`§5.1` corrected and `§5.2` added.

**Shipped to disk (not yet pushed):**

| File | Change |
|---|---|
| `dashboard.py` | New `GET /api/export-db` (`VACUUM INTO` snapshot, `conn.backup()` fallback for SQLite < 3.27) and `GET /api/export-bundle` (zip: xlsx + db + README). ⬇️ Download Data button repointed at the bundle. `_build_export_workbook()` / `_snapshot_db()` extracted as shared helpers. **Auth gate removed from `export-db`** — see BK-02 in `CLAUDE.md §9`; the xlsx route was already public and dumped every table, so the gate protected only schema DDL while blocking the very button that needed it |
| `local/backup_local.sh` | Rewritten: pulls `.db.gz` (the backup) + `.xlsx` (reading copy); `PRAGMA integrity_check` + `MIN_PRICE_ROWS` floor before keeping; prints un-backfillable snapshot-table counts; `crawl_ok` warning; restore recipe in footer |
| `local/com.simpo.semibackup.plist` | New launchd agent, daily 09:15 — replaces cron |
| `local/.backup_env.example` | Template for the gitignored `RELAY_API_KEY` file |
| `.gitignore` | `backups/`, `*.db.gz`, `local/.backup_env` — the old xlsx backups were landing in a **tracked** directory |

**Verified locally 2026-08-09** (mock server + sqlite shim): auth gate 401/401/200 incl.
fail-closed on an empty server key · `VACUUM INTO` consistent with WAL open · magic-string
check · integrity gate · row-floor breach aborts **and preserves existing backups, leaving no
partial `.db`** · unreachable host aborts cleanly · prune honours `KEEP` · **restore drill
passed** (gunzip → `integrity_check ok` → row count intact).

**Open — the three that cannot be done from code:**

1. **Push and re-verify against prod.** `curl .../api/export-db -o t.db` (no key needed now),
   confirm magic + `integrity_check` + `daily_prices` ≈ 46 k. Then click ⬇️ Download Data and
   confirm you get **one .zip with three members**. Container SQLite version is unverified —
   if it is < 3.27 the `conn.backup()` fallback fires; both paths are correct, but confirm
   which one ran by checking the file is not oddly large (VACUUM compacts).
   **Watch peak memory on the bundle route:** the workbook is held in RAM while the zip is
   built. The `.db` is streamed from disk by `ZipFile.write()` specifically to avoid holding
   both uncompressed, but on a small Railway container a large export is the plausible OOM,
   and gunicorn's `--timeout 120` is the plausible timeout. If either bites, the fix is to
   stream the zip rather than buffer it — not to drop the `.db` from the bundle.
2. **Install the launchd agent and DELETE the old crontab line.** Both running = two
   backups/day and a confusing log. Grant Full Disk Access to `/bin/bash`, then
   `launchctl start com.simpo.semibackup` once — do not wait for 09:15 to discover TCC.
3. **Point `BACKUP_DIR` at cloud storage** (`~/Library/CloudStorage/…`). Until then the only
   copy of production lives on one Mac, in the project folder.

**Known minor:** `STAMP` is minute-granular, so two runs inside the same minute overwrite one
file. Irrelevant at daily cadence; do not "fix" it by adding seconds without checking the
prune globs still match.

---

## 🟠 Durability Follow-ups — **#2 VERIFIED, #3 SCRIPT HARDENED 2026-08-02; #1 CLOSED-AS-IMPOSSIBLE 2026-08-09 (see BK-01)**

> **#2 — volume guard verified in prod (2026-08-02):**
> `/health` → `{"db":true,"status":"ok","volume_ok":true,"volume_reason":"ok"}`.
> The DB is on the mounted volume; the silent-ephemeral failure mode (§5.1) is not active.
>
> **#3 — `backup_local.sh` tested end-to-end before being trusted, not just read:**
> HTTP 200, valid `.xlsx` (PK magic), 2.8 MB, 14 sheets, 46,047 `Daily Prices` rows;
> prune tested at `KEEP=12` with 16 files → 12 retained. It works.
>
> The workbook doubles as an independent confirmation of the pending push: it still shows
> `SC DRAM Spot` = **87** rows and a `SC Book-to-Bill` sheet = **41** rows, i.e. the falsified
> DDR rows and the dead B2B table are live in production right now.
>
> **Three defects found while testing — all in the *scheduling*, which is the part nobody
> tests:**
>
> 1. **The documented crontab line fails on a fresh machine.** `>> backups/backup.log` is
>    opened by the shell *before* the script runs, so if `backups/` does not exist the job
>    dies at redirect time and the script never executes — error going to local mail nobody
>    reads. The script's own `mkdir -p` is too late. Corrected line now includes
>    `mkdir -p backups &&`.
> 2. **macOS TCC will block this silently.** The project lives in `~/Documents`, which is
>    TCC-protected; cron has no Full Disk Access by default, so the job fails
>    "Operation not permitted" every week with no visible symptom. Documented in the script
>    header with the fix and a "schedule it 2 minutes out and verify" instruction.
> 3. **The retention policy could delete the last good backup** (fixed in code). A valid 200
>    plus a valid zip is not proof of intact data: if prod re-seeds onto ephemeral storage the
>    export is a well-formed workbook with a fraction of the history. Because pruning keeps
>    the N most *recent* files, N consecutive degraded backups quietly evict every good copy —
>    the retention policy itself becomes the data-loss mechanism. Added a size-regression
>    guard: if the new file is <50 % of the previous one, warn loudly and **skip pruning**.
>    Verified both branches (healthy → prunes to 12; simulated gutted export → prune withheld,
>    13 files retained).
>
> **#1 — CLOSED AS IMPOSSIBLE 2026-08-09, and that finding invalidated #3's premise.**
> Railway volume backups are a **Pro-plan feature**; this project is on **Hobby**, so the
> "first line of defence" `CLAUDE.md §5.1` asserted never existed. Worse, the surviving layer
> pulled `/api/export-xlsx`, which **cannot be restored from** — no import path, and Excel
> coerces NULL/int/date on the way out. Two documented layers, zero working ones.
> Superseded by **BK-01** below.

<details><summary>Original item (kept for context)</summary>

The volume guard, `volume_ok` reporting, and `backup_local.sh` are implemented (see
`CLAUDE.md §5.1`). Three steps remain that **cannot be done from code**:

1. **Enable Railway volume backups** — service → Settings → Volumes → Backups → schedule
   Daily. Incremental copy-on-write, billed on the delta only; the DB is tens of MB so cost
   is negligible. This is the single highest-value item here.
2. **Confirm the guard passes in prod** after the next deploy:
   ```bash
   curl https://web-production-e3819.up.railway.app/health   # → "volume_ok": true
   ```
   If it returns `false`, read `volume_reason` — the seed crawl will have been skipped and a
   red banner shown, by design.
3. **Cron the off-platform backup:**
   ```bash
   crontab -e
   0 9 * * 0 cd "/Users/simpochiu/Documents/Claude - Industry Data Pj" && mkdir -p backups && ./backup_local.sh >> backups/backup.log 2>&1
   ```
   (`mkdir -p backups` is load-bearing — see the 2026-08-02 note above. macOS also needs
   Full Disk Access granted to cron or this fails silently every week.)

**Do before enabling IBKR (`CLAUDE.md §11`).** Today a wipe costs scraped `sc_prices` history
and the sentiment/cycle snapshot series. Once the IV relay runs, `options_iv_history` becomes
data that exists nowhere else and cannot be back-filled.

</details>

---

## 🟡 Recommended Next Steps (prioritized, not started)

1. **Railway Cron** — schedule `python crawler.py --quick` weekdays 06:00 UTC for automated
   daily refresh.
2. **Monthly curated-data refresh** — DRAM spot + fab capacity in `products_config.py`
   (see Maintenance Calendar in `CLAUDE.md §10`).
3. ~~**Enable IBKR IV**~~ — **done differently.** Replaced by `iv_crawler.py` (cloud-native
   derived IV + Deribit DVOL, no broker/subscription/daemon). IBKR path kept dormant in
   case its specific IV model is ever required — `CLAUDE.md §11.2`.
   **Still open:** add the Railway Cron entry `python iv_crawler.py` (weekdays, after the
   US close) — until then IV only refreshes on redeploy, and the 4-day `options_iv`
   freshness SLA will fire.
   **Also open:** the equity IV series starts with a single observation per ticker, so
   `iv_1m_avg` fills at ~21 trading days, `iv_pct_vs_1y` at ~21, `iv_1y_avg` at 252. Blank
   cells before then are correct — do not "fix" them (`CLAUDE.md §9 IV-03`).
4. **Post-deploy crawl-health check** — call `/api/db-stats` with the relay key to confirm
   row counts after each deploy.
5. **In-UI fresh crawl** — verify the ⚡ Run Crawl navbar button (protected, ~2 min).
6. **Citation metadata in crawl output** — have `crawler.py` store `source_name` and
   `source_url` per data point to satisfy the strict-sourcing persona in `CLAUDE.md §8`.

---

## ⚠️ Action Required After Next Deploy — Re-crawl for 5Y Price History

`config.py` `PRICE_HISTORY_PERIOD` was changed from `"2y"` → `"5y"`. The existing
Railway DB still only has ~2 years of `daily_prices` rows. To populate the full
5-year window (needed for 3Y/5Y rangeselector buttons on Overview and Cycles tabs):

```bash
# Locally:
python3 crawler.py   # full crawl — INSERT OR IGNORE fills in historical rows safely
# Then commit + push to Railway, which will do the same on next boot with fresh DB,
# OR trigger the crawl via the ⚡ Run Crawl navbar button on the live site.
```

This is safe: `daily_prices` uses `INSERT OR IGNORE`, so existing rows are untouched.

---

## ✅ Completed Last Session (2026-05-31) — for context, do not redo

Implemented and committed (verify in git history if unsure):
- Sentiment tab: HV30 fallback, perf color-coding, Category column, Vol-Source badge.
- Cycles tab: Category column, per-ticker `_build_cycle_chart`, `vol_diff_last_cycle` fix in `crawler.py`.
- Supply Chain tab: Steam seed data + `re.DOTALL` regex fix, DRAM merged into RAM sub-tab, price-index x-axis sync.
- Overview tab: removed duplicate `font=` kwarg crash (see `CLAUDE.md §7.1`).
- Supply Chain tab: removed duplicate `xaxis=` kwarg crash (see `CLAUDE.md §7.1`).
- Financials tab: expanded comparison window from 8 to 12 quarters (3 years).
- Bug fix: 1Y/3Y/5Y rangeselector buttons returning empty data — two root causes fixed:
  - `PRICE_HISTORY_PERIOD` `"2y"` → `"5y"` in `config.py` (+ re-crawl needed, see above).
  - Supply-chain charts (`_sc_dram_inline`, `_sc_price_section`, `_sc_vs_etf_panel`) now
    anchor initial x-range to actual data end date rather than today, so the default view
    is not empty when curated data lags the current date.
