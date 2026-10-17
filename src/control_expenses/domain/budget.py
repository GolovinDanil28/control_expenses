"""Правила месячного бюджета.

Здесь только арифметика на ``Decimal``: остаток месяца с учётом обязательств,
дневная норма с округлением вниз, порог приближения и состояние превышения.
Доставка оповещений — capability ``reminders``.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from control_expenses.domain.money import Money


def days_left_in_month(today: date) -> int:
    """Число дней от ``today`` до конца месяца включительно."""
    last_day = calendar.monthrange(today.year, today.month)[1]
    return last_day - today.day + 1


def month_bounds(day: date) -> tuple[date, date]:
    """Первый и последний день месяца, к которому относится ``day``."""
    last_day = calendar.monthrange(day.year, day.month)[1]
    return date(day.year, day.month, 1), date(day.year, day.month, last_day)


def period_of(day: date) -> str:
    """Идентификатор месяца в формате ``YYYY-MM``."""
    return f"{day.year:04d}-{day.month:02d}"


@dataclass(frozen=True)
class CommitmentObligation:
    """Неоплаченное обязательство месяца для расчёта остатка.

    ``amount is None`` — плавающее обязательство, фактическая сумма которого ещё
    ни разу не вводилась. ``is_estimate`` — сумма взята из прошлого месяца и
    остаток помечается как оценка.
    """

    amount: Money | None
    is_estimate: bool = False


def committed_total(obligations: Sequence[CommitmentObligation]) -> tuple[Money, bool]:
    """Сумма обязательств месяца и признак «оценка грубая».

    Плавающее обязательство без известной суммы не включается в сумму, но
    помечает результат как требующий уточнения.
    """
    total = Money.zero()
    rough = False
    for obligation in obligations:
        if obligation.amount is None:
            rough = True
            continue
        total = total + obligation.amount
        rough = rough or obligation.is_estimate
    return total, rough


@dataclass(frozen=True)
class BudgetStatus:
    """Состояние бюджета месяца на конкретный момент."""

    limit: Money
    spent: Money
    committed: Money
    days_left: int
    is_estimate: bool = False

    @property
    def remaining(self) -> Money:
        """Остаток месяца: лимит минус обязательства минус потраченное."""
        return self.limit - self.committed - self.spent

    @property
    def is_over(self) -> bool:
        return self.remaining.is_negative

    @property
    def overrun(self) -> Money:
        """Сумма перебора лимита (ноль, если лимит не превышен)."""
        return -self.remaining if self.is_over else Money.zero()

    @property
    def daily(self) -> Money:
        """Дневная норма с округлением вниз; ноль при превышении лимита."""
        if self.is_over or self.days_left <= 0:
            return Money.zero()
        return self.remaining // self.days_left

    @property
    def covered(self) -> Money:
        """Доля лимита, покрытая тратами и неоплаченными обязательствами."""
        return self.spent + self.committed


def threshold_reached(limit: Money, covered: Money, ratio: Decimal) -> bool:
    """Достигнут ли порог ``ratio`` от лимита суммой ``covered``."""
    if limit.is_zero:
        return False
    return covered.rubles >= limit.rubles * ratio
