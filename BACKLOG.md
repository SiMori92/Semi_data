# BACKLOG.md — Open & In-Progress Work

> Companion to `CLAUDE.md`. This file holds work that is **not yet done**: half-finished
> edits, deferred fixes, and prioritized next steps. `CLAUDE.md` stays timeless; anything
> with a "TODO" or "in progress" status lives here.
>
> Convention: when you finish a backlog item, delete its row/section and (if it produced a
> reusable lesson) add a row to `CLAUDE.md §9 Known Issues`.
>
> Last updated: 2026-06-01

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
