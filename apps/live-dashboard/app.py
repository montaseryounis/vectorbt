# -*- coding: utf-8 -*-

# Copyright (c) 2026 Oleg Polakow. All rights reserved.
# This code is licensed under Apache 2.0 with Commons Clause license (see LICENSE.md for details)

"""Live strategy dashboard built on top of vectorbt.

Streams OHLCV data from a CCXT exchange or Twelve Data, refreshes it incrementally
via ``Data.update()`` on each UI tick, runs a vectorbt backtest on every refresh, and
renders an interactive Plotly dashboard in the browser.

Run with::

    python app.py

then visit http://127.0.0.1:8050/ in your web browser.

API credentials are read from environment variables and are NEVER hardcoded:

    export VBT_EXCHANGE=binance          # any ccxt exchange id
    export VBT_API_KEY=your_api_key
    export VBT_API_SECRET=your_api_secret

Public OHLCV endpoints work without keys, but providing them raises rate limits
and unlocks private endpoints.
"""

import os
import time

import dash
from dash import Dash, dcc, html, Input, Output, State, no_update
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import vectorbt as vbt

# ---------------------------------------------------------------------------- #
# Configuration (all overridable via environment variables)
# ---------------------------------------------------------------------------- #

# Optional market preset, e.g. VBT_MARKET=saudi loads the Tadawul catalog and forces
# the Twelve Data source with exchange=Tadawul.
MARKET = os.environ.get("VBT_MARKET", "").lower()

# Data source: "ccxt" (crypto exchanges) or "twelvedata" (stocks/forex/crypto).
SOURCE = os.environ.get("VBT_SOURCE", "ccxt").lower()
if MARKET in ("saudi", "tadawul"):
    SOURCE = "twelvedata"

EXCHANGE = os.environ.get("VBT_EXCHANGE", "binance")
API_KEY = os.environ.get("VBT_API_KEY")
API_SECRET = os.environ.get("VBT_API_SECRET")

# Twelve Data uses its own single API key.
TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY")

# Optional Twelve Data market disambiguation, e.g. the Saudi market (Tadawul):
#   VBT_TD_EXCHANGE=Tadawul   (or VBT_TD_MIC=XSAU, VBT_TD_COUNTRY="Saudi Arabia")
TD_EXCHANGE = os.environ.get("VBT_TD_EXCHANGE")
TD_MIC = os.environ.get("VBT_TD_MIC")
TD_COUNTRY = os.environ.get("VBT_TD_COUNTRY")
if MARKET in ("saudi", "tadawul") and not (TD_EXCHANGE or TD_MIC or TD_COUNTRY):
    TD_EXCHANGE = "Tadawul"

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", 8050))

# Intraday is sparse on Tadawul, so default the Saudi preset to daily bars over a year.
_is_saudi = MARKET in ("saudi", "tadawul")

# Normalize Twelve Data-style interval names to the dashboard's vocabulary so values
# like "1day"/"1min" (a common env mistake) still match the dropdown options.
_TF_ALIASES = {
    "1min": "1m", "5min": "5m", "15min": "15m", "30min": "30m", "45min": "45m",
    "60min": "1h", "1day": "1d", "1week": "1w", "1month": "1M",
}


def _norm_tf(tf):
    return _TF_ALIASES.get(tf, tf)


DEFAULT_TIMEFRAME = _norm_tf(os.environ.get("VBT_TIMEFRAME", "1d" if _is_saudi else "1m"))
DEFAULT_LOOKBACK = os.environ.get("VBT_LOOKBACK", "1 year ago" if _is_saudi else "2 days ago UTC")

# Resolve the symbol list and the (optionally labeled) dropdown options.
# Precedence: VBT_SYMBOLS override > market preset > source defaults.
_symbols_env = os.environ.get("VBT_SYMBOLS")
if _symbols_env:
    SYMBOLS = [s.strip() for s in _symbols_env.split(",") if s.strip()]
    SYMBOL_OPTIONS = [{"label": s, "value": s} for s in SYMBOLS]
    DEFAULT_SYMBOL = os.environ.get("VBT_SYMBOL", SYMBOLS[0])
