"""Тесты use case'ов отчётов на фейковых портах: capability ``reports``."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import NamedTuple

from control_expenses.application.commitments.replies import UpcomingBill
from control_expenses.application.reports.service import ReportService
from control_expenses.domain.budget import BudgetStatus
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
    def __init__(self) -> None:
        self.items: list[Expense] = []

    def add(self, expense: Expense) -> Expense:
        self.items.append(expense)
        return expense

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

    def totals_by_category(self, start: date, end: date) -> tuple[tuple[str | None, Money], ...]:
        totals: dict[str | None, Money] = {}
        for item in self.items:
            if start <= item.spent_on <= end:
                totals[item.category] = totals.get(item.category, Money.zero()) + item.amount
        return tuple(sorted(totals.items(), key=lambda pair: pair[1], reverse=True))


class FakeBudgetStatus:
    def __init__(
        self,
        status: BudgetStatus | None,
        period: str = PERIOD,
        spent: Money | None = None,
    ) -> None:
        self._status = status
        self._period = period
        if spent is not None:
            self._spent = spent
        else:
            self._spent = status.spent if status is not None else Money.zero()

    def month_status(self) -> tuple[str, BudgetStatus | None, Money]:
        return self._period, self._status, self._spent


class FakeUpcoming:
    def __init__(self, bills: tuple[UpcomingBill, ...] = ()) -> None:
        self.bills = bills

    def upcoming(self, today: date, limit: int = 3) -> tuple[UpcomingBill, ...]:
        return self.bills[:limit]


class Env(NamedTuple):
    service: ReportService
    expenses: FakeExpenseRepository


def _status(limit: str, spent: str, committed: str = "0", days_left: int = 16) -> BudgetStatus:
    return BudgetStatus(
        limit=Money.from_rubles(limit),
        spent=Money.from_rubles(spent),
        committed=Money.from_rubles(committed),
        days_left=days_left,
    )


def _env(
    *,
    status: BudgetStatus | None = None,
    bills: tuple[UpcomingBill, ...] = (),
) -> Env:
    expenses = FakeExpenseRepository()
    service = ReportService(
        clock=FakeClock(),
        expenses=expenses,
        budget=FakeBudgetStatus(status),
        upcoming=FakeUpcoming(bills),
    )
    return Env(service=service, expenses=expenses)


def _add(env: Env, amount: str, category: str | None, spent_on: date, chat_id: int = 1) -> None:
    env.expenses.items.append(
        Expense(
            amount=Money.from_rubles(amount),
            spent_on=spent_on,
            source_chat_id=chat_id,
            category=category,
        )
    )


def test_period_report_lists_categories_and_total() -> None:
    env = _env()
    _add(env, "4000", "Еда", date(2026, 10, 2))
    _add(env, "1400", "Транспорт", date(2026, 10, 5))
    text = env.service.handle_command("01.10 07.10").text
    assert "Отчёт за 01.10–07.10" in text
    assert "Всего: 5 400 ₽" in text
    assert "Еда — 4 000 ₽" in text
    assert "Транспорт — 1 400 ₽" in text


def test_period_report_without_data() -> None:
    env = _env()
    text = env.service.handle_command("01.10 07.10").text
    assert "не было" in text


def test_period_report_rejects_bad_dates() -> None:
    env = _env()
    assert "Не понял даты" in env.service.handle_command("абв 07.10").text


def test_period_report_rejects_reversed_range() -> None:
    env = _env()
    assert "раньше начала" in env.service.handle_command("07.10 01.10").text


def test_report_requires_two_dates() -> None:
    env = _env()
    assert "Формат" in env.service.handle_command("01.10").text


def test_month_report_shows_plan_and_norm() -> None:
    env = _env(status=_status("60000", "20000", days_left=16))
    _add(env, "20000", "Еда", date(2026, 10, 3))
    text = env.service.handle_command("").text
    assert "Бюджет на 2026-10: 60 000 ₽" in text
    assert "Остаток: 40 000 ₽" in text
    assert "Дневная норма: 2 500 ₽" in text
    assert "По категориям:" in text


def test_month_report_without_budget() -> None:
    env = _env(status=None)
    _add(env, "500", "Еда", date(2026, 10, 3))
    text = env.service.handle_command("").text
    assert "не настроен" in text
    assert "Еда — 500 ₽" in text


def test_month_report_without_expenses() -> None:
    env = _env(status=_status("60000", "0"))
    text = env.service.handle_command("").text
    assert "Трат за текущий месяц не было" in text


def test_month_report_compares_with_previous_month() -> None:
    env = _env(status=_status("60000", "20000", days_left=16))
    _add(env, "20000", "Еда", date(2026, 10, 3))
    _add(env, "15000", "Еда", date(2026, 9, 10))
    text = env.service.handle_command("").text
    assert "К предыдущему периоду: +5 000 ₽ (+33%)" in text


def test_month_report_without_previous_data_has_no_comparison() -> None:
    env = _env(status=_status("60000", "20000", days_left=16))
    _add(env, "20000", "Еда", date(2026, 10, 3))
    assert "К предыдущему периоду" not in env.service.handle_command("").text


def test_report_hides_chat_identifiers() -> None:
    env = _env(status=_status("60000", "9000", days_left=16))
    _add(env, "4000", "Еда", date(2026, 10, 3), chat_id=111)
    _add(env, "5000", "Транспорт", date(2026, 10, 4), chat_id=222)
    text = env.service.handle_command("").text
    assert "111" not in text
    assert "222" not in text
    assert "Еда — 4 000 ₽" in text


def test_weekly_summary_with_expenses_budget_and_bills() -> None:
    env = _env(
        status=_status("60000", "20000", days_left=16),
        bills=(
            UpcomingBill(
                title="Квартира", due=date(2026, 11, 5), amount=Money.from_rubles("15000")
            ),
        ),
    )
    _add(env, "3000", "Еда", date(2026, 10, 12))
    text = env.service.weekly_summary().text
    assert "Сводка за неделю (10.10–16.10)" in text
    assert "Еда — 3 000 ₽" in text
    assert "Дневная норма: 2 500 ₽" in text
    assert "Квартира" in text


def test_weekly_summary_without_expenses_but_with_budget() -> None:
    env = _env(status=_status("60000", "0", days_left=16))
    text = env.service.weekly_summary().text
    assert "Трат за неделю не было" in text
    assert "Дневная норма: 3 750 ₽" in text


def test_weekly_summary_insufficient_data() -> None:
    env = _env(status=None)
    text = env.service.weekly_summary().text
    assert "Недостаточно данных" in text
    assert "/budget" in text
