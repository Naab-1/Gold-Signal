from datetime import UTC, datetime

from goldsignal.notifications.sessions import session_label, to_accra_time


def test_london_session_winter():
    # Jan 15 2026, 10:00 UTC -> London local 10:00 GMT (in window), NY local 05:00 EST (closed)
    dt = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
    assert session_label(dt) == "London session"


def test_overlap_in_summer_but_not_winter_at_same_utc_hour():
    """Proves DST is handled dynamically, not via a hardcoded UTC offset:
    the same UTC clock hour (12:00) is London-only in winter but an
    overlap in summer, because only New York observes a different DST
    transition date/offset than London.
    """
    winter = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    summer = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    assert session_label(winter) == "London session"
    assert session_label(summer) == "London–New York overlap"


def test_new_york_session_after_london_closes():
    # Jan 15 2026, 18:00 UTC -> London local 18:00 (closed), NY local 13:00 EST (open)
    dt = datetime(2026, 1, 15, 18, 0, tzinfo=UTC)
    assert session_label(dt) == "New York session"


def test_outside_major_sessions():
    # Jan 15 2026, 02:00 UTC -> both London and New York closed
    dt = datetime(2026, 1, 15, 2, 0, tzinfo=UTC)
    assert session_label(dt) == "outside major sessions"


def test_to_accra_time_matches_utc_no_dst():
    dt = datetime(2026, 6, 1, 12, 30, tzinfo=UTC)
    accra = to_accra_time(dt)
    assert accra.hour == 12
    assert accra.minute == 30
