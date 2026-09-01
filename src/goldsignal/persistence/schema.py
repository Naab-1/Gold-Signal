"""Signal-journal schema. A single `signals` table — every emitted signal
(including NO_TRADE, so "why" is always auditable) is stored here.
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signals_mode_instrument_time
    ON signals (strategy_mode, instrument, signal_timestamp DESC);
"""
