from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from spatalk.tenants.schema import WEEKDAYS, TenantConfig

Urgency = Literal["normal", "urgent"]


def _parse(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


class BusinessCalendar:
    """Business-hours arithmetic in the tenant's timezone. Every result is aware and in UTC."""

    def __init__(self, cfg: TenantConfig):
        self._cfg = cfg
        self._tz = ZoneInfo(cfg.timezone)

    def _local(self, at: datetime) -> datetime:
        return at.astimezone(self._tz)

    def _spans_on(self, day: datetime) -> list[tuple[datetime, datetime]]:
        if day.date() in self._cfg.holidays:
            return []
        key = WEEKDAYS[day.weekday()]
        out = []
        for start, end in self._cfg.hours.get(key, []):
            s = datetime.combine(day.date(), _parse(start), tzinfo=self._tz)
            e = datetime.combine(day.date(), _parse(end), tzinfo=self._tz)
            out.append((s, e))
        return out

    def is_open(self, at: datetime) -> bool:
        loc = self._local(at)
        return any(s <= loc < e for s, e in self._spans_on(loc))

    def next_open(self, at: datetime) -> datetime:
        loc = self._local(at)
        for offset in range(0, 15):
            day = loc + timedelta(days=offset)
            for s, e in self._spans_on(day):
                if offset == 0 and s <= loc < e:
                    return loc.astimezone(timezone.utc)
                if s > loc:
                    return s.astimezone(timezone.utc)
        raise ValueError("no opening hours in the next two weeks")

    def add_business_hours(self, at: datetime, hours: float) -> datetime:
        remaining = timedelta(hours=hours)
        cursor = self._local(self.next_open(at))
        for _ in range(60):
            for s, e in self._spans_on(cursor):
                if cursor < s:
                    cursor = s
                if s <= cursor < e:
                    room = e - cursor
                    if remaining <= room:
                        return (cursor + remaining).astimezone(timezone.utc)
                    remaining -= room
                    cursor = e
            cursor = datetime.combine(
                (cursor + timedelta(days=1)).date(), time(0, 0), tzinfo=self._tz
            )
        raise ValueError("could not place due time within 60 days")

    def due_for(self, urgency: Urgency, at: datetime) -> datetime:
        if urgency == "urgent":
            return at.astimezone(timezone.utc) + timedelta(
                minutes=self._cfg.escalation.urgent_minutes
            )
        return self.add_business_hours(at, self._cfg.escalation.standard_business_hours)


def _clock(t: datetime) -> str:
    h = t.hour % 12 or 12
    suffix = "a.m." if t.hour < 12 else "p.m."
    return f"{h}:{t.minute:02d} {suffix}"


def humanize_due(due: datetime, now: datetime, tz: str, urgent: bool) -> str:
    if urgent:
        minutes = max(1, round((due - now).total_seconds() / 60))
        return f"within {minutes} minutes"
    z = ZoneInfo(tz)
    d, n = due.astimezone(z), now.astimezone(z)
    if d.date() == n.date():
        return f"by {_clock(d)} today"
    if d.date() == (n + timedelta(days=1)).date():
        return f"by {_clock(d)} tomorrow"
    return f"by {_clock(d)} on {d.strftime('%A')}"
