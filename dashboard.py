"""
dashboard.py — Semiconductor Industry Interactive Dashboard
===========================================================
Launches a Dash web app that reads from semiconductor_data.db.

Run:
    python dashboard.py
Then open http://127.0.0.1:8050 in your browser.
"""

import sqlite3
from datetime import datetime, timedelta

import numpy as np
import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, dash_table
from plotly.subplots import make_subplots
from scipy.signal import argrelextrema

# Supply-chain product lists (for grouping in SC tab)
from products_config import (
    GPU_PRODUCTS, GPU_ENTERPRISE_PRODUCTS,
    CPU_PRODUCTS, CPU_ENTERPRISE_PRODUCTS,
    RAM_PRODUCTS,
    ENTERPRISE_PRODUCT_LAUNCHES,
)

# IBKR integration (optional — graceful if not installed / not enabled)
from ibkr_options_crawler import ibkr_is_enabled, init_ibkr_tables

from config import (
    DB_PATH,
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    SEMI_COMPANIES,
    SEMI_ETFS,
    TICKER_TYPES,
    CHART_COLORS,
    now_hkt as _now_hkt,
)

# ── Colour theme ──────────────────────────────────────────────────────────────
BG       = "#0d1117"
BG2      = "#161b22"
BG3      = "#21262d"
ACCENT   = "#58a6ff"
GREEN    = "#3fb950"
RED      = "#f85149"
YELLOW   = "#d29922"
TEXT     = "#e6edf3"
SUBTEXT  = "#8b949e"

PLOTLY_TEMPLATE = dict(
    layout=dict(
        paper_bgcolor=BG2,
        plot_bgcolor =BG3,
        font         =dict(color=TEXT, family="Inter, Segoe UI, sans-serif"),
        xaxis        =dict(gridcolor="#30363d", linecolor="#30363d", zerolinecolor="#30363d"),
        yaxis        =dict(gridcolor="#30363d", linecolor="#30363d", zerolinecolor="#30363d"),
        legend       =dict(bgcolor=BG2, bordercolor="#30363d"),
        colorway     =CHART_COLORS,
        margin       =dict(l=50, r=20, t=40, b=40),
    )
)


# ══════════════════════════════════════════════════════════════════════════════
# DATA LAYER
# ══════════════════════════════════════════════════════════════════════════════

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def query(sql: str, params=()) -> pd.DataFrame:
    try:
        with get_conn() as c:
            return pd.read_sql_query(sql, c, params=params)
    except Exception:
        return pd.DataFrame()


def all_tickers() -> list[str]:
    df = query("SELECT DISTINCT ticker FROM daily_prices ORDER BY ticker")
    return df["ticker"].tolist() if not df.empty else []


def last_crawl_time() -> str:
    df = query("SELECT finished_at FROM crawl_runs WHERE status='completed' ORDER BY id DESC LIMIT 1")
    if df.empty or df["finished_at"].iloc[0] is None:
        return "Never"
    try:
        dt = datetime.fromisoformat(df["finished_at"].iloc[0])
        return dt.strftime("%d %b %Y  %H:%M HKT")
    except Exception:
        return df["finished_at"].iloc[0]


def price_data(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(tickers))
    return query(
        f"SELECT ticker,date,open,high,low,close,volume FROM daily_prices "
        f"WHERE ticker IN ({placeholders}) AND date BETWEEN ? AND ? ORDER BY ticker,date",
        tickers + [start, end],
    )


def financials_data(tickers: list[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(tickers))
    return query(
        f"SELECT * FROM quarterly_financials WHERE ticker IN ({placeholders}) ORDER BY ticker,period_end",
        tickers,
    )


def sentiment_data(tickers: list[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(tickers))
    # Latest snapshot per ticker
    return query(
        f"""SELECT s.* FROM market_sentiment s
            INNER JOIN (
                SELECT ticker, MAX(snapshot_date) AS md FROM market_sentiment
                WHERE ticker IN ({placeholders}) GROUP BY ticker
            ) latest ON s.ticker=latest.ticker AND s.snapshot_date=latest.md
            ORDER BY s.ticker""",
        tickers,
    )


def cycle_data(tickers: list[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(tickers))
    return query(
        f"""SELECT c.* FROM cycle_analysis c
            INNER JOIN (
                SELECT ticker, MAX(snapshot_date) AS md FROM cycle_analysis
                WHERE ticker IN ({placeholders}) GROUP BY ticker
            ) latest ON c.ticker=latest.ticker AND c.snapshot_date=latest.md
            ORDER BY c.ticker""",
        tickers,
    )


def company_info_data(tickers: list[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(tickers))
    return query(
        f"SELECT * FROM company_info WHERE ticker IN ({placeholders})",
        tickers,
    )


# ══════════════════════════════════════════════════════════════════════════════
# LAYOUT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _card(children, style=None):
    base = {"background": BG2, "borderRadius": "8px", "padding": "16px",
            "border": f"1px solid #30363d", "marginBottom": "12px"}
    if style:
        base.update(style)
    return html.Div(children, style=base)


def _kpi(label: str, value: str, delta: str = "", color: str = TEXT):
    return html.Div([
        html.Div(label, style={"fontSize": "11px", "color": SUBTEXT, "textTransform": "uppercase", "letterSpacing": "0.5px"}),
        html.Div(value, style={"fontSize": "22px", "fontWeight": "700", "color": color}),
        html.Div(delta, style={"fontSize": "12px", "color": GREEN if delta.startswith("+") else (RED if delta.startswith("-") else SUBTEXT)}),
    ], style={"padding": "8px 0"})


def _section_title(text: str):
    return html.Div(text, style={"fontSize": "13px", "fontWeight": "600",
                                  "color": ACCENT, "textTransform": "uppercase",
                                  "letterSpacing": "1px", "marginBottom": "8px"})


def _crawl_timestamp() -> str:
    """Return last completed crawl time in System Directive format: YYYY-MM-DD HH:MM HKT.
    Falls back to 'Data not available in the latest crawl.' if no record exists."""
    df = query(
        "SELECT finished_at FROM crawl_runs WHERE status='completed' ORDER BY id DESC LIMIT 1"
    )
    if df.empty or df["finished_at"].iloc[0] is None:
        return "Data not available in the latest crawl."
    try:
        dt = datetime.fromisoformat(str(df["finished_at"].iloc[0]))
        return dt.strftime("%Y-%m-%d %H:%M HKT")
    except Exception:
        return str(df["finished_at"].iloc[0])


def _source_footer(source_name: str, notes: str = "") -> html.Div:
    """Return a standardised attribution footer per the System Directive.
    Renders: [Source: <source_name>] · [Data Last Crawled/Updated: YYYY-MM-DD HH:MM HKT]
    """
    ts = _crawl_timestamp()
    text_parts = [
        html.Span(f"[Source: {source_name}]",
                  style={"color": ACCENT, "fontWeight": "600", "marginRight": "12px"}),
        html.Span(f"[Data Last Crawled/Updated: {ts}]",
                  style={"color": SUBTEXT}),
    ]
    if notes:
        text_parts.append(
            html.Span(f"  ·  {notes}", style={"color": SUBTEXT})
        )
    return html.Div(text_parts, style={
        "fontSize": "11px", "marginTop": "10px", "paddingTop": "8px",
        "borderTop": "1px solid #30363d", "fontFamily": "monospace",
    })


def _time_rangeselector(active_index: int = 0) -> dict:
    """Standard 1Y / 3Y / 5Y Plotly rangeselector.
    Buttons are anchored relative to today (stepmode='backward') so they always
    show the correct window regardless of when the dashboard is opened.
    active_index: kept as a parameter for call-site compatibility but is not
    passed to Plotly — the 'active' key is not supported by the installed
    Plotly version (raises ValueError on Rangeselector objects).
    The displayed window is controlled by xaxis.range instead.
    """
    return dict(
        buttons=[
            dict(count=1, label="1Y", step="year", stepmode="backward"),
            dict(count=3, label="3Y", step="year", stepmode="backward"),
            dict(count=5, label="5Y", step="year", stepmode="backward"),
        ],
        activecolor=ACCENT,
        bgcolor=BG2,
        bordercolor="#30363d",
        borderwidth=1,
        font=dict(color=TEXT, size=11),
    )


def _range_start(years: int = 1) -> str:
    """Return ISO date string for `years` years before today (system time)."""
    return (_now_hkt() - timedelta(days=365 * years)).strftime("%Y-%m-%d")


def ticker_checklist(group_name: str, tickers: list[str], default_checked: list[str]):
    return html.Div([
        _section_title(group_name),
        dbc.Checklist(
            id=f"chk-{group_name.lower().replace(' ', '-').replace('/', '')}",
            options=[{"label": t, "value": t} for t in tickers],
            value=[t for t in default_checked if t in tickers],
            labelStyle={"display": "block", "fontSize": "13px", "color": TEXT,
                        "margin": "2px 0", "cursor": "pointer"},
            inputStyle={"marginRight": "6px", "accentColor": ACCENT},
        ),
    ], style={"marginBottom": "16px"})


# ── Module-level ticker category helpers (shared by Overview & Sentiment tabs) ─
_CAT_ORDER = {
    "Semi Companies": SEMI_COMPANIES,
    "Semi ETFs":      SEMI_ETFS,
    "Macro / Other":  ["TQQQ", "QQQ", "VIX", "USD", "10YTreasury", "Gold", "BTC", "ETH"],
    "Tech / Mixed":   ["MSFT", "GOOG", "META", "AAPL", "TSLA", "AMZN", "ORCL", "BRK.A"],
}
_SHORT_CAT = {
    "Semi Companies": "Semi",
    "Semi ETFs":      "ETF",
    "Macro / Other":  "Macro",
    "Tech / Mixed":   "Tech",
}
_cat_rank = {
    tkr: (ci, ti)
    for ci, (_, members) in enumerate(_CAT_ORDER.items())
    for ti, tkr in enumerate(members)
}


def _ticker_cat(tkr: str) -> str:
    """Return short category label, e.g. 'Semi', 'ETF', 'Macro', 'Tech'."""
    for cat, members in _CAT_ORDER.items():
        if tkr in members:
            return _SHORT_CAT[cat]
    return "Other"


def _ticker_label(tkr: str) -> str:
    """Return '[Cat] Ticker' label for display, e.g. '[Semi] NVDA'."""
    cat = _ticker_cat(tkr)
    return f"[{cat}] {tkr}" if cat != "Other" else tkr


def _compute_hv30(tickers: list) -> pd.DataFrame:
    """Compute 30-day Historical Volatility (annualised %) from daily_prices.
    Returns a DataFrame with columns [ticker, hv30]."""
    if not tickers:
        return pd.DataFrame(columns=["ticker", "hv30"])
    placeholders = ",".join("?" * len(tickers))
    # Fetch ~50 trading days so we have enough after dropna
    cutoff = (_now_hkt() - timedelta(days=75)).strftime("%Y-%m-%d")
    df = query(
        f"SELECT ticker, date, close FROM daily_prices "
        f"WHERE ticker IN ({placeholders}) AND date >= ? ORDER BY ticker, date",
        tickers + [cutoff],
    )
    if df.empty:
        return pd.DataFrame(columns=["ticker", "hv30"])
    rows = []
    for tkr, grp in df.groupby("ticker"):
        grp = grp.sort_values("date")
        if len(grp) < 10:
            rows.append({"ticker": tkr, "hv30": None})
            continue
        log_ret = grp["close"].pct_change().dropna()
        # Use last 30 observations
        hv = log_ret.tail(30).std() * (252 ** 0.5) * 100
        rows.append({"ticker": tkr, "hv30": round(hv, 1) if pd.notna(hv) else None})
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# APP DEFINITION
# ══════════════════════════════════════════════════════════════════════════════

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY, dbc.icons.BOOTSTRAP],
    title="Semi Industry Tracker",
    suppress_callback_exceptions=True,
)

# Expose the underlying Flask server so gunicorn can find it:
#   gunicorn dashboard:server --bind 0.0.0.0:$PORT
server = app.server

app.layout = dbc.Container(fluid=True, style={"background": BG, "minHeight": "100vh", "padding": "0"}, children=[

    # ── Top nav bar ───────────────────────────────────────────────────────────
    dbc.Navbar(
        dbc.Container(fluid=True, children=[
            html.Span("⚡ Semiconductor Industry Tracker", style={
                "color": TEXT, "fontSize": "17px", "fontWeight": "700", "letterSpacing": "0.3px"
            }),
            html.Div([
                html.Span("Last crawl: ", style={"color": SUBTEXT, "fontSize": "12px"}),
                html.Span(id="last-crawl-time", style={"color": ACCENT, "fontSize": "12px"}),
                # ── Reload confirmation stamp (updates on every manual refresh) ─
                html.Span(id="reload-stamp", style={
                    "color": GREEN, "fontSize": "11px", "marginLeft": "12px",
                    "opacity": "0.8",
                }),
                # ── IBKR connection badge ──────────────────────────────────
                html.Span(id="ibkr-status-badge", style={"marginLeft": "20px"}),
                dbc.Button("🔄 Reload Charts", id="btn-refresh", color="primary",
                           size="sm", style={"marginLeft": "16px", "fontSize": "12px"},
                           title="Re-read data from the database and redraw all charts"),
                dbc.Button("⚡ Run Crawl", id="btn-run-crawl", color="warning",
                           size="sm", style={"marginLeft": "8px", "fontSize": "12px"},
                           title="Fetch fresh market data from Yahoo Finance (takes ~2 min)"),
            ], style={"display": "flex", "alignItems": "center", "gap": "0"}),
            # ── Run-crawl status toast ────────────────────────────────────────
            dbc.Toast(
                id="crawl-toast",
                header="Crawl Status",
                is_open=False,
                dismissable=True,
                icon="success",
                style={"position": "fixed", "top": 66, "right": 16, "width": 320, "zIndex": 9999},
            ),
        ]),
        color=BG2, dark=True,
        style={"borderBottom": f"1px solid #30363d", "padding": "10px 20px"}
    ),

    dbc.Row(style={"margin": "0"}, children=[

        # ── Sidebar ───────────────────────────────────────────────────────────
        dbc.Col(width=2, style={"background": BG2, "borderRight": f"1px solid #30363d",
                                 "padding": "16px", "minHeight": "calc(100vh - 56px)",
                                 "overflowY": "auto"}, children=[

            _section_title("Date Range"),
            dcc.DatePickerRange(
                id="date-range",
                start_date=(_now_hkt() - timedelta(days=365)).strftime("%Y-%m-%d"),
                end_date=_now_hkt().strftime("%Y-%m-%d"),
                display_format="DD MMM YYYY",
                style={"fontSize": "12px", "width": "100%"},
            ),
            html.Hr(style={"borderColor": "#30363d", "margin": "12px 0"}),

            ticker_checklist(
                "Semi Companies",
                SEMI_COMPANIES,
                ["NVDA", "AMD", "ASML", "AVGO", "QCOM", "MU", "TSM", "INTC"],
            ),
            ticker_checklist("Semi ETFs",   SEMI_ETFS,   ["SMH", "SOXX"]),
            ticker_checklist("Macro / Other",
                ["TQQQ", "QQQ", "VIX", "USD", "10YTreasury", "Gold", "BTC", "ETH"],
                ["VIX", "10YTreasury", "Gold"],
            ),
            ticker_checklist("Tech / Mixed",
                ["MSFT", "GOOG", "META", "AAPL", "TSLA", "AMZN", "ORCL", "BRK.A"],
                [],
            ),

            html.Hr(style={"borderColor": "#30363d", "margin": "12px 0"}),

            dbc.Button("Select All", id="btn-select-all", color="secondary",
                       outline=True, size="sm", style={"width": "100%", "marginBottom": "6px", "fontSize": "12px"}),
            dbc.Button("Clear All",  id="btn-clear-all",  color="secondary",
                       outline=True, size="sm", style={"width": "100%", "fontSize": "12px"}),

            # Hidden store for selected tickers
            dcc.Store(id="selected-tickers", data=[
                "NVDA", "AMD", "ASML", "AVGO", "QCOM", "MU", "TSM", "INTC",
                "SMH", "SOXX", "VIX", "10YTreasury"
            ]),
        ]),

        # ── Main content ──────────────────────────────────────────────────────
        dbc.Col(style={"padding": "16px", "overflowY": "auto",
                       "maxHeight": "calc(100vh - 56px)"}, children=[

            dbc.Tabs(id="main-tabs", active_tab="tab-overview", children=[
                dbc.Tab(label="📊 Overview",       tab_id="tab-overview"),
                dbc.Tab(label="💰 Financials",     tab_id="tab-financials"),
                dbc.Tab(label="🌡️ Sentiment",      tab_id="tab-sentiment"),
                dbc.Tab(label="🔄 Cycles",         tab_id="tab-cycles"),
                dbc.Tab(label="⚖️ Period Compare", tab_id="tab-compare"),
                dbc.Tab(label="🏭 Supply Chain",   tab_id="tab-supplychain"),
            ], style={"marginBottom": "16px",
                      "--bs-nav-tabs-border-color": "#30363d"}),

            dcc.Loading(
                id="tab-loading",
                type="circle",
                color=ACCENT,
                children=html.Div(id="tab-content"),
            ),
        ]),
    ]),

    # Interval for auto-refresh status
    dcc.Interval(id="status-interval", interval=30_000, n_intervals=0),
    # Store for crawl-job state (polled by status-interval)
    dcc.Store(id="crawl-job-store", data={"running": False, "message": ""}),
])


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — ticker selection sync
# ══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("selected-tickers", "data"),
    Input("chk-semi-companies",  "value"),
    Input("chk-semi-etfs",       "value"),
    Input("chk-macro--other",    "value"),
    Input("chk-tech--mixed",     "value"),
    prevent_initial_call=False,
)
def sync_tickers(semi, etfs, macro, tech):
    result = []
    for lst in [semi, etfs, macro, tech]:
        if lst:
            result.extend(lst)
    return result


@app.callback(
    Output("chk-semi-companies", "value"),
    Output("chk-semi-etfs",      "value"),
    Output("chk-macro--other",   "value"),
    Output("chk-tech--mixed",    "value"),
    Input("btn-select-all",      "n_clicks"),
    Input("btn-clear-all",       "n_clicks"),
    prevent_initial_call=True,
)
def select_clear_all(select_clicks, clear_clicks):
    from dash import ctx
    if ctx.triggered_id == "btn-select-all":
        return (
            SEMI_COMPANIES,
            SEMI_ETFS,
            ["TQQQ", "QQQ", "VIX", "USD", "10YTreasury", "Gold", "BTC", "ETH"],
            ["MSFT", "GOOG", "META", "AAPL", "TSLA", "AMZN", "ORCL", "BRK.A"],
        )
    # Clear All
    return [], [], [], []


@app.callback(
    Output("last-crawl-time", "children"),
    Input("status-interval", "n_intervals"),
    Input("btn-refresh", "n_clicks"),
)
def update_crawl_time(*_):
    return last_crawl_time()


@app.callback(
    Output("reload-stamp", "children"),
    Input("btn-refresh", "n_clicks"),
    prevent_initial_call=True,
)
def show_reload_stamp(_):
    """Show 'Reloaded HH:MM HKT' next to Last Crawl after each manual refresh."""
    return f"✓ Reloaded {_now_hkt().strftime('%H:%M')} HKT"


@app.callback(
    Output("crawl-toast",     "children"),
    Output("crawl-toast",     "is_open"),
    Output("crawl-toast",     "icon"),
    Output("last-crawl-time", "children", allow_duplicate=True),
    Input("btn-run-crawl",    "n_clicks"),
    prevent_initial_call=True,
)
def trigger_crawl(_):
    """Start a background crawl and notify the user."""
    import threading, subprocess, sys, os as _os
    from dash import no_update

    # Check if already running
    if _crawl_running.get("active"):
        return "Crawl already in progress — please wait.", True, "warning", no_update

    def _run_crawl():
        _crawl_running["active"] = True
        try:
            script_dir = _os.path.dirname(_os.path.abspath(__file__))
            py = sys.executable
            subprocess.run([py, _os.path.join(script_dir, "crawler.py"), "--quick"],
                           timeout=360, cwd=script_dir)
            subprocess.run([py, _os.path.join(script_dir, "supply_chain_crawler.py")],
                           timeout=360, cwd=script_dir)
        except Exception:
            pass
        finally:
            _crawl_running["active"] = False

    threading.Thread(target=_run_crawl, daemon=True).start()
    return (
        "Crawl started — prices & supply-chain data refreshing (~2 min). "
        "Last Crawl timestamp will update when complete.",
        True, "primary",
        last_crawl_time(),
    )


# Module-level dict to track crawl state across gunicorn requests
_crawl_running: dict = {"active": False}



@app.callback(
    Output("ibkr-status-badge", "children"),
    Input("status-interval", "n_intervals"),
)
def update_ibkr_badge(_):
    """Show a small IBKR connection-status chip in the navbar."""
    enabled = ibkr_is_enabled()
    has_data = not query(
        "SELECT 1 FROM options_iv LIMIT 1"
    ).empty if enabled else False

    if not enabled:
        return html.Span(
            [html.Span("⚫", style={"marginRight": "4px"}), "IBKR: disabled"],
            style={"fontSize": "11px", "color": SUBTEXT,
                   "border": f"1px solid #30363d", "borderRadius": "4px",
                   "padding": "2px 8px", "cursor": "default"},
            title="Set 'enabled': true in ibkr_config.json to activate",
        )
    elif has_data:
        return html.Span(
            [html.Span("🟢", style={"marginRight": "4px"}), "IBKR: live IV"],
            style={"fontSize": "11px", "color": GREEN,
                   "border": f"1px solid {GREEN}", "borderRadius": "4px",
                   "padding": "2px 8px"},
            title="Real-time IV data from Interactive Brokers",
        )
    else:
        return html.Span(
            [html.Span("🟡", style={"marginRight": "4px"}), "IBKR: no data yet"],
            style={"fontSize": "11px", "color": YELLOW,
                   "border": f"1px solid {YELLOW}", "borderRadius": "4px",
                   "padding": "2px 8px"},
            title="IBKR enabled but no IV data — run: python ibkr_options_crawler.py",
        )


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — tab content
# ══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("tab-content", "children"),
    Input("main-tabs",        "active_tab"),
    Input("selected-tickers", "data"),
    Input("date-range",       "start_date"),
    Input("date-range",       "end_date"),
    Input("btn-refresh",      "n_clicks"),
)
def render_tab(active_tab, tickers, start_date, end_date, _refresh):
    if not tickers:
        return _card(html.P("Select at least one ticker from the sidebar.", style={"color": SUBTEXT}))

    start = start_date[:10] if start_date else "2023-01-01"
    end   = end_date[:10]   if end_date   else _now_hkt().strftime("%Y-%m-%d")

    _TAB_MAP = {
        "tab-overview":     lambda: tab_overview(tickers, start, end),
        "tab-financials":   lambda: tab_financials(tickers),
        "tab-sentiment":    lambda: tab_sentiment(tickers),
        "tab-cycles":       lambda: tab_cycles(tickers),
        "tab-compare":      lambda: tab_compare(tickers),
        "tab-supplychain":  lambda: tab_supply_chain(),
    }

    fn = _TAB_MAP.get(active_tab)
    if fn is None:
        return html.Div("Select a tab.")

    try:
        return fn()
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        return _card([
            _section_title("⚠️ Tab Error"),
            html.P(f"{type(exc).__name__}: {exc}",
                   style={"color": RED, "fontWeight": "600", "marginBottom": "8px"}),
            html.Pre(tb, style={"color": SUBTEXT, "fontSize": "11px",
                                "overflowX": "auto", "whiteSpace": "pre-wrap"}),
        ])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════

