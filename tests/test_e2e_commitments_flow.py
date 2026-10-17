"""Сквозной путь обязательств: оплата уменьшает бюджет, оценки живут в БД."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

from control_expenses.application.budgets.service import BudgetService
from control_expenses.application.commitments.service import CommitmentService
from control_expenses.infrastructure.db.database import Database
from control_expenses.infrastructure.db.repositories import (
    SqliteBudgetRepository,
    SqliteBudgetStateRepository,
    SqliteCategoryRepository,
    SqliteCommitmentOccurrenceRepository,
    SqliteCommitmentPromptStore,
    SqliteCommitmentRepository,
    SqliteExpenseRepository,
)

TODAY = date(2026, 10, 16)
CHAT = 1234


class FixedClock:
    def __init__(self, today: date = TODAY) -> None:
        self._today = today

    def now(self) -> datetime:
        return datetime.combine(self._today, time(12, 0), tzinfo=UTC)

    def today(self) -> date:
        return self._today


def _services(database: Database) -> tuple[CommitmentService, BudgetService]:
    connection = database.connection()
    clock = FixedClock()
    categories = SqliteCategoryRepository(connection)
    expenses = SqliteExpenseRepository(connection)
    commitment_service = CommitmentService(
        clock=clock,
        commitments=SqliteCommitmentRepository(connection),
        occurrences=SqliteCommitmentOccurrenceRepository(connection),
        prompts=SqliteCommitmentPromptStore(connection),
        expenses=expenses,
        categories=categories,
    )
    budget_service = BudgetService(
        clock=clock,
        expenses=expenses,
        budgets=SqliteBudgetRepository(connection),
        states=SqliteBudgetStateRepository(connection),
        default_limit=None,
        threshold_ratio=Decimal("0.8"),
        obligations=commitment_service,
    )
    return commitment_service, budget_service


def test_fixed_commitment_reduces_then_stops_reducing_budget(tmp_path: Path) -> None:
    database = Database(tmp_path / "commitments.db")
    database.migrate()
    commitment, budget = _services(database)

    budget.handle_command("60000")
    commitment.add_bill("Квартира 15000 5")

    # неоплаченное обязательство уменьшает остаток
    pending = budget.handle_command("").text
    assert "Остаток: 45 000 ₽" in pending

    commitment.pay(CHAT, 1)
    paid = budget.handle_command("").text
    # оплата учтена только в потраченном, остаток не уменьшился дважды
    assert "Потрачено: 15 000 ₽" in paid
    assert "Остаток: 45 000 ₽" in paid
    assert "Перебор" not in paid
    database.close()


def test_variable_amount_is_remembered_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "variable.db"
    database = Database(path)
    database.migrate()
    commitment, _ = _services(database)
    commitment.add_bill("Коммунальные var 10")
    commitment.pay(CHAT, 1)
    commitment.handle_prompt_text(CHAT, "3000")
    database.close()

    # «рестарт»: следующая оценка обязательства берёт прошлую фактическую сумму
    restarted = Database(path)
    restarted.migrate()
    commitment2, _ = _services(restarted)
    total, rough = commitment2.month_obligations("2026-11")
    assert total.format_ru() == "3 000 ₽"
    assert rough is True
    restarted.close()
