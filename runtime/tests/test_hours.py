from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

TOR = ZoneInfo("America/Toronto")
BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle
    return load_bundle(BUNDLE)


def _at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TOR)


def test_is_open_uses_tenant_hours():
    from spatalk.brain.hours import BusinessCalendar
    cal = BusinessCalendar(_cfg())
    assert cal.is_open(_at(2026, 9, 1, 14))          # Tue 14:00, open 10-18
    assert not cal.is_open(_at(2026, 9, 1, 19))      # Tue 19:00
    assert not cal.is_open(_at(2026, 8, 31, 11))     # Mon 11:00, opens 12:00


def test_next_open_after_close_is_next_day_opening():
    from spatalk.brain.hours import BusinessCalendar
    cal = BusinessCalendar(_cfg())
    nxt = cal.next_open(_at(2026, 9, 1, 19)).astimezone(TOR)
    assert (nxt.day, nxt.hour, nxt.minute) == (2, 10, 0)


def test_next_open_when_open_is_now():
    from spatalk.brain.hours import BusinessCalendar
    cal = BusinessCalendar(_cfg())
    at = _at(2026, 9, 1, 14)
    assert cal.next_open(at) == at.astimezone(timezone.utc)


def test_add_business_hours_rolls_over_close():
    from spatalk.brain.hours import BusinessCalendar
    cal = BusinessCalendar(_cfg())
    # Tue 16:30 + 3h business = 1.5h to close (18:00) + 1.5h next day from 10:00 = Wed 11:30
    out = cal.add_business_hours(_at(2026, 9, 1, 16, 30), 3).astimezone(TOR)
    assert (out.day, out.hour, out.minute) == (2, 11, 30)


def test_due_for_urgent_is_wall_clock():
    from spatalk.brain.hours import BusinessCalendar
    cal = BusinessCalendar(_cfg())
    at = _at(2026, 9, 1, 23)
    assert (cal.due_for("urgent", at) - at.astimezone(timezone.utc)).total_seconds() == 15 * 60


def test_due_for_normal_after_hours_lands_next_morning():
    from spatalk.brain.hours import BusinessCalendar
    cal = BusinessCalendar(_cfg())
    due = cal.due_for("normal", _at(2026, 9, 1, 23)).astimezone(TOR)
    assert (due.day, due.hour, due.minute) == (2, 13, 0)


def test_humanize_due():
    from spatalk.brain.hours import humanize_due
    now = _at(2026, 9, 1, 23)
    assert humanize_due(_at(2026, 9, 1, 23, 15), now, "America/Toronto", urgent=True) == "within 15 minutes"
    assert humanize_due(_at(2026, 9, 2, 13), now, "America/Toronto", urgent=False) == "by 1:00 p.m. tomorrow"
    assert humanize_due(_at(2026, 9, 1, 23, 30), now, "America/Toronto", urgent=False) == "by 11:30 p.m. today"
    assert humanize_due(_at(2026, 9, 3, 10), now, "America/Toronto", urgent=False) == "by 10:00 a.m. on Thursday"