def tab_overview(tickers, start, end):
    prices = price_data(tickers, start, end)
    sent   = sentiment_data(tickers)

    if prices.empty:
        return _card(html.P("No price data found. Run crawler.py first.", style={"color": RED}))

    # ── KPI cards (latest price + 1m performance) ─────────────────────────
    kpi_cards = []
    for tkr in tickers:
        df = prices[prices["ticker"] == tkr].sort_values("date")
        if df.empty:
            continue
        latest = df["close"].iloc[-1]
        p1m_row = sent[sent["ticker"] == tkr]["perf_1m"].values if not sent.empty else []
        p1m  = p1m_row[0] if len(p1m_row) > 0 and p1m_row[0] is not None else None
        delta = (f"+{p1m:.1f}%" if p1m and p1m >= 0 else f"{p1m:.1f}%") if p1m is not None else ""
        col   = GREEN if p1m and p1m >= 0 else RED if p1m and p1m < 0 else TEXT
        kpi_cards.append(
            dbc.Col(width=2, children=_card(_kpi(tkr, f"${latest:,.2f}", delta, col),
                                            style={"textAlign": "center"}))
        )

    # ── Merged Price + Volume subplot (shared X axis, auto-synced) ───────────
    # Always fetch 5 Y so 1Y / 3Y / 5Y rangeselector buttons have full data.
    _price_start_5y = (_now_hkt() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    prices_5y = price_data(tickers, _price_start_5y, end)

    fig_price = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.68, 0.32],
        subplot_titles=("Price Performance (Base=100 at range start)", "Trading Volume"),
    )

    # Row 1 — normalised price lines
    for i, tkr in enumerate(tickers):
        df = prices_5y[prices_5y["ticker"] == tkr].sort_values("date")
        if df.empty or len(df) < 2:
            continue
        base = df["close"].iloc[0]
        if base == 0:
            continue
        norm = df["close"] / base * 100
        fig_price.add_trace(go.Scatter(
            x=df["date"], y=norm, name=tkr, mode="lines",
            line=dict(width=2, color=CHART_COLORS[i % len(CHART_COLORS)]),
            hovertemplate=f"<b>{tkr}</b><br>Date: %{{x}}<br>Indexed: %{{y:.1f}}<extra></extra>",
        ), row=1, col=1)

    # Row 2 — volume bars (full 5 Y so they sync with the price range)
    for i, tkr in enumerate(tickers[:8]):   # cap at 8 for readability
        df = prices_5y[prices_5y["ticker"] == tkr].sort_values("date")
        if df.empty:
            continue
        fig_price.add_trace(go.Bar(
            x=df["date"], y=df["volume"], name=tkr,
            marker_color=CHART_COLORS[i % len(CHART_COLORS)],
            showlegend=False,   # legend already shown by price trace above
            hovertemplate=f"<b>{tkr}</b><br>%{{x}}<br>Vol: %{{y:,.0f}}<extra></extra>",
        ), row=2, col=1)

    # Default view: last 1 year; rangeselector drives both rows via shared xaxis
    _1y_ago = (_now_hkt() - timedelta(days=365)).strftime("%Y-%m-%d")

    _base_layout = PLOTLY_TEMPLATE["layout"].copy()
    fig_price.update_layout(
        **_base_layout,
        height=620,
        hovermode="x unified",
        barmode="overlay",
        bargap=0.1,
    )
    # Shared x-axis lives on xaxis (row 1); xaxis2 (row 2) inherits the range
    fig_price.update_xaxes(
        range=[_1y_ago, end],
        rangeselector=dict(
            buttons=[
                dict(count=1, label="1Y", step="year", stepmode="backward"),
                dict(count=3, label="3Y", step="year", stepmode="backward"),
                dict(count=5, label="5Y", step="year", stepmode="backward"),
            ],
            activecolor=ACCENT,
            bgcolor=BG2,
            bordercolor="#30363d",
            borderwidth=1,
            font=dict(color=TEXT, size=12),
            x=0, y=1.06, xanchor="left",
        ),
        rangeslider=dict(visible=False),
        type="date",
        row=1, col=1,
    )
    fig_price.update_yaxes(title_text="Index (Base=100)", row=1, col=1,
                            gridcolor="#21262d", color=TEXT)
    fig_price.update_yaxes(title_text="Volume", row=2, col=1,
                            gridcolor="#21262d", color=TEXT)
    # Style the subplot title annotations to match the dark theme
    for ann in fig_price.layout.annotations:
        ann.update(font=dict(color=TEXT, size=13))

    # ── Performance heatmap — with sidebar category labels ───────────────
    # Uses module-level _CAT_ORDER, _SHORT_CAT, _ticker_label, _cat_rank
    if not sent.empty:
        cols_perf = ["perf_5d", "perf_10d", "perf_1m"]
        hm_data = sent[["ticker"] + cols_perf].set_index("ticker")
        hm_data = hm_data.apply(pd.to_numeric, errors="coerce")

        # Sort rows by category order so same-group tickers appear together
        sorted_idx = sorted(hm_data.index, key=lambda t: _cat_rank.get(t, (99, 99)))
        hm_data = hm_data.loc[sorted_idx]

        y_labels  = [_ticker_label(t) for t in hm_data.index]

        fig_hm = go.Figure(go.Heatmap(
            z=hm_data.values,
            x=["5-Day %", "10-Day %", "1-Month %"],
            y=y_labels,
            colorscale=[[0, RED], [0.5, BG3], [1, GREEN]],
            zmid=0,
            text=hm_data.round(1).astype(str).values + "%",
            texttemplate="%{text}",
            hovertemplate="<b>%{y}</b><br>%{x}: %{z:.2f}%<extra></extra>",
        ))
        fig_hm.update_layout(**PLOTLY_TEMPLATE["layout"],
                              title="Return Heatmap",
                              height=max(280, len(tickers) * 30))
        heatmap_section = dcc.Graph(figure=fig_hm, config={"displayModeBar": False})
    else:
        heatmap_section = html.P("Sentiment data not yet available.", style={"color": SUBTEXT})

    return html.Div([
        dbc.Row(kpi_cards, className="g-2", style={"marginBottom": "12px"}),
        _card(dcc.Graph(figure=fig_price, config={"displayModeBar": True})),
        _card(heatmap_section),
        _card(_source_footer("Yahoo Finance / yfinance",
                              "OHLCV daily price data and 1-month performance. "
                              "Prices are as-of market close.")),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — FINANCIALS
# ══════════════════════════════════════════════════════════════════════════════

def tab_financials(tickers):
    """Render the Financials tab (all available data, up to 5 years)."""
    df = financials_data(tickers)
    if df.empty:
        return _card(html.P("No quarterly financial data. Run crawler.py — financials are only available for listed companies.", style={"color": SUBTEXT}))

    df["period_end"] = pd.to_datetime(df["period_end"])
    df = df.sort_values("period_end")

    # Show up to 5 years of data.
    _cutoff_5y = pd.Timestamp(_now_hkt() - timedelta(days=365 * 5))
    df_view = df[df["period_end"] >= _cutoff_5y]

    # Quarterly label used as categorical x-axis — evenly-spaced bars regardless
    # of how many tickers are grouped.
    def _qlabel(ts) -> str:
        return f"{ts.year}-Q{ts.quarter}"

    def metric_chart(col: str, title: str, pct: bool = False):
        fig = go.Figure()
        for i, tkr in enumerate(tickers):
            sub = df_view[df_view["ticker"] == tkr].dropna(subset=[col])
            if sub.empty:
                continue
            vals  = sub[col] / 1e9 if not pct else sub[col]
            xlbls = sub["period_end"].apply(_qlabel)
            fig.add_trace(go.Bar(
                x=xlbls, y=vals, name=tkr,
                marker_color=CHART_COLORS[i % len(CHART_COLORS)],
                hovertemplate=f"<b>{tkr}</b><br>%{{x}}<br>{title}: %{{y:{',.1f' if pct else ',.2f'}}}"
                              + ("%" if pct else "B") + "<extra></extra>",
            ))
        suffix = "%" if pct else " (USD Billions)"
        fig.update_layout(
            **PLOTLY_TEMPLATE["layout"],
            title=title + suffix, barmode="group",
            height=320, yaxis_title=title,
        )
        return dcc.Graph(figure=fig, config={"displayModeBar": False})

    def trend_chart(col: str, title: str, pct: bool = False):
        fig = go.Figure()
        for i, tkr in enumerate(tickers):
            sub = df_view[df_view["ticker"] == tkr].dropna(subset=[col])
            if sub.empty:
                continue
            xlbls = sub["period_end"].apply(_qlabel)
            fig.add_trace(go.Scatter(
                x=xlbls, y=sub[col], name=tkr, mode="lines+markers",
                line=dict(width=2, color=CHART_COLORS[i % len(CHART_COLORS)]),
                hovertemplate=f"<b>{tkr}</b><br>%{{x}}<br>{title}: %{{y:.2f}}{'%' if pct else ''}<extra></extra>",
            ))
        fig.update_layout(
            **PLOTLY_TEMPLATE["layout"],
            title=title + (" (%)" if pct else ""),
            height=280,
        )
        return dcc.Graph(figure=fig, config={"displayModeBar": False})

    # Latest financials table
    latest_cols = ["ticker", "period_end", "revenue", "gross_margin",
                   "op_margin", "net_margin", "pe_ratio", "eps", "market_cap"]
    latest = df_view.sort_values("period_end").groupby("ticker").last().reset_index()
    tbl_data = latest[[c for c in latest_cols if c in latest.columns]].copy()
    for col in ["revenue", "market_cap"]:
        if col in tbl_data:
            tbl_data[col] = (tbl_data[col] / 1e9).map(lambda x: f"${x:,.1f}B" if pd.notna(x) else "—")
    for col in ["gross_margin", "op_margin", "net_margin"]:
        if col in tbl_data:
            tbl_data[col] = tbl_data[col].map(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
    for col in ["pe_ratio", "eps"]:
        if col in tbl_data:
            tbl_data[col] = tbl_data[col].map(lambda x: f"{x:.2f}" if pd.notna(x) else "—")
    if "period_end" in tbl_data:
        tbl_data["period_end"] = tbl_data["period_end"].dt.strftime("%Y-%m-%d")

    tbl = dash_table.DataTable(
        data=tbl_data.to_dict("records"),
        columns=[{"name": c.replace("_", " ").title(), "id": c} for c in tbl_data.columns],
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": BG2},
        ],
        page_size=20,
    )

    return html.Div([
        _card([_section_title("Latest Quarter Summary"), tbl]),
        dbc.Row([
            dbc.Col(_card(metric_chart("revenue",        "Revenue")),        width=6),
            dbc.Col(_card(metric_chart("gross_profit",   "Gross Profit")),   width=6),
        ]),
        dbc.Row([
            dbc.Col(_card(metric_chart("operating_profit", "Operating Profit")), width=6),
            dbc.Col(_card(metric_chart("rd_expense",       "R&D Expense")),     width=6),
        ]),
        dbc.Row([
            dbc.Col(_card(metric_chart("net_profit",  "Net Profit")),  width=6),
            dbc.Col(_card(trend_chart("gross_margin", "Gross Margin", pct=True)), width=6),
        ]),
        dbc.Row([
            dbc.Col(_card(trend_chart("op_margin",  "Operating Margin", pct=True)), width=4),
            dbc.Col(_card(trend_chart("net_margin", "Net Margin",       pct=True)), width=4),
            dbc.Col(_card(trend_chart("rd_to_revenue", "R&D / Revenue", pct=True)), width=4),
        ]),
        dbc.Row([
            dbc.Col(_card(trend_chart("ar_turnover",        "Accounts Receivable Turnover")), width=6),
            dbc.Col(_card(trend_chart("inventory_turnover", "Inventory Turnover")),           width=6),
        ]),
        _card(_source_footer("Yahoo Finance / yfinance",
                              f"Quarterly financials sourced from SEC EDGAR filings via yfinance. "
                              f"Showing up to 5 years of quarterly data. "
                              f"Revenue, profit, margins, R&D, AR and inventory turnover ratios.")),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — MARKET SENTIMENT
# ══════════════════════════════════════════════════════════════════════════════

def _ibkr_iv_data(tickers: list) -> pd.DataFrame:
    """Load IBKR IV snapshots for selected tickers (latest row per ticker)."""
    if not tickers:
        return pd.DataFrame()
    ph = ",".join("?" * len(tickers))
    return query(
        f"""SELECT i.* FROM options_iv i
            INNER JOIN (
                SELECT ticker, MAX(snapshot_date) AS md
                FROM options_iv WHERE ticker IN ({ph}) GROUP BY ticker
            ) latest ON i.ticker=latest.ticker AND i.snapshot_date=latest.md
            ORDER BY i.ticker""",
        tickers,
    )


def _ibkr_iv_history(tickers: list) -> pd.DataFrame:
    """Load full IBKR daily IV history for selected tickers."""
    if not tickers:
        return pd.DataFrame()
    ph = ",".join("?" * len(tickers))
    return query(
        f"SELECT * FROM options_iv_history WHERE ticker IN ({ph}) ORDER BY ticker, date",
        tickers,
    )


def tab_sentiment(tickers):
    sent    = sentiment_data(tickers)
    ibkr_iv = _ibkr_iv_data(tickers)
    has_ibkr = not ibkr_iv.empty

    if sent.empty and not has_ibkr:
        return _card(html.P("No sentiment data found. Run crawler.py first.", style={"color": SUBTEXT}))

    # ── Data source banner ────────────────────────────────────────────────
    source_note = (
        html.Div([
            html.Span("📡 Options IV source: ", style={"color": SUBTEXT, "fontSize": "12px"}),
            html.Span(
                "Interactive Brokers (real-time)" if has_ibkr else "Yahoo Finance (delayed ATM estimate)",
                style={"color": ACCENT if has_ibkr else YELLOW, "fontSize": "12px", "fontWeight": "600"},
            ),
            html.Span(
                " — run python ibkr_options_crawler.py to upgrade to IBKR real-time data" if not has_ibkr else "",
                style={"color": SUBTEXT, "fontSize": "11px"},
            ),
        ], style={"marginBottom": "12px"})
    )

    # ══════════════════════════════════════════════════════════════════════
    # SECTION A — IMPLIED VOLATILITY (IBKR preferred, yfinance fallback)
    # ══════════════════════════════════════════════════════════════════════

    if has_ibkr:
        # ── A1: IV Term Structure grouped bar (current, 1m, 1q, 6m, 1y) ──
        iv_cols   = ["iv_current", "iv_1m_avg", "iv_1q_avg", "iv_6m_avg", "iv_1y_avg"]
        iv_labels = ["Current", "1-Month Avg", "1-Quarter Avg", "6-Month Avg", "1-Year Avg"]
        iv_colors = [ACCENT,     "#74C0FC",     "#51CF66",       YELLOW,       "#CC5DE8"]

        fig_term = go.Figure()
        for col, lbl, col_color in zip(iv_cols, iv_labels, iv_colors):
            sub = ibkr_iv.dropna(subset=[col])
            if sub.empty:
                continue
            fig_term.add_trace(go.Bar(
                name=lbl,
                x=sub["ticker"],
                y=sub[col].round(1),
                marker_color=col_color,
                hovertemplate=f"<b>%{{x}}</b><br>{lbl}: %{{y:.1f}}%<extra></extra>",
            ))
        fig_term.update_layout(
            **PLOTLY_TEMPLATE["layout"],
            title="Options IV — Term Structure per Ticker (IBKR Real-Time)",
            barmode="group", height=380,
            xaxis_title="Ticker", yaxis_title="Implied Volatility (%)",
        )

        # ── A2: IV vs 52-week range (percentile gauge bars) ───────────────
        pct_df = ibkr_iv.dropna(subset=["iv_pct_vs_1y", "iv_current",
                                         "iv_52w_low", "iv_52w_high"])
        fig_pct = go.Figure()
        if not pct_df.empty:
            fig_pct.add_trace(go.Bar(
                x=pct_df["ticker"],
                y=pct_df["iv_pct_vs_1y"],
                marker_color=[
                    RED    if v > 80 else
                    YELLOW if v > 50 else
                    GREEN
                    for v in pct_df["iv_pct_vs_1y"]
                ],
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "IV Percentile (1Y): %{y:.0f}%<br>"
                    "<extra></extra>"
                ),
                customdata=pct_df[["iv_current", "iv_52w_low", "iv_52w_high"]].values,
            ))
            fig_pct.update_traces(
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "IV Percentile (1Y): %{y:.0f}%<br>"
                    "Current IV: %{customdata[0]:.1f}%<br>"
                    "52W Low: %{customdata[1]:.1f}%  |  52W High: %{customdata[2]:.1f}%"
                    "<extra></extra>"
                )
            )
        fig_pct.add_hline(y=80, line_dash="dot", line_color=RED,    line_width=1,
                          annotation_text="High fear zone (>80th pct)", annotation_font_color=RED)
        fig_pct.add_hline(y=20, line_dash="dot", line_color=GREEN,  line_width=1,
                          annotation_text="Low vol zone (<20th pct)",   annotation_font_color=GREEN)
        fig_pct.update_layout(
            **PLOTLY_TEMPLATE["layout"],
            title="IV Percentile vs 1-Year Range — Where is IV sitting today?",
            height=300, showlegend=False,
            xaxis_title="Ticker", yaxis_title="IV Percentile (%)",
        )

        # ── A3: IV history line chart for selected tickers ────────────────
        iv_hist = _ibkr_iv_history(tickers)
        fig_ivh = go.Figure()
        if not iv_hist.empty:
            for i, (tkr, grp) in enumerate(iv_hist.groupby("ticker")):
                grp = grp.sort_values("date")
                fig_ivh.add_trace(go.Scatter(
                    x=grp["date"], y=grp["iv_pct"],
                    name=tkr, mode="lines",
                    line=dict(width=2, color=CHART_COLORS[i % len(CHART_COLORS)]),
                    hovertemplate=f"<b>{tkr}</b><br>Date: %{{x}}<br>IV: %{{y:.1f}}%<extra></extra>",
                ))
        fig_ivh.update_layout(
            **PLOTLY_TEMPLATE["layout"],
            title="Daily Implied Volatility History (IBKR)",
            height=340, xaxis_title="Date", yaxis_title="IV (%)",
            hovermode="x unified",
        )
        fig_ivh.update_xaxes(
            type="date",
            rangeselector=_time_rangeselector(active_index=0),   # 1Y default
            range=[_range_start(1), _now_hkt().strftime("%Y-%m-%d")],
            rangeslider=dict(visible=False),
        )

        # ── A4: IV snapshot table ─────────────────────────────────────────
        iv_tbl = ibkr_iv[["ticker", "snapshot_date", "iv_current",
                           "iv_1m_avg", "iv_1q_avg", "iv_6m_avg",
                           "iv_1y_avg", "iv_pct_vs_1y",
                           "iv_52w_low", "iv_52w_high"]].copy()
        for col in ["iv_current", "iv_1m_avg", "iv_1q_avg",
                    "iv_6m_avg", "iv_1y_avg", "iv_52w_low", "iv_52w_high"]:
            iv_tbl[col] = iv_tbl[col].map(
                lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
        iv_tbl["iv_pct_vs_1y"] = iv_tbl["iv_pct_vs_1y"].map(
            lambda x: f"{x:.0f}th" if pd.notna(x) else "—")
        iv_tbl.columns = ["Ticker", "Date", "IV Current",
                          "1M Avg", "1Q Avg", "6M Avg",
                          "1Y Avg", "1Y Pct", "52W Low", "52W High"]
        iv_table = dash_table.DataTable(
            data=iv_tbl.to_dict("records"),
            columns=[{"name": c, "id": c} for c in iv_tbl.columns],
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"backgroundColor": BG3, "color": TEXT,
                        "border": "1px solid #30363d",
                        "fontSize": "12px", "padding": "5px 10px"},
            style_header={"backgroundColor": BG2, "color": ACCENT,
                          "fontWeight": "600", "border": "1px solid #30363d"},
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": BG2},
            ],
        )

        iv_section = html.Div([
            _card([
                _section_title("Options IV — Snapshot Table (IBKR Real-Time)"),
                iv_table,
            ]),
            _card(dcc.Graph(figure=fig_term, config={"displayModeBar": True})),
            dbc.Row([
                dbc.Col(_card(dcc.Graph(figure=fig_pct, config={"displayModeBar": False})), width=6),
                dbc.Col(_card(dcc.Graph(figure=fig_ivh, config={"displayModeBar": True})), width=6),
            ]),
        ])

    else:
        # ── Fallback: yfinance ATM IV ──────────────────────────────────────
        # iv_df: rows where IV was successfully fetched (may be a subset of tickers)
        iv_df = sent.dropna(subset=["implied_volatility"]) if not sent.empty else pd.DataFrame()

        if not iv_df.empty:
            # Sort descending so highest-IV tickers are most prominent
            iv_df = iv_df.sort_values("implied_volatility", ascending=False)
            fig_iv = go.Figure(go.Bar(
                x=iv_df["ticker"],
                y=iv_df["implied_volatility"].round(1),
                marker_color=[
                    RED    if v > 60 else
                    YELLOW if v > 30 else
                    GREEN
                    for v in iv_df["implied_volatility"]
                ],
                text=iv_df["implied_volatility"].map(lambda v: f"{v:.1f}%"),
                textposition="outside",
                hovertemplate="<b>%{x}</b><br>IV (ATM): %{y:.1f}%<extra></extra>",
            ))
            fig_iv.update_layout(
                **PLOTLY_TEMPLATE["layout"],
                title=f"Implied Volatility — ATM Estimate via yfinance "
                      f"({len(iv_df)} of {len(sent)} tickers have IV data)",
                height=320, showlegend=False,
                xaxis_title="Ticker", yaxis_title="Implied Volatility (%)",
            )
            fig_iv.update_yaxes(rangemode="tozero")

            # Tickers where IV is genuinely missing (ETFs, bonds, crypto, etc.)
            missing = sent[sent["implied_volatility"].isna()]["ticker"].tolist()
            missing_note = (
                f"IV not available for: {', '.join(missing[:12])}"
                + (" …" if len(missing) > 12 else "")
            ) if missing else ""

            iv_section = _card([
                dcc.Graph(figure=fig_iv, config={"displayModeBar": False}),
                html.Div([
                    html.Span(
                        "⚠️ Source: yfinance ATM snapshot (annualised) — "
                        "no historical period averages.  ",
                        style={"color": YELLOW, "fontSize": "12px"},
                    ),
                    html.Span(
                        "Connect Interactive Brokers for full IV term structure.",
                        style={"color": SUBTEXT, "fontSize": "12px"},
                    ),
                ], style={"marginTop": "8px"}),
                html.P(missing_note, style={"color": SUBTEXT, "fontSize": "11px",
                                            "marginTop": "4px"}) if missing_note else html.Span(),
            ])

        else:
            # IV column is entirely NULL — likely a --quick crawl with old crawler
            # that never tried the fast path. Show an informative placeholder.
            iv_section = _card([
                _section_title("Implied Volatility — ATM Estimate"),
                html.Div([
                    html.P(
                        "IV data is not yet in the database.",
                        style={"color": YELLOW, "fontWeight": "600", "fontSize": "13px",
                               "margin": "0 0 6px 0"},
                    ),
                    html.P(
                        "The crawler now fetches IV automatically on every crawl "
                        "(including --quick mode). "
                        "Trigger a fresh crawl with the ⚡ Run Crawl button in the navbar "
                        "and then reload — IV data will appear for US-listed stocks "
                        "(ETFs, bonds, and crypto may still show N/A).",
                        style={"color": SUBTEXT, "fontSize": "12px", "margin": "0"},
                    ),
                ], style={"padding": "20px", "textAlign": "center"}),
            ])

    # ══════════════════════════════════════════════════════════════════════
    # SECTION B — PRICE PERFORMANCE SENTIMENT (unchanged)
    # ══════════════════════════════════════════════════════════════════════

    if sent.empty:
        return html.Div([source_note, iv_section])

    drop_df    = sent.dropna(subset=["days_since_large_drop"]).sort_values("days_since_large_drop")
    fig_drop   = go.Figure(go.Bar(
        x=drop_df["ticker"],
        y=drop_df["days_since_large_drop"],
        marker_color=[GREEN if v > 90 else YELLOW if v > 30 else RED
                      for v in drop_df["days_since_large_drop"]],
        hovertemplate="<b>%{x}</b><br>Days since ≥5% drop: %{y}<extra></extra>",
    ))
    fig_drop.update_layout(**PLOTLY_TEMPLATE["layout"],
                            title="Days Since Last Large Single-Day Drop (≥5%)",
                            height=280, showlegend=False)

    perf_df    = sent.dropna(subset=["perf_5d", "perf_1m"])
    fig_scatter= go.Figure()
    if not perf_df.empty:
        fig_scatter.add_trace(go.Scatter(
            x=perf_df["perf_5d"], y=perf_df["perf_1m"],
            mode="markers+text", text=perf_df["ticker"],
            textposition="top center",
            marker=dict(size=14,
                        color=[GREEN if r > 0 else RED for r in perf_df["perf_1m"]],
                        line=dict(width=1, color="#30363d")),
            hovertemplate="<b>%{text}</b><br>5-Day: %{x:.1f}%<br>1-Month: %{y:.1f}%<extra></extra>",
        ))
        fig_scatter.add_hline(y=0, line_dash="dash", line_color=SUBTEXT, line_width=1)
        fig_scatter.add_vline(x=0, line_dash="dash", line_color=SUBTEXT, line_width=1)
    fig_scatter.update_layout(**PLOTLY_TEMPLATE["layout"],
                               title="5-Day vs 1-Month Return (%)",
                               height=360, xaxis_title="5-Day Return (%)",
                               yaxis_title="1-Month Return (%)")

    # ── Performance + IV summary table ───────────────────────────────────
    tbl_df = sent[["ticker", "close_price", "perf_5d", "perf_10d", "perf_1m",
                   "days_since_large_drop"]].copy()

    # 1. Category column — add & sort by sidebar order
    tbl_df["category"] = tbl_df["ticker"].map(_ticker_cat)
    tbl_df["_sort_key"] = tbl_df["ticker"].map(lambda t: _cat_rank.get(t, (99, 99)))
    tbl_df = tbl_df.sort_values("_sort_key").drop(columns=["_sort_key"])

    # 2. IV column — IBKR preferred; yfinance next; HV30 final fallback
    if has_ibkr:
        iv_now = ibkr_iv[["ticker", "iv_current"]].rename(columns={"iv_current": "_iv_val"})
        tbl_df = tbl_df.merge(iv_now, on="ticker", how="left")
        tbl_df["iv_source"] = tbl_df["_iv_val"].apply(lambda x: "IBKR" if pd.notna(x) else "N/A")
    else:
        tbl_df = tbl_df.merge(sent[["ticker", "implied_volatility"]].rename(
            columns={"implied_volatility": "_iv_val"}), on="ticker", how="left")
        # Where yfinance IV is NULL, substitute HV30
        hv_df  = _compute_hv30(tbl_df["ticker"].tolist())
        tbl_df = tbl_df.merge(hv_df, on="ticker", how="left")
        def _pick_iv(row):
            if pd.notna(row["_iv_val"]):
                return row["_iv_val"], "IV"
            if pd.notna(row.get("hv30")):
                return row["hv30"], "HV30"
            return None, "N/A"
        tbl_df[["_iv_val", "iv_source"]] = tbl_df.apply(
            lambda r: pd.Series(_pick_iv(r)), axis=1)
        tbl_df = tbl_df.drop(columns=["hv30"], errors="ignore")

    # 3. Format numeric columns as strings (enables colour-conditional styling)
    for col in ["perf_5d", "perf_10d", "perf_1m"]:
        tbl_df[col] = tbl_df[col].map(lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
    tbl_df["_iv_val"] = tbl_df["_iv_val"].map(
        lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
    tbl_df["close_price"]           = tbl_df["close_price"].map(
        lambda x: f"${x:,.2f}" if pd.notna(x) else "—")
    tbl_df["days_since_large_drop"] = tbl_df["days_since_large_drop"].map(
        lambda x: str(int(x)) if pd.notna(x) else "—")

    # Reorder & rename columns for display
    tbl_df = tbl_df.rename(columns={
        "ticker":               "Ticker",
        "category":             "Category",
        "close_price":          "Close Price",
        "perf_5d":              "Perf 5D",
        "perf_10d":             "Perf 10D",
        "perf_1m":              "Perf 1M",
        "days_since_large_drop":"Days Since Drop",
        "_iv_val":              "Vol %",
        "iv_source":            "Vol Source",
    })
    display_cols = ["Ticker", "Category", "Close Price",
                    "Perf 5D", "Perf 10D", "Perf 1M",
                    "Days Since Drop", "Vol %", "Vol Source"]
    tbl_df = tbl_df[[c for c in display_cols if c in tbl_df.columns]]

    # 4. Conditional styles: green/red for perf columns; source badge colours
    perf_cols = ["Perf 5D", "Perf 10D", "Perf 1M"]
    cond_styles = [{"if": {"row_index": "odd"}, "backgroundColor": BG2}]
    for col in perf_cols:
        cond_styles += [
            {"if": {"filter_query": f'{{{col}}} contains "+"', "column_id": col},
             "color": GREEN, "fontWeight": "600"},
            {"if": {"filter_query": f'{{{col}}} contains "-"', "column_id": col},
             "color": RED,   "fontWeight": "600"},
        ]
    # Vol Source badge colouring
    cond_styles += [
        {"if": {"filter_query": '{Vol Source} = "IBKR"',  "column_id": "Vol Source"},
         "color": GREEN,  "fontWeight": "600"},
        {"if": {"filter_query": '{Vol Source} = "IV"',    "column_id": "Vol Source"},
         "color": ACCENT, "fontWeight": "600"},
        {"if": {"filter_query": '{Vol Source} = "HV30"',  "column_id": "Vol Source"},
         "color": YELLOW, "fontWeight": "600"},
        {"if": {"filter_query": '{Vol Source} = "N/A"',   "column_id": "Vol Source"},
         "color": SUBTEXT},
    ]

    tbl = dash_table.DataTable(
        data=tbl_df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in tbl_df.columns],
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=cond_styles,
    )

    iv_source = ("Interactive Brokers TWS — real-time options IV term structure"
                 if has_ibkr else
                 "Yahoo Finance / yfinance — delayed ATM IV estimate (no period averages)")
    return html.Div([
        source_note,
        _card([_section_title("Sentiment Snapshot"), tbl]),
        iv_section,
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=fig_drop,    config={"displayModeBar": False})), width=6),
            dbc.Col(_card(dcc.Graph(figure=fig_scatter, config={"displayModeBar": True})),  width=6),
        ]),
        _card(_source_footer(iv_source,
                              "Performance metrics (5d/10d/1m) from Yahoo Finance / yfinance.")),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — CYCLE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

