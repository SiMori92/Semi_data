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

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, dash_table
from plotly.subplots import make_subplots

# Supply-chain product lists (for grouping in SC tab)
from products_config import GPU_PRODUCTS, CPU_PRODUCTS, RAM_PRODUCTS

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
        return dt.strftime("%d %b %Y  %H:%M UTC")
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
                # ── IBKR connection badge ──────────────────────────────────
                html.Span(id="ibkr-status-badge", style={"marginLeft": "20px"}),
                dbc.Button("🔄 Refresh Data", id="btn-refresh", color="primary",
                           size="sm", style={"marginLeft": "16px", "fontSize": "12px"}),
            ], style={"display": "flex", "alignItems": "center"}),
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
                start_date=(datetime.today() - timedelta(days=365)).strftime("%Y-%m-%d"),
                end_date=datetime.today().strftime("%Y-%m-%d"),
                display_format="DD MMM YYYY",
                style={"fontSize": "12px", "width": "100%"},
            ),
            html.Hr(style={"borderColor": "#30363d", "margin": "12px 0"}),

            ticker_checklist(
                "Semi Companies",
                SEMI_COMPANIES,
                ["NVDA", "AMD", "ASML", "AVGO", "QCOM", "MU", "TSM", "INTC"],
            ),
            ticker_checklist("Semi ETFs",   SEMI_ETFS,   ["SMH"]),
            ticker_checklist("Macro / Other",
                ["TQQQ", "VIX", "USD", "10YTreasury", "Gold", "BTC", "ETH"],
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
                "NVDA", "AMD", "ASML", "AVGO", "QCOM", "MU", "TSM", "INTC", "SMH", "VIX", "10YTreasury"
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
            ["TQQQ", "VIX", "USD", "10YTreasury", "Gold", "BTC", "ETH"],
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
    end   = end_date[:10]   if end_date   else datetime.today().strftime("%Y-%m-%d")

    if active_tab == "tab-overview":
        return tab_overview(tickers, start, end)
    elif active_tab == "tab-financials":
        return tab_financials(tickers)
    elif active_tab == "tab-sentiment":
        return tab_sentiment(tickers)
    elif active_tab == "tab-cycles":
        return tab_cycles(tickers)
    elif active_tab == "tab-compare":
        return tab_compare(tickers)
    elif active_tab == "tab-supplychain":
        return tab_supply_chain()
    return html.Div("Select a tab.")


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

    # ── Normalised price chart (base 100) ─────────────────────────────────
    fig_price = go.Figure()
    for i, tkr in enumerate(tickers):
        df = prices[prices["ticker"] == tkr].sort_values("date")
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
        ))
    fig_price.update_layout(**PLOTLY_TEMPLATE["layout"],
                             title="Price Performance (Base=100)", height=400,
                             hovermode="x unified")

    # ── Volume bar chart (latest 60 days, selected tickers) ───────────────
    fig_vol = go.Figure()
    cutoff  = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d")
    for i, tkr in enumerate(tickers[:8]):   # limit to 8 for readability
        df = prices[(prices["ticker"] == tkr) & (prices["date"] >= cutoff)].sort_values("date")
        if df.empty:
            continue
        fig_vol.add_trace(go.Bar(
            x=df["date"], y=df["volume"], name=tkr,
            marker_color=CHART_COLORS[i % len(CHART_COLORS)],
            hovertemplate=f"<b>{tkr}</b><br>%{{x}}<br>Vol: %{{y:,.0f}}<extra></extra>",
        ))
    fig_vol.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="Trading Volume (last 60 days)", height=280,
                           barmode="overlay", bargap=0.1)

    # ── Performance heatmap ───────────────────────────────────────────────
    if not sent.empty:
        cols_perf = ["perf_5d", "perf_10d", "perf_1m"]
        hm_data = sent[["ticker"] + cols_perf].set_index("ticker")
        hm_data = hm_data.apply(pd.to_numeric, errors="coerce")
        fig_hm = go.Figure(go.Heatmap(
            z=hm_data.values,
            x=["5-Day %", "10-Day %", "1-Month %"],
            y=hm_data.index.tolist(),
            colorscale=[[0, RED], [0.5, BG3], [1, GREEN]],
            zmid=0,
            text=hm_data.round(1).astype(str).values + "%",
            texttemplate="%{text}",
            hovertemplate="<b>%{y}</b><br>%{x}: %{z:.2f}%<extra></extra>",
        ))
        fig_hm.update_layout(**PLOTLY_TEMPLATE["layout"],
                              title="Return Heatmap", height=max(250, len(tickers)*28))
        heatmap_section = dcc.Graph(figure=fig_hm, config={"displayModeBar": False})
    else:
        heatmap_section = html.P("Sentiment data not yet available.", style={"color": SUBTEXT})

    return html.Div([
        dbc.Row(kpi_cards, className="g-2", style={"marginBottom": "12px"}),
        _card(dcc.Graph(figure=fig_price, config={"displayModeBar": True})),
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=fig_vol, config={"displayModeBar": False})), width=7),
            dbc.Col(_card(heatmap_section), width=5),
        ]),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — FINANCIALS
