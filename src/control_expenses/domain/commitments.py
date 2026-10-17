"""Правила обязательств: день месяца и ближайшее наступление.

День платежа может быть больше длины месяца (например, 31-е в феврале) — дата
прижимается к последнему дню месяца.
"""

from __future__ import annotations

import calendar
from datetime import date

from control_expenses.domain.errors import InvalidDayOfMonthError

FIRST_DAY_OF_MONTH = 1
LAST_DAY_OF_MONTH = 31
MONTHS_IN_YEAR = 12


def clamp_to_month(year: int, month: int, day: int) -> date:
    """Дата ``day`` в указанном месяце, прижатая к его длине."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def occurrence_date(day_of_month: int, period: str) -> date:
    """Дата наступления обязательства в месяце ``period`` (``YYYY-MM``)."""
    year, _, month = period.partition("-")
    return clamp_to_month(int(year), int(month), day_of_month)


def next_occurrence(day_of_month: int, today: date) -> date:
    """Ближайшая дата наступления: в текущем месяце или в следующем."""
    if not FIRST_DAY_OF_MONTH <= day_of_month <= LAST_DAY_OF_MONTH:
        raise InvalidDayOfMonthError(f"day_of_month must be 1..31, got {day_of_month}")
    current = clamp_to_month(today.year, today.month, day_of_month)
    if current >= today:
        return current
    if today.month == MONTHS_IN_YEAR:
        return clamp_to_month(today.year + 1, 1, day_of_month)
    return clamp_to_month(today.year, today.month + 1, day_of_month)
