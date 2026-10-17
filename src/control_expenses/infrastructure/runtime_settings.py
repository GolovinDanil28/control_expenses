"""Перенос настроек расписания из окружения в БД.

Значения из окружения задают defaults: уже сохранённые в БД настройки (в том
числе изменённые командой ``/schedule``) не перезатираются.
"""

from __future__ import annotations

from control_expenses.application.ports import SettingsRepository
from control_expenses.infrastructure.config import Settings

RUNTIME_KEYS = (
    "weekly_report_dow",
    "weekly_report_time",
    "quiet_start",
    "quiet_end",
    "timezone",
)


def seed_runtime_settings(repo: SettingsRepository, settings: Settings) -> None:
    """Записать значения по умолчанию для отсутствующих ключей расписания."""
    defaults = {
        "weekly_report_dow": str(settings.weekly_report_dow),
        "weekly_report_time": settings.weekly_report_time,
        "quiet_start": settings.quiet_start,
        "quiet_end": settings.quiet_end,
        "timezone": settings.timezone,
    }
    for key in RUNTIME_KEYS:
        if repo.get(key) is None:
            repo.set(key, defaults[key])
