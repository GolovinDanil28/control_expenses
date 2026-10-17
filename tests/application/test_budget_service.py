"""Тесты use case'ов бюджета на фейковых портах: сценарии capability ``budgets``."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import NamedTuple

import pytest

from control_expenses.application.budgets.service import BudgetService
from control_expenses.application.budgets.state import BudgetState
from control_expenses.application.replies import TextReply
from control_expenses.domain.entities import Expense
from control_expenses.domain.money import Money

TODAY = date(2026, 10, 16)
PERIOD = "2026-10"


class FakeClock:
    def now(self) -> datetime:
        return datetime.combine(TODAY, time(12, 0), tzinfo=UTC)

    def today(self) -> date:
        return TODAY


class FakeExpenseRepository:
    def __init__(self, items: list[Expense] | None = None) -> None:
        self.items: list[Expense] = items if items is not None else []

    def add(self, expense: Expense) -> Expense:
        saved = replace(expense, id=len(self.items) + 1)
        self.items.append(saved)
        return saved

    def update(self, expense: Expense) -> Expense:
        return expense

    def last(self, source_chat_id: int) -> Expense | None:
        return None

    def delete(self, expense_id: int) -> None:
        self.items = [item for item in self.items if item.id != expense_id]

    def spent_between(self, start: date, end: date) -> Money:
        total = Money.zero()
        for item in self.items:
            if start <= item.spent_on <= end:
                total = total + item.amount
        return total


class FakeBudgetRepository:
    def __init__(self) -> None:
        self.limits: dict[str, Money] = {}

    def limit_for(self, period: str) -> Money | None:
        return self.limits.get(period)

    def set_limit(self, period: str, limit: Money) -> None:
        self.limits[period] = limit


class FakeBudgetStateRepository:
    def __init__(self) -> None:
        self.states: dict[str, BudgetState] = {}

    def get(self, period: str) -> BudgetState:
        return self.states.get(period, BudgetState(period=period))

    def save(self, state: BudgetState) -> None:
        self.states[state.period] = state


class Env(NamedTuple):
    service: BudgetService
    expenses: FakeExpenseRepository
    budgets: FakeBudgetRepository
    states: FakeBudgetStateRepository


def _expense(amount: str, spent_on: date = TODAY) -> Expense:
    return Expense(
        amount=Money.from_rubles(amount),
        spent_on=spent_on,
        source_chat_id=1,
        category="Еда",
    )


def _env(default_limit: str | None = None, ratio: str = "0.8") -> Env:
    expenses = FakeExpenseRepository()
    budgets = FakeBudgetRepository()
    states = FakeBudgetStateRepository()
    service = BudgetService(
        clock=FakeClock(),
        expenses=expenses,
        budgets=budgets,
        states=states,
        default_limit=None if default_limit is None else Money.from_rubles(default_limit),
        threshold_ratio=Decimal(ratio),
    )
    return Env(service=service, expenses=expenses, budgets=budgets, states=states)


@pytest.fixture
def env() -> Env:
    return _env()


def _text(reply: TextReply) -> str:
    return reply.text


def test_status_without_limit_reports_not_configured(env: Env) -> None:
    text = _text(env.service.handle_command(""))
    assert "не настроен" in text


def test_set_limit_for_current_month(env: Env) -> None:
    env.expenses.items.append(_expense("20000"))
    text = _text(env.service.handle_command("60000"))
    assert env.budgets.limits[PERIOD].format_ru() == "60 000 ₽"
    assert "Остаток: 40 000 ₽" in text
    assert "дневная норма: 2 500 ₽" in text


def test_set_limit_for_future_month_keeps_current(env: Env) -> None:
    env.service.handle_command("65000 2026-11")
    assert env.budgets.limits["2026-11"].format_ru() == "65 000 ₽"
    assert PERIOD not in env.budgets.limits


def test_set_limit_rejects_zero_and_text(env: Env) -> None:
    zero = _text(env.service.handle_command("0"))
    text = _text(env.service.handle_command("abc"))
    assert "положительным" in zero
    assert "положительным" in text
    assert env.budgets.limits == {}


def test_set_limit_rejects_bad_period(env: Env) -> None:
    reply = _text(env.service.handle_command("65000 2026-13"))
    assert "Некорректный период" in reply
    assert env.budgets.limits == {}


def test_default_limit_used_when_month_has_no_explicit(env: Env) -> None:
    env = _env(default_limit="60000")
    assert env.service.limit_for(PERIOD) is not None
    assert env.service.limit_for(PERIOD) == Money.from_rubles("60000")


def test_status_shows_overrun(env: Env) -> None:
    env.service.handle_command("1000")
    env.expenses.items.append(_expense("1500"))
    text = _text(env.service.handle_command(""))
    assert "Перебор: 500 ₽" in text
    assert "Дневная норма: 0 ₽" in text


def test_record_after_expense_fixes_overrun_once(env: Env) -> None:
    env.service.handle_command("1000")
    env.expenses.items.append(_expense("1500"))
    env.service.record_after_expense()
    state = env.states.get(PERIOD)
    assert state.overrun_fixed is True
    assert state.overrun.format_ru() == "500 ₽"
    assert state.threshold_fixed is True
    env.service.record_after_expense()
    assert env.states.get(PERIOD).overrun.format_ru() == "500 ₽"


def test_record_after_expense_fixes_threshold_once(env: Env) -> None:
    env.service.handle_command("10000")
    env.expenses.items.append(_expense("8000"))
    env.service.record_after_expense()
    state = env.states.get(PERIOD)
    assert state.threshold_fixed is True
    assert state.overrun_fixed is False
    assert env.service.handle_command("").text.count("Достигнут порог 80%") == 1


def test_record_after_expense_quiet_when_within_limit(env: Env) -> None:
    env.service.handle_command("10000")
    env.expenses.items.append(_expense("1000"))
    env.service.record_after_expense()
    state = env.states.get(PERIOD)
    assert state.threshold_fixed is False
    assert state.overrun_fixed is False


def test_record_after_expense_without_limit_is_quiet(env: Env) -> None:
    env.expenses.items.append(_expense("1000"))
    env.service.record_after_expense()
    assert env.states.states == {}


class FakeObligations:
    def __init__(self, total: Money, rough: bool = False) -> None:
        self._total = total
        self._rough = rough

    def month_obligations(self, period: str) -> tuple[Money, bool]:
        return self._total, self._rough


def _service_with_obligations(total: str) -> tuple[BudgetService, FakeExpenseRepository]:
    expenses = FakeExpenseRepository()
    service = BudgetService(
        clock=FakeClock(),
        expenses=expenses,
        budgets=FakeBudgetRepository(),
        states=FakeBudgetStateRepository(),
        default_limit=None,
        threshold_ratio=Decimal("0.8"),
        obligations=FakeObligations(Money.from_rubles(total)),
    )
    return service, expenses


def test_status_accounts_for_obligations() -> None:
    service, expenses = _service_with_obligations("15000")
    expenses.items.append(_expense("20000"))
    service.handle_command("60000")
    text = service.handle_command("").text
    # лимит 60 000, потрачено 20 000, обязательство 15 000 → остаток 25 000
    assert "Остаток: 25 000 ₽" in text


def test_obligations_reported_as_estimate() -> None:
    expenses = FakeExpenseRepository()
    service = BudgetService(
        clock=FakeClock(),
        expenses=expenses,
        budgets=FakeBudgetRepository(),
        states=FakeBudgetStateRepository(),
        default_limit=None,
        threshold_ratio=Decimal("0.8"),
        obligations=FakeObligations(Money.from_rubles("3000"), rough=True),
    )
    service.handle_command("60000")
    assert "оценка" in service.handle_command("").text
