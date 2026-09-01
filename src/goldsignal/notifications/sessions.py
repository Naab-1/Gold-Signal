"""Dynamic trading-session labeling for the Ghanaian user context.

Session windows are computed from real IANA timezones (Europe/London,
America/New_York), not hardcoded UTC offsets, so London/New York
daylight-saving transitions are handled automatically. Ghana
(Africa/Accra) has no DST, but it's converted the same way for
consistency rather than hand-rolling a fixed +00:00 offset.

Session hours are an approximation of typical forex trading-session
hours in each market's own local time — not an authoritative exchange
schedule.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

_LONDON = ZoneInfo("Europe/London")
_NEW_YORK = ZoneInfo("America/New_York")
_ACCRA = ZoneInfo("Africa/Accra")

_LONDON_OPEN, _LONDON_CLOSE = time(8, 0), time(16, 30)
_NEW_YORK_OPEN, _NEW_YORK_CLOSE = time(8, 0), time(17, 0)


def session_label(utc_timestamp: datetime) -> str:
    london_local = utc_timestamp.astimezone(_LONDON).time()
    new_york_local = utc_timestamp.astimezone(_NEW_YORK).time()

    in_london = _LONDON_OPEN <= london_local < _LONDON_CLOSE
    in_new_york = _NEW_YORK_OPEN <= new_york_local < _NEW_YORK_CLOSE

    if in_london and in_new_york:
        return "London–New York overlap"
    if in_london:
        return "London session"
    if in_new_york:
        return "New York session"
    return "outside major sessions"


def to_accra_time(utc_timestamp: datetime) -> datetime:
    return utc_timestamp.astimezone(_ACCRA)
