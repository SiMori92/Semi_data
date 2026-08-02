# Quality Assurance Review — Investment-Decision Fitness

**Subject:** Semiconductor Industry Tracker (`web-production-e3819.up.railway.app`)
**Reviewer role:** Financial analyst / information-system auditor, semiconductor sector
**Question tested:** *Can this system supply accurate and current industry data sufficient to support semiconductor investment decisions?*

`[Audit Performed: 2026-08-02 · Evidence base: local source tree + curated datasets, read directly]`

**Scope limitation (material):** the live production endpoints (`/health`, `/api/db-stats`, `/api/export-xlsx`) could not be reached from this session — `https://web-production-e3819.up.railway.app/` was blocked/timed out by the fetch layer. No `.git` metadata is present in the mounted folder, so deployed state could not be reconciled against disk. **Every finding below is derived from source code and curated data on disk.** Where a finding depends on production state, it is marked `[UNVERIFIED-PROD]`.

---

## 1. The Verdict

**Not fit for investment decision support in its current state — but not trash.** The equity/price layer is sound and the project's self-instrumentation (freshness, shape-consistency, provenance vocabulary) is better than most commercial data operations. The **industry-data layer — the entire reason this exists rather than a Yahoo Finance tab — rests on roughly 75 genuinely-published data points**, and two undetected defects (fabricated historical valuation metrics; an unverifiable refresh schedule) are of the same severity class as the six data-integrity bugs the project has already fixed.

| Layer | Verdict | Basis |
|---|---|---|
| Price / OHLCV (33 tickers) | 🟢 Sound | yfinance, `INSERT OR REPLACE`, split-safe |
| Quarterly financials | 🔴 **Corrupted** | P/E, market cap, EPS-fallback are point-in-time contamination (F-02) |
| Implied volatility | 🟡 Usable, thin | Derived not published; no backfill possible by design |
| Supply chain / retail prices | 🔴 **Synthetic** | 24 of 26 series formula-generated (F-03) |
| DRAM spot | 🟡 Honest but sparse | 36 rows, 2 series, 17-month deliberate hole |
| Macro demand indicators | 🟢 Accurate / 🔴 **Too sparse to use** | 1–6 observations per series (F-04) |
| Refresh cadence | 🔴 **Unverifiable** | Depends on config that exists in no file (F-01) |

`[Data Last Verified: 2026-08-02 from local source tree]`

---

## 2. The Stress Test — Findings by Severity

### F-01 · P0 — The refresh schedule exists only in documentation, not in configuration

`startup.sh` runs the full crawlers **only when `daily_prices` has zero rows**:

```
89:  # ── Run full crawlers only if database has no price data yet ────────
95:  echo "=== No price data found — running full crawlers now (~3 min) ==="
105: echo "=== Price data found — skipping full crawl ==="
```

On a healthy persistent volume, that branch never fires again after first seed. Every deploy thereafter runs only `supply_chain_crawler.py --curated-only` (zero network calls) plus a backgrounded `iv_crawler.py`.

**All ongoing refresh of prices, financials, sentiment, cycles, and every live scraper therefore depends on a Railway Cron job that appears in no file in this repository.** `railway.toml`, `Procfile`, `Dockerfile`, and `startup.sh` contain no schedule. `CLAUDE.md §10` asserts the cadence as though it were configured; `startup.sh:114` explicitly defers to "the real cadence is a Railway Cron."

**Why this is P0:** the schedule is the single point of failure for the entire freshness proposition, it is invisible to code review, it survives no rebuild of the Railway service, and its failure mode is a dashboard that looks completely normal while serving frozen data. This is the identical failure class as the volume-mount bug documented in `CLAUDE.md §5.1` — infrastructure state that is asserted rather than verified.

The 4-day `_FRESHNESS_SPEC` SLA on `daily_prices` would eventually catch it. That is a detection control, not a preventive one, and it depends on someone reading a navbar badge.

**`[UNVERIFIED-PROD]`** — whether the cron exists could not be checked from this session.

---

### F-02 · P0 — Historical P/E and market capitalisation are fabricated (new finding, not in §9)

`crawler.py` lines 308–314, inside the per-quarter loop:

```python
records.append((
    display_name, period_end,
    revenue, gp, gm, op, op_margin, rd, rd_ratio, net, net_margin,
    eps or _safe(info.get("trailingEps")),   # ← TTM figure into a quarterly row
    _safe(info.get("trailingPE")),           # ← TODAY's P/E into every quarter
    _safe(info.get("marketCap")),            # ← TODAY's market cap into every quarter
    ar, ar_turn, inv, inv_turn,
))
```

`info` is a **single snapshot fetched once**, then written identically into every historical row for that ticker.

**Consequences:**

| Column | Stored value | What a reader assumes | Result |
|---|---|---|---|
| `pe_ratio` | today's trailing P/E | P/E as of `period_end` | Valuation history is a flat line at today's multiple |
| `market_cap` | today's market cap | market cap at `period_end` | Cap history is a flat line; any cap-weighted calc is wrong |
| `eps` (when Diluted EPS missing) | trailing **twelve-month** EPS | that quarter's EPS | ~4× overstatement, silently, in a quarterly series |

The Financials tab surfaces `pe_ratio` and `market_cap` in the "Latest Quarter Summary" table (`dashboard.py:1408`). For the latest row the values are approximately right — which is exactly why this has gone unnoticed. **The corruption is in the history**, and the history is what leaves the building via `/api/export-xlsx`.

`_CONSISTENCY_SPEC` (the shape-plausibility check built after SC-12) covers five supply-chain tables and **does not cover `quarterly_financials`**. A perfectly constant series is precisely the `frozen` pattern that check was written to detect. The control exists; it was never pointed at the equity data.

**Severity rationale:** the project deleted 34 DRAM rows rather than relabel them, on the principle that "a wrong number is worse than no number" (§8). This is the same violation, in the table an investor is most likely to trust, against a source (Yahoo/yfinance) the project treats as authoritative.

---

### F-03 · P0 — The supply-chain price layer is 92% formula-generated

Re-running the SC-16 smoothness test against the *current* `CURATED_RETAIL_PRICES` (908 rows, 26 series):

| Series | n | Longest run of identical price deltas | Distinct deltas across entire history |
|---|---|---|---|
| Xeon-8490H | 41 | **21** | 4 |
| A100-SXM4-80GB | 65 | **15** | 15 |
| B200-SXM-192GB | 18 | **15** | **3** |
| H100-SXM5-80GB | 43 | **15** | 7 |
| H200-SXM-141GB | 24 | **15** | **2** |
| DDR4-3200-16GB | 60 | **14** (delta *and* ratio) | 4 |
| i9-12900K | 14 | **12** | **2** |
| R9-7950X | 41 | 12 | 9 |

**24 of 26 series (92%) carry a synthetic fingerprint** — a run of ≥4 identical month-over-month deltas or ratios, or ≤3 distinct deltas across the full history. No traded price behaves this way. These are interpolations between two anchor points.

To the project's credit this is **correctly labelled** `SRC_MODELED` and rendered as dotted open-marker traces (`_trace_style()`, SC-16). The labelling is not the defect. The defect is **that this constitutes the substance of the supply-chain module** — the enterprise GPU price index, the CPU price index, and the consumer price history are all drawn from it.

**Staleness compounds it:** newest curated retail observation is **2026-05-01**, i.e. **93 days old** against a 45-day SLA `[Data Last Updated: 2026-05-01]`. Steam GPU share also stops at **2026-05**. Backlog item SC-04 is open and explicitly unclaimed.

---

### F-04 · P0 — The macro demand layer is accurate and too sparse to analyse

This is the layer the project's own round-2 audit called "sound," and the individual figures were cross-verified against WSTS/SIA and MOTIE/KITA. The values are right. The **series lengths are not usable**:

| Indicator | Rows | Coverage | Source |
|---|---:|---|---|
| `tsmc_revenue` | 6 | 2026-01 → 2026-06 | TSMC IR (live scrape) |
| `umc_revenue` | 6 | 2026-01 → 2026-06 | UMC IR (live scrape) |
| `nanya_revenue` | 5 | 2026-01 → 2026-05 | Nanya IR (live scrape) |
| `wsts_billings` | 3 | 2026-03 → 2026-05 | WSTS / SIA (curated) |
| `semi_wwsems_billings` | 3 | 2025-Q2 → 2026-Q1 | SEMI WWSEMS (curated) |
| **`korea_chip_exports_20d`** | **1** | 2026-07 only | Korea MOTIE / KITA (curated) |
| **Total** | **24** | — | — |