elif MARKET in ("saudi", "tadawul"):
    from markets import SAUDI_TADAWUL

    SYMBOLS = [code for _, code, _ in SAUDI_TADAWUL]
    SYMBOL_OPTIONS = [{"label": f"{code} — {name}", "value": code} for _, code, name in SAUDI_TADAWUL]
    DEFAULT_SYMBOL = os.environ.get("VBT_SYMBOL", SYMBOLS[0])
elif SOURCE == "twelvedata":
    SYMBOLS = ["BTC/USD", "ETH/USD", "AAPL", "TSLA", "EUR/USD"]
    SYMBOL_OPTIONS = [{"label": s, "value": s} for s in SYMBOLS]
    DEFAULT_SYMBOL = os.environ.get("VBT_SYMBOL", "BTC/USD")
else:
    SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT"]
    SYMBOL_OPTIONS = [{"label": s, "value": s} for s in SYMBOLS]
    DEFAULT_SYMBOL = os.environ.get("VBT_SYMBOL", "BTC/USDT")

TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]
# Make sure the default is always selectable (e.g. a custom VBT_TIMEFRAME).
if DEFAULT_TIMEFRAME not in TIMEFRAMES:
    TIMEFRAMES = [DEFAULT_TIMEFRAME] + TIMEFRAMES

# How often the page polls for a redraw (ms). Kept in sync with the data updater.
REFRESH_MS = int(os.environ.get("VBT_REFRESH_MS", 15_000))

# vectorbt portfolio assumptions (realistic, executable defaults).
FEES = float(os.environ.get("VBT_FEES", 0.001))  # 0.1% taker fee
SLIPPAGE = float(os.environ.get("VBT_SLIPPAGE", 0.0005))
INIT_CASH = float(os.environ.get("VBT_INIT_CASH", 10_000))


def _ccxt_config():
    """Build a ccxt config dict from the environment without leaking secrets."""
    config = {"enableRateLimit": True}
    if API_KEY and API_SECRET:
        config["apiKey"] = API_KEY
        config["secret"] = API_SECRET
    return config


# ---------------------------------------------------------------------------- #
# Live data layer: one cached Data object per (symbol, timeframe), refreshed
# incrementally and throttled on access (driven by the UI's periodic callback).
# ---------------------------------------------------------------------------- #

# We deliberately avoid vbt.DataUpdater's asyncio background scheduler, which needs a
# running event loop and fails ("no running event loop") inside a gunicorn sync worker.
_feeds = {}  # (symbol, timeframe) -> {"data": Data, "last": float}

# Don't hit the data provider more often than the refresh interval (min 5s) to
# respect rate limits (e.g. Twelve Data's free tier).
_MIN_UPDATE_S = max(REFRESH_MS / 1000, 5)


def _download(symbol, timeframe):
    if SOURCE == "twelvedata":
        return vbt.TwelveData.download(
            symbol,
            apikey=TWELVEDATA_API_KEY,
            interval=timeframe,
            start=DEFAULT_LOOKBACK,
            exchange=TD_EXCHANGE,
            mic_code=TD_MIC,
            country=TD_COUNTRY,
        )
    return vbt.CCXTData.download(
        symbol,
        exchange=EXCHANGE,
        config=_ccxt_config(),
        timeframe=timeframe,
        start=DEFAULT_LOOKBACK,
        show_progress=False,
    )


def get_feed(symbol, timeframe):
    """Return a cached Data object for ``(symbol, timeframe)``, refreshed in place."""
    key = (symbol, timeframe)
    now = time.monotonic()
    feed = _feeds.get(key)
    if feed is None:
        data = _download(symbol, timeframe)
        _feeds[key] = {"data": data, "last": now}
        return data

    # Pull only the bars since the last fetch, and only if enough time has passed.
    if now - feed["last"] >= _MIN_UPDATE_S:
        try:
            feed["data"] = feed["data"].update()
        except Exception:
            pass  # keep serving the last good data; surfaced errors come from refresh()
        feed["last"] = now
    return feed["data"]


# ---------------------------------------------------------------------------- #
# Strategy layer
# ---------------------------------------------------------------------------- #