_CYCLE_WINDOW = 15   # trading days — matches crawler.py CYCLE_DETECTION_WINDOW


def _build_cycle_chart(ticker: str) -> go.Figure:
    """Return a Plotly figure: price line + green/red shading per cycle segment.
    Fetches up to 5 years of data; rangeselector lets user switch 1Y/3Y/5Y view.
    """
    # Fetch 5 years so the 5Y button is fully populated
    cutoff = (_now_hkt() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    df = query(
        "SELECT date, close FROM daily_prices WHERE ticker=? AND date>=? ORDER BY date",
        [ticker, cutoff],
    )
    fig = go.Figure()
    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title=f"{ticker} — Cycle Detection  (window = {_CYCLE_WINDOW} trading days)",
        height=400, xaxis_title="Date", yaxis_title="Price (USD)",
        hovermode="x unified",
    )
    if df.empty or len(df) < _CYCLE_WINDOW * 3:
        fig.add_annotation(
            text="Not enough price history for cycle detection (need ≥ 2 years).",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(color=SUBTEXT, size=13),
        )
        return fig

    closes = df["close"].values.astype(float)
    dates  = pd.to_datetime(df["date"]).values

    peaks   = argrelextrema(closes, np.greater_equal, order=_CYCLE_WINDOW)[0]
    troughs = argrelextrema(closes, np.less_equal,    order=_CYCLE_WINDOW)[0]

    # Build sorted event list: (index, type)
    events = sorted(
        [(i, "peak")   for i in peaks] +
        [(i, "trough") for i in troughs],
        key=lambda e: e[0],
    )

    # Shade each segment between consecutive events
    for k in range(len(events) - 1):
        i0, t0 = events[k]
        i1, t1 = events[k + 1]
        d0, d1 = dates[i0], dates[i1]
        p0, p1 = closes[i0], closes[i1]

        if t0 == "trough" and t1 == "peak":
            pct   = (p1 / p0 - 1) * 100
            color = GREEN
            label = f"+{pct:.0f}%"
        elif t0 == "peak" and t1 == "trough":
            pct   = (p1 / p0 - 1) * 100
            color = RED
            label = f"{pct:.0f}%"
        else:
            color = SUBTEXT
            label = ""

        fig.add_vrect(
            x0=str(d0)[:10], x1=str(d1)[:10],
            fillcolor=color, opacity=0.10, line_width=0,
            annotation_text=label,
            annotation_position="top left",
            annotation_font=dict(color=color, size=9),
        )

    # Price line
    fig.add_trace(go.Scatter(
        x=[str(d)[:10] for d in dates],
        y=closes,
        name=ticker,
        line=dict(color=ACCENT, width=2),
        hovertemplate="<b>%{x}</b>  $%{y:,.2f}<extra></extra>",
    ))

    # Peak markers
    if len(peaks):
        fig.add_trace(go.Scatter(
            x=[str(dates[i])[:10] for i in peaks],
            y=closes[peaks],
            mode="markers", name="Peak",
            marker=dict(symbol="triangle-up", color=GREEN, size=10,
                        line=dict(width=1, color=BG3)),
            hovertemplate="<b>Peak</b>  $%{y:,.2f}<extra></extra>",
        ))

    # Trough markers
    if len(troughs):
        fig.add_trace(go.Scatter(
            x=[str(dates[i])[:10] for i in troughs],
            y=closes[troughs],
            mode="markers", name="Trough",
            marker=dict(symbol="triangle-down", color=RED, size=10,
                        line=dict(width=1, color=BG3)),
            hovertemplate="<b>Trough</b>  $%{y:,.2f}<extra></extra>",
        ))

    # 1Y / 3Y / 5Y rangeselector — default view is 2Y so full context is visible
    _cyc_today = _now_hkt().strftime("%Y-%m-%d")
    fig.update_xaxes(
        type="date",
        rangeselector=_time_rangeselector(active_index=1),   # 3Y default
        range=[_range_start(2), _cyc_today],
        rangeslider=dict(visible=False),
    )

    return fig