`[Data Last Updated: 2026-07 (Korea) · 2026-06 (TSMC/UMC) · 2026-Q1 (SEMI)]`

You cannot compute a year-on-year from 6 months. You cannot identify a cycle turn from 3 observations. You cannot compute a correlation, a lead-lag relationship, or a moving average from 1 data point. **Korea's 20-day chip exports is the single best high-frequency leading indicator in the sector, and this system holds one observation of it.**

The genuinely-published, non-modeled industry data in the entire system totals: 24 demand rows + 36 DRAM rows + 7 fab-metric rows ≈ **~67 data points**, plus 98 live PassMark benchmark rows (a performance index, not a market metric).

---

### F-05 · P1 — Provenance evaporates on export, and the export is unauthenticated

`/api/export-xlsx` (`dashboard.py:4838`) is **public by design** and streams every table in the database. The README sheet it generates carries only:

```python
readme = pd.DataFrame([{"table": ..., "rows": ..., "columns": ..., "note": ...}])
```

— table name, row count, column count, truncation note. **Nothing else.**

The entire disclosure apparatus built by SC-05 and SC-16 — the `SRC_MODELED` vocabulary, the dotted-line rendering, the yellow in-panel notices, the colour-coded source column, the "As of" badges, the freshness report — **exists only in the Dash UI.** The workbook is the artifact that gets emailed, pasted into a model, and forwarded to a third party. It arrives stripped of every caveat, containing 908 synthetic retail prices and a flat P/E history, in the same visual register as the real OHLCV.

This is the project's own §8 zero-hallucination rule failing at the boundary where it matters most. Additionally, an unauthenticated endpoint returning the complete database is an access-control gap independent of the provenance issue.

---

### F-06 · P1 — The Financials tab misstates its own source and coverage

`dashboard.py:1461` footer text:

> "Quarterly financials sourced from **SEC EDGAR filings via yfinance**. Showing **up to 5 years** of quarterly data."

Both claims are wrong:

1. **yfinance does not read EDGAR.** It scrapes Yahoo Finance, whose fundamentals are vendor-supplied (Refinitiv-lineage), normalised, restated, and occasionally wrong. Citing EDGAR implies a primary-filing chain of custody the system does not have. This is textbook SC-05 — naming an authority the project does not source from.
2. **Coverage is ~5 quarters, not 5 years.** `yf.Ticker().quarterly_income_stmt` returns 4–5 columns. The project's own audit snapshot records `quarterly_financials` = **154 rows** across ~31 tickers ≈ **4.97 quarters each**.

An analyst reading "5 years of EDGAR data" and receiving 5 quarters of vendor-normalised data has been materially misled about the instrument in front of them.

---

### F-07 · P1 — Turnover ratios are quarterly, presented as turnover

`crawler.py:305–307`:

```python
ar_turn  = _safe(revenue / ar)     # quarterly revenue ÷ period-end AR
inv_turn = _safe(cogs / inv)       # quarterly COGS ÷ period-end inventory
```

Neither is annualised. Convention is annual revenue ÷ average AR, and annual COGS ÷ average inventory. As computed, both read **~4× lower** than any comparable figure an analyst will benchmark against, and both use period-end rather than average balances. They are charted as "Accounts Receivable Turnover" and "Inventory Turnover" with no qualifier (`dashboard.py:1457-1458`).

Inventory turns are one of the two or three metrics that actually matter in a semiconductor cycle call. A 4× understatement is not a rounding issue.

Minor, same block: `gm = gp/revenue if revenue and gp` — a legitimately zero gross profit is silently discarded as missing rather than recorded as zero.

---

### F-08 · P2 — Scraper failure is loud in logs, quiet on screen; PassMark has no gate at all

The validation gates are well built. `crawl_steam_survey`, `crawl_trendforce_spot`, `crawl_tsmc_revenue`, `crawl_umc_revenue`, and `crawl_nanya_revenue` all validate parse output (entry counts, plausibility ranges, period extraction) and on failure `log.error(...); return` — retaining the curated seed rather than writing garbage. That is the right design and directly reflects lessons from SC-01/SC-02.

