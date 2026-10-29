# Responsive dashboard work plan

Status: implemented locally; visual device QA and release gate pending (see `QA_RESPONSIVE_2026-10-30.md`)
Base: `main` at `89645d9`
Scope: the Dash UI in `dashboard.py`; no data model, crawler, or API changes

## Goal

Make the six dashboard tabs usable on a phone in portrait orientation. A user should be able to choose tickers and dates, switch tabs, inspect charts and tables, and see data status without zooming the whole page or losing a control off screen. Keep desktop behavior intact.

## Current code findings

- The application shell uses a `dbc.Col(width=2)` sidebar beside a main column with a viewport-height scroll region (`dashboard.py`, app layout). At phone widths, the sidebar consumes the first screen and the nested scrolling makes the content hard to reach.
- The navbar puts status chips and three action buttons in one non-wrapping flex row. The six main tabs and the Supply Chain sub-tabs can exceed a phone viewport.
- KPI cards use `width=2`; chart pairs use fixed `width=4/5/6/7`; the Period Compare form uses `5/5/2`. These retain desktop proportions on narrow screens.
- Many Plotly figures have fixed heights and desktop margins, legends, labels, and range controls. Wide tables already use local horizontal scrolling, but their key fields and scroll affordance need a phone review.
- Most styling is inline in `dashboard.py`; there is no `assets/` stylesheet or mobile breakpoint. This is a source inspection, not a live-device finding: the Railway page was unavailable from the inspection environment.

## Implementation sequence

### 1. Establish a measured baseline

1. Run the checked-out app with representative data and capture each of the six tabs at 320, 375, 390, 768, and 1280 CSS px. Cover both an empty-data state and populated charts/tables where possible.
2. Record horizontal overflow, clipped controls, nested scroll traps, unreadable chart labels, and touch targets. Prioritize the common journey: select ticker/date → Overview → another tab → inspect table/chart → download.
3. Confirm the production URL and deployed commit before using production screenshots as evidence; the URL in the setup/QA documents was not reachable during this review.

### 2. Fix the shell and navigation first

1. Add `assets/responsive.css` with a small set of semantic class names on the existing layout; use Bootstrap breakpoints rather than copying inline styles across tabs.
2. Keep the sidebar visible on desktop. Below the tablet breakpoint, move its existing date and ticker controls into an accessible collapsible filter panel near the top. Reuse the same component IDs and callback wiring; show the selected ticker count on the closed panel.
3. Let the navbar wrap into a compact title/status row and an action row. Give status chips a readable tap/click disclosure because their detail currently relies on hover `title` text. Keep the refresh, crawl, and download actions discoverable.
4. Make the six main tabs and Supply Chain sub-tabs horizontally scrollable with clear active state and keyboard access. Remove the phone's viewport-height inner scroll region so the document has one natural vertical scroll.
5. Check the storage warning and crawl toast at phone width; constrain them to the viewport and allow long text to wrap.

### 3. Adapt content by component type

1. Give every grid column a responsive width: KPI cards two per row on typical phones (one at 320 px if needed), chart pairs one per row on phones, and the Period Compare date fields/button full width in sequence. Apply the same rule to Overview, Financials, Sentiment, Cycles, Period Compare, and all Supply Chain panels.
2. Make date pickers, dropdowns, buttons, and checklist rows fit the available width and meet a 44 × 44 CSS px target where practical. Ensure opening a date picker does not put its calendar off screen.
3. Keep tables in their own horizontal scroll containers. Preserve an identifying first column where feasible, add an explicit scroll cue, and make sort/pagination controls usable by touch. Avoid shrinking text to fit every column.
4. Introduce a shared mobile chart treatment: smaller margins and fonts, bottom or compact legends, sensible heights, and Plotly `responsive`/resize behavior. Review range-selector buttons and long axis labels individually; simplify only the presentation, not the underlying series or provenance labels.
5. Keep source, freshness, modeled/published, and stale-data notes visible and readable after cards stack. Those notes are decision-critical and must not be hidden to save space.

### 4. Build QA into each delivery slice

1. Create a small, deterministic SQLite fixture containing enough price, financial, sentiment, cycle, and supply-chain rows to render every tab. Include missing/stale rows and long labels. Keep tests isolated from the live database and crawler; never use a production crawl as a UI test.
2. Add browser tests (for example, Playwright) for the core journey and callback behavior. Run these against the fixture at 375 and 1280 CSS px on every change to the dashboard or responsive stylesheet. Test at 320, 390, and 768 px in the release run. Inspect browser console errors and failed Dash callback requests, not just visible text.
3. After each slice, capture screenshots of changed views and compare them with approved baselines. Review image differences manually so expected chart/data variation is not treated as a layout failure. Check the actual content and controls beneath any overlay.
4. Review keyboard navigation, visible focus, semantic names for icon-only controls, screen-reader announcements for the filter panel and status details, and 200% text enlargement. Use an automated accessibility scan as a supplement to manual checks.