def tab_cycles(tickers):
    cyc = cycle_data(tickers)

    if cyc.empty:
        return _card(html.P("No cycle data found. Run crawler.py with ≥2 years of price history.",
                            style={"color": SUBTEXT}))

    cyc = cyc.dropna(subset=["up_cycle_magnitude", "down_cycle_magnitude"], how="all")

    # ── Summary table — with Category column, sorted by sidebar order ────
    tbl_df = cyc[["ticker", "up_cycle_magnitude", "up_cycle_duration",
                  "down_cycle_magnitude", "down_cycle_duration",
                  "vol_diff_last_cycle"]].copy()

    tbl_df["category"]  = tbl_df["ticker"].map(_ticker_cat)
    tbl_df["_sort_key"] = tbl_df["ticker"].map(lambda t: _cat_rank.get(t, (99, 99)))
    tbl_df = tbl_df.sort_values("_sort_key").drop(columns=["_sort_key"])
    tbl_df = tbl_df[["ticker", "category", "up_cycle_magnitude", "up_cycle_duration",
                      "down_cycle_magnitude", "down_cycle_duration", "vol_diff_last_cycle"]]

    for col in ["up_cycle_magnitude", "down_cycle_magnitude"]:
        tbl_df[col] = tbl_df[col].map(lambda x: f"+{x:.1f}%" if pd.notna(x) and x >= 0
                                      else (f"{x:.1f}%" if pd.notna(x) else "—"))
    tbl_df["vol_diff_last_cycle"] = tbl_df["vol_diff_last_cycle"].map(
        lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
    for col in ["up_cycle_duration", "down_cycle_duration"]:
        tbl_df[col] = tbl_df[col].map(lambda x: f"{int(x)}d" if pd.notna(x) else "—")

    tbl_df = tbl_df.rename(columns={
        "ticker":               "Ticker",
        "category":             "Category",
        "up_cycle_magnitude":   "↑ Magnitude",
        "up_cycle_duration":    "↑ Duration",
        "down_cycle_magnitude": "↓ Magnitude",
        "down_cycle_duration":  "↓ Duration",
        "vol_diff_last_cycle":  "Vol Δ vs Prior Cycle",
    })

    # Conditional colour: green for positive magnitudes/vol, red for negative
    tbl_cond = [{"if": {"row_index": "odd"}, "backgroundColor": BG2}]
    for col in ["↑ Magnitude", "Vol Δ vs Prior Cycle"]:
        tbl_cond += [
            {"if": {"filter_query": f'{{{col}}} contains "+"', "column_id": col},
             "color": GREEN, "fontWeight": "600"},
        ]
    for col in ["↓ Magnitude", "Vol Δ vs Prior Cycle"]:
        tbl_cond += [
            {"if": {"filter_query": f'{{{col}}} contains "-"', "column_id": col},
             "color": RED, "fontWeight": "600"},
        ]

    tbl = dash_table.DataTable(
        data=tbl_df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in tbl_df.columns],
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=tbl_cond,
    )

    # ── Up vs Down cycle magnitude ────────────────────────────────────────
    # Sort bars by category order for the bar charts too
    cyc_sorted = cyc.copy()
    cyc_sorted["_sk"] = cyc_sorted["ticker"].map(lambda t: _cat_rank.get(t, (99, 99)))
    cyc_sorted = cyc_sorted.sort_values("_sk").drop(columns=["_sk"])

    fig_mag = go.Figure()
    fig_mag.add_trace(go.Bar(
        name="Up Cycle (%)", x=cyc_sorted["ticker"], y=cyc_sorted["up_cycle_magnitude"],
        marker_color=GREEN,
        hovertemplate="<b>%{x}</b><br>Up: +%{y:.1f}%<extra></extra>",
    ))
    fig_mag.add_trace(go.Bar(
        name="Down Cycle (%)", x=cyc_sorted["ticker"], y=cyc_sorted["down_cycle_magnitude"],
        marker_color=RED,
        hovertemplate="<b>%{x}</b><br>Down: %{y:.1f}%<extra></extra>",
    ))
    fig_mag.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="Last Cycle Magnitude (Up vs Down)",
                           barmode="group", height=350)

    # ── Cycle duration ────────────────────────────────────────────────────
    fig_dur = go.Figure()
    fig_dur.add_trace(go.Bar(
        name="Up Duration (days)", x=cyc_sorted["ticker"], y=cyc_sorted["up_cycle_duration"],
        marker_color=GREEN,
        hovertemplate="<b>%{x}</b><br>Up: %{y} days<extra></extra>",
    ))
    fig_dur.add_trace(go.Bar(
        name="Down Duration (days)", x=cyc_sorted["ticker"], y=cyc_sorted["down_cycle_duration"],
        marker_color=RED,
        hovertemplate="<b>%{x}</b><br>Down: %{y} days<extra></extra>",
    ))
    fig_dur.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="Last Cycle Duration (trading days)",
                           barmode="group", height=300)

    # ── Volume difference vs last cycle ───────────────────────────────────
    vol_df = cyc_sorted.dropna(subset=["vol_diff_last_cycle"])
    fig_vol = go.Figure(go.Bar(
        x=vol_df["ticker"], y=vol_df["vol_diff_last_cycle"],
        marker_color=[GREEN if v > 0 else RED for v in vol_df["vol_diff_last_cycle"]],
        hovertemplate="<b>%{x}</b><br>Vol Δ vs last cycle: %{y:+.1f}%<extra></extra>",
    ))
    fig_vol.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="Volume Change vs Previous Cycle (%)",
                           showlegend=False, height=280)
    fig_vol.add_hline(y=0, line_dash="dash", line_color=SUBTEXT, line_width=1)

    # ── Per-ticker cycle price chart ──────────────────────────────────────
    default_ticker = tickers[0] if tickers else ""
    initial_fig    = _build_cycle_chart(default_ticker) if default_ticker else go.Figure()

    cycle_chart_section = _card([
        _section_title("Cycle Price Chart"),
        html.Div([
            html.Label("Select ticker:", style={"color": SUBTEXT, "fontSize": "12px",
                                                 "marginRight": "8px"}),
            dcc.Dropdown(
                id="cycles-ticker-select",
                options=[{"label": t, "value": t} for t in tickers],
                value=default_ticker,
                clearable=False,
                style={"width": "200px", "display": "inline-block",
                       "backgroundColor": BG3, "color": TEXT,
                       "border": "1px solid #30363d"},
            ),
        ], style={"marginBottom": "10px"}),
        html.Div([
            html.Span("🟢 Green shading = up cycle  ", style={"color": GREEN, "fontSize": "12px"}),
            html.Span("🔴 Red shading = down cycle  ", style={"color": RED, "fontSize": "12px"}),
            html.Span("▲ Peak  ▼ Trough — % label shows magnitude of each cycle segment",
                      style={"color": SUBTEXT, "fontSize": "11px"}),
        ], style={"marginBottom": "8px"}),
        dcc.Graph(id="cycles-price-chart", figure=initial_fig,
                  config={"displayModeBar": True}),
    ])

    return html.Div([
        _card([_section_title("Cycle Summary"), tbl]),
        cycle_chart_section,
        _card(dcc.Graph(figure=fig_mag, config={"displayModeBar": True})),
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=fig_dur, config={"displayModeBar": False})), width=7),
            dbc.Col(_card(dcc.Graph(figure=fig_vol, config={"displayModeBar": False})), width=5),
        ]),
        _card(_source_footer("Yahoo Finance / yfinance — scipy.signal.argrelextrema",
                              "Cycle peaks/troughs detected via rolling local extrema "
                              f"(window={_CYCLE_WINDOW} trading days). "
                              "Volume Δ = current up-cycle avg volume vs prior up-cycle.")),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — PERIOD COMPARISON
# ══════════════════════════════════════════════════════════════════════════════

def tab_compare(tickers):
    """Side-by-side comparison of any two calendar quarters."""

    # Period selector controls (rendered first; comparison triggered by callback)
    return html.Div([
        _card([
            _section_title("Select Two Periods to Compare"),
            dbc.Row([
                dbc.Col([
                    html.Label("Period A", style={"color": SUBTEXT, "fontSize": "12px"}),
                    dcc.DatePickerRange(
                        id="cmp-period-a",
                        start_date=(_now_hkt() - timedelta(days=180)).strftime("%Y-%m-%d"),
                        end_date=(_now_hkt() - timedelta(days=91)).strftime("%Y-%m-%d"),
                        display_format="DD MMM YYYY",
                    ),
                ], width=5),
                dbc.Col([
                    html.Label("Period B", style={"color": SUBTEXT, "fontSize": "12px"}),
                    dcc.DatePickerRange(
                        id="cmp-period-b",
                        start_date=(_now_hkt() - timedelta(days=90)).strftime("%Y-%m-%d"),
                        end_date=_now_hkt().strftime("%Y-%m-%d"),
                        display_format="DD MMM YYYY",
                    ),
                ], width=5),
                dbc.Col([
                    html.Div(style={"height": "20px"}),
                    dbc.Button("Compare →", id="btn-compare", color="primary",
                               style={"marginTop": "4px"}),
                ], width=2),
            ]),
        ]),
        html.Div(id="cmp-output"),
        # Pass tickers down via store
        dcc.Store(id="cmp-tickers", data=tickers),
    ])


@app.callback(
    Output("cycles-price-chart", "figure"),
    Input("cycles-ticker-select", "value"),
    prevent_initial_call=True,
)
def update_cycle_price_chart(ticker):
    if not ticker:
        return go.Figure()
    return _build_cycle_chart(ticker)


@app.callback(
    Output("cmp-output", "children"),
    Input("btn-compare", "n_clicks"),
    State("cmp-period-a",  "start_date"),
    State("cmp-period-a",  "end_date"),
    State("cmp-period-b",  "start_date"),
    State("cmp-period-b",  "end_date"),
    State("cmp-tickers",   "data"),
    prevent_initial_call=True,
)
def run_comparison(_, a_start, a_end, b_start, b_end, tickers):
    if not tickers:
        return html.P("No tickers selected.", style={"color": SUBTEXT})

    a_start = (a_start or "")[:10]
    a_end   = (a_end   or "")[:10]
    b_start = (b_start or "")[:10]
    b_end   = (b_end   or "")[:10]

    # ── Price-based comparison ────────────────────────────────────────────
    pa = price_data(tickers, a_start, a_end)
    pb = price_data(tickers, b_start, b_end)

    def period_return(prices_df):
        out = {}
        for tkr in tickers:
            sub = prices_df[prices_df["ticker"] == tkr].sort_values("date")
            if len(sub) >= 2:
                out[tkr] = (sub["close"].iloc[-1] / sub["close"].iloc[0] - 1) * 100
        return out

    ra, rb = period_return(pa), period_return(pb)
    common = [t for t in tickers if t in ra and t in rb]

    fig_ret = go.Figure()
    fig_ret.add_trace(go.Bar(
        name=f"Period A ({a_start} → {a_end})",
        x=common, y=[ra[t] for t in common],
        marker_color=ACCENT,
        hovertemplate="<b>%{x}</b><br>Period A: %{y:+.1f}%<extra></extra>",
    ))
    fig_ret.add_trace(go.Bar(
        name=f"Period B ({b_start} → {b_end})",
        x=common, y=[rb[t] for t in common],
        marker_color=YELLOW,
        hovertemplate="<b>%{x}</b><br>Period B: %{y:+.1f}%<extra></extra>",
    ))
    fig_ret.add_hline(y=0, line_dash="dash", line_color=SUBTEXT, line_width=1)
    fig_ret.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="Price Return — Period A vs B",
                           barmode="group", height=380)

    # ── Financial metrics comparison (Revenue, Gross Profit, Net Profit) ──
    fin_a_rows = query(
        f"SELECT ticker, AVG(revenue) as rev, AVG(gross_profit) as gp, "
        f"AVG(net_profit) as np FROM quarterly_financials "
        f"WHERE ticker IN ({','.join('?'*len(tickers))}) "
        f"AND period_end BETWEEN ? AND ? GROUP BY ticker",
        tickers + [a_start, a_end],
    )
    fin_b_rows = query(
        f"SELECT ticker, AVG(revenue) as rev, AVG(gross_profit) as gp, "
        f"AVG(net_profit) as np FROM quarterly_financials "
        f"WHERE ticker IN ({','.join('?'*len(tickers))}) "
        f"AND period_end BETWEEN ? AND ? GROUP BY ticker",
        tickers + [b_start, b_end],
    )

    charts = [_card(dcc.Graph(figure=fig_ret, config={"displayModeBar": True}))]

    for metric, label in [("rev", "Avg Revenue"), ("gp", "Avg Gross Profit"), ("np", "Avg Net Profit")]:
        if fin_a_rows.empty and fin_b_rows.empty:
            break
        merged = pd.merge(fin_a_rows[["ticker", metric]].rename(columns={metric: "A"}),
                          fin_b_rows[["ticker", metric]].rename(columns={metric: "B"}),
                          on="ticker", how="outer").dropna(subset=["A", "B"])
        if merged.empty:
            continue
        fig_f = go.Figure()
        fig_f.add_trace(go.Bar(name=f"Period A", x=merged["ticker"],
                                y=merged["A"]/1e9, marker_color=ACCENT,
                                hovertemplate="<b>%{x}</b><br>A: $%{y:.2f}B<extra></extra>"))
        fig_f.add_trace(go.Bar(name=f"Period B", x=merged["ticker"],
                                y=merged["B"]/1e9, marker_color=YELLOW,
                                hovertemplate="<b>%{x}</b><br>B: $%{y:.2f}B<extra></extra>"))
        fig_f.update_layout(**PLOTLY_TEMPLATE["layout"],
                             title=f"{label} (USD Bn) — Period A vs B",
                             barmode="group", height=300)
        charts.append(_card(dcc.Graph(figure=fig_f, config={"displayModeBar": False})))

    return html.Div(charts)


# ══════════════════════════════════════════════════════════════════════════════
# SUPPLY CHAIN — DB HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def sc_prices_query(category: str, source: str = None) -> pd.DataFrame:
    """Return price history for all products in a category (GPU/GPU-Enterprise/CPU/RAM)."""
    model_ids = list(
        ({**GPU_PRODUCTS}            if category == "GPU" else
         {**GPU_ENTERPRISE_PRODUCTS} if category == "GPU-Enterprise" else
         {**CPU_PRODUCTS}            if category == "CPU" else
         {**RAM_PRODUCTS}).keys()
    )
    if not model_ids:
        return pd.DataFrame()
    ph = ",".join("?" * len(model_ids))
    src_clause = f"AND source='{source}'" if source else ""
    return query(
        f"SELECT p.model_id, p.date, p.source, p.price_usd, p.passmark_score, "
        f"p.price_perf, p.in_stock, c.name, c.brand "
        f"FROM sc_prices p LEFT JOIN sc_products c ON p.model_id=c.model_id "
        f"WHERE p.model_id IN ({ph}) {src_clause} ORDER BY p.date, p.model_id",
        model_ids,
    )


def sc_capacity_query(company: str = None) -> pd.DataFrame:
    clause = f"WHERE company='{company}'" if company else ""
    return query(
        f"SELECT * FROM sc_capacity {clause} ORDER BY company, period"
    )


def sc_dram_query() -> pd.DataFrame:
    return query("SELECT * FROM sc_dram_spot ORDER BY product_type, period")


def sc_btb_query() -> pd.DataFrame:
    return query("SELECT * FROM sc_semi_btb ORDER BY period")


def sc_steam_query() -> pd.DataFrame:
    """Latest Steam HW Survey GPU shares."""
    return query("""
        SELECT s.model_name, s.share_pct, s.period
        FROM sc_market_share s
        INNER JOIN (SELECT MAX(period) AS mp FROM sc_market_share) latest
          ON s.period = latest.mp
        ORDER BY s.share_pct DESC
    """)


# ── Price Index vs SOXX ETF Correlation Chart ────────────────────────────────

