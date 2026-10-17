"""Сквозной путь бюджета: лимит, статус и однократная фиксация превышения."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

from control_expenses.application.budgets.service import BudgetService
from control_expenses.domain.entities import Expense
from control_expenses.domain.money import Money
from control_expenses.infrastructure.db.database import Database
from control_expenses.infrastructure.db.repositories import (
    SqliteBudgetRepository,
    SqliteBudgetStateRepository,
    SqliteExpenseRepository,
)

TODAY = date(2026, 10, 16)


class FixedClock:
    def now(self) -> datetime:
        return datetime.combine(TODAY, time(12, 0), tzinfo=UTC)

    def today(self) -> date:
        return TODAY


def _budget_service(database: Database) -> BudgetService:
    connection = database.connection()
    return BudgetService(
        clock=FixedClock(),
        expenses=SqliteExpenseRepository(connection),
        budgets=SqliteBudgetRepository(connection),
        states=SqliteBudgetStateRepository(connection),
        default_limit=None,
        threshold_ratio=Decimal("0.8"),
    )


def _add_expense(database: Database, amount: str) -> None:
    SqliteExpenseRepository(database.connection()).add(
        Expense(
            amount=Money.from_rubles(amount),
            spent_on=TODAY,
            source_chat_id=1,
            category="Еда",
        )
    )


def test_budget_status_end_to_end(tmp_path: Path) -> None:
    database = Database(tmp_path / "budget.db")
    database.migrate()
    service = _budget_service(database)

    assert "не настроен" in service.handle_command("").text
    assert "Лимит на 2026-10: 60 000 ₽" in service.handle_command("60000").text

    _add_expense(database, "20000")
    status = service.handle_command("").text
    assert "Остаток: 40 000 ₽" in status
    assert "Дневная норма: 2 500 ₽" in status
    database.close()


def test_overrun_state_fixed_once_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "overrun.db"
    database = Database(path)
    database.migrate()
    SqliteBudgetRepository(database.connection()).set_limit("2026-10", Money.from_rubles("1000"))
    _add_expense(database, "1500")

    _budget_service(database).record_after_expense()
    state = SqliteBudgetStateRepository(database.connection()).get("2026-10")
    assert state.overrun_fixed is True
    assert state.overrun.format_ru() == "500 ₽"
    database.close()

    # «рестарт»: фиксация живёт в БД, состояние сохраняется
    restarted = Database(path)
    restarted.migrate()
    restarted_state = SqliteBudgetStateRepository(restarted.connection()).get("2026-10")
    assert restarted_state.overrun_fixed is True
    assert restarted_state.overrun.format_ru() == "500 ₽"
    restarted.close()