Two gaps:

1. **The consequence of failure is invisible to the user.** The only surfaced signal is a freshness badge whose SLAs run 45–160 days. A scraper can be dead for a full quarter while the panel shows last-known values. Railway logs are not a monitoring system — no alerting, no digest, nobody reads them.
2. **`crawl_passmark()` has no validation gate.** Unlike its four siblings it performs no minimum-entry check, no miss-rate threshold, and emits no `log.error` on a degraded parse — it logs a count and writes whatever it matched. PassMark is currently one of only two genuinely-live supply-chain sources.

---

### F-09 · P2 — Universe gaps that matter for this specific cycle

| Missing | Why it matters now |
|---|---|
| Samsung Electronics, SK Hynix, Kioxia | Memory is the dominant driver of the current cycle; **three of the largest players are untracked** because they are not US-listed. `MU` alone is not the memory complex |
| TEL, KLA, Nikon, Canon, ASM International | Equipment coverage is `ASML`/`LRCX`/`AMAT` only |
| Consensus estimates, revisions breadth | No forward-looking input of any kind; the system is entirely backward-looking |
| Book-to-bill / order backlog | SEMI NA B2B was correctly retired (source discontinued 2016) and **nothing replaced the concept** |
| Lead times, channel inventory days | The classic semiconductor cycle-turn indicators; absent entirely |
| Foundry utilisation | Deliberately blank — correctly, since no foundry discloses it per node (SC-11) |

---

### F-10 · P2 — Deployed state cannot be reconciled with source `[UNVERIFIED-PROD]`

`BACKLOG.md` records, dated 2026-08-02: *"**Not yet pushed** — the fixes above are on disk only."* That batch includes the deletion of the 34 falsified DDR rows (SC-04) and the retirement of the discontinued SEMI B2B panel (SC-00).

No `.git` metadata is present in the mounted folder and production is unreachable from this session, so **it cannot be confirmed that the live dashboard is not still serving the falsified DRAM series** — the series that ran ~18× low with the sign inverted through the largest DRAM upcycle on record, labelled as a TrendForce publication.

For an investor evaluating this system, "the repository is correct" and "the dashboard you are looking at is correct" are different claims, and only the first can currently be evidenced.

---

## 3. Counter-Arguments — The Strongest Case *For* This System

An honest review has to state these, because they are true and they change the recommendation:

1. **The instrumentation is genuinely superior to most commercial data operations.** Per-source freshness SLAs, per-key rather than per-table monitoring (SC-08), shape-plausibility checks with severity splitting (SC-12), a formal provenance vocabulary, and a rendering rule that makes modeled data *look* modeled (SC-16) — most sell-side data pipelines have none of this. The `CLAUDE.md §9` register of 25+ documented failure modes with root causes is professional-grade.

2. **Every price-layer criticism above is about breadth, not correctness.** The OHLCV data is right, split-adjusted correctly, and current. For its honest scope — a 33-ticker price/volatility/financials dashboard — it works.

3. **Most findings here were self-identified first.** SC-04 (staleness) is an open ticket. SC-16 (modeled retail) was found and mitigated internally. The project's own round-2 audit caught the WSTS-vs-DRAM contradiction. This team is not blind; it is under-resourced relative to its ambition.

4. **The real diagnosis is a scope/budget mismatch, not incompetence.** "Industry data for semiconductor investment decisions" is a Gartner/TrendForce/SEMI licence problem — six figures a year. This project attempts it with free scraping plus hand transcription. **The correct response is to narrow the claim, not to condemn the build.** A system that honestly presents itself as "market data + a labelled directional supply-chain sidebar" is defensible today. One that presents itself as an industry-data platform is not.

5. **Counter to my own F-03:** one could argue modeled series are legitimate if labelled, and the project labels them exhaustively. The rebuttal is F-05 — the labels do not survive export, and a reader takes direction and rate-of-change from a line regardless of its footnote. The project already wrote that exact sentence into §9 and then left the export path unguarded.

---

## 4. Application Example — What Actually Happens at the Decision Point