def _sc_vs_etf_panel():
    """
    Overlay the enterprise GPU / CPU / RAM (HBM) price indices (monthly avg,
    normalised to base=100) against SOXX (iShares Semiconductor ETF).
    Falls back to SMH if SOXX has not been crawled yet.
    GPU = NVIDIA/AMD AI accelerators (A100 → H100 → H200 → B200 + MI300X).
    CPU = Intel Xeon Platinum + AMD EPYC server-class CPUs.
    RAM = HBM3 / HBM3E per-stack contract price (the AI memory benchmark).
    Vertical markers indicate when each new generation reached GA.
    """

    # ── 1. Build monthly price indices for each category ─────────────────────
    # RAM: restrict to HBM-class enterprise memory only (HBM3 + HBM3E stacks)
    _HBM_PRODUCTS = {k: v for k, v in RAM_PRODUCTS.items()
                     if v.get("type") in ("HBM3", "HBM3E")}
    CATEGORIES = [
        ("GPU", GPU_ENTERPRISE_PRODUCTS, "#76b900"),
        ("CPU", CPU_ENTERPRISE_PRODUCTS, "#0071C5"),
        ("RAM", _HBM_PRODUCTS,           "#ED1C24"),
    ]

    price_series: dict[str, pd.Series] = {}

    for cat, products, _ in CATEGORIES:
        model_ids = list(products.keys())
        if not model_ids:
            continue
        ph = ",".join("?" * len(model_ids))
        # Include all sources (curated + passmark + newegg) so that each
        # crawler run automatically extends the index with the latest data point.
        # Monthly resampling (mean) handles multi-source overlap gracefully:
        # curated rows provide the historical backbone; live crawl rows extend
        # the rightmost bin each time the crawler runs.
        df = query(
            f"SELECT date, price_usd FROM sc_prices "
            f"WHERE model_id IN ({ph}) "
            f"AND price_usd IS NOT NULL "
            f"ORDER BY date",
            model_ids,
        )
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df["price_usd"] = pd.to_numeric(df["price_usd"], errors="coerce")
        # Monthly average across all models in the category
        monthly = (
            df.set_index("date")["price_usd"]
            .resample("MS")          # Month Start
            .mean()
            .dropna()
        )
        if monthly.empty or len(monthly) < 2:
            continue
        price_series[cat] = monthly

    # ── 2. Fetch SOXX (fallback: SMH) from daily_prices ──────────────────────
    etf_ticker = None
    for candidate in ("SOXX", "SMH"):
        df_etf = query(
            "SELECT date, close FROM daily_prices WHERE ticker=? ORDER BY date",
            [candidate],
        )
        if not df_etf.empty:
            etf_ticker = candidate
            break

    etf_monthly: pd.Series | None = None
    if etf_ticker is not None and not df_etf.empty:
        df_etf["date"]  = pd.to_datetime(df_etf["date"], errors="coerce")
        df_etf["close"] = pd.to_numeric(df_etf["close"], errors="coerce")
        etf_monthly = (
            df_etf.set_index("date")["close"]
            .resample("MS")
            .last()             # Use month-end close as the ETF reference price
            .dropna()
        )
        if etf_monthly.empty or len(etf_monthly) < 2:
            etf_monthly = None

    # ── 3. If no data at all — return placeholder ────────────────────────────
    if not price_series and etf_monthly is None:
        return _card([
            _section_title("Price Index vs SOXX ETF — Correlation"),
            html.P(
                "No supply-chain price or ETF data yet. "
                "Run: python supply_chain_crawler.py && python crawler.py --quick",
                style={"color": SUBTEXT, "fontSize": "12px"},
            ),
        ])

    # ── 4. Determine common date range and normalise to base=100 ─────────────
    all_starts = [s.index.min() for s in price_series.values()]
    if etf_monthly is not None:
        all_starts.append(etf_monthly.index.min())
    common_start = max(all_starts) if all_starts else None

    def _normalise(series: pd.Series, base_date) -> pd.Series:
        """Slice from base_date and rebase to 100."""
        s = series[series.index >= base_date].copy()
        base = s.iloc[0] if not s.empty and s.iloc[0] != 0 else None
        return (s / base * 100) if base else s

    CAT_COLORS = {"GPU": "#76b900", "CPU": "#00A3E0", "RAM": "#ED1C24"}

    # ── 5. Build normalised overlay chart ────────────────────────────────────
    fig = go.Figure()

    # ETF first (drawn behind)
    if etf_monthly is not None and common_start is not None:
        etf_norm = _normalise(etf_monthly, common_start)
        fig.add_trace(go.Scatter(
            x=etf_norm.index,
            y=etf_norm.values.round(2),
            name=f"{etf_ticker} ETF",
            mode="lines",
            line=dict(width=3, color=ACCENT, dash="solid"),
            hovertemplate=f"<b>{etf_ticker}</b><br>%{{x|%b %Y}}<br>Index: %{{y:.1f}}<extra></extra>",
        ))
        # Shade area under ETF
        fig.add_trace(go.Scatter(
            x=etf_norm.index, y=etf_norm.values.round(2),
            mode="none",
            fill="tozeroy",
            fillcolor=f"rgba(88,166,255,0.07)",
            showlegend=False, hoverinfo="skip",
        ))

    # Price indices
    for cat, _, _col in CATEGORIES:
        if cat not in price_series:
            continue
        s = price_series[cat]
        s_norm = _normalise(s, common_start) if common_start else _normalise(s, s.index.min())
        col = CAT_COLORS.get(cat, ACCENT)
        fig.add_trace(go.Scatter(
            x=s_norm.index,
            y=s_norm.values.round(2),
            name=f"{cat} Price Index",
            mode="lines+markers",
            line=dict(width=2, color=col, dash="dot"),
            marker=dict(size=5, color=col),
            hovertemplate=f"<b>{cat} Price Index</b><br>%{{x|%b %Y}}<br>Index: %{{y:.1f}}<extra></extra>",
        ))

    # Reference line at 100
    fig.add_hline(y=100, line_dash="dash", line_color=SUBTEXT, line_width=1,
                  annotation_text="Base = 100", annotation_position="right",
                  annotation_font_color=SUBTEXT, annotation_font_size=10)

    # ── Product-generation launch markers ─────────────────────────────────────
    # Alternate annotation positions so labels don't overlap when launches
    # cluster (e.g. Nov 2022 has both H100 GA and Genoa GA).
    _LAUNCH_CAT_COLOR = {"GPU": "#76b900", "CPU": "#0071C5", "RAM": "#ED1C24"}
    _launch_positions = ["top left", "top right", "top left", "top right",
                         "top left", "top right", "top left", "top right",
                         "top left"]
    for _i, (lcat, lshort, _ldesc, ldate) in enumerate(ENTERPRISE_PRODUCT_LAUNCHES):
        _lcol = _LAUNCH_CAT_COLOR.get(lcat, SUBTEXT)
        fig.add_vline(
            x=datetime.strptime(ldate, "%Y-%m-%d"),
            line_width=1,
            line_dash="dot",
            line_color=_lcol,
            annotation_text=f"▲ {lshort}",
            annotation_position=_launch_positions[_i % len(_launch_positions)],
            annotation_font_color=_lcol,
            annotation_font_size=9,
        )

    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title=(
            f"Enterprise AI Hardware Price Index vs {etf_ticker} ETF — Normalised to 100"
            if etf_ticker else "Enterprise AI Hardware Price Index — Normalised to 100"
        ),
        height=480,
        xaxis_title="Month",
        yaxis_title="Index (Base = 100 at common start)",
        hovermode="x unified",
    )
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    # Default view: 2Y so curated supply-chain indices (ending ~2025-05) and
    # the live ETF series are both visible on initial load.
    # ETF right-edge stays at today; 1Y/3Y/5Y buttons step backward from there.
    fig.update_xaxes(
        type="date",
        rangeselector=_time_rangeselector(active_index=0),   # 1Y default
        range=[_range_start(2), _now_hkt().strftime("%Y-%m-%d")],
        rangeslider=dict(visible=False),
    )

    # ── 6. Rolling 3-month correlation bar chart (GPU / CPU / RAM vs ETF) ────
    corr_cards = []
    if etf_monthly is not None and common_start is not None:
        etf_s = etf_monthly[etf_monthly.index >= common_start]
        for cat, _, _ in CATEGORIES:
            if cat not in price_series:
                continue
            s = price_series[cat]
            combined = pd.concat(
                [s.rename("price"), etf_s.rename("etf")], axis=1
            ).dropna()
            if len(combined) < 4:
                continue
            corr = combined["price"].corr(combined["etf"])
            col  = (GREEN if corr >= 0.6 else YELLOW if corr >= 0.2
                    else RED if corr <= -0.2 else SUBTEXT)
            corr_cards.append(dbc.Col(
                _card([
                    html.Div(cat, style={"fontSize": "11px", "color": SUBTEXT,
                                         "textTransform": "uppercase", "letterSpacing": "0.5px"}),
                    html.Div(
                        f"r = {corr:+.2f}",
                        style={"fontSize": "26px", "fontWeight": "700", "color": col},
                    ),
                    html.Div(
                        "vs " + etf_ticker,
                        style={"fontSize": "11px", "color": SUBTEXT},
                    ),
                    html.Div(
                        ("Strong +ve" if corr >= 0.6 else
                         "Moderate +ve" if corr >= 0.2 else
                         "Weak / No" if corr > -0.2 else "Negative") + " correlation",
                        style={"fontSize": "11px", "color": col, "marginTop": "2px"},
                    ),
                ], style={"textAlign": "center"}),
                width=4,
            ))

    # Rolling 6-month window correlation line chart
    fig_roll = None
    if etf_monthly is not None and common_start is not None:
        etf_s = etf_monthly[etf_monthly.index >= common_start]
        fig_roll = go.Figure()
        has_roll = False
        for cat, _, _ in CATEGORIES:
            if cat not in price_series:
                continue
            s = price_series[cat]
            combined = pd.concat(
                [s.rename("price"), etf_s.rename("etf")], axis=1
            ).dropna()
            if len(combined) < 6:
                continue
            rolling_corr = (
                combined["price"]
                .rolling(window=6, min_periods=4)
                .corr(combined["etf"])
            )
            col = CAT_COLORS.get(cat, ACCENT)
            fig_roll.add_trace(go.Scatter(
                x=rolling_corr.index,
                y=rolling_corr.values.round(3),
                name=f"{cat} vs {etf_ticker}",
                mode="lines",
                line=dict(width=2, color=col),
                hovertemplate=(
                    f"<b>{cat} vs {etf_ticker}</b><br>"
                    "%{x|%b %Y}<br>6M Rolling r: %{y:.2f}<extra></extra>"
                ),
            ))
            has_roll = True

        if has_roll:
            fig_roll.add_hline(y=0,    line_dash="dash", line_color=SUBTEXT,  line_width=1)
            fig_roll.add_hline(y=0.6,  line_dash="dot",  line_color=GREEN,    line_width=1,
                               annotation_text="Strong +ve (0.6)", annotation_font_color=GREEN,
                               annotation_font_size=10, annotation_position="right")
            fig_roll.add_hline(y=-0.6, line_dash="dot",  line_color=RED,      line_width=1,
                               annotation_text="Strong −ve (−0.6)", annotation_font_color=RED,
                               annotation_font_size=10, annotation_position="right")
            fig_roll.update_layout(
                **PLOTLY_TEMPLATE["layout"],
                title=f"6-Month Rolling Correlation: Price Index vs {etf_ticker}",
                height=280,
                xaxis_title="Month",
                yaxis_title="Pearson r",
                hovermode="x unified",
            )
            fig_roll.update_yaxes(range=[-1.05, 1.05])
            # 2Y default so rolling-corr data (limited by curated SC series)
            # is visible on initial load alongside the live ETF series.
            fig_roll.update_xaxes(
                type="date",
                rangeselector=_time_rangeselector(active_index=0),   # 1Y default
                range=[_range_start(2), _now_hkt().strftime("%Y-%m-%d")],
                rangeslider=dict(visible=False),
            )
        else:
            fig_roll = None

    # ── 7. Latest price snapshot table ───────────────────────────────────────
    tbl_rows = []
    for cat, _, _ in CATEGORIES:
        if cat not in price_series:
            continue
        s = price_series[cat]
        if len(s) < 2:
            continue
        latest_price = s.iloc[-1]
        prev_price   = s.iloc[-2]
        mom          = (latest_price / prev_price - 1) * 100
        yoy_price    = s.iloc[-13] if len(s) >= 13 else None
        yoy          = ((latest_price / yoy_price - 1) * 100) if yoy_price else None
        tbl_rows.append({
            "Category": cat,
            "Period": s.index[-1].strftime("%Y-%m"),
            "Avg Price (USD)": f"${latest_price:,.0f}",
            "MoM Δ": f"{mom:+.1f}%",
            "YoY Δ": f"{yoy:+.1f}%" if yoy is not None else "—",
        })
    if etf_monthly is not None:
        s = etf_monthly
        if len(s) >= 2:
            lp  = s.iloc[-1]; pp = s.iloc[-2]
            mom = (lp / pp - 1) * 100
            yoy_p = s.iloc[-13] if len(s) >= 13 else None
            yoy   = ((lp / yoy_p - 1) * 100) if yoy_p else None
            tbl_rows.append({
                "Category": f"{etf_ticker} ETF",
                "Period": s.index[-1].strftime("%Y-%m"),
                "Avg Price (USD)": f"${lp:,.2f}",
                "MoM Δ": f"{mom:+.1f}%",
                "YoY Δ": f"{yoy:+.1f}%" if yoy is not None else "—",
            })

    tbl_df = pd.DataFrame(tbl_rows)
    snapshot_tbl = None
    if not tbl_df.empty:
        snapshot_tbl = dash_table.DataTable(
            data=tbl_df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in tbl_df.columns],
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={
                "backgroundColor": BG3, "color": TEXT,
                "border": "1px solid #30363d", "fontSize": "13px", "padding": "6px 12px",
            },
            style_header={
                "backgroundColor": BG2, "color": ACCENT,
                "fontWeight": "600", "border": "1px solid #30363d",
            },
            style_data_conditional=[
                {"if": {"filter_query": '{MoM Δ} contains "+"'}, "color": GREEN},
                {"if": {"filter_query": '{MoM Δ} contains "-"'},  "color": RED},
                {"if": {"filter_query": '{YoY Δ} contains "+"'}, "color": GREEN},
                {"if": {"filter_query": '{YoY Δ} contains "-"'},  "color": RED},
                {"if": {"row_index": "odd"}, "backgroundColor": BG2},
            ],
        )

    # ── 8. Assemble panel ────────────────────────────────────────────────────
    note_etf = (
        f"Comparing enterprise AI hardware price trends against "
        f"{etf_ticker} (iShares Semiconductor ETF) as a proxy for semiconductor "
        f"industry equity performance. "
        f"GPU = NVIDIA/AMD AI accelerators (A100 → H100 → H200 → B200, MI300X); "
        f"CPU = Intel Xeon Platinum + AMD EPYC server flagship SKUs; "
        f"RAM = HBM3/HBM3E per-stack contract ASP (the AI memory price benchmark). "
        f"▲ markers indicate when each new product generation reached GA — "
        f"the index tracks the full portfolio across generations."
    )

    children = [
        _section_title(f"Enterprise AI Hardware Price Index vs {etf_ticker} ETF — Industry Correlation"),
        html.P(note_etf, style={"color": SUBTEXT, "fontSize": "12px", "marginBottom": "12px"}),
        dcc.Graph(figure=fig, config={"displayModeBar": True}),
    ]

    if corr_cards:
        children += [
            html.Div(style={"marginTop": "8px"}),
            _section_title("Full-Period Pearson Correlation"),
            dbc.Row(corr_cards, className="g-2"),
        ]

    if fig_roll is not None:
        children.append(_card(dcc.Graph(figure=fig_roll, config={"displayModeBar": True})))

    if snapshot_tbl is not None:
        children += [
            html.Div(style={"marginTop": "8px"}),
            _section_title("Category-Level Monthly Avg Price & ETF Snapshot"),
            html.P(
                "Category-level average enterprise ASP for the most recent month — "
                "mean across all tracked models per category: "
                "GPU = AI accelerators (A100/H100/H200/B200 + MI300X); "
                "CPU = Intel Xeon Platinum + AMD EPYC server SKUs; "
                "RAM = HBM3/HBM3E per-stack contract price.",
                style={"color": SUBTEXT, "fontSize": "12px", "marginBottom": "8px"},
            ),
            snapshot_tbl,
        ]

    etf_note = (f"SOXX (iShares Semiconductor ETF)" if etf_ticker == "SOXX"
                else f"{etf_ticker} (VanEck Semiconductor ETF — SOXX proxy until SOXX is crawled)")
    children.append(_source_footer(
        f"NVIDIA/AMD/Intel enterprise ODP + TrendForce contract-price estimates (GPU/CPU/HBM)  ·  "
        f"Yahoo Finance / yfinance ({etf_note})",
        "GPU index = avg contract ASP across A100/H100/H200/B200/MI300X per month.  "
        "CPU index = avg ODP-derived ASP across Xeon Platinum + EPYC server SKUs.  "
        "RAM index = HBM3 (48 GB stack) / HBM3E (96 GB stack) per-stack contract price.  "
        f"All series normalised to 100 at common start: "
        f"{common_start.strftime('%Y-%m') if common_start else 'N/A'}.  "
        "▲ markers = product generation GA dates.",
    ))

    return _card(children)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — SUPPLY CHAIN
# ══════════════════════════════════════════════════════════════════════════════

def tab_supply_chain():
    """
    Supply Chain tab — category sub-tabs (GPU / CPU / RAM) using dbc.Tabs
    with content pre-rendered directly in each tab child (no server callback
    needed — Dash handles show/hide via CSS). This avoids the Dash anti-pattern
    of having a callback output nested inside another callback's output.
    """

    _TAB_STYLE = {"--bs-nav-tabs-border-color": "#30363d"}

    def _safe_price_section(cat):
        try:
            return _sc_price_section(cat)
        except Exception as exc:
            return _card(html.P(
                f"Error loading {cat} price data: {exc}",
                style={"color": RED, "fontSize": "13px"},
            ))

    def _safe_enterprise_gpu():
        try:
            return _sc_enterprise_gpu_section()
        except Exception as exc:
            return _card(html.P(
                f"Error loading Enterprise GPU data: {exc}",
                style={"color": RED, "fontSize": "13px"},
            ))

    def _safe_enterprise_ram():
        try:
            return _sc_enterprise_ram_section()
        except Exception as exc:
            return _card(html.P(
                f"Error loading Enterprise RAM data: {exc}",
                style={"color": RED, "fontSize": "13px"},
            ))

    # dbc.Tabs renders tab content directly — no server round-trip required.
    # All three sections are built once when the Supply Chain tab is opened.
    # GPU tab: enterprise data-center GPUs (A100/H100/H200/B200/MI300X).
    # RAM tab: enterprise HBM (HBM3/HBM3E) with consumer DRAM section below.
    price_tabs = dbc.Tabs(
        [
            dbc.Tab(_safe_enterprise_gpu(), label="🖥️  GPU (Enterprise)", tab_id="sc-tab-gpu",
                    label_style={"fontSize": "13px", "color": TEXT},
                    active_label_style={"color": ACCENT, "fontWeight": "600"}),
            dbc.Tab(_safe_price_section("CPU"), label="⚙️  CPU", tab_id="sc-tab-cpu",
                    label_style={"fontSize": "13px", "color": TEXT},
                    active_label_style={"color": ACCENT, "fontWeight": "600"}),
            dbc.Tab(_safe_enterprise_ram(), label="💾  RAM (Enterprise)", tab_id="sc-tab-ram",
                    label_style={"fontSize": "13px", "color": TEXT},
                    active_label_style={"color": ACCENT, "fontWeight": "600"}),
        ],
        active_tab="sc-tab-gpu",
        style=_TAB_STYLE,
    )

    return html.Div([
        _card([
            _section_title("Supply Chain Intelligence"),
            html.P(
                "Product-level supply chain metrics across GPU, CPU, and RAM. "
                "Price data: PassMark + Newegg (live).  Volume: Steam HW Survey. "
                "Orders: SEMI B2B.  Capacity/Occupancy: curated from earnings calls. "
                "Delivery: Newegg in-stock status.",
                style={"color": SUBTEXT, "fontSize": "12px", "margin": "0"},
            ),
            _source_footer(
                "PassMark / Newegg / Valve (Steam) / SEMI / Company Earnings Transcripts / TrendForce",
                "Each panel carries its own source attribution below.",
            ),
        ]),

        # ── PANEL 1 + 2: Price Index & In-Stock (GPU / CPU / RAM sub-tabs) ───
        _card([_section_title("Product Category — Price Index & Availability"), price_tabs]),

        # ── PANEL 3: Price Index vs SOXX ETF Correlation ─────────────────────
        _sc_vs_etf_panel(),

        # ── PANEL 4: Sales Volume — Steam Survey ──────────────────────────────
        _sc_steam_panel(),

        # ── PANEL 5: Order Volume — SEMI B2B ─────────────────────────────────
        _sc_btb_panel(),

        # ── PANEL 5 + 6: Manufacturer Capacity & Occupancy ───────────────────
        _sc_capacity_panel(),
        # Note: DRAM & HBM Spot Prices are now embedded in the RAM sub-tab above
    ])


