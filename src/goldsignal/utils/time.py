"""UTC time helpers shared across GoldSignal."""

from datetime import UTC, datetime, timedelta


def is_utc(dt: datetime) -> bool:
    """Return True if `dt` is timezone-aware and expressed in UTC (zero offset)."""
    return dt.tzinfo is not None and dt.utcoffset() == timedelta(0)


def require_utc(dt: datetime, *, field_name: str = "timestamp") -> datetime:
    """Raise ValueError unless `dt` is a timezone-aware UTC datetime."""
    if not is_utc(dt):
        raise ValueError(f"{field_name} must be a timezone-aware UTC datetime, got {dt!r}")
    return dt


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def floor_to_duration(dt: datetime, duration: timedelta) -> datetime:
    """Round `dt` down to the most recent multiple of `duration` since the
    epoch — used to compute "the latest closed candle we'd expect right
    now" for a given timeframe.
    """
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    elapsed = dt - epoch
    whole_periods = elapsed // duration
    return epoch + whole_periods * duration


def format_timedelta(delta: timedelta) -> str:
    """Human-readable duration for Telegram messages, e.g. "4h 43m" or
    "36h 12m" — never negative, floors to whole minutes.
    """
    total_minutes = max(0, int(delta.total_seconds() // 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours == 0:
        return f"{minutes}m"
    return f"{hours}h {minutes}m"