**Scenario:** August 2026. The investor holds `MU` and `TSM`. WSTS shows semiconductor billings **+104% YoY**. The question that decides the position: *is the DRAM upcycle peaking, or is there another two quarters?* Turning-point calls are where semiconductor money is made and lost.

**Walking that query through this system:**

| Step | System response | Fit for purpose |
|---|---|---|
| Check DRAM spot trend | 2 series, 36 rows, deliberate 17-month hole, DDR4 anchored at a single point (2026-07). `_mem_yoy()` correctly returns "—" | 🔴 No trend computable |
| Check demand momentum | WSTS: **3 observations**. Korea 20-day exports: **1 observation** | 🔴 No momentum computable |
| Check supplier revenue run-rate | TSMC/UMC/Nanya: 5–6 months each, live-scraped, accurate | 🟡 Directionally useful, too short for YoY |
| Check pricing power in the channel | Enterprise/consumer retail index — **92% formula-generated**, last observed 2026-05-01 | 🔴 Misleading; a modeled glide will read as a smooth trend |
| Check MU's inventory build | `inventory_turnover` present but ~4× understated and un-annualised (F-07); ~5 quarters of history | 🔴 Unbenchmarkable |
| Check valuation vs. prior peaks | `pe_ratio` is a flat line at today's multiple (F-02) | 🔴 Actively wrong |
| Check the equity's own volatility | Derived IV30, correctly labelled as derived | 🟢 Works |
| Export it all to a model | Workbook arrives with every caveat stripped (F-05) | 🔴 Highest-risk step |

**Outcome:** the system answers the easy part of the question (what did the stock do) and fails the part that determines the trade (is the cycle turning). Worse, three of the six failures return a *plausible-looking number* rather than a blank — which is the specific harm §8 was written to prevent.

**The one thing it does well here:** `_mem_yoy()` returning `"—"` instead of a fabricated percentage is exactly right, and is the behaviour the rest of the system should be held to.

---

## 5. The Fix — Prioritised, With Effort

### Tier 0 — Do before this dashboard informs any position (days)