def _sc_dram_inline(height: int = 360) -> html.Div:
    """DRAM & HBM spot price chart + YoY table — embedded inside the RAM tab."""
    df = sc_dram_query()
    if df.empty:
        return _card(html.P(
            "DRAM spot price data not yet loaded. Run: python supply_chain_crawler.py",
            style={"color": SUBTEXT, "fontSize": "12px"},
        ))

    df["price_usd"] = pd.to_numeric(df["price_usd"], errors="coerce")
    df = df.sort_values("period")

    DRAM_COLORS = {
        "DDR4": "#74C0FC", "DDR5": "#51CF66", "HBM3E": "#FF6B6B",
        "HBM3": "#CC5DE8", "LPDDR5X": "#FFD43B",
    }

    # Unit label per product type:
    #   DDR4 / DDR5  → price is per benchmark die (USD/die)
    #   HBM3 / HBM3E → price is per GB of stack capacity (USD/GB)
    _UNIT_LABEL = {
        "DDR4": "$/die", "DDR5": "$/die",
        "HBM3": "$/GB",  "HBM3E": "$/GB",
        "LPDDR5X": "$/die",
    }

    fig = go.Figure()
    for ptype, grp in df.groupby("product_type"):
        unit = _UNIT_LABEL.get(ptype, "USD")
        for spec, sub in grp.groupby("spec_label"):
            fig.add_trace(go.Scatter(
                x=sub["period"], y=sub["price_usd"],
                name=f"{ptype} — {spec}",
                mode="lines+markers",
                line=dict(width=2, color=DRAM_COLORS.get(ptype, ACCENT)),
                hovertemplate=(
                    f"<b>{ptype}</b> {spec}<br>"
                    f"%{{x}}<br>${{y:.2f}} {unit}<extra></extra>"
                ),
            ))
    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="DRAM & HBM Spot / Contract Prices — DDR4/DDR5 (USD/die) · HBM3E (USD/GB)",
        height=height, xaxis_title="Month", yaxis_title="Price (USD)",
    )
    # Anchor x-range to actual data end so initial 1Y view is not empty when
    # curated data lags today.  stepmode="backward" buttons stay relative to
    # the right edge, so 1Y/3Y/5Y still work correctly.
    _dram_end_dt  = pd.to_datetime(df.sort_values("period")["period"].iloc[-1][:7] + "-01")
    _dram_rend    = (_dram_end_dt + pd.DateOffset(months=2)).strftime("%Y-%m-%d")
    _dram_rstart  = (_dram_end_dt - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    fig.update_xaxes(
        type="date",
        rangeselector=_time_rangeselector(active_index=0),   # 1Y default
        range=[_dram_rstart, _dram_rend],
        rangeslider=dict(visible=False),
    )

    # YoY delta table
    latest = df.sort_values("period").groupby(["product_type", "spec_label"]).last()
    prior_df = df[df["period"] <= (pd.to_datetime(df["period"].max()) - pd.DateOffset(months=12))
                 .strftime("%Y-%m")].groupby(["product_type", "spec_label"])["price_usd"].last()
    rows_tbl = []
    for idx, row in latest.iterrows():
        p_now  = row["price_usd"]
        p_prev = prior_df.get(idx)
        yoy    = ((p_now / p_prev - 1) * 100) if p_prev and p_prev > 0 else None
        rows_tbl.append({
            "Type": idx[0], "Spec": idx[1], "Period": row["period"],
            "Spot Price (USD)": f"${p_now:.2f}",
            "YoY Δ": f"{yoy:+.1f}%" if yoy is not None else "—",
            "Source": row.get("source", "TrendForce"),
        })
    tbl_df = pd.DataFrame(rows_tbl)
    tbl = dash_table.DataTable(
        data=tbl_df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in tbl_df.columns],
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=[
            {"if": {"filter_query": '{YoY Δ} contains "+"', "column_id": "YoY Δ"},
             "color": GREEN, "fontWeight": "600"},
            {"if": {"filter_query": '{YoY Δ} contains "-"', "column_id": "YoY Δ"},
             "color": RED, "fontWeight": "600"},
            {"if": {"row_index": "odd"}, "backgroundColor": BG2},
        ],
    )

    dram_note = html.P(
        "This chart tracks two distinct pricing layers of the memory market. "
        "DDR4 (8Gb die) and DDR5 (16Gb die) are quoted in USD per benchmark die — "
        "the single bare chip that OEMs solder onto a DIMM; these prices move with "
        "consumer PC demand and inventory cycles. "
        "HBM3E is quoted in USD per GB of stack capacity — a contract price "
        "negotiated between SK Hynix / Samsung / Micron and hyperscalers such as "
        "NVIDIA and Google; it reflects AI accelerator supply tightness rather than "
        "consumer demand. Because the two series use different units they should be "
        "read independently — focus on the direction and rate of change for each, "
        "not on comparing absolute levels across series.",
        style={"color": SUBTEXT, "fontSize": "12px", "marginBottom": "10px"},
    )

    return html.Div([
        _card([
            _section_title("DRAM & HBM Spot / Contract Prices"),
            dram_note,
            dcc.Graph(figure=fig, config={"displayModeBar": True}),
        ]),
        _card([
            _section_title("DRAM & HBM — Latest Spot Prices & Year-on-Year Change"),
            tbl,
            _source_footer("TrendForce / DRAMeXchange",
                           "DDR4 8Gb 1Gx8 & DDR5 16Gb 2Gx8: weekly spot benchmark die price (USD/die). "
                           "HBM3E 12-Hi: estimated contract price per GB of stack capacity (USD/GB). "
                           "⚠ DDR4/DDR5 and HBM3E use different units — do not compare absolute levels across series. "
                           "Update CURATED_DRAM_SPOT in products_config.py monthly."),
        ]),
    ])


def _sc_enterprise_gpu_section():
    """
    Enterprise / Data-Center GPU price index with:
    - Per-card contract price history for A100, H100, H200, B200, MI300X
    - Flagship-era shaded bands (Ampere → Hopper → Hopper+ → Blackwell)
    - Product launch / GA vertical annotations
    - FP16 TFLOPS vs latest price scatter (instead of consumer PassMark)
    - YoY price change table
    """
    df_curated = sc_prices_query("GPU-Enterprise", source="curated")

    # ── Generation milestone definitions ─────────────────────────────────────
    # (era_label, x0, x1, fill_rgba, text_color, text)
    FLAGSHIP_ERAS = [
        ("Ampere Era (A100)",  "2020-11-01", "2022-10-31", "rgba(139,92,246,0.07)",  "#9d7dea", "Ampere"),
        ("Hopper Era (H100)",  "2022-11-01", "2024-05-31", "rgba(0,163,224,0.07)",   "#0071C5", "Hopper"),
        ("Hopper+ (H200)",     "2024-06-01", "2024-11-30", "rgba(0,200,180,0.07)",   "#00C8B4", "H200"),
        ("Blackwell (B200)",   "2024-12-01", "2026-07-31", "rgba(118,185,0,0.07)",   "#76b900", "Blackwell"),
    ]
    # (model_id, ga_date, label, color)
    GA_MARKERS = [
        ("A100-SXM4-80GB",  "2020-11-01", "A100 Launch",    "#9d7dea"),
        ("H100-SXM5-80GB",  "2022-11-01", "H100 GA",        "#0071C5"),
        ("MI300X-192GB",    "2024-01-01", "MI300X GA",      "#ED1C24"),
        ("H200-SXM-141GB",  "2024-06-01", "H200 GA",        "#00C8B4"),
        ("B200-SXM-192GB",  "2024-12-01", "B200 GA",        "#76b900"),
    ]
    COLOR_BY_MODEL = {
        "A100-SXM4-80GB":  "#9d7dea",
        "H100-SXM5-80GB":  "#0071C5",
        "H200-SXM-141GB":  "#00C8B4",
        "B200-SXM-192GB":  "#76b900",
        "MI300X-192GB":    "#ED1C24",
    }

    # ── Price history line chart ───────────────────────────────────────────────
    fig_price = go.Figure()

    if not df_curated.empty:
        for mid, grp in df_curated.groupby("model_id"):
            grp = grp.sort_values("date")
            prod_name = grp["name"].iloc[0] if "name" in grp.columns else mid
            col = COLOR_BY_MODEL.get(mid, CHART_COLORS[0])
            fig_price.add_trace(go.Scatter(
                x=grp["date"], y=grp["price_usd"],
                name=prod_name, mode="lines+markers",
                line=dict(width=2.5, color=col),
                marker=dict(size=4),
                hovertemplate=(
                    f"<b>{prod_name}</b><br>%{{x|%b %Y}}<br>"
                    f"Price: $%{{y:,.0f}}<extra></extra>"
                ),
            ))

    fig_price.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Enterprise GPU — Estimated Contract/Spot Price (USD/card)",
        height=400, xaxis_title="", yaxis_title="Price (USD / card)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )

    # Flagship-era shaded backgrounds
    for (era_label, x0, x1, fill, tc, short) in FLAGSHIP_ERAS:
        fig_price.add_vrect(
            x0=x0, x1=x1, fillcolor=fill, line_width=0,
            annotation_text=short, annotation_position="top left",
            annotation=dict(font_size=10, font_color=tc, yshift=-14),
        )

    # Product GA vertical dashed lines
    for (mid, ga_date, label, col) in GA_MARKERS:
        fig_price.add_vline(
            x=ga_date, line_dash="dot", line_color=col, line_width=1.5,
            annotation_text=f"◆ {label}",
            annotation_position="top right",
            annotation=dict(font_size=9, font_color=col, textangle=-90, yshift=-10),
        )

    # Anchor x-axis to data
    if not df_curated.empty:
        _pr_end_dt = pd.to_datetime(df_curated["date"].max())
        _pr_rend   = (_pr_end_dt + pd.DateOffset(months=2)).strftime("%Y-%m-%d")
        _pr_rstart = (_pr_end_dt - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    else:
        _pr_rend   = _now_hkt().strftime("%Y-%m-%d")
        _pr_rstart = _range_start(1)
    fig_price.update_xaxes(
        type="date",
        rangeselector=_time_rangeselector(active_index=1),   # 3Y default
        range=[_pr_rstart, _pr_rend],
        rangeslider=dict(visible=False),
    )

    # ── FP16 TFLOPS vs Latest Price scatter ──────────────────────────────────
    # Use specs from GPU_ENTERPRISE_PRODUCTS.tflops_fp16_dense
    fig_perf = go.Figure()
    if not df_curated.empty:
        latest_price = (
            df_curated.sort_values("date")
            .groupby("model_id")[["price_usd", "name"]]
            .last()
            .reset_index()
        )
        for _, row in latest_price.iterrows():
            mid   = row["model_id"]
            prod  = GPU_ENTERPRISE_PRODUCTS.get(mid, {})
            tflops = prod.get("tflops_fp16_dense")
            if tflops is None or pd.isna(row["price_usd"]):
                continue
            col       = COLOR_BY_MODEL.get(mid, CHART_COLORS[0])
            prod_name = row["name"] if pd.notna(row.get("name", None)) else mid
            fig_perf.add_trace(go.Scatter(
                x=[row["price_usd"]], y=[tflops],
                mode="markers+text",
                name=prod_name,
                text=[prod_name],
                textposition="top center",
                textfont=dict(size=9),
                marker=dict(size=14, color=col, line=dict(width=1, color="#30363d")),
                hovertemplate=(
                    f"<b>{prod_name}</b><br>Latest price: $%{{x:,.0f}}<br>"
                    f"FP16 Dense: {tflops} TFLOPS<extra></extra>"
                ),
            ))
    fig_perf.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Enterprise GPU — FP16 Dense TFLOPS vs Latest Price",
        height=360, xaxis_title="Latest Contract Price (USD/card)",
        yaxis_title="FP16 Dense TFLOPS", showlegend=False,
    )

    # ── YoY price change table ─────────────────────────────────────────────────
    yoy_section = html.Span()
    if not df_curated.empty:
        latest_snap = (
            df_curated.sort_values("date")
            .groupby("model_id")
            .last()
            .reset_index()[["model_id", "date", "price_usd"]]
        )
        _cutoff_1y = (pd.Timestamp(_now_hkt()) - pd.DateOffset(months=12)).strftime("%Y-%m-%d")
        hist_1y = (
            df_curated[df_curated["date"] <= _cutoff_1y]
            .sort_values("date")
            .groupby("model_id")["price_usd"]
            .last()
            .rename("price_1y_ago")
        )
        yoy_df = (
            latest_snap
            .merge(df_curated[["model_id", "name"]].drop_duplicates("model_id"),
                   on="model_id", how="left")
            .merge(hist_1y, on="model_id", how="left")
        )
        yoy_df["YoY Δ"] = yoy_df.apply(
            lambda r: f"{(r['price_usd'] / r['price_1y_ago'] - 1) * 100:+.1f}%"
                      if pd.notna(r["price_1y_ago"]) and r["price_1y_ago"] > 0 else "—",
            axis=1,
        )
        yoy_df["Generation"] = yoy_df["model_id"].map({
            "A100-SXM4-80GB": "Ampere",
            "H100-SXM5-80GB": "Hopper",
            "H200-SXM-141GB": "Hopper+",
            "B200-SXM-192GB": "Blackwell",
            "MI300X-192GB":   "CDNA3 (AMD)",
        }).fillna("—")
        yoy_df["FP16 TFLOPS"] = yoy_df["model_id"].map(
            {mid: str(p.get("tflops_fp16_dense", "—"))
             for mid, p in GPU_ENTERPRISE_PRODUCTS.items()}
        ).fillna("—")
        yoy_df = yoy_df.rename(columns={
            "name": "Product", "date": "As of",
            "price_usd": "Latest Price (USD)", "price_1y_ago": "Price 1Y Ago (USD)",
        })
        yoy_df["Latest Price (USD)"] = yoy_df["Latest Price (USD)"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        yoy_df["Price 1Y Ago (USD)"] = yoy_df["Price 1Y Ago (USD)"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        yoy_df = yoy_df[[
            "Product", "Generation", "FP16 TFLOPS",
            "Latest Price (USD)", "Price 1Y Ago (USD)", "YoY Δ",
        ]]
        yoy_tbl = dash_table.DataTable(
            data=yoy_df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in yoy_df.columns],
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"backgroundColor": BG3, "color": TEXT,
                        "border": "1px solid #30363d",
                        "fontSize": "13px", "padding": "6px 10px"},
            style_header={"backgroundColor": BG2, "color": ACCENT,
                          "fontWeight": "600", "border": "1px solid #30363d"},
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": BG2},
                {"if": {"filter_query": '{YoY Δ} contains "+"', "column_id": "YoY Δ"},
                 "color": GREEN, "fontWeight": "600"},
                {"if": {"filter_query": '{YoY Δ} contains "-"', "column_id": "YoY Δ"},
                 "color": RED, "fontWeight": "600"},
            ],
        )
        yoy_section = _card([
            _section_title("Enterprise GPU — Latest Prices & Year-on-Year Change"),
            yoy_tbl,
        ])

    return html.Div([
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=fig_price, config={"displayModeBar": True})), width=7),
            dbc.Col(_card(dcc.Graph(figure=fig_perf,  config={"displayModeBar": True})), width=5),
        ]),
        yoy_section,
        _card(_source_footer(
            "NVIDIA / AMD Official Specs · TrendForce Enterprise GPU Channel Estimates · "
            "Goldman Sachs / Wells Fargo Semiconductor Research · Public Cloud GPU Spot Pricing",
            "Prices are estimated per-card contract/spot prices (USD). "
            "Not retail — enterprise GPUs are sold via OEM/cloud channels. "
            "FP16 Dense TFLOPS from official datasheets (no sparsity multiplier). "
            "Flagship eras: Ampere (A100) → Hopper (H100) → Hopper+ (H200) → Blackwell (B200). "
            "Update GPU_ENTERPRISE_PRODUCTS in products_config.py monthly.",
        )),
    ])


