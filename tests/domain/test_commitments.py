"""Тесты правил обязательств: день месяца и ближайшее наступление."""

from datetime import date

import pytest

from control_expenses.domain.commitments import (
    clamp_to_month,
    next_occurrence,
    occurrence_date,
)
from control_expenses.domain.errors import InvalidDayOfMonthError


def test_clamp_to_month_february() -> None:
    assert clamp_to_month(2026, 2, 31) == date(2026, 2, 28)
    assert clamp_to_month(2024, 2, 31) == date(2024, 2, 29)
    assert clamp_to_month(2026, 10, 5) == date(2026, 10, 5)


def test_occurrence_date_in_period() -> None:
    assert occurrence_date(5, "2026-10") == date(2026, 10, 5)
    assert occurrence_date(31, "2026-02") == date(2026, 2, 28)


def test_next_occurrence_current_month() -> None:
    assert next_occurrence(20, date(2026, 10, 16)) == date(2026, 10, 20)
    assert next_occurrence(16, date(2026, 10, 16)) == date(2026, 10, 16)


def test_next_occurrence_moves_to_next_month() -> None:
    assert next_occurrence(5, date(2026, 10, 16)) == date(2026, 11, 5)


def test_next_occurrence_wraps_year() -> None:
    assert next_occurrence(1, date(2026, 12, 15)) == date(2027, 1, 1)


def test_next_occurrence_clamps_short_month() -> None:
    assert next_occurrence(31, date(2026, 2, 10)) == date(2026, 2, 28)


def test_next_occurrence_rejects_bad_day() -> None:
    with pytest.raises(InvalidDayOfMonthError):
        next_occurrence(0, date(2026, 10, 16))
