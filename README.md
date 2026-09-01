# GoldSignal

Rule-based XAU/USD paper-trading signal research tool. Sends transparent,
deterministic BUY/SELL/NO_TRADE signals — it never places real trades.

> **This is not financial advice.** GoldSignal is an experimental research
> and paper-trading tool. It does not guarantee profit, is not personalized
> financial advice, and its `confidence_score` is a count of satisfied rule
> conditions — **not** a probability of profit. The backtest results in
> `backtest_output/` (once you run one) are against **mock synthetic
> data only**, not real market history — do not treat them as evidence
> either mode is profitable.

## What it does (and doesn't) do

- Evaluates two independently-configured, independently-versioned strategies:
  - **Scalp**: 5-minute entries, confirmed on the 15-minute chart.
  - **Day-Trade**: 15-minute entries, confirmed on the 1-hour chart.
- Each signal is rule-based (EMA 20/50 trend, RSI 14, ATR 14,
  breakout-and-retest structure confirmation) and fully transparent: every
  signal records exactly which conditions passed and which failed.
- BUY/SELL signals carry up to three profit targets (TP1–TP3), each backed
  by real market structure and a minimum net-of-cost reward — never
  mechanically invented.
- **Does not** execute trades, connect to a broker, or use an LLM to predict
  price direction.

## Current status: Phase 3

The rule engine (Phase 1), backtester (Phase 2), real data/Telegram/
persistence (Phase 3), and automatic scheduled checks via GitHub Actions
now exist. Not implemented yet: the FastAPI dashboard with mode
toggles/history (Phase 4).

### Running against real data

1. Copy `.env.example` to `.env` and fill in:
   - `GOLDSIGNAL_DATA_PROVIDER=twelvedata` and `GOLDSIGNAL_TWELVEDATA_API_KEY`
   - `GOLDSIGNAL_TELEGRAM_BOT_TOKEN` and `GOLDSIGNAL_TELEGRAM_CHAT_ID`
   - `GOLDSIGNAL_DATABASE_URL` (a Neon or any Postgres connection string)
2. Run one signal check by hand:
   ```bash
   venv\Scripts\python -m goldsignal.live.run_once --mode scalp
   ```
   This fetches recent candles, evaluates the strategy, saves the result
   to Postgres (creating the `signals` table on first run), and sends a
   Telegram message if a BUY/SELL fires (or logs why it didn't). There is
   no scheduler yet — run this by hand, or point an external cron at it
   yourself, whenever you want a check (Phase 4 automates this).

### Automatic checks (GitHub Actions)

`.github/workflows/check-signals.yml` runs both modes automatically
every 15 minutes via GitHub Actions, once the repo has these secrets set
(Settings → Secrets and variables → Actions → New repository secret —
same 4 values as your local `.env`):

```
GOLDSIGNAL_TWELVEDATA_API_KEY
GOLDSIGNAL_TELEGRAM_BOT_TOKEN
GOLDSIGNAL_TELEGRAM_CHAT_ID
GOLDSIGNAL_DATABASE_URL
```

You can also trigger it manually from the repo's **Actions** tab (the
"Run workflow" button) without waiting for the schedule, to test it.

Run a backtest (still mock data only — see Known Limitations):

```bash
venv\Scripts\python -m goldsignal.backtest.cli --mode both --preset all
```

Writes `trades.csv`/`trades.json` (every simulated trade, including target
fills and stop adjustments) and `summary.csv`/`summary.json` (metrics
separated by mode × trade-management preset × development/out-of-sample
split — never blended) to `backtest_output/`. See `--help` for options
(seed, candle count, split ratio, instrument).

## Setup

```bash
python -m venv venv
venv\Scripts\pip install -r requirements-dev.txt
venv\Scripts\pip install -e .
copy .env.example .env
```

`.env` only needs to exist if you want to override a default — every
setting has a sensible built-in default (see `.env.example` for the full
list, split into global settings and per-mode `GOLDSIGNAL_SCALP_*` /
`GOLDSIGNAL_DAYTRADE_*` settings).

## Running tests

```bash
venv\Scripts\python -m pytest
venv\Scripts\python -m ruff check .
venv\Scripts\python -m ruff format --check .
```

## Project layout

```
src/goldsignal/
├── config.py           # env-var configuration (global + per-mode)
├── models/              # Candle, Timeframe, StrategySignal, ProfitTarget
├── data/                 # DataProvider interface, mock provider, validation
├── indicators/           # EMA, RSI, ATR, swing structure / breakout-retest
└── strategy/
    ├── cost_model.py      # spread/slippage estimate, net-reward-after-costs
    ├── targets.py          # TP1-TP3 selection from structure + R rules
    ├── trade_management.py # partial-close presets, breakeven rule types
    ├── scalp.py             # ScalpStrategy
    └── day_trade.py          # DayTradeStrategy
backtest/
├── engine.py              # walk-forward signal generation + trade-management simulation
├── metrics.py              # BacktestTrade list -> BacktestSummary
├── split.py                 # chronological development / out-of-sample split
├── export.py                 # CSV/JSON writers
└── cli.py                     # `python -m goldsignal.backtest.cli` (still mock data)
notifications/
├── sessions.py             # dynamic London/New York/overlap labeling + Ghana time
├── formatting.py            # Telegram message text
└── telegram.py               # sends the message
persistence/
├── db.py                   # Postgres connection + schema setup
├── schema.py                # signals table DDL
└── signals_repo.py           # save/query signals, dedup ("same trade idea") logic
live/
└── run_once.py            # manual one-shot: fetch real candles -> evaluate -> persist -> alert
tests/
```

## Known limitations (Phase 3)

- **Backtesting is still mock-data only** — `backtest/cli.py` hasn't been
  switched to the real provider. Never use backtest output as evidence a
  strategy is profitable, and never use current output for real trading
  decisions.
- No scheduler yet — `live/run_once.py` is run by hand (or by a cron you
  set up yourself). Phase 4 automates this and adds a dashboard.
- No GHS conversion in Telegram messages yet — needs an account
  balance/currency and a live FX rate, both Phase 4.
- Costs (spread/slippage/transaction cost) are still conservative
  configured estimates, not real historical bid/ask data from TwelveData.
- Breakeven logic only supports a single stop-to-breakeven move, not a
  general trailing stop.
- `evaluate()` recomputes indicators over the full candle history on every
  call — O(n²) in candle count for the backtester; fine at the volumes
  tested so far.
- 1-minute scalping is intentionally out of scope — execution latency,
  spread, slippage, and noise make backtests at that timeframe unrealistic.
- TwelveData's free tier's exact interval/history limits for XAU/USD
  weren't independently confirmed beyond their public docs — check your
  own dashboard if `live/run_once.py` returns unexpectedly little data.