def build_portfolio(price, strategy, fast, slow, freq):
    """Run a vectorbt backtest for the chosen strategy on the latest price."""
    if strategy == "sma":
        fast_ma = vbt.MA.run(price, fast)
        slow_ma = vbt.MA.run(price, slow)
        entries = fast_ma.ma_crossed_above(slow_ma)
        exits = fast_ma.ma_crossed_below(slow_ma)
        overlays = {f"SMA {fast}": fast_ma.ma, f"SMA {slow}": slow_ma.ma}
    elif strategy == "rsi":
        rsi = vbt.RSI.run(price, window=fast)
        entries = rsi.rsi_crossed_below(30)
        exits = rsi.rsi_crossed_above(70)
        overlays = {}
    else:  # buy & hold benchmark
        overlays = {}

    if strategy == "hold":
        pf = vbt.Portfolio.from_holding(price, init_cash=INIT_CASH, freq=freq)
    else:
        pf = vbt.Portfolio.from_signals(
            price,
            entries,
            exits,
            init_cash=INIT_CASH,
            fees=FEES,
            slippage=SLIPPAGE,
            freq=freq,
        )
    return pf, overlays


# ---------------------------------------------------------------------------- #
# Plotting
# ---------------------------------------------------------------------------- #

def make_figure(data, pf, overlays):
    df = data.get()
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        row_heights=[0.7, 0.3], subplot_titles=("Price & signals", "Equity"),
    )
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"],
            low=df["Low"], close=df["Close"], name="OHLC",
        ),
        row=1, col=1,
    )
    for name, series in overlays.items():
        fig.add_trace(
            go.Scatter(x=series.index, y=series.values, name=name, mode="lines"),
            row=1, col=1,
        )
    equity = pf.value()
    fig.add_trace(
        go.Scatter(x=equity.index, y=equity.values, name="Equity",
                   line=dict(color="#26a69a")),
        row=2, col=1,
    )
    fig.update_layout(
        template="plotly_dark", height=720, margin=dict(l=40, r=20, t=40, b=20),
        xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.05),
    )
    return fig


def make_stats(pf):
    """Render a compact, human-readable stats panel for a single symbol."""
    def row(label, value):
        return html.Tr([html.Td(label, className="k"), html.Td(value, className="v")])

    fmt = lambda x: f"{x:,.2f}"
    return html.Table([
        row("Start value", fmt(pf.init_cash)),
        row("End value", fmt(float(pf.value().iloc[-1]))),
        row("Total return %", fmt(float(pf.total_return()) * 100)),
        row("Benchmark return %", fmt(float(pf.total_benchmark_return()) * 100)),
        row("Max drawdown %", fmt(float(pf.max_drawdown()) * 100)),
        row("Sharpe ratio", fmt(float(pf.sharpe_ratio()))),
        row("Total trades", str(int(pf.trades.count()))),
        row("Win rate %", fmt(float(pf.trades.win_rate()) * 100)),
    ], className="stats")


def make_comparison_figure(equities):
    """Overlay normalized equity curves (base 100) for several symbols."""
    fig = go.Figure()
    for symbol, equity in equities.items():
        norm = equity / equity.iloc[0] * 100
        fig.add_trace(go.Scatter(x=norm.index, y=norm.values, name=symbol, mode="lines"))
    fig.update_layout(
        template="plotly_dark", height=720, margin=dict(l=40, r=20, t=40, b=20),
        title="Equity (normalized to 100)", legend=dict(orientation="h", y=1.05),
    )
    return fig


def make_comparison_stats(rows):
    """Render a sortable-looking comparison table across symbols."""
    fmt = lambda x: f"{x:,.2f}"
    head = html.Tr([html.Th(h) for h in ["Symbol", "Return %", "Sharpe", "MaxDD %", "Trades"]])
    body = [
        html.Tr([
            html.Td(r["symbol"], className="k"),
            html.Td(fmt(r["ret"]), className="v"),
            html.Td(fmt(r["sharpe"]), className="v"),
            html.Td(fmt(r["maxdd"]), className="v"),
            html.Td(str(r["trades"]), className="v"),
        ])
        for r in rows
    ]
    return html.Table([head] + body, className="stats")


# ---------------------------------------------------------------------------- #
# Dash app
# ---------------------------------------------------------------------------- #