def _sc_enterprise_ram_section():
    """
    Enterprise / AI-accelerator HBM price index with:
    - HBM3 and HBM3E contract price history (USD/GB) with generation era shading
    - Key generation GA vertical annotations
    - Memory bandwidth (GB/s per stack) vs latest spot price scatter
    - YoY price change table
    - Consumer DRAM inline section below for context
    """
    df_all = sc_dram_query()
    df_hbm = df_all[df_all["product_type"].isin(["HBM3", "HBM3E"])].copy()

    # ── Generation era definitions ────────────────────────────────────────────
    HBM_ERAS = [
        ("HBM3 Era",  "2022-06-01", "2023-12-31", "rgba(0,113,197,0.07)",  "#0071C5", "HBM3"),
        ("HBM3E Era", "2024-01-01", "2026-07-31", "rgba(118,185,0,0.07)",  "#76b900", "HBM3E"),
    ]
    HBM_MARKERS = [
        ("2022-06-01", "HBM3 GA (SK Hynix)",    "#0071C5"),
        ("2024-01-01", "HBM3E GA (H100/MI300X)", "#76b900"),
    ]
    HBM_COLORS = {
        "HBM3":  "#0071C5",
        "HBM3E": "#76b900",
    }
    # Per-stack bandwidth: speed_mhz × 1024-bit interface / 8 / 1000 (→ GB/s)
    HBM_SPECS = {
        "HBM3":  {"bandwidth_gbs": 819,  "capacity_gb": 48, "config": "8-Hi"},
        "HBM3E": {"bandwidth_gbs": 1177, "capacity_gb": 96, "config": "12-Hi"},
    }

    # ── Price history line chart ──────────────────────────────────────────────
    fig_price = go.Figure()
    if not df_hbm.empty:
        df_hbm["period_dt"] = pd.to_datetime(df_hbm["period"] + "-01")
        for ptype, grp in df_hbm.groupby("product_type"):
            grp = grp.sort_values("period_dt")
            col = HBM_COLORS.get(ptype, CHART_COLORS[0])
            fig_price.add_trace(go.Scatter(
                x=grp["period_dt"], y=grp["price_usd"],
                name=ptype,
                mode="lines+markers",
                line=dict(width=2.5, color=col),
                marker=dict(size=5),
                hovertemplate=(
                    f"<b>{ptype}</b><br>%{{x|%b %Y}}<br>"
                    f"$%{{y:.2f}}/GB<extra></extra>"
                ),
            ))

    fig_price.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Enterprise RAM (HBM) — Estimated Contract Price (USD/GB)",
        height=400, xaxis_title="", yaxis_title="Contract Price (USD / GB)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )

    for (era_label, x0, x1, fill, tc, short) in HBM_ERAS:
        fig_price.add_vrect(
            x0=x0, x1=x1, fillcolor=fill, line_width=0,
            annotation_text=short, annotation_position="top left",
            annotation=dict(font_size=10, font_color=tc, yshift=-14),
        )
    for (ga_date, label, col) in HBM_MARKERS:
        fig_price.add_vline(
            x=ga_date, line_dash="dot", line_color=col, line_width=1.5,
            annotation_text=f"◆ {label}",
            annotation_position="top right",
            annotation=dict(font_size=9, font_color=col, textangle=-90, yshift=-10),
        )

    # Anchor to data end; default 3Y view (covers HBM3 → HBM3E transition)
    if not df_hbm.empty:
        _end_dt  = pd.to_datetime(df_hbm["period"].max() + "-01")
        _rend    = (_end_dt + pd.DateOffset(months=2)).strftime("%Y-%m-%d")
        _rstart  = (_end_dt - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    else:
        _rend   = _now_hkt().strftime("%Y-%m-%d")
        _rstart = _range_start(1)
    fig_price.update_xaxes(
        type="date",
        rangeselector=_time_rangeselector(active_index=1),   # 3Y default
        range=[_rstart, _rend],
        rangeslider=dict(visible=False),
    )

    # ── Bandwidth vs Latest Spot Price scatter ────────────────────────────────
    fig_perf = go.Figure()
    if not df_hbm.empty:
        latest_hbm = (df_hbm.sort_values("period")
                      .groupby("product_type")[["price_usd"]]
                      .last()
                      .reset_index())
        for _, row in latest_hbm.iterrows():
            ptype = row["product_type"]
            specs = HBM_SPECS.get(ptype)
            if specs is None or pd.isna(row["price_usd"]):
                continue
            col = HBM_COLORS.get(ptype, CHART_COLORS[0])
            bw  = specs["bandwidth_gbs"]
            cap = specs["capacity_gb"]
            cfg = specs["config"]
            fig_perf.add_trace(go.Scatter(
                x=[row["price_usd"]], y=[bw],
                mode="markers+text",
                name=ptype,
                text=[ptype],
                textposition="top center",
                textfont=dict(size=10),
                marker=dict(size=16, color=col, line=dict(width=1, color="#30363d")),
                hovertemplate=(
                    f"<b>{ptype} ({cfg})</b><br>Spot: $%{{x:.2f}}/GB<br>"
                    f"Bandwidth: {bw} GB/s per stack<br>"
                    f"Capacity: {cap} GB per stack<extra></extra>"
                ),
            ))
    fig_perf.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="HBM — Memory Bandwidth vs Spot Price",
        height=360,
        xaxis_title="Latest Contract Price (USD / GB)",
        yaxis_title="Memory Bandwidth (GB/s per stack)",
        showlegend=False,
    )

    # ── YoY price change table ────────────────────────────────────────────────
    yoy_section = html.Span()
    if not df_hbm.empty:
        latest_snap = (df_hbm.sort_values("period")
                       .groupby("product_type")
                       .last()
                       .reset_index()[["product_type", "period", "price_usd", "source"]])
        _cutoff_1y = (pd.Timestamp(_now_hkt()) - pd.DateOffset(months=12)).strftime("%Y-%m")
        prior_1y = (df_hbm[df_hbm["period"] <= _cutoff_1y]
                    .sort_values("period")
                    .groupby("product_type")["price_usd"]
                    .last()
                    .rename("price_1y_ago"))
        yoy_df = latest_snap.merge(prior_1y, on="product_type", how="left")
        yoy_df["YoY Δ"] = yoy_df.apply(
            lambda r: f"{(r['price_usd'] / r['price_1y_ago'] - 1) * 100:+.1f}%"
                      if pd.notna(r.get("price_1y_ago")) and r["price_1y_ago"] > 0 else "—",
            axis=1,
        )
        yoy_df["Bandwidth (GB/s)"] = yoy_df["product_type"].map(
            {k: str(v["bandwidth_gbs"]) for k, v in HBM_SPECS.items()}
        ).fillna("—")
        yoy_df["Capacity (GB)"] = yoy_df["product_type"].map(
            {k: str(v["capacity_gb"]) for k, v in HBM_SPECS.items()}
        ).fillna("—")
        yoy_df = yoy_df.rename(columns={
            "product_type": "Generation", "period": "As of",
            "price_usd": "Spot Price (USD/GB)", "price_1y_ago": "Price 1Y Ago (USD/GB)",
        })
        yoy_df["Spot Price (USD/GB)"]     = yoy_df["Spot Price (USD/GB)"].map(
            lambda x: f"${x:.2f}" if pd.notna(x) else "—")
        yoy_df["Price 1Y Ago (USD/GB)"]   = yoy_df["Price 1Y Ago (USD/GB)"].map(
            lambda x: f"${x:.2f}" if pd.notna(x) else "—")
        yoy_df = yoy_df[[
            "Generation", "Bandwidth (GB/s)", "Capacity (GB)",
            "Spot Price (USD/GB)", "Price 1Y Ago (USD/GB)", "YoY Δ", "source",
        ]]
        yoy_tbl = dash_table.DataTable(
            data=yoy_df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in yoy_df.columns],
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"backgroundColor": BG3, "color": TEXT,
                        "border": "1px solid #30363d",
                        "fontSize": "13px", "padding": "6px 10px"},
            style_header={"backgroundColor": BG2, "color": ACCENT,
                          "fontWeight": "600", "border": "1px solid #30363d"},
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": BG2},
                {"if": {"filter_query": '{YoY Δ} contains "+"', "column_id": "YoY Δ"},
                 "color": GREEN, "fontWeight": "600"},
                {"if": {"filter_query": '{YoY Δ} contains "-"', "column_id": "YoY Δ"},
                 "color": RED, "fontWeight": "600"},
            ],
        )
        yoy_section = _card([
            _section_title("HBM — Latest Contract Prices & Year-on-Year Change"),
            yoy_tbl,
        ])

    return html.Div([
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=fig_price, config={"displayModeBar": True})), width=7),
            dbc.Col(_card(dcc.Graph(figure=fig_perf,  config={"displayModeBar": True})), width=5),
        ]),
        yoy_section,
        _card(_source_footer(
            "TrendForce / DRAMeXchange · SK Hynix / Samsung / Micron Earnings Transcripts",
            "HBM3 8-Hi and HBM3E 12-Hi: estimated contract prices per GB of stack capacity (USD/GB). "
            "Sold exclusively to hyperscalers and AI chip OEMs (NVIDIA, AMD, Google, Microsoft). "
            "Bandwidth calculated from JEDEC spec: speed_MT/s × 1024-bit interface / 8. "
            "HBM3 era: Jun 2022 – Dec 2023 (SK Hynix primary, Samsung qualified Q4 2022). "
            "HBM3E era: Jan 2024 onward (12-Hi stack, 96 GB, first shipped in H200/MI300X). "
            "Update CURATED_DRAM_SPOT in products_config.py monthly.",
        )),
        html.Div(style={"marginTop": "8px"}),
        _sc_dram_inline(),   # consumer DDR4/DDR5 spot prices for context
    ])


def _sc_price_section(category: str):
    """Price Index + Estimated Delivery (in-stock) for one category."""
    df_pass    = sc_prices_query(category, source="passmark")
    df_new     = sc_prices_query(category, source="newegg")
    df_curated = sc_prices_query(category, source="curated")

    cat_label = {"GPU": "GPU", "GPU-Enterprise": "Enterprise GPU",
                 "CPU": "CPU", "RAM": "RAM Memory"}[category]
    COLOR_MAP = {
        "NVIDIA": "#76b900", "AMD": "#ED1C24", "Intel": "#0071C5",
        "Samsung": "#1428A0", "SK Hynix": "#F15A24", "Micron": "#E31837",
    }

    # ── Price history line chart — synced date range with DRAM panel ─────
    # Priority: PassMark historical > Curated (for RAM) > Newegg (bar, fallback)
    df_hist = df_pass if not df_pass.empty else df_curated
    fig_price = go.Figure()
    if not df_hist.empty:
        for i, (mid, grp) in enumerate(df_hist.groupby("model_id")):
            short = grp["name"].iloc[0] if "name" in grp.columns else mid
            col   = CHART_COLORS[i % len(CHART_COLORS)]
            fig_price.add_trace(go.Scatter(
                x=grp["date"], y=grp["price_usd"],
                name=short, mode="lines+markers",
                line=dict(width=2, color=col),
                hovertemplate=f"<b>{short}</b><br>Date: %{{x}}<br>Price: $%{{y:.0f}}<extra></extra>",
            ))
    elif not df_new.empty:
        latest = df_new.sort_values("date").groupby("model_id").last().reset_index()
        fig_price.add_trace(go.Bar(
            x=latest["name"] if "name" in latest else latest["model_id"],
            y=latest["price_usd"],
            marker_color=ACCENT,
            hovertemplate="<b>%{x}</b><br>Price: $%{y:.0f}<extra></extra>",
        ))
    fig_price.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title=f"{cat_label} — Price Index (USD)",
        height=360, xaxis_title="Date", yaxis_title="Retail Price (USD)",
    )
    # Anchor range to actual data end so the default 1Y view is not empty
    # when curated prices lag today.
    if not df_hist.empty:
        _pr_end_dt   = pd.to_datetime(df_hist["date"].max())
        _pr_rend     = (_pr_end_dt + pd.DateOffset(months=2)).strftime("%Y-%m-%d")
        _pr_rstart   = (_pr_end_dt - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    else:
        _pr_rend   = _now_hkt().strftime("%Y-%m-%d")
        _pr_rstart = _range_start(1)
    fig_price.update_xaxes(
        type="date",
        rangeselector=_time_rangeselector(active_index=0),   # 1Y default
        range=[_pr_rstart, _pr_rend],
        rangeslider=dict(visible=False),
    )

    # ── Performance / Price scatter ───────────────────────────────────────
    fig_pp = go.Figure()
    if category == "RAM":
        # RAM has no PassMark scores — show Speed (MHz) vs Latest Price scatter
        _pp_title    = f"{cat_label} — Speed vs Price (MHz / USD)"
        _pp_y_label  = "Speed (MHz)"
        # Get latest curated price per product
        _ram_latest: dict = {}
        if not df_curated.empty:
            _ram_grp = (df_curated.sort_values("date")
                        .groupby("model_id").last()
                        .reset_index())
            for _, _r in _ram_grp.iterrows():
                _ram_latest[_r["model_id"]] = float(_r["price_usd"])
        _type_color = {
            "DDR5":    CHART_COLORS[0],
            "DDR4":    CHART_COLORS[1],
            "HBM3E":   CHART_COLORS[2],
            "HBM3":    CHART_COLORS[3],
            "LPDDR5X": CHART_COLORS[4],
        }
        for i, (mid, prod) in enumerate(RAM_PRODUCTS.items()):
            speed = prod.get("speed_mhz")
            price = _ram_latest.get(mid) or prod.get("msrp_usd")
            if speed is None or price is None:
                continue  # skip HBM stacks with no retail price
            rtype = prod.get("type", "")
            col   = _type_color.get(rtype, CHART_COLORS[i % len(CHART_COLORS)])
            label = prod.get("name", mid)
            cap   = prod.get("capacity_gb", "?")
            fig_pp.add_trace(go.Scatter(
                x=[price], y=[speed],
                mode="markers+text",
                name=label,
                text=[label],
                textposition="top center",
                textfont=dict(size=9),
                marker=dict(size=12, color=col, line=dict(width=1, color="#30363d")),
                hovertemplate=(
                    f"<b>{label}</b><br>Price: $%{{x:.0f}}"
                    f"<br>Speed: %{{y:,}} MHz"
                    f"<br>Capacity: {cap} GB"
                    f"<br>Type: {rtype}<extra></extra>"
                ),
            ))
    else:
        _pp_title   = f"{cat_label} — Performance vs Price (PassMark Score / USD)"
        _pp_y_label = "PassMark Score"
        if not df_pass.empty:
            latest_pass = df_pass.dropna(subset=["passmark_score", "price_usd"])
            latest_pass = (latest_pass.sort_values("date")
                           .groupby("model_id").last()
                           .reset_index())
            if not latest_pass.empty:
                for i, row in latest_pass.iterrows():
                    brand = row.get("brand", "")
                    col   = COLOR_MAP.get(brand, CHART_COLORS[i % len(CHART_COLORS)])
                    fig_pp.add_trace(go.Scatter(
                        x=[row["price_usd"]], y=[row["passmark_score"]],
                        mode="markers+text",
                        name=row.get("name", row["model_id"]),
                        text=[row.get("name", row["model_id"])],
                        textposition="top center",
                        textfont=dict(size=9),
                        marker=dict(size=12, color=col, line=dict(width=1, color="#30363d")),
                        hovertemplate=(
                            f"<b>%{{text}}</b><br>Price: $%{{x:.0f}}"
                            f"<br>Score: %{{y:,.0f}}<extra></extra>"
                        ),
                    ))
    fig_pp.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title=_pp_title,
        height=320, xaxis_title="Retail Price (USD)",
        yaxis_title=_pp_y_label, showlegend=False,
    )

    # ── Latest Prices & Year-on-Year Change table ─────────────────────────
    yoy_section = html.Span()   # empty by default; skipped for RAM (DRAM inline section serves this role)
    if category != "RAM" and not df_hist.empty:
        # Latest price per product and price ~12 months prior
        latest_snap = (df_hist.sort_values("date")
                       .groupby("model_id")
                       .last()
                       .reset_index()[["model_id", "date", "price_usd"]])
        _cutoff_1y = (pd.Timestamp(_now_hkt()) - pd.DateOffset(months=12)).strftime("%Y-%m-%d")
        hist_1y = (df_hist[df_hist["date"] <= _cutoff_1y]
                   .sort_values("date")
                   .groupby("model_id")["price_usd"]
                   .last()
                   .rename("price_1y_ago"))
        yoy_df = latest_snap.merge(
            df_hist[["model_id", "name"]].drop_duplicates("model_id"),
            on="model_id", how="left",
        ).merge(hist_1y, on="model_id", how="left")
        yoy_df["YoY Δ"] = yoy_df.apply(
            lambda r: f"{(r['price_usd'] / r['price_1y_ago'] - 1) * 100:+.1f}%"
                      if pd.notna(r["price_1y_ago"]) and r["price_1y_ago"] > 0 else "—",
            axis=1,
        )
        yoy_df = yoy_df.rename(columns={
            "name": "Product", "date": "As of",
            "price_usd": "Latest Price (USD)", "price_1y_ago": "Price 1Y Ago (USD)",
        })
        yoy_df["Latest Price (USD)"] = yoy_df["Latest Price (USD)"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        yoy_df["Price 1Y Ago (USD)"] = yoy_df["Price 1Y Ago (USD)"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        yoy_df = yoy_df[["Product", "As of", "Latest Price (USD)",
                          "Price 1Y Ago (USD)", "YoY Δ"]]
        yoy_tbl = dash_table.DataTable(
            data=yoy_df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in yoy_df.columns],
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"backgroundColor": BG3, "color": TEXT,
                        "border": "1px solid #30363d",
                        "fontSize": "13px", "padding": "6px 10px"},
            style_header={"backgroundColor": BG2, "color": ACCENT,
                          "fontWeight": "600", "border": "1px solid #30363d"},
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": BG2},
                {"if": {"filter_query": '{YoY Δ} contains "+"', "column_id": "YoY Δ"},
                 "color": GREEN, "fontWeight": "600"},
                {"if": {"filter_query": '{YoY Δ} contains "-"', "column_id": "YoY Δ"},
                 "color": RED, "fontWeight": "600"},
            ],
        )
        yoy_section = _card([
            _section_title(f"{cat_label} — Latest Prices & Year-on-Year Change"),
            yoy_tbl,
        ])

    # ── In-stock / Estimated Delivery table (Newegg) ─────────────────────
    delivery_section = html.Span()  # hidden if no Newegg data
    if not df_new.empty:
        latest_new = df_new.sort_values("date").groupby("model_id").last().reset_index()
        latest_new["Status"]  = latest_new["in_stock"].map(
            {1: "✅ In Stock", 0: "❌ Out of Stock"}).fillna("❓ Unknown")
        latest_new["Price"]   = latest_new["price_usd"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        tbl_df = latest_new[["name", "Price", "Status", "date"]].rename(
            columns={"name": "Product", "date": "Checked"})
        tbl = dash_table.DataTable(
            data=tbl_df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in tbl_df.columns],
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                        "fontSize": "13px", "padding": "6px 10px"},
            style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                          "border": "1px solid #30363d"},
            style_data_conditional=[
                {"if": {"filter_query": '{Status} contains "In Stock"'}, "color": GREEN},
                {"if": {"filter_query": '{Status} contains "Out of Stock"'}, "color": RED},
            ],
        )
        delivery_section = _card([
            _section_title(f"Estimated Delivery — {cat_label} (Newegg Stock Status)"),
            tbl,
        ])

    # ── For RAM: embed DRAM & HBM spot prices inline (expanded height) ───
    dram_section = html.Span()
    if category == "RAM":
        dram_section = _sc_dram_inline(height=500)

    return html.Div([
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=fig_price, config={"displayModeBar": True})), width=7),
            dbc.Col(_card(dcc.Graph(figure=fig_pp,    config={"displayModeBar": True})), width=5),
        ]),
        yoy_section,
        dram_section,
        delivery_section,
        _card(_source_footer(
            "PassMark Performance Test / Newegg / TrendForce / Curated Market Data",
            "Price history: PassMark benchmark database (GPU/CPU) or curated retail pricing. "
            "YoY: latest vs same month prior year. "
            "Performance/Price scatter: PassMark Score vs retail USD. "
            "Stock status: Newegg live listing. "
            "Run supply_chain_crawler.py to refresh.",
        )),
    ])


# ── Steam HW Survey (Sales Volume proxy) ─────────────────────────────────────

def _sc_steam_panel():
    df = sc_steam_query()

    if df.empty:
        return _card([
            _section_title("Sales Volume — GPU Market Share (Steam Hardware Survey)"),
            html.P("No Steam survey data yet. Run: python supply_chain_crawler.py",
                   style={"color": SUBTEXT, "fontSize": "12px"}),
        ])

    # Top 20 GPUs by share
    top = df.head(20).copy()
    top["vendor"] = top["model_name"].apply(
        lambda x: "NVIDIA" if "NVIDIA" in x.upper() or "RTX" in x.upper() or "GTX" in x.upper()
        else ("AMD" if "AMD" in x.upper() or "RADEON" in x.upper() or "RX " in x.upper()
              else ("Intel" if "INTEL" in x.upper() or "ARC" in x.upper() else "Other"))
    )
    color_map = {"NVIDIA": "#76b900", "AMD": "#ED1C24", "Intel": "#0071C5", "Other": SUBTEXT}

    fig = go.Figure(go.Bar(
        x=top["share_pct"],
        y=top["model_name"],
        orientation="h",
        marker_color=[color_map.get(v, SUBTEXT) for v in top["vendor"]],
        hovertemplate="<b>%{y}</b><br>Market Share: %{x:.2f}%<extra></extra>",
    ))
    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title=f"GPU Installed-Base Market Share — Steam HW Survey ({top['period'].iloc[0]})",
        height=480, xaxis_title="% of Steam Users",
        showlegend=False,
    )
    fig.update_yaxes(autorange="reversed")

    # Vendor pie
    vendor_agg = (
        df.assign(vendor=df["model_name"].apply(
            lambda x: "NVIDIA" if "NVIDIA" in x.upper() or "RTX" in x.upper() or "GTX" in x.upper()
            else ("AMD" if "AMD" in x.upper() or "RX " in x.upper() else "Other")
        )).groupby("vendor")["share_pct"].sum().reset_index()
    )
    fig_pie = go.Figure(go.Pie(
        labels=vendor_agg["vendor"],
        values=vendor_agg["share_pct"].round(1),
        marker_colors=["#76b900", "#ED1C24", SUBTEXT],
        hole=0.45,
        hovertemplate="<b>%{label}</b>: %{value:.1f}%<extra></extra>",
    ))
    fig_pie.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="GPU Vendor Share", height=300)

    return _card([
        _section_title("Sales Volume — GPU Market Share (Steam Hardware Survey)"),
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig,     config={"displayModeBar": False}), width=8),
            dbc.Col(dcc.Graph(figure=fig_pie, config={"displayModeBar": False}), width=4),
        ]),
        html.P(
            "Note: Steam survey reflects the installed base of active gamers, not monthly units shipped. "
            "Use as a relative market share proxy; absolute sales volumes require IDC/Mercury Research data.",
            style={"color": SUBTEXT, "fontSize": "11px", "marginTop": "8px"},
        ),
        _source_footer("Valve / Steam Hardware Survey",
                       "Monthly survey of ~120M active Steam users. Reflects installed base, not shipment volumes."),
    ])


