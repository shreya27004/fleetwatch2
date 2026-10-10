"""Time sources.

The registry never calls ``datetime.now()`` directly. It asks a ``Clock``.
Production uses ``SystemClock``; tests use ``FakeClock`` and jump forward
instantly, so the 30-second timeout can be tested without sleeping.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 9, 21, 10, 30, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