### 5. Release verification

1. Run the automated checks below, then a manual pass on iPhone Safari and Android Chrome (physical devices or a device cloud). Cover portrait and landscape, the date-picker popup, Plotly hover/tap behavior, table scrolling, and the browser's back/forward and reload actions.
2. Verify the desktop layout at 768 and 1280 px, including all tab and sub-tab transitions. Confirm that moving filters does not duplicate Dash IDs, callback outputs, or components rendered inside another callback's output.
3. Capture before/after evidence, the tested commit, browser/device details, fixture version, test results, and any accepted limitations in the PR. After deployment, perform a read-only smoke check against the deployed commit and inspect app/callback logs; do not run a crawl merely to test the interface.

## QA test matrix and pass criteria

| Area | Checks | Required result |
| --- | --- | --- |
| Shell at 320, 375, 390, 768, 1280 px | Navbar, warning banner, toast, filter panel, main tabs, Supply Chain sub-tabs | No page-level horizontal scroll, clipped primary control, overlapping text, or inaccessible content. Only tables and tab strips may scroll sideways. |
| Filters and state | Open/close filters, choose/clear tickers, change dates, switch tabs, reload | Selections survive closing filters and switching tabs; each tab honors the filters that apply to it; reload behavior matches the existing app; no callback error. |
| Six tabs | Overview, Financials, Sentiment, Cycles, Period Compare, Supply Chain and each sub-tab | Charts/tables load with populated and empty fixtures; actions and labels remain usable on phone; no content disappears at a breakpoint. |
| Charts | Plotly resize, legends, range selectors, tooltips, dense labels, orientation change | Charts fit their cards; data points and units remain readable; tap/drag does not trap page scrolling. |
| Tables | Horizontal scroll, identifying columns, sort/pagination, long values | The complete row remains accessible; sorting and pagination work by touch and keyboard; no forced page zoom. |
| Status and provenance | Freshness, crawl/IV status, stale/empty data, source and modeled/published notes | Warnings and attribution remain visible; details are available by tap and keyboard, not hover alone. |
| Actions | Compare, refresh, download link, crawl control | Compare and refresh work; download returns the expected file locally; crawl control has a safe mocked test and is not invoked against production. |
| Accessibility | Keyboard, focus order, names/labels, contrast, 200% text | No keyboard trap or hidden focused element; critical status and controls have usable names and readable text. |

### Automated gate before merge

- The app imports and starts with the fixture; no duplicate-ID or duplicate-output callback error occurs.
- Browser journey tests pass at 375 and 1280 px; the release matrix passes at all five widths. The browser console has no uncaught error and Dash requests have no 4xx/5xx failure caused by the change.
- Layout assertions detect page-level overflow and off-screen primary controls. Screenshot review finds no unexplained regression on the six tabs.
- Existing project regression checks still pass. Any failure must be fixed or documented with evidence that it predates this change and does not affect the responsive work.

### Human sign-off before release

- One iPhone Safari and one Android Chrome pass the core journey without pinch zoom. Touch targets aim for at least 44 × 44 CSS px where practical, and no essential action depends on hover.
- A reviewer checks one dense chart, one wide table, an empty-data state, and a stale-data warning on each platform. This is the highest-risk content for a data dashboard.
- The PR includes a short issue list for any remaining cosmetic defects. A broken core journey, hidden warning, clipped action, callback error, or page-level overflow blocks release.

## Suggested delivery slices

| Slice | Output | Exit condition |
| --- | --- | --- |
| A | Baseline screenshots, fixture, and issue list | All tabs measured at target widths; fixture renders every tab |
| B | Responsive shell, filters, navbar, tabs | Core navigation and state tests pass at 320 and 375 px |
| C | Cards, forms, tables, charts across six tabs | Tab, chart, table, and action tests pass on phone and desktop |
| D | Device QA, regression fixes, and release evidence | Automated gate and human sign-off above pass |

Estimated effort: **7–11 development days**, including fixture and browser-test setup, plus access to at least one iPhone and Android browser for final verification. The biggest uncertainty is chart and date-picker behavior with real data; baseline inspection should refine the estimate.

## Implementation constraints

- Preserve existing Dash component IDs and callback outputs while changing presentation. The app has documented prior failures from duplicate outputs and callbacks nested in rendered tab content.
- Keep the desktop information density. Use responsive stacking and disclosure on phones, rather than removing metrics or source attribution.
- Avoid a full UI framework rewrite for this scope. The existing Dash Bootstrap grid and an `assets/` stylesheet can address the main layout failures with less regression risk.
