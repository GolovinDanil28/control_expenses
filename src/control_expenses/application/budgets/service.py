"""Сценарии месячного бюджета: лимит, статус, фиксация порога и превышения.

Один сценарий спецификации ``budgets`` = одна ветка сервиса. Взносы обязательств
(``commitments``) в остаток попадут, когда появится та capability; формула и
фиксации уже принимают их через ``committed``.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from decimal import Decimal

from control_expenses.application.money_text import parse_amount_text
from control_expenses.application.ports import (
    BudgetRepository,
    BudgetStateRepository,
    Clock,
    ExpenseRepository,
    ObligationQuery,
)
from control_expenses.application.replies import TextReply
from control_expenses.domain.budget import (
    BudgetStatus,
    days_left_in_month,
    month_bounds,
    period_of,
    threshold_reached,
)
from control_expenses.domain.money import Money

_PERIOD_RE = re.compile(r"\d{4}-\d{2}")


class BudgetService:
    """Сценарии установки лимита и состояния бюджета месяца."""

    def __init__(
        self,
        *,
        clock: Clock,
        expenses: ExpenseRepository,
        budgets: BudgetRepository,
        states: BudgetStateRepository,
        default_limit: Money | None,
        threshold_ratio: Decimal,
        obligations: ObligationQuery | None = None,
    ) -> None:
        self._clock = clock
        self._expenses = expenses
        self._budgets = budgets
        self._states = states
        self._default_limit = default_limit
        self._threshold_ratio = threshold_ratio
        self._obligations = obligations

    def handle_command(self, arguments: str) -> TextReply:
        """`/budget` без аргументов — текущий статус; с суммой — установка лимита."""
        if not arguments.strip():
            return TextReply(self._status_text())
        return self._set_limit(arguments)

    def limit_for(self, period: str) -> Money | None:
        """Лимит месяца: явный, иначе лимит по умолчанию, иначе ``None``."""
        explicit = self._budgets.limit_for(period)
        return explicit if explicit is not None else self._default_limit

    def month_status(self) -> tuple[str, BudgetStatus | None, Money]:
        """Публичная оценка текущего месяца — для отчётов и недельной сводки."""
        return self._evaluate()

    def record_after_expense(self) -> None:
        """Оценить бюджет после записи траты и один раз за месяц зафиксировать событие.

        Доставку оповещений берёт на себя capability ``reminders``: здесь только
        фиксация состояния, поэтому тихий час и дедупликация соблюдаются.
        """
        period, status, _ = self._evaluate()
        if status is None:
            return
        state = self._states.get(period)
        if status.is_over and not state.overrun_fixed:
            self._states.save(
                replace(
                    state,
                    overrun_fixed=True,
                    threshold_fixed=True,
                    overrun=status.overrun,
                )
            )
            return
        if not state.threshold_fixed and threshold_reached(
            status.limit, status.covered, self._threshold_ratio
        ):
            self._states.save(replace(state, threshold_fixed=True))

    def _set_limit(self, arguments: str) -> TextReply:
        period = period_of(self._clock.today())
        amount_text = arguments
        match = _PERIOD_RE.search(arguments)
        if match is not None:
            if not _is_valid_period(match.group(0)):
                return TextReply("Некорректный период. Формат: ГГГГ-ММ, например 2026-11.")
            period = match.group(0)
            amount_text = arguments[: match.start()] + arguments[match.end() :]
        amount = parse_amount_text(amount_text)
        if amount is None or amount.is_zero or amount.is_negative:
            return TextReply("Лимит должен быть положительным числом, например: /budget 60000")
        self._budgets.set_limit(period, amount)
        return TextReply(self._limit_confirmation(period))

    def _limit_confirmation(self, period: str) -> str:
        limit = self.limit_for(period)
        assert limit is not None  # лимит только что записан
        today = self._clock.today()
        if period != period_of(today):
            return f"Лимит на {period}: {limit.format_ru()}."
        status = self._build_status(today, limit, self._spent(today))
        remaining = status.remaining.format_ru()
        return (
            f"Лимит на {period}: {limit.format_ru()}.\n"
            f"Остаток: {remaining}, дневная норма: {status.daily.format_ru()}."
        )

    def _status_text(self) -> str:
        period, status, spent = self._evaluate()
        if status is None:
            return (
                f"Бюджет на {period} не настроен. Потрачено: {spent.format_ru()}.\n"
                "Задайте лимит: /budget 60000"
            )
        lines = [
            f"Бюджет на {period}: {status.limit.format_ru()}",
            f"Потрачено: {status.spent.format_ru()}",
            f"Остаток: {status.remaining.format_ru()}",
            f"Дневная норма: {status.daily.format_ru()}",
        ]
        if status.is_over:
            lines.append(f"Перебор: {status.overrun.format_ru()}")
        elif self._states.get(period).threshold_fixed:
            percent = int(self._threshold_ratio * 100)
            lines.append(f"Достигнут порог {percent}%: покрыто {status.covered.format_ru()}.")
        if status.is_estimate:
            lines.append("Остаток — оценка: суммы обязательств ещё не введены.")
        return "\n".join(lines)

    def _evaluate(self) -> tuple[str, BudgetStatus | None, Money]:
        today = self._clock.today()
        period = period_of(today)
        spent = self._spent(today)
        limit = self.limit_for(period)
        if limit is None:
            return period, None, spent
        return period, self._build_status(today, limit, spent), spent

    def _build_status(self, today: date, limit: Money, spent: Money) -> BudgetStatus:
        committed, is_estimate = self._month_obligations(today)
        return BudgetStatus(
            limit=limit,
            spent=spent,
            committed=committed,
            days_left=days_left_in_month(today),
            is_estimate=is_estimate,
        )

    def _month_obligations(self, today: date) -> tuple[Money, bool]:
        if self._obligations is None:
            return Money.zero(), False
        return self._obligations.month_obligations(period_of(today))

    def _spent(self, today: date) -> Money:
        start, end = month_bounds(today)
        return self._expenses.spent_between(start, end)


def _is_valid_period(period: str) -> bool:
    year, _, month = period.partition("-")
    return int(year) > 0 and 1 <= int(month) <= 12