# ══════════════════════════════════════════════════════════════════════════════

def tab_financials(tickers):
    df = financials_data(tickers)
    if df.empty:
        return _card(html.P("No quarterly financial data. Run crawler.py — financials are only available for listed companies.", style={"color": SUBTEXT}))

    df["period_end"] = pd.to_datetime(df["period_end"])
    df = df.sort_values("period_end")

    def metric_chart(col: str, title: str, pct: bool = False, yformat: str = "$,.0f"):
        fig = go.Figure()
        for i, tkr in enumerate(tickers):
            sub = df[df["ticker"] == tkr].dropna(subset=[col])
            if sub.empty:
                continue
            vals = sub[col] / 1e9 if not pct else sub[col]
            fig.add_trace(go.Bar(
                x=sub["period_end"].dt.strftime("%Y-Q%q"),
                y=vals, name=tkr,
                marker_color=CHART_COLORS[i % len(CHART_COLORS)],
                hovertemplate=f"<b>{tkr}</b><br>%{{x}}<br>{title}: %{{y:{',.1f' if pct else ',.2f'}}}" +
                              ("%" if pct else "B") + "<extra></extra>",
            ))
        suffix = "%" if pct else " (USD Billions)"
        fig.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title=title + suffix, barmode="group",
                           height=320, yaxis_title=title)
        return dcc.Graph(figure=fig, config={"displayModeBar": False})

    def trend_chart(col: str, title: str, pct: bool = False):
        fig = go.Figure()
        for i, tkr in enumerate(tickers):
            sub = df[df["ticker"] == tkr].dropna(subset=[col])
            if sub.empty:
                continue
            vals = sub[col]
            fig.add_trace(go.Scatter(
                x=sub["period_end"].dt.strftime("%Y-Q%q"),
                y=vals, name=tkr, mode="lines+markers",
                line=dict(width=2, color=CHART_COLORS[i % len(CHART_COLORS)]),
                hovertemplate=f"<b>{tkr}</b><br>%{{x}}<br>{title}: %{{y:.2f}}{'%' if pct else ''}<extra></extra>",
            ))
        fig.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title=title + (" (%)" if pct else ""),
                           height=280)
        return dcc.Graph(figure=fig, config={"displayModeBar": False})

    # Latest financials table
    latest_cols = ["ticker", "period_end", "revenue", "gross_margin",
                   "op_margin", "net_margin", "pe_ratio", "eps", "market_cap"]
    latest = df.sort_values("period_end").groupby("ticker").last().reset_index()
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
            title="Daily Implied Volatility History — 1 Year (IBKR)",
            height=340, xaxis_title="Date", yaxis_title="IV (%)",
            hovermode="x unified",
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
        iv_df  = sent.dropna(subset=["implied_volatility"]) if not sent.empty else pd.DataFrame()
        fig_iv = go.Figure()
        if not iv_df.empty:
            fig_iv.add_trace(go.Bar(
                x=iv_df["ticker"],
                y=iv_df["implied_volatility"],
                marker_color=[
                    RED if v > 60 else YELLOW if v > 30 else GREEN
                    for v in iv_df["implied_volatility"]
                ],
                hovertemplate="<b>%{x}</b><br>IV (ATM est.): %{y:.1f}%<extra></extra>",
            ))
        fig_iv.update_layout(
            **PLOTLY_TEMPLATE["layout"],
            title="Implied Volatility — ATM Estimate (yfinance fallback)",
            height=300, showlegend=False,
        )
        iv_section = _card([
            dcc.Graph(figure=fig_iv, config={"displayModeBar": False}),
            html.P(
                "⚠️ Showing yfinance ATM snapshot — no period averages available. "
                "Connect Interactive Brokers for full IV term structure (current, 1m, 1q, 6m, 1y averages).",
                style={"color": YELLOW, "fontSize": "12px", "marginTop": "8px"},
            ),
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

    # Performance + IV summary table
    tbl_df = sent[["ticker", "close_price", "perf_5d", "perf_10d", "perf_1m",
                   "days_since_large_drop"]].copy()
    # Merge IBKR current IV if available, else fallback to yfinance
    if has_ibkr:
        iv_now = ibkr_iv[["ticker", "iv_current"]].rename(columns={"iv_current": "implied_volatility"})
        tbl_df = tbl_df.merge(iv_now, on="ticker", how="left")
    else:
        tbl_df = tbl_df.merge(
            sent[["ticker", "implied_volatility"]], on="ticker", how="left")
    for col in ["perf_5d", "perf_10d", "perf_1m"]:
        tbl_df[col] = tbl_df[col].map(lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
    tbl_df["implied_volatility"] = tbl_df["implied_volatility"].map(
        lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
    tbl_df["close_price"]        = tbl_df["close_price"].map(
        lambda x: f"${x:,.2f}" if pd.notna(x) else "—")
    tbl_df["days_since_large_drop"] = tbl_df["days_since_large_drop"].map(
        lambda x: str(int(x)) if pd.notna(x) else "—")

    tbl = dash_table.DataTable(
        data=tbl_df.to_dict("records"),
        columns=[{"name": c.replace("_", " ").title(), "id": c} for c in tbl_df.columns],
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": BG2}],
    )

    return html.Div([
        source_note,
        _card([_section_title("Sentiment Snapshot"), tbl]),
        iv_section,
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=fig_drop,    config={"displayModeBar": False})), width=6),
            dbc.Col(_card(dcc.Graph(figure=fig_scatter, config={"displayModeBar": True})),  width=6),
        ]),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — CYCLE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def tab_cycles(tickers):
    cyc = cycle_data(tickers)

    if cyc.empty:
        return _card(html.P("No cycle data found. Run crawler.py with ≥2 years of price history.", style={"color": SUBTEXT}))

    cyc = cyc.dropna(subset=["up_cycle_magnitude", "down_cycle_magnitude"], how="all")

    # ── Up vs Down cycle magnitude ────────────────────────────────────────
    fig_mag = go.Figure()
    fig_mag.add_trace(go.Bar(
        name="Up Cycle (%)", x=cyc["ticker"], y=cyc["up_cycle_magnitude"],
        marker_color=GREEN,
        hovertemplate="<b>%{x}</b><br>Up: +%{y:.1f}%<extra></extra>",
    ))
    fig_mag.add_trace(go.Bar(
        name="Down Cycle (%)", x=cyc["ticker"], y=cyc["down_cycle_magnitude"],
        marker_color=RED,
        hovertemplate="<b>%{x}</b><br>Down: %{y:.1f}%<extra></extra>",
    ))
    fig_mag.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="Last Cycle Magnitude (Up vs Down)",
                           barmode="group", height=350)

    # ── Cycle duration ────────────────────────────────────────────────────
    fig_dur = go.Figure()
    fig_dur.add_trace(go.Bar(
        name="Up Duration (days)", x=cyc["ticker"], y=cyc["up_cycle_duration"],
        marker_color=GREEN,
        hovertemplate="<b>%{x}</b><br>Up: %{y} days<extra></extra>",
    ))
    fig_dur.add_trace(go.Bar(
        name="Down Duration (days)", x=cyc["ticker"], y=cyc["down_cycle_duration"],
        marker_color=RED,
        hovertemplate="<b>%{x}</b><br>Down: %{y} days<extra></extra>",
    ))
    fig_dur.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="Last Cycle Duration (trading days)",
                           barmode="group", height=300)

    # ── Volume difference vs last cycle ───────────────────────────────────
    vol_df = cyc.dropna(subset=["vol_diff_last_cycle"])
    fig_vol = go.Figure(go.Bar(
        x=vol_df["ticker"], y=vol_df["vol_diff_last_cycle"],
        marker_color=[GREEN if v > 0 else RED for v in vol_df["vol_diff_last_cycle"]],
        hovertemplate="<b>%{x}</b><br>Vol Δ vs last cycle: %{y:+.1f}%<extra></extra>",
    ))
    fig_vol.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="Volume Change vs Previous Cycle (%)",
                           showlegend=False, height=280)
    fig_vol.add_hline(y=0, line_dash="dash", line_color=SUBTEXT, line_width=1)

    # Summary table
    tbl_df = cyc[["ticker", "up_cycle_magnitude", "up_cycle_duration",
                  "down_cycle_magnitude", "down_cycle_duration", "vol_diff_last_cycle"]].copy()
    for col in ["up_cycle_magnitude", "down_cycle_magnitude", "vol_diff_last_cycle"]:
        tbl_df[col] = tbl_df[col].map(lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
    for col in ["up_cycle_duration", "down_cycle_duration"]:
        tbl_df[col] = tbl_df[col].map(lambda x: f"{int(x)}d" if pd.notna(x) else "—")

    tbl = dash_table.DataTable(
        data=tbl_df.to_dict("records"),
        columns=[{"name": c.replace("_", " ").title(), "id": c} for c in tbl_df.columns],
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": BG2}],
    )

    return html.Div([
        _card([_section_title("Cycle Summary"), tbl]),
        _card(dcc.Graph(figure=fig_mag, config={"displayModeBar": True})),
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=fig_dur, config={"displayModeBar": False})), width=7),
            dbc.Col(_card(dcc.Graph(figure=fig_vol, config={"displayModeBar": False})), width=5),
        ]),
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
                        start_date=(datetime.today() - timedelta(days=180)).strftime("%Y-%m-%d"),
                        end_date=(datetime.today() - timedelta(days=91)).strftime("%Y-%m-%d"),
                        display_format="DD MMM YYYY",
                    ),
                ], width=5),
                dbc.Col([
                    html.Label("Period B", style={"color": SUBTEXT, "fontSize": "12px"}),
                    dcc.DatePickerRange(
                        id="cmp-period-b",
                        start_date=(datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d"),
                        end_date=datetime.today().strftime("%Y-%m-%d"),
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
    """Return price history for all products in a category (GPU/CPU/RAM)."""
    model_ids = list(
        ({**GPU_PRODUCTS} if category == "GPU" else
         {**CPU_PRODUCTS} if category == "CPU" else
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


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — SUPPLY CHAIN
# ══════════════════════════════════════════════════════════════════════════════

def tab_supply_chain():
    """
    Supply Chain tab — six panels covering the six schema metrics
    for GPU, CPU, and RAM:
      1. Price Index          (PassMark + Newegg history)
      2. Sales Volume         (Steam HW Survey market share)
      3. Order Volume         (SEMI NA Equipment Book-to-Bill)
      4. Manufacturer Capacity (fab capacity from earnings)
      5. Manufacturer Occupancy (fab utilisation %)
      6. Estimated Delivery   (Newegg in-stock status)
    """

    # ── Category radio ───────────────────────────────────────────────────────
    cat_selector = dbc.RadioItems(
        id="sc-category",
        options=[
            {"label": "🖥️  GPU",    "value": "GPU"},
            {"label": "⚙️  CPU",    "value": "CPU"},
            {"label": "💾  RAM",    "value": "RAM"},
            {"label": "All",        "value": "ALL"},
        ],
        value="GPU",
        inline=True,
        inputStyle={"marginRight": "4px", "accentColor": ACCENT},
        labelStyle={"marginRight": "20px", "color": TEXT, "fontSize": "13px"},
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
        ]),

        # ── Category selector ────────────────────────────────────────────────
        _card([_section_title("Product Category"), cat_selector]),

        # ── PANEL 1 + 2: Price Index & In-Stock ─────────────────────────────
        # Pre-render GPU panel so the tab is not blank on first load.
        # The update_sc_price_panel callback updates this when the radio changes.
        html.Div(id="sc-price-panel", children=_sc_price_section("GPU")),

        # ── PANEL 3: Sales Volume — Steam Survey ─────────────────────────────
        _sc_steam_panel(),

        # ── PANEL 4: Order Volume — SEMI B2B ─────────────────────────────────
        _sc_btb_panel(),

        # ── PANEL 5 + 6: Manufacturer Capacity & Occupancy ───────────────────
        _sc_capacity_panel(),

        # ── PANEL 7: DRAM Spot Price ──────────────────────────────────────────
        _sc_dram_panel(),

        dcc.Store(id="sc-cat-store", data="GPU"),
    ])


# ── Callback: update price panel when category changes ───────────────────────
@app.callback(
    Output("sc-price-panel", "children"),
    Input("sc-category", "value"),
)
def update_sc_price_panel(category):
    if category == "ALL":
        cats = ["GPU", "CPU", "RAM"]
    else:
        cats = [category]

    panels = []
    for cat in cats:
        panels.append(_sc_price_section(cat))
    return html.Div(panels)


def _sc_price_section(category: str):
    """Price Index + Estimated Delivery (in-stock) for one category."""
    df_pass = sc_prices_query(category, source="passmark")
    df_new  = sc_prices_query(category, source="newegg")

    cat_label = {"GPU": "GPU", "CPU": "CPU", "RAM": "RAM Memory"}[category]
    COLOR_MAP = {
        "NVIDIA": "#76b900", "AMD": "#ED1C24", "Intel": "#0071C5",
        "Samsung": "#1428A0", "SK Hynix": "#F15A24", "Micron": "#E31837",
    }

    # ── Price history line chart (PassMark historical + Newegg current) ──
    fig_price = go.Figure()
    if not df_pass.empty:
        for i, (mid, grp) in enumerate(df_pass.groupby("model_id")):
            short = grp["name"].iloc[0] if "name" in grp.columns else mid
            brand = grp["brand"].iloc[0] if "brand" in grp.columns else ""
            col   = CHART_COLORS[i % len(CHART_COLORS)]
            fig_price.add_trace(go.Scatter(
                x=grp["date"], y=grp["price_usd"],
                name=short, mode="lines+markers",
                line=dict(width=2, color=col),
                hovertemplate=f"<b>{short}</b><br>Date: %{{x}}<br>Price: $%{{y:.0f}}<extra></extra>",
            ))
    if not df_new.empty and df_pass.empty:
        # Only Newegg data available — show as bar
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
        height=340, xaxis_title="Date", yaxis_title="Retail Price (USD)",
    )

    # ── Performance / Price scatter (PassMark score vs price) ────────────
    fig_pp = go.Figure()
    if not df_pass.empty:
        latest_pass = df_pass.dropna(subset=["passmark_score", "price_usd"])
        latest_pass = latest_pass.sort_values("date").groupby("model_id").last().reset_index()
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
        title=f"{cat_label} — Performance vs Price (PassMark Score / USD)",
        height=320, xaxis_title="Retail Price (USD)",
        yaxis_title="PassMark Score", showlegend=False,
    )

    # ── In-stock / Estimated Delivery table (Newegg) ─────────────────────
    delivery_section = _card(html.P(
        "Run supply_chain_crawler.py to fetch live Newegg availability data.",
        style={"color": SUBTEXT, "fontSize": "12px"}
    ))
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
                {"if": {"filter_query": '{Status} contains "In Stock"'},
                 "color": GREEN},
                {"if": {"filter_query": '{Status} contains "Out of Stock"'},
                 "color": RED},
            ],
        )
        delivery_section = _card([
            _section_title(f"Estimated Delivery — {cat_label} (Newegg Stock Status)"),
            tbl,
        ])

    return html.Div([
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=fig_price, config={"displayModeBar": True})), width=7),
            dbc.Col(_card(dcc.Graph(figure=fig_pp,    config={"displayModeBar": True})), width=5),
        ]),
        delivery_section,
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
        yaxis=dict(autorange="reversed"),
        showlegend=False,
    )

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
        yaxis=dict(range=[0.7, max(df["btb_ratio"].max() * 1.1, 1.4)]),
    )

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
        yaxis=dict(range=[40, 105]),
    )

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
        xaxis=dict(tickangle=-20),
    )

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
            html.P(
                "Source: TSMC / Samsung / SK Hynix / Micron / Intel quarterly earnings transcripts. "
                "Update CURATED_CAPACITY in products_config.py each quarter.",
                style={"color": SUBTEXT, "fontSize": "11px", "marginTop": "8px"},
            ),
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

    fig = go.Figure()
    for ptype, grp in df.groupby("product_type"):
        for spec, sub in grp.groupby("spec_label"):
            fig.add_trace(go.Scatter(
                x=sub["period"], y=sub["price_usd"],
                name=f"{ptype} — {spec}",
                mode="lines+markers",
                line=dict(width=2, color=DRAM_COLORS.get(ptype, ACCENT)),
                hovertemplate=f"<b>{ptype}</b> {spec}<br>%{{x}}<br>$%{{y:.2f}}/unit<extra></extra>",
            ))

    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="RAM Memory — DRAM & HBM Spot / Contract Prices (USD per die / per GB)",
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
        dcc.Graph(figure=fig, config={"displayModeBar": True}),
        html.Div(style={"marginTop": "12px"}),
        _section_title("Latest Prices & Year-on-Year Change"),
        tbl,
        html.P(
            "DDR4/DDR5 prices: TrendForce weekly spot report (benchmark die, USD). "
            "HBM3E: estimated contract price per GB. "
            "Update CURATED_DRAM_SPOT in products_config.py monthly.",
            style={"color": SUBTEXT, "fontSize": "11px", "marginTop": "8px"},
        ),
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

        now_str = datetime.utcnow().strftime("%Y-%m-%d")
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


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print(f"⚠️  Database not found at '{DB_PATH}'.")
        print("   Run  python crawler.py --quick  first to fetch data.\n")

    print(f"🚀  Dashboard running → http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False)
