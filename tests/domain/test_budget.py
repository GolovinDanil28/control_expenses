"""Тесты правил бюджета: сценарии capability ``budgets``."""

from datetime import date
from decimal import Decimal

from control_expenses.domain.budget import (
    BudgetStatus,
    CommitmentObligation,
    committed_total,
    days_left_in_month,
    month_bounds,
    period_of,
    threshold_reached,
)
from control_expenses.domain.money import Money


def _status(
    limit: str,
    spent: str = "0",
    committed: str = "0",
    days_left: int = 30,
    *,
    is_estimate: bool = False,
) -> BudgetStatus:
    return BudgetStatus(
        limit=Money.from_rubles(limit),
        spent=Money.from_rubles(spent),
        committed=Money.from_rubles(committed),
        days_left=days_left,
        is_estimate=is_estimate,
    )


def test_days_left_includes_today() -> None:
    # Октябрь: 31 день. 2026-10-16 → 31 − 16 + 1 = 16
    assert days_left_in_month(date(2026, 10, 16)) == 16


def test_days_left_last_day_of_month() -> None:
    assert days_left_in_month(date(2026, 10, 31)) == 1


def test_month_bounds() -> None:
    start, end = month_bounds(date(2026, 10, 16))
    assert start == date(2026, 10, 1)
    assert end == date(2026, 10, 31)


def test_month_bounds_february() -> None:
    start, end = month_bounds(date(2026, 2, 10))
    assert start == date(2026, 2, 1)
    assert end == date(2026, 2, 28)


def test_period_of() -> None:
    assert period_of(date(2026, 10, 16)) == "2026-10"
    assert period_of(date(2026, 1, 5)) == "2026-01"


def test_committed_total_sums_amounts() -> None:
    total, rough = committed_total(
        [
            CommitmentObligation(Money.from_rubles("15000")),
            CommitmentObligation(Money.from_rubles("500")),
        ]
    )
    assert total.format_ru() == "15 500 ₽"
    assert rough is False


def test_committed_total_excludes_unknown_variable_and_flags_estimate() -> None:
    total, rough = committed_total(
        [
            CommitmentObligation(Money.from_rubles("15000")),
            CommitmentObligation(None),
        ]
    )
    assert total.format_ru() == "15 000 ₽"
    assert rough is True


def test_committed_total_flags_history_based_estimate() -> None:
    total, rough = committed_total(
        [CommitmentObligation(Money.from_rubles("3000"), is_estimate=True)]
    )
    assert total.format_ru() == "3 000 ₽"
    assert rough is True


def test_commitment_reduces_remaining() -> None:
    # лимит 60 000, потрачено 20 000, обязательство 15 000 → остаток 25 000
    status = _status("60000", spent="20000", committed="15000")
    assert status.remaining.format_ru() == "25 000 ₽"


def test_daily_norm_rounds_down() -> None:
    # остаток 10 000 за 3 дня → 3 333 ₽ 33 коп
    status = _status("10000", days_left=3)
    assert status.daily.format_ru() == "3 333 ₽ 33 коп"


def test_daily_norm_plain() -> None:
    # остаток 25 000 за 10 дней → 2 500 ₽
    status = _status("25000", days_left=10)
    assert status.daily.format_ru() == "2 500 ₽"


def test_daily_norm_last_day() -> None:
    status = _status("3000", days_left=1)
    assert status.daily.format_ru() == "3 000 ₽"


def test_negative_remaining_means_overrun_and_zero_norm() -> None:
    status = _status("1000", spent="1500", days_left=5)
    assert status.is_over is True
    assert status.daily.format_ru() == "0 ₽"
    assert status.overrun.format_ru() == "500 ₽"


def test_no_overrun_when_within_limit() -> None:
    status = _status("1000", spent="400", days_left=5)
    assert status.is_over is False
    assert status.overrun.is_zero


def test_covered_is_spent_plus_committed() -> None:
    status = _status("60000", spent="20000", committed="15000")
    assert status.covered.format_ru() == "35 000 ₽"


def test_threshold_reached() -> None:
    limit = Money.from_rubles("60000")
    covered = Money.from_rubles("48000")
    assert threshold_reached(limit, covered, Decimal("0.8")) is True
    assert threshold_reached(limit, covered, Decimal("0.9")) is False


def test_threshold_with_zero_limit_is_false() -> None:
    assert threshold_reached(Money.zero(), Money.from_rubles("1"), Decimal("0.5")) is False