# ── SEMI Book-to-Bill (Order Volume) ─────────────────────────────────────────

def _sc_btb_panel():
    df = sc_btb_query()

    if df.empty:
        return _card([
            _section_title("Order Volume — SEMI NA Equipment Book-to-Bill"),
            html.P("No B2B data. Run: python supply_chain_crawler.py",
                   style={"color": SUBTEXT, "fontSize": "12px"}),
        ])

    df["btb_ratio"] = pd.to_numeric(df["btb_ratio"], errors="coerce")
    df = df.sort_values("period")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["period"], y=df["btb_ratio"],
        mode="lines+markers",
        line=dict(width=2, color=ACCENT),
        marker=dict(size=7, color=[
            GREEN if v >= 1.0 else RED for v in df["btb_ratio"]
        ]),
        hovertemplate="<b>%{x}</b><br>B2B Ratio: %{y:.2f}<extra></extra>",
        name="B2B Ratio",
    ))
    fig.add_hline(y=1.0, line_dash="dash", line_color=YELLOW, line_width=1.5,
                  annotation_text="Neutral (1.00)", annotation_position="right")
    # Shaded zones
    fig.add_hrect(y0=1.0, y1=2.0, fillcolor=GREEN, opacity=0.05, line_width=0,
                  annotation_text="Orders > Billings (Demand expanding)",
                  annotation_font_size=10, annotation_font_color=GREEN)
    fig.add_hrect(y0=0.0, y1=1.0, fillcolor=RED, opacity=0.05, line_width=0,
                  annotation_text="Billings > Orders (Demand contracting)",
                  annotation_font_size=10, annotation_font_color=RED)
    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Order Volume — SEMI North America Equipment Book-to-Bill Ratio",
        height=320, xaxis_title="Month", yaxis_title="B2B Ratio",
    )
    fig.update_yaxes(range=[0.7, max(df["btb_ratio"].max() * 1.1, 1.4)])

    # Latest value KPI
    latest = df.iloc[-1]
    kpi_color = GREEN if latest["btb_ratio"] >= 1.0 else RED
    kpi = _kpi(
        f"Latest B2B  ({latest['period']})",
        f"{latest['btb_ratio']:.2f}",
        "Orders > Billings" if latest["btb_ratio"] >= 1 else "Billings > Orders",
        kpi_color,
    )

    return _card([
        _section_title("Order Volume — SEMI NA Equipment Book-to-Bill"),
        dbc.Row([
            dbc.Col(_card(kpi, style={"textAlign": "center"}), width=2),
            dbc.Col(dcc.Graph(figure=fig, config={"displayModeBar": True}), width=10),
        ]),
        html.P(
            "SEMI NA Equipment B2B > 1.0 indicates semiconductor equipment orders are outpacing billings — "
            "a leading indicator that fabs are investing in capacity expansion. "
            "Typically leads fab utilisation by 6–18 months.",
            style={"color": SUBTEXT, "fontSize": "11px", "marginTop": "8px"},
        ),
        _source_footer("SEMI (Semiconductor Equipment & Materials International)",
                       "North America Equipment Book-to-Bill Report. Published monthly. "
                       "Update CURATED_SEMI_BTB in products_config.py each month."),
    ])


# ── Manufacturer Capacity & Occupancy ────────────────────────────────────────

def _sc_capacity_panel():
    df = sc_capacity_query()

    if df.empty:
        return _card([
            _section_title("Manufacturer Capacity & Occupancy"),
            html.P("No capacity data. Run: python supply_chain_crawler.py",
                   style={"color": SUBTEXT, "fontSize": "12px"}),
        ])

    df["utilisation_pct"] = pd.to_numeric(df["utilisation_pct"], errors="coerce")
    df["capacity_kwpm"]   = pd.to_numeric(df["capacity_kwpm"],   errors="coerce")

    COMPANIES = ["TSMC", "Samsung", "SK Hynix", "Micron", "Intel"]
    CO_COLORS  = {
        "TSMC": "#00A3E0", "Samsung": "#1428A0", "SK Hynix": "#F15A24",
        "Micron": "#E31837", "Intel": "#0071C5",
    }

    # ── Utilisation trend by company ─────────────────────────────────────
    fig_util = go.Figure()
    for company in COMPANIES:
        sub = df[df["company"] == company].sort_values("period")
        if sub.empty:
            continue
        # Average utilisation per quarter across all segments
        avg = sub.groupby("period")["utilisation_pct"].mean().reset_index()
        fig_util.add_trace(go.Scatter(
            x=avg["period"], y=avg["utilisation_pct"],
            name=company, mode="lines+markers",
            line=dict(width=2, color=CO_COLORS.get(company, ACCENT)),
            hovertemplate=f"<b>{company}</b><br>%{{x}}<br>Avg Util: %{{y:.0f}}%<extra></extra>",
        ))
    fig_util.add_hline(y=80, line_dash="dot", line_color=YELLOW, line_width=1,
                       annotation_text="Healthy (80%)", annotation_position="right")
    fig_util.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Manufacturer Occupancy — Average Fab Utilisation by Company (%)",
        height=360, xaxis_title="Quarter", yaxis_title="Utilisation (%)",
    )
    fig_util.update_yaxes(range=[40, 105])

    # ── Latest utilisation gauge cards ────────────────────────────────────
    gauge_figs = []
    for company in COMPANIES:
        sub = df[df["company"] == company].sort_values("period")
        if sub.empty:
            continue
        latest_util = sub.groupby("period")["utilisation_pct"].mean().iloc[-1]
        period      = sub["period"].iloc[-1]
        col         = GREEN if latest_util >= 80 else YELLOW if latest_util >= 60 else RED

        fig_g = go.Figure(go.Indicator(
            mode="gauge+number",
            value=latest_util,
            number={"suffix": "%", "font": {"color": col, "size": 22}},
            gauge=dict(
                axis=dict(range=[0, 100], tickcolor=SUBTEXT),
                bar=dict(color=col),
                bgcolor=BG3,
                bordercolor="#30363d",
                steps=[
                    {"range": [0,  60], "color": "#2d1b1b"},
                    {"range": [60, 80], "color": "#2d2a1b"},
                    {"range": [80, 100],"color": "#1b2d1b"},
                ],
                threshold=dict(line=dict(color=YELLOW, width=2), thickness=0.75, value=80),
            ),
            title={"text": f"<b>{company}</b><br><span style='font-size:10px;color:{SUBTEXT}'>"
                           f"{period}</span>",
                   "font": {"color": TEXT, "size": 13}},
        ))
        fig_g.update_layout(
            paper_bgcolor=BG2, plot_bgcolor=BG2,
            margin=dict(l=15, r=15, t=60, b=10),
            height=200,
        )
        gauge_figs.append(dbc.Col(
            _card(dcc.Graph(figure=fig_g, config={"displayModeBar": False})),
            width=12 // min(len(COMPANIES), 5) or 2,
        ))

    # ── Capacity bar chart (wafers per month) ─────────────────────────────
    fig_cap = go.Figure()
    latest_cap = df.sort_values("period").groupby(["company", "product_type"]).last().reset_index()
    for company in COMPANIES:
        sub = latest_cap[latest_cap["company"] == company]
        if sub.empty:
            continue
        fig_cap.add_trace(go.Bar(
            name=company,
            x=sub["product_type"],
            y=sub["capacity_kwpm"],
            marker_color=CO_COLORS.get(company, ACCENT),
            hovertemplate=f"<b>{company}</b><br>%{{x}}<br>Capacity: %{{y:.0f}}k wpm<extra></extra>",
        ))
    fig_cap.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Manufacturer Capacity — Latest Quarter (1,000s of 300mm-eq wafers/month)",
        height=320, barmode="group", xaxis_title="Segment",
        yaxis_title="Capacity (k wpm)",
    )
    fig_cap.update_xaxes(tickangle=-20)

    # ── Detailed data table ───────────────────────────────────────────────
    tbl_df = df[["company", "segment", "product_type", "period",
                 "capacity_kwpm", "utilisation_pct", "notes"]].copy()
    tbl_df = tbl_df.sort_values(["company", "period"])
    tbl_df["utilisation_pct"] = tbl_df["utilisation_pct"].map(
        lambda x: f"{x:.0f}%" if pd.notna(x) else "—")
    tbl_df["capacity_kwpm"]   = tbl_df["capacity_kwpm"].map(
        lambda x: f"{x:.0f}k" if pd.notna(x) else "—")
    tbl_df.columns = ["Company", "Segment", "Product", "Period",
                      "Capacity (k wpm)", "Utilisation", "Notes"]
    tbl = dash_table.DataTable(
        data=tbl_df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in tbl_df.columns],
        sort_action="native",
        filter_action="native",
        page_size=12,
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "12px", "padding": "5px 8px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": BG2}],
    )

    return html.Div([
        _card([
            _section_title("Manufacturer Capacity & Occupancy"),
            dbc.Row(gauge_figs, className="g-2"),
        ]),
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=fig_util, config={"displayModeBar": True})), width=7),
            dbc.Col(_card(dcc.Graph(figure=fig_cap,  config={"displayModeBar": False})), width=5),
        ]),
        _card([
            _section_title("Capacity Detail (from Earnings Calls)"),
            tbl,
            _source_footer("TSMC / Samsung / SK Hynix / Micron / Intel — Quarterly Earnings Transcripts",
                           "Update CURATED_CAPACITY in products_config.py each quarter."),
        ]),
    ])


# ── DRAM Spot Prices ──────────────────────────────────────────────────────────

def _sc_dram_panel():
    df = sc_dram_query()

    if df.empty:
        return _card([
            _section_title("RAM Memory — DRAM & HBM Spot Prices"),
            html.P("No DRAM data. Run: python supply_chain_crawler.py",
                   style={"color": SUBTEXT, "fontSize": "12px"}),
        ])

    df["price_usd"] = pd.to_numeric(df["price_usd"], errors="coerce")
    df = df.sort_values("period")

    DRAM_COLORS = {
        "DDR4": "#74C0FC", "DDR5": "#51CF66", "HBM3E": "#FF6B6B",
        "HBM3": "#CC5DE8", "LPDDR5X": "#FFD43B",
    }
    _UNIT_LABEL = {
        "DDR4": "$/die", "DDR5": "$/die",
        "HBM3": "$/GB",  "HBM3E": "$/GB",
        "LPDDR5X": "$/die",
    }

    fig = go.Figure()
    for ptype, grp in df.groupby("product_type"):
        unit = _UNIT_LABEL.get(ptype, "USD")
        for spec, sub in grp.groupby("spec_label"):
            fig.add_trace(go.Scatter(
                x=sub["period"], y=sub["price_usd"],
                name=f"{ptype} — {spec}",
                mode="lines+markers",
                line=dict(width=2, color=DRAM_COLORS.get(ptype, ACCENT)),
                hovertemplate=(
                    f"<b>{ptype}</b> {spec}<br>"
                    f"%{{x}}<br>${{y:.2f}} {unit}<extra></extra>"
                ),
            ))

    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="RAM Memory — DRAM & HBM Spot / Contract Prices — DDR4/DDR5 (USD/die) · HBM3E (USD/GB)",
        height=380, xaxis_title="Month", yaxis_title="Price (USD)",
    )

    # YoY delta table
    latest = df.sort_values("period").groupby(["product_type", "spec_label"]).last()
    prior  = df[df["period"] <= (pd.to_datetime(df["period"].max()) - pd.DateOffset(months=12))
                .strftime("%Y-%m")].groupby(["product_type", "spec_label"])["price_usd"].last()
    rows_tbl = []
    for idx, row in latest.iterrows():
        p_now  = row["price_usd"]
        p_prev = prior.get(idx)
        yoy    = ((p_now / p_prev - 1) * 100) if p_prev and p_prev > 0 else None
        rows_tbl.append({
            "Type": idx[0], "Spec": idx[1], "Period": row["period"],
            "Price (USD)": f"${p_now:.2f}",
            "YoY Δ": f"{yoy:+.1f}%" if yoy is not None else "—",
            "Source": row.get("source", ""),
        })
    tbl_df = pd.DataFrame(rows_tbl)
    tbl = dash_table.DataTable(
        data=tbl_df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in tbl_df.columns],
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=[
            {"if": {"filter_query": '{YoY Δ} contains "+"'}, "color": GREEN},
            {"if": {"filter_query": '{YoY Δ} contains "-"'}, "color": RED},
            {"if": {"row_index": "odd"}, "backgroundColor": BG2},
        ],
    )

    return _card([
        _section_title("RAM Memory — DRAM & HBM Spot Prices"),
        html.P(
            "DDR4 (8Gb die) and DDR5 (16Gb die) prices are quoted in USD per benchmark die. "
            "HBM3E is quoted in USD per GB of stack capacity — a hyperscaler contract price "
            "driven by AI accelerator demand (NVIDIA H100/H200/B200). "
            "⚠ The two series use different units; compare trends within a series, "
            "not absolute levels across series.",
            style={"color": SUBTEXT, "fontSize": "12px", "marginBottom": "10px"},
        ),
        dcc.Graph(figure=fig, config={"displayModeBar": True}),
        html.Div(style={"marginTop": "12px"}),
        _section_title("Latest Prices & Year-on-Year Change"),
        tbl,
        _source_footer("TrendForce / DRAMeXchange",
                       "DDR4 8Gb 1Gx8 & DDR5 16Gb 2Gx8: weekly spot benchmark die price (USD/die). "
                       "HBM3E 12-Hi: estimated contract price per GB of stack capacity (USD/GB). "
                       "Update CURATED_DRAM_SPOT in products_config.py monthly."),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# FLASK / RELAY ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

import os
import json
import hashlib
import hmac
from flask import request as flask_request, jsonify

# API key for the IBKR relay — set RELAY_API_KEY env var on the cloud host.
# The same key must be set in ibkr_relay.py on your local machine.
_RELAY_API_KEY = os.environ.get("RELAY_API_KEY", "")


@server.route("/health")
def health():
    """Health-check endpoint used by Railway / Render / Fly.io uptime probes."""
    return jsonify({"status": "ok", "db": os.path.exists(DB_PATH)}), 200


@server.route("/api/upload-iv", methods=["POST"])
def upload_iv():
    """
    Relay endpoint: receives IV snapshots POSTed by ibkr_relay.py running locally.

    Expected JSON body:
    {
      "snapshots": [
        {
          "ticker": "NVDA",
          "iv_current": 0.52,
          "iv_1m_avg": 0.48,
          "iv_1q_avg": 0.50,
          "iv_6m_avg": 0.47,
          "iv_1y_avg": 0.45,
          "iv_pct_vs_1y": 72.0,
          "iv_52w_high": 0.75,
          "iv_52w_low": 0.28,
          "as_of": "2025-03-15T10:30:00"
        },
        ...
      ]
    }
    """
    # ── Auth ──────────────────────────────────────────────────────────────────
    if _RELAY_API_KEY:
        auth = flask_request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(auth, _RELAY_API_KEY):
            return jsonify({"error": "Unauthorized"}), 401

    # ── Parse ─────────────────────────────────────────────────────────────────
    try:
        payload = flask_request.get_json(force=True)
        snapshots = payload.get("snapshots", [])
    except Exception as e:
        return jsonify({"error": f"Bad JSON: {e}"}), 400

    if not snapshots:
        return jsonify({"error": "Empty snapshots list"}), 400

    # ── Store ─────────────────────────────────────────────────────────────────
    try:
        conn = get_conn()
        # Ensure IBKR tables exist (first upload may precede any local ibkr crawl)
        try:
            init_ibkr_tables(conn)
        except Exception:
            pass

        now_str = _now_hkt().strftime("%Y-%m-%d")
        cur = conn.cursor()
        for s in snapshots:
            ticker        = s.get("ticker", "")
            snapshot_date = (s.get("as_of") or now_str)[:10]   # accept either key; take date part only
            cur.execute("""
                INSERT OR REPLACE INTO options_iv
                    (ticker, snapshot_date, iv_current, iv_1m_avg, iv_1q_avg, iv_6m_avg,
                     iv_1y_avg, iv_pct_vs_1y, iv_52w_high, iv_52w_low, source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                ticker,
                snapshot_date,
                s.get("iv_current"),
                s.get("iv_1m_avg"),
                s.get("iv_1q_avg"),
                s.get("iv_6m_avg"),
                s.get("iv_1y_avg"),
                s.get("iv_pct_vs_1y"),
                s.get("iv_52w_high"),
                s.get("iv_52w_low"),
                "relay",
            ))
        conn.commit()
        conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok", "stored": len(snapshots)}), 200


@server.route("/api/db-stats")
def db_stats():
    """Return row counts for all key tables — useful for monitoring crawl health."""
    auth = flask_request.headers.get("X-API-Key", "")
    if _RELAY_API_KEY and not hmac.compare_digest(auth, _RELAY_API_KEY):
        return jsonify({"error": "Unauthorized"}), 401

    tables = [
        "daily_prices", "quarterly_financials", "market_sentiment",
        "cycle_analysis", "company_info", "crawl_runs",
        "sc_prices", "sc_market_share", "sc_semi_btb",
        "sc_dram_spot", "sc_capacity", "options_iv",
    ]
    stats = {}
    try:
        conn = get_conn()
        for t in tables:
            try:
                stats[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception:
                stats[t] = "table missing"
        # Last crawl info
        try:
            row = conn.execute(
                "SELECT started_at, finished_at, status, tickers_ok "
                "FROM crawl_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            stats["last_crawl"] = dict(zip(
                ["started_at", "finished_at", "status", "tickers_ok"], row
            )) if row else None
        except Exception:
            stats["last_crawl"] = None
        conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(stats), 200


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print(f"⚠️  Database not found at '{DB_PATH}'.")
        print("   Run  python crawler.py --quick  first to fetch data.\n")

    print(f"🚀  Dashboard running → http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False)
