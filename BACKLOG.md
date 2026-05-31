# BACKLOG.md — Open & In-Progress Work

> Companion to `CLAUDE.md`. This file holds work that is **not yet done**: half-finished
> edits, deferred fixes, and prioritized next steps. `CLAUDE.md` stays timeless; anything
> with a "TODO" or "in progress" status lives here.
>
> Convention: when you finish a backlog item, delete its row/section and (if it produced a
> reusable lesson) add a row to `CLAUDE.md §9 Known Issues`.
>
> Last updated: 2026-05-31

---

## 🟠 Open — Hardware Price Index Curated Data Lags ~12 Months

**Status (verified 2026-05-31 against code):** Part 2 is DONE; Part 1 is barely started.
- ✅ **Part 2 (code blend)** — `_sc_vs_etf_panel()` in `dashboard.py` (now ~line 1841) already
  queries **all** sources (`curated + passmark + newegg`); the `AND source='curated'` filter
  and the misleading "breaks normalisation" comment are gone. No code change needed.
- 🟠 **Part 1 (curated data)** — `CURATED_RETAIL_PRICES`, `CURATED_DRAM_SPOT`, and
  `CURATED_SEMI_BTB` now run to `2025-05` (advanced one month from `2025-04`). Today is
  `2026-05`, so curated values are still ~12 months stale. The chart no longer flat-lines
  *only if* live Newegg/PassMark crawl rows exist; if the live scrapers are returning empty
  (DOM drift — see §10 maintenance), the index still effectively stops at 2025-05.

### Part 1 (remaining) — Extend curated data in `products_config.py`

Add monthly rows `2025-06` → `2026-05` for all 13 product IDs, format:
```python
("PRODUCT-ID", "YYYY-MM-01", "curated", price_usd, None, None, None),
```

Last-known (now 2025-05) prices and expected trend — extend forward from these:

| product_id | 2025-04 | Trend driver → expected range |
|---|---|---|
| RTX-4090 | $1600 | RTX 5090 (Jan 2025) → ~$1350–1500 |
| RTX-4070-Super | $550 | RTX 5070S (Jan 2025) → ~$450–530 |
| RTX-4060 | $265 | RTX 5060 Ti (May 2025) → ~$199–250 |
| RX-7900-XTX | $730 | RX 9070 XT (Mar 2025 @ $599) → ~$549–700 |
| RX-7600 | $225 | RX 9060 XT pipeline → ~$185 |
| R9-7950X | $380 | Zen 5 competition → ~$295–360 |
| R7-7800X3D | $328 | R7 9800X3D (Nov 2024) → ~$249–315 |
| i9-14900K | $455 | 2-gen-old → ~$349–440 |
| R5-7600X | $150 | near floor → ~$125–148 |
| DDR5-5600-32GB | $92 | DRAM oversupply → ~$72–88 |
| DDR5-6000-32GB | $112 | → ~$88–108 |
| DDR4-3600-32GB | $60 | mature/flat → ~$54–60 |
| DDR4-3200-16GB | $32 | floor → ~$28–32 |

Also extend `CURATED_DRAM_SPOT` and `CURATED_SEMI_BTB` through `2026-05`.

> These are *modeled* curated values. Per `CLAUDE.md §8` (zero-hallucination), replace with
> sourced figures (TrendForce / SEMI / retailer data) rather than shipping estimates. This is
> the real blocker — sourcing, not the mechanical row-adding.

**Done when:** curated series run to the current month locally, chart extends to ~2026-05,
push + verify on Railway. Then remove this section and add a Known-Issues row.

---

## 🟡 Recommended Next Steps (prioritized, not started)

1. **Railway Cron** — schedule `python crawler.py --quick` weekdays 06:00 UTC for automated
   daily refresh.
2. **Monthly curated-data refresh** — DRAM spot + fab capacity in `products_config.py`
   (see Maintenance Calendar in `CLAUDE.md §10`).
3. **Enable IBKR IV** — follow `CLAUDE.md §11` once TWS is configured.
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
