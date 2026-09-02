"""Signal-journal schema. A single `signals` table — every emitted signal
(including NO_TRADE, so "why" is always auditable) is stored here.

`signal_id` (instrument+mode+timeframe+candle timestamp+direction+version)
is already the idempotency key for *evaluating* a candle: reprocessing the
same closed candle produces the same row and `ON CONFLICT DO NOTHING`
no-ops it. `telegram_sent_at`/`missed_reason` extend that same row to make
the *alerting* step idempotent too, and to record setups discovered too
late (during a scheduler-gap catch-up sweep) to still be actionable.

`scan_checkpoints`/`scheduler_runs`/`scheduler_alert_state` support durable,
gap-tolerant catch-up processing: a checkpoint per (strategy, version,
timeframe, provider, instrument) tracks the last successfully processed
closed candle, an append-only run log gives the monitoring numbers
(last invocation, last success, gap duration), and the alert-state row
makes the health/recovery Telegram notices transition-based (sent once
per state change, not once per run).
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT PRIMARY KEY,
    instrument TEXT NOT NULL,
    strategy_mode TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_timeframe TEXT NOT NULL,
    confirmation_timeframe TEXT NOT NULL,
    signal_timestamp TIMESTAMPTZ NOT NULL,
    entry_price DOUBLE PRECISION,
    stop_loss DOUBLE PRECISION,
    targets_json TEXT NOT NULL,
    confidence_score DOUBLE PRECISION NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    telegram_sent_at TIMESTAMPTZ,
    missed_reason TEXT,
    detected_late BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_signals_mode_instrument_time
    ON signals (strategy_mode, instrument, signal_timestamp DESC);

ALTER TABLE signals ADD COLUMN IF NOT EXISTS telegram_sent_at TIMESTAMPTZ;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS missed_reason TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS detected_late BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS scan_checkpoints (
    strategy_mode TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    entry_timeframe TEXT NOT NULL,
    data_provider TEXT NOT NULL,
    instrument TEXT NOT NULL,
    last_processed_candle_close TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (strategy_mode, strategy_version, entry_timeframe, data_provider, instrument)
);

CREATE TABLE IF NOT EXISTS scheduler_runs (
    id BIGSERIAL PRIMARY KEY,
    strategy_mode TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    succeeded BOOLEAN,
    candles_processed INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_scheduler_runs_mode_time
    ON scheduler_runs (strategy_mode, strategy_version, started_at DESC);

CREATE TABLE IF NOT EXISTS scheduler_alert_state (
    strategy_mode TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    is_healthy BOOLEAN NOT NULL DEFAULT true,
    unhealthy_since TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (strategy_mode, strategy_version)
);
"""
