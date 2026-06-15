# -*- coding: utf-8 -*-

# Copyright (c) 2026 Oleg Polakow. All rights reserved.
# This code is licensed under Apache 2.0 with Commons Clause license (see LICENSE.md for details)

"""Live strategy dashboard built on top of vectorbt.

Streams OHLCV data from any CCXT-supported exchange (Binance by default), keeps it
fresh in the background via ``vbt.DataUpdater``, runs a vectorbt backtest on every
refresh, and renders an interactive Plotly dashboard in the browser.

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

import dash
from dash import Dash, dcc, html, Input, Output, State, no_update
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import vectorbt as vbt

# ---------------------------------------------------------------------------- #
# Configuration (all overridable via environment variables)
# ---------------------------------------------------------------------------- #

EXCHANGE = os.environ.get("VBT_EXCHANGE", "binance")
API_KEY = os.environ.get("VBT_API_KEY")
API_SECRET = os.environ.get("VBT_API_SECRET")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", 8050))

DEFAULT_SYMBOL = os.environ.get("VBT_SYMBOL", "BTC/USDT")
DEFAULT_TIMEFRAME = os.environ.get("VBT_TIMEFRAME", "1m")
DEFAULT_LOOKBACK = os.environ.get("VBT_LOOKBACK", "2 days ago UTC")

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT"]
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]

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
# Live data layer: one cached Data object per (symbol, timeframe), kept fresh by
# a background DataUpdater so the UI never blocks on a network call.
# ---------------------------------------------------------------------------- #

_feeds = {}  # (symbol, timeframe) -> {"updater": DataUpdater}


def get_feed(symbol, timeframe):
    """Return a live, auto-updating data feed for ``(symbol, timeframe)``."""
    key = (symbol, timeframe)
    feed = _feeds.get(key)
    if feed is not None:
        return feed["updater"].data

    data = vbt.CCXTData.download(
        symbol,
        exchange=EXCHANGE,
        config=_ccxt_config(),
        timeframe=timeframe,
        start=DEFAULT_LOOKBACK,
        show_progress=False,
    )
    updater = vbt.DataUpdater(data)
    # Poll the exchange in the background; the UI reads updater.data on each tick.
    updater.update_every(int(REFRESH_MS / 1000), "seconds", in_background=True)
    _feeds[key] = {"updater": updater}
    return updater.data


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
    """Render a compact, human-readable stats panel."""
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


# ---------------------------------------------------------------------------- #
# Dash app
# ---------------------------------------------------------------------------- #

app = Dash(__name__, title="vectorbt — Live Dashboard")
server = app.server  # for gunicorn / WSGI deployment

controls = html.Div(className="controls", children=[
    html.Div([html.Label("Symbol"), dcc.Dropdown(
        SYMBOLS, DEFAULT_SYMBOL, id="symbol", clearable=False)]),
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
    html.P(f"Exchange: {EXCHANGE} · auto-refresh every {REFRESH_MS // 1000}s · "
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
def refresh(_, symbol, timeframe, strategy, fast, slow):
    try:
        data = get_feed(symbol, timeframe)
        price = data.get("Close")
        pf, overlays = build_portfolio(
            price, strategy, int(fast or 10), int(slow or 50), freq=timeframe)
        return make_figure(data, pf, overlays), make_stats(pf)
    except Exception as exc:  # surface errors in the UI instead of a blank page
        return no_update, html.Div(f"⚠️ {exc}", className="error")


if __name__ == "__main__":
    print(f"Starting live dashboard on http://{HOST}:{PORT}  (exchange={EXCHANGE})")
    if not (API_KEY and API_SECRET):
        print("No API credentials found in env — using public endpoints only.")
    app.run(host=HOST, port=PORT, debug=bool(os.environ.get("DEBUG")))
