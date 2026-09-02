from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    def __init__(self, at: datetime):
        if at.tzinfo is None:
            raise ValueError("FixedClock needs an aware datetime")
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, **kwargs) -> None:
        self._at = self._at + timedelta(**kwargs)
