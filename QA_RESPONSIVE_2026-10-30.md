# Responsive dashboard QA — 2026-10-30

Base revision: `89645d9` (`main` before local edits).
Scope: local UI changes in `dashboard.py` and `assets/responsive.css`.

## Passed locally

- Python syntax check and `git diff --check`.
- Four `unittest` checks in `tests/test_responsive_smoke.py` pass with `DB_PATH` pointing to a temporary copy of the 2026-08-09 backup. The tests cover shell ID uniqueness, asset delivery, ticker selection/count callbacks, all six tab renders and their Dash callback JSON responses, Period Compare and Cycles actions, responsive graph properties, status disclosures and their callback JSON responses, and the empty enterprise-memory state.
- Flask test client returns HTTP 200 for `/`, `/_dash-layout`, `/_dash-dependencies`, and `/assets/responsive.css`.
- The local `/api/export-bundle` action returns HTTP 200 and a ZIP payload (`application/zip`, `PK` signature) against the QA database copy.
- All six tabs render without a `Tab Error` against the copied database. Graph counts observed: Overview 2, Financials 11, Sentiment 5, Cycles 4, Period Compare 0 before Compare is clicked, Supply Chain 13. All rendered graphs use responsive resizing.
- A separate empty-database check exposed an Enterprise RAM error; the panel now shows an explained empty state instead. All six tabs were rechecked against an empty database without a tab or panel error.

## Pending release gate

- Browser/device visual QA at 320, 375, 390, 768, and 1280 CSS px is **not verified**. The computer-use browser host was unavailable and Chrome UI permissions were not granted in this environment. No screenshot or touch result should be inferred from the server-side tests.
- Verify the collapsed filter, date-picker portal, status disclosures, tab strips, Plotly controls, table scrolling, and page-level overflow in iPhone Safari and Android Chrome before release.
- Verify the production URL and deployed commit, then run the read-only post-deploy smoke check. No production deployment or crawl was performed here.

## Reproduce

```sh
DB_PATH=/path/to/a/representative-qa-copy.db python -m unittest discover -s tests -v
```

Use a disposable copy of the database, not the live volume. The test suite does not run a crawler or mutate source data.