app = Dash(__name__, title="vectorbt — Live Dashboard")
server = app.server  # for gunicorn / WSGI deployment

controls = html.Div(className="controls", children=[
    html.Div([html.Label("Symbols"), dcc.Dropdown(
        SYMBOL_OPTIONS, [DEFAULT_SYMBOL], id="symbol", multi=True, clearable=False)]),
    html.Div([html.Label("Timeframe"), dcc.Dropdown(
        TIMEFRAMES, DEFAULT_TIMEFRAME, id="timeframe", clearable=False)]),
    html.Div([html.Label("Strategy"), dcc.Dropdown(
        options=[
            {"label": "SMA crossover", "value": "sma"},
            {"label": "RSI mean-reversion", "value": "rsi"},
            {"label": "Buy & hold", "value": "hold"},
        ], value="sma", id="strategy", clearable=False)]),
    html.Div([html.Label("Fast / window"), dcc.Input(
        id="fast", type="number", value=10, min=2, step=1)]),
    html.Div([html.Label("Slow"), dcc.Input(
        id="slow", type="number", value=50, min=2, step=1)]),
])

app.layout = html.Div(className="wrap", children=[
    html.H2(["vectorbt ", html.Span("Live Dashboard", className="accent")]),
    html.P(f"Source: {'Twelve Data' if SOURCE == 'twelvedata' else EXCHANGE} · "
           f"auto-refresh every {REFRESH_MS // 1000}s · "
           f"fees {FEES:.3%} · slippage {SLIPPAGE:.3%}", className="sub"),
    controls,
    html.Div(className="grid", children=[
        dcc.Graph(id="chart", className="chart"),
        html.Div(id="stats", className="panel"),
    ]),
    dcc.Interval(id="tick", interval=REFRESH_MS),
])


@app.callback(
    Output("chart", "figure"),
    Output("stats", "children"),
    Input("tick", "n_intervals"),
    Input("symbol", "value"),
    Input("timeframe", "value"),
    Input("strategy", "value"),
    Input("fast", "value"),
    Input("slow", "value"),
)
def refresh(_, symbols, timeframe, strategy, fast, slow):
    # Normalize the multi-select value to a non-empty list.
    if isinstance(symbols, str):
        symbols = [symbols]
    symbols = symbols or [DEFAULT_SYMBOL]
    timeframe = _norm_tf(timeframe) or DEFAULT_TIMEFRAME  # never send an empty interval
    fast, slow = int(fast or 10), int(slow or 50)

    try:
        # Single symbol: detailed candlestick + equity + stats panel.
        if len(symbols) == 1:
            data = get_feed(symbols[0], timeframe)
            price = data.get("Close")
            pf, overlays = build_portfolio(price, strategy, fast, slow, freq=timeframe)
            return make_figure(data, pf, overlays), make_stats(pf)

        # Multiple symbols: normalized equity overlay + comparison table.
        equities, rows = {}, []
        for sym in symbols:
            data = get_feed(sym, timeframe)
            price = data.get("Close")
            pf, _ = build_portfolio(price, strategy, fast, slow, freq=timeframe)
            equities[sym] = pf.value()
            rows.append(dict(
                symbol=sym,
                ret=float(pf.total_return()) * 100,
                sharpe=float(pf.sharpe_ratio()),
                maxdd=float(pf.max_drawdown()) * 100,
                trades=int(pf.trades.count()),
            ))
        rows.sort(key=lambda r: r["ret"], reverse=True)
        return make_comparison_figure(equities), make_comparison_stats(rows)
    except Exception as exc:  # surface errors in the UI instead of a blank page
        return no_update, html.Div(f"⚠️ {exc}", className="error")


if __name__ == "__main__":
    print(f"Starting live dashboard on http://{HOST}:{PORT}  (source={SOURCE})")
    if SOURCE == "twelvedata" and not TWELVEDATA_API_KEY:
        print("TWELVEDATA_API_KEY not set — Twelve Data requests will fail.")
    elif SOURCE != "twelvedata" and not (API_KEY and API_SECRET):
        print("No exchange API credentials found in env — using public endpoints only.")
    app.run(host=HOST, port=PORT, debug=bool(os.environ.get("DEBUG")))
