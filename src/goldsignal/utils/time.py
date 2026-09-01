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
