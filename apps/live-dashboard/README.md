# Live Strategy Dashboard

A real-time trading research dashboard built on [vectorbt](https://github.com/polakowo/vectorbt).

It streams OHLCV data from either any [ccxt](https://github.com/ccxt/ccxt)-supported
exchange (Binance by default) **or [Twelve Data](https://twelvedata.com)** (stocks,
ETFs, forex, and crypto), keeps it fresh in the background with `vbt.DataUpdater`, runs
a vectorbt backtest on every refresh, and renders an interactive Plotly dashboard that
auto-updates in the browser.

![dashboard](assets/screenshot.png)

## Features

- **Live data feed** via `vbt.CCXTData` or `vbt.TwelveData` + background `vbt.DataUpdater` (non-blocking polling).
- **Multi-symbol comparison** — select several symbols to overlay normalized equity
  curves and rank them in a comparison table (return, Sharpe, max drawdown, trades).
- **Interactive controls** — switch symbols, timeframe, strategy, and parameters on the fly.
- **Three strategies** out of the box: SMA crossover, RSI mean-reversion, and Buy & hold.
- **Realistic backtests** — fees and slippage applied by default.
- **Live analytics panel** — return, drawdown, Sharpe, trade count, win rate.
- **Deploy-ready** — `gunicorn`, `Procfile`, and `Dockerfile` included.

## Quick start

```sh
cd apps/live-dashboard
pip install -r requirements.txt

# Optional: configure credentials & defaults
cp .env.example .env        # then edit, or just export the vars

python app.py               # http://127.0.0.1:8050
```

Public ccxt OHLCV endpoints work **without** API keys. Providing keys raises rate limits.

### Using Twelve Data instead

```sh
export VBT_SOURCE=twelvedata
export TWELVEDATA_API_KEY=your_key   # https://twelvedata.com
python app.py
```

Or straight from the library (newly added `vbt.TwelveData`):

```python
import vectorbt as vbt

# use_cache serves identical requests from an in-memory TTL cache to save credits
data = vbt.TwelveData.download("AAPL", interval="1h", start="5 days ago UTC",
                               apikey="your_key", use_cache=True, cache_ttl=60)
price = data.get("Close")
pf = vbt.Portfolio.from_holding(price, freq="1h")
print(pf.stats())
```

`vbt.TwelveData` supports an opt-in TTL response cache (`use_cache`, `cache_ttl`) to
stay under Twelve Data's rate limit; clear it with
`from vectorbt.data.custom import clear_twelvedata_cache`.

### Saudi market (Tadawul) — one-variable preset

Set **`VBT_MARKET=saudi`** to load a built-in, labeled catalog of 40+ Tadawul stocks
grouped by sector (Aramco, Al Rajhi, SABIC, STC, Almarai, Jarir, …). It automatically
selects the Twelve Data source with `exchange=Tadawul` and sensible daily-bar defaults:

```sh
VBT_MARKET=saudi
TWELVEDATA_API_KEY=your_key
```

The symbol dropdown then shows readable entries like `2222 — Saudi Aramco`.

### Other non-US markets (manual)

For any other market, disambiguate symbols explicitly:

```sh
VBT_SOURCE=twelvedata
VBT_TD_EXCHANGE=Tadawul          # or VBT_TD_MIC=XSAU / VBT_TD_COUNTRY="Saudi Arabia"
VBT_SYMBOLS=2222,1120,2010,7010,1180
VBT_TIMEFRAME=1day
```

From the library directly:

```python
data = vbt.TwelveData.download("2222", exchange="Tadawul", interval="1day",
                               start="6 months ago", apikey="your_key")
```

> **Note:** Tadawul (and most non-US exchanges) usually require a **paid** Twelve Data
> plan. On the free tier these requests may return an access/permission error.

## Configuration

All settings are environment variables (see `.env.example`):

| Variable             | Default          | Description                                  |
|----------------------|------------------|----------------------------------------------|
| `VBT_SOURCE`         | `ccxt`           | `ccxt` or `twelvedata`                        |
| `VBT_EXCHANGE`       | `binance`        | Any ccxt exchange id (ccxt source)           |
| `VBT_API_KEY`        | —                | Exchange API key (ccxt, optional)            |
| `VBT_API_SECRET`     | —                | Exchange API secret (ccxt, optional)         |
| `TWELVEDATA_API_KEY` | —                | Twelve Data API key (twelvedata source)      |
| `VBT_SYMBOL`      | `BTC/USDT`       | Default symbol                               |
| `VBT_TIMEFRAME`   | `1m`             | Default timeframe                            |
| `VBT_LOOKBACK`    | `2 days ago UTC` | How far back to load on start                |
| `VBT_REFRESH_MS`  | `15000`          | Poll/redraw interval in milliseconds         |
| `VBT_FEES`        | `0.001`          | Trading fee (fraction)                       |
| `VBT_SLIPPAGE`    | `0.0005`         | Slippage (fraction)                          |
| `VBT_INIT_CASH`   | `10000`          | Starting capital                             |

> **Security:** credentials are read only from the environment and never written to disk
> or embedded in the code. Keep your real `.env` out of version control.

## Deployment

**Docker**

```sh
docker build -t vbt-live .
docker run -p 8050:8050 -e VBT_EXCHANGE=binance vbt-live
```

**Railway** (recommended for this app — it needs a long-running server for the
background data updater)

A root `railway.json` already points Railway at `apps/live-dashboard/Dockerfile.railway`,
which builds from the repo root so it installs **this repo's** vectorbt (with the
`TwelveData` source) instead of the older PyPI release. **No "Root Directory" setting
is needed** — just deploy the repo as-is:

1. Railway → **New Project → Deploy from GitHub repo** → pick this repository
   (deploy the `master` branch).
2. **Settings → Variables** → add (see the table above):
   - `VBT_SOURCE=twelvedata`
   - `TWELVEDATA_API_KEY=your_key`
   - (or for ccxt: `VBT_EXCHANGE`, `VBT_API_KEY`, `VBT_API_SECRET`)
   - Do **not** set `PORT` — Railway injects it automatically.
3. **Settings → Networking → Generate Domain** to get a public URL.
4. Deploy. The image starts gunicorn on `0.0.0.0:$PORT` with a `/` health check.

> If Railway shows a JupyterLab login page, it built the **root** `Dockerfile`
> (vectorbt's notebook image) instead of `railway.json`. Trigger a fresh deploy so
> the `railway.json` build config is picked up, or set **Settings → Build → Builder**
> to *Dockerfile* with **Dockerfile Path** `apps/live-dashboard/Dockerfile.railway`.

CLI alternative (from the repo root):

```sh
npm i -g @railway/cli
railway login
railway init
railway up
railway variables --set TWELVEDATA_API_KEY=your_key --set VBT_SOURCE=twelvedata
```

**Heroku / Render** — the included `Procfile` runs the app under gunicorn.

## How it works

```
ccxt exchange ──> vbt.CCXTData ──> vbt.DataUpdater (background polling)
                                        │
              dcc.Interval tick ────────┼──> data.get("Close")
                                        │       └──> vbt.Portfolio.from_signals(...)
                                        └──> Plotly figure + live stats panel
```

The data layer and the UI are decoupled: the `DataUpdater` refreshes the cached `Data`
object on its own schedule, so the UI callback never blocks on a network request — it
just reads the latest in-memory data and re-runs the (vectorized, sub-millisecond)
backtest.

## Notes

- vectorbt is a **research/analysis** tool, not an order-execution engine. This dashboard
  does not place live trades.
- ccxt uses **polling**, not websockets. For true tick streaming, push websocket updates
  into the `Data` object yourself.
