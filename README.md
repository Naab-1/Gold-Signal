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

`.github/workflows/check-signals.yml` runs both modes automatically via
GitHub Actions, once the repo has these secrets set (Settings → Secrets
and variables → Actions → New repository secret — same 4 values as your
local `.env`):

```
GOLDSIGNAL_TWELVEDATA_API_KEY
GOLDSIGNAL_TELEGRAM_BOT_TOKEN
GOLDSIGNAL_TELEGRAM_CHAT_ID
GOLDSIGNAL_DATABASE_URL
```

You can also trigger it manually from the repo's **Actions** tab (the
"Run workflow" button), to test it.

#### Scheduler reliability

GitHub's own `schedule:` cron is kept as a free backup trigger, but it is
**not reliable enough on its own** for a 5-minute scalp timeframe — a real
gap of 4h43m between two "every 15 minutes" runs was observed in
practice. Two things address this:

1. **Durable catch-up processing.** `live/run_once.py` no longer just asks
   "is there a signal right now?" — it persists a checkpoint (the last
   successfully processed closed candle, per strategy/version/timeframe/
   provider) and walks every closed candle since then, oldest first,
   alerting on each exactly once. A scheduler gap of any length gets
   fully caught up on the next run instead of silently losing whatever
   happened during the gap. See "How the catch-up scan works" below.
2. **A more reliable external trigger.** The workflow now also accepts a
   `repository_dispatch` event (type `"scan"`), which any external
   always-on pinger can fire with a plain authenticated HTTPS POST — this
   is what should actually drive 5-minute-or-better cadence, not GitHub's
   internal cron. To set one up (free, using
   [cron-job.org](https://cron-job.org), swappable for any similar
   service since the trigger is just an HTTP call):
   1. Create a GitHub **fine-grained personal access token**
      (Settings → Developer settings → Personal access tokens → Fine-grained
      tokens) scoped to **only this repository**, with **Contents:
      Read and write** permission (that's what `repository_dispatch`
      requires) and nothing else.
   2. Sign up at cron-job.org (or any HTTP-cron service) and create a job:
      - URL: `https://api.github.com/repos/Naab-1/Gold-Signal/dispatches`
      - Method: `POST`
      - Schedule: every 3–5 minutes
      - Headers: `Authorization: Bearer <your fine-grained token>`,
        `Accept: application/vnd.github+json`,
        `Content-Type: application/json`
      - Body: `{"event_type": "scan"}`
   3. That's it — the token lives only in cron-job.org's own config, never
      in this repo. Swapping to a different pinger later is a config
      change on that service, not a code change here.

Because catch-up processing is idempotent, it's safe to run both triggers
side by side, or to have them overlap — nothing gets double-sent, and
nothing gets silently skipped.

#### How the catch-up scan works

- A checkpoint is kept per (strategy, strategy version, entry timeframe,
  data provider, instrument) in `scan_checkpoints`.
- Every run fetches candles from the checkpoint (plus indicator warm-up)
  through now, finds every **fully closed** candle after the checkpoint,
  and evaluates them **chronologically, oldest first** — the checkpoint
  only advances after a candle's evaluation, persistence, and (if
  actionable) alerting all succeed. A failure partway through a sweep
  leaves the checkpoint at the last success, so the failed candle is
  retried on the next run rather than skipped.
- Every stored row's `signal_id` already encodes instrument + mode +
  timeframe + candle timestamp + direction + strategy version, so
  reprocessing the same candle is a harmless no-op (`ON CONFLICT DO
  NOTHING`). Telegram sends are separately idempotent via a
  claim-before-send column (`telegram_sent_at`) — a retry can never
  double-send.
- A signal discovered late (its candle closed some time ago, not just
  now) is checked against the current price before alerting
  (`strategy/actionability.py`): if price already ran past the stop or a
  target, or the setup's own expiration already passed, it's recorded as
  `missed_reason` and — if Telegram is configured — sent as a distinct
  "⚠️ SETUP DETECTED LATE — DO NOT ENTER" notice, never as a live entry.
- Scheduler/data-feed health is tracked in `scheduler_runs` and
  `scheduler_alert_state`: if two expected 5-minute scan intervals
  (10 minutes) pass without a successful run, a "🛑 SYSTEM HEALTH" notice
  is sent once (not every run while still down); a "✅ SYSTEM RECOVERED"
  notice fires once when it clears. Both are visually and structurally
  distinct from trade alerts and never confused with one.
- Only the existing strict A+ tier is ever sent to Telegram here. The
  A/WATCHLIST classification work (`strategy/classification.py`) is not
  wired into this pipeline — that's deliberately deferred until its
  out-of-sample backtest results justify activation.

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