| # | Fix | Where |
|---|---|---|
| 1 | **Stop writing snapshot P/E, market cap, and TTM EPS into historical quarters.** Write `NULL` for historical rows; keep the snapshot in a separate `ticker_snapshot` table with its own `as_of` date. An empty column that says why is honest (the project's own IV-03 principle) | `crawler.py:308-314` |
| 2 | **Add `quarterly_financials` to `_CONSISTENCY_SPEC`.** The `frozen` rule would have caught #1 on day one | `dashboard.py` |
| 3 | **Put the schedule in the repo.** Commit the cron definition (`railway.toml` or an equivalent checked-in config) and add a `last_successful_crawl` timestamp per crawler to `/health`. Config-as-code, not config-as-documentation | `railway.toml`, `startup.sh`, `crawl_runs` |
| 4 | **Carry provenance into the export.** Add a `PROVENANCE` sheet listing, per table and per source: published / modeled / derived, latest period, SLA status, and the `_freshness_report()` output. Prefix modeled sheets `MODELED_`. Authenticate the endpoint | `dashboard.py:4838-4900` |
| 5 | **Correct the two false statements in the Financials footer** — "Yahoo Finance (vendor-normalised; not primary filings)" and "~5 quarters" | `dashboard.py:1461` |

### Tier 1 — Restore analytical usability (weeks)

| # | Fix | Note |
|---|---|---|
| 6 | **Annualise the turnover ratios** and use average balances; or rename them `ar_turnover_quarterly` / `inventory_turnover_quarterly` | Renaming is acceptable; silently non-standard is not |
| 7 | **Backfill the demand indicators to ≥36 months.** WSTS/SIA and Korea MOTIE both publish long free histories. This is transcription work, not engineering, and it converts F-04 from unusable to the system's strongest asset | Highest analytical return per hour of any item here |
| 8 | **Resolve SC-04 with option (c) — leave stale, let the badge report it.** Do not generate three more months of modeled retail prices. Option (b) manufactures exactly the artifact this audit is flagging | Backlog SC-04 |
| 9 | **Add a validation gate to `crawl_passmark()`** matching its four siblings | `supply_chain_crawler.py:560` |
| 10 | **Route crawler `log.error` to an actual alert** — a daily digest email keyed on `_stale_sources()` + any `log.error`. Logs nobody reads are not a control | — |

### Tier 2 — Close the scope/claim gap (strategic — investor's decision)

| # | Option | Trade-off |
|---|---|---|
| 11 | **Narrow the claim.** Retitle to "Semiconductor Market & Volatility Tracker," demote the supply-chain tab to "Directional Indicators (modeled)" | Free. Makes the system honest today |
| 12 | **Add the missing memory complex** — Samsung (005930.KS), SK Hynix (000660.KS) via yfinance | Low effort, high relevance to the current cycle |
| 13 | **Buy one real feed.** A single TrendForce or SEMI SMG subscription replaces the entire modeled retail/DRAM layer with licensed data | The only path that makes "industry data" a truthful description |
| 14 | **Or delete the modeled layer entirely.** 908 synthetic rows contribute negative information value against a §8 standard | Free, and consistent with the SC-04 precedent of deleting rather than relabelling |

---

## 6. Bottom Line for the Investor

**Use it for:** price action, relative performance, volatility regime, cycle-shape visualisation across 33 tickers, and the three live foundry revenue scrapes. All sound.

**Do not use it for:** valuation history, inventory or receivables analysis, DRAM price trend, channel pricing, demand momentum, or any cycle-turn call. Six of those return plausible-looking numbers that are wrong or too sparse to mean anything.

**Do not forward the XLSX export to anyone** until F-05 is fixed. It is the only artifact that leaves the system, and it is the one artifact with no disclosure.

**Single highest-value action:** Tier-0 item #1 (stop fabricating historical valuation metrics) followed by Tier-1 item #7 (backfill the demand series to 36 months). The first removes actively-wrong data; the second converts the system's most accurate layer from decorative to decision-grade.

---

## Data Sources Glossary

| Source | Used for | Nature | Last observation on disk |
|---|---|---|---|
| Yahoo Finance via `yfinance` | OHLCV, quarterly fundamentals, market cap | Vendor-normalised third-party (**not** SEC EDGAR, contrary to the in-app footer) | Refresh cadence unverifiable — see F-01 |
| Yahoo option chains (`iv_crawler.py`) | 30-day ATM constant-maturity IV | **Derived by this project**, not published | Rolling averages null by design (IV-03) |
| Deribit DVOL | BTC/ETH implied volatility | Genuinely published index | ~400 days backfilled |
| TSMC Investor Relations | Monthly revenue, quarterly metrics | Published primary, live-scraped | 2026-06 (monthly) · 2026-Q2 (quarterly) |
| UMC Investor Relations | Monthly revenue | Published primary, live-scraped | 2026-06 |
| Nanya Technology IR | Monthly revenue | Published primary, live-scraped | 2026-05 |
| TrendForce (public articles) | DRAM spot anchors | Published, hand-transcribed — **no licence held** | 2026-07 (DDR4/DDR5, 36 rows total) |
| WSTS / SIA | Global billings | Published, hand-transcribed | 2026-05 (**3 rows**) |
| SEMI WWSEMS | Equipment billings | Published, hand-transcribed | 2026-Q1 (**3 rows**) |
| Korea MOTIE / KITA | 20-day chip exports | Published, hand-transcribed | 2026-07 (**1 row**) |
| PassMark | GPU/CPU benchmark scores | Live-scraped, **no validation gate** (F-08) | Live |
| Newegg | Retail prices | Live-scraped, historically 0% parse success (SC-01) | Write-guarded |
| Steam Hardware Survey | Consumer GPU share | Live-scraped w/ validation gate | 2026-05 |
| `products_config.py` curated retail | Enterprise & consumer price indices | **Modeled — 24 of 26 series formula-generated** (F-03) | 2026-05-01 (93 days stale) |

`[Data Last Crawled/Updated: values above read from local source tree, 2026-08-02. Production state UNVERIFIED — see Scope Limitation.]`

---

*Prepared as an independent quality-assurance review. Findings F-02, F-05, F-06, F-07, and the F-08 PassMark gap are not recorded in `CLAUDE.md §9` or `BACKLOG.md` and appear to be new. This document is an information-systems and data-quality assessment; it is not investment advice, and the reviewer is not a licensed financial advisor.*
