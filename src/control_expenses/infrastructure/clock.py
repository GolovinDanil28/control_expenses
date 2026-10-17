"""Системные часы в настроенной таймзоне."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


class SystemClock:
    """Реализация порта ``Clock`` поверх системного времени."""

    def __init__(self, timezone: str) -> None:
        self._zone = ZoneInfo(timezone)

    def now(self) -> datetime:
        return datetime.now(self._zone)

    def today(self) -> date:
        return self.now().date()
