"""Сквозной путь отчётов на реальной SQLite."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

from control_expenses.application.budgets.service import BudgetService
from control_expenses.application.commitments.service import CommitmentService
from control_expenses.application.reports.service import ReportService
from control_expenses.domain.entities import Expense
from control_expenses.domain.money import Money
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


class FixedClock:
    def now(self) -> datetime:
        return datetime.combine(TODAY, time(12, 0), tzinfo=UTC)

    def today(self) -> date:
        return TODAY


def _report_service(database: Database) -> ReportService:
    connection = database.connection()
    clock = FixedClock()
    expenses = SqliteExpenseRepository(connection)
    commitment = CommitmentService(
        clock=clock,
        commitments=SqliteCommitmentRepository(connection),
        occurrences=SqliteCommitmentOccurrenceRepository(connection),
        prompts=SqliteCommitmentPromptStore(connection),
        expenses=expenses,
        categories=SqliteCategoryRepository(connection),
    )
    budget = BudgetService(
        clock=clock,
        expenses=expenses,
        budgets=SqliteBudgetRepository(connection),
        states=SqliteBudgetStateRepository(connection),
        default_limit=None,
        threshold_ratio=Decimal("0.8"),
        obligations=commitment,
    )
    return ReportService(clock=clock, expenses=expenses, budget=budget, upcoming=commitment)


def _add(database: Database, amount: str, category: str, spent_on: date) -> None:
    SqliteExpenseRepository(database.connection()).add(
        Expense(
            amount=Money.from_rubles(amount),
            spent_on=spent_on,
            source_chat_id=1,
            category=category,
        )
    )


def test_month_report_end_to_end(tmp_path: Path) -> None:
    database = Database(tmp_path / "reports.db")
    database.migrate()
    _add(database, "20000", "Еда", date(2026, 10, 3))
    _add(database, "15000", "Еда", date(2026, 9, 10))

    BudgetService(
        clock=FixedClock(),
        expenses=SqliteExpenseRepository(database.connection()),
        budgets=SqliteBudgetRepository(database.connection()),
        states=SqliteBudgetStateRepository(database.connection()),
        default_limit=None,
        threshold_ratio=Decimal("0.8"),
    ).handle_command("60000")

    service = _report_service(database)
    text = service.handle_command("").text
    assert "Бюджет на 2026-10: 60 000 ₽" in text
    assert "Остаток: 40 000 ₽" in text
    assert "Еда — 20 000 ₽" in text
    assert "К предыдущему периоду: +5 000 ₽ (+33%)" in text

    period = service.handle_command("01.10 07.10").text
    assert "Отчёт за 01.10–07.10" in period
    assert "Всего: 20 000 ₽" in period
    database.close()


def test_weekly_summary_end_to_end(tmp_path: Path) -> None:
    database = Database(tmp_path / "summary.db")
    database.migrate()
    _add(database, "3000", "Еда", date(2026, 10, 12))
    commitment = CommitmentService(
        clock=FixedClock(),
        commitments=SqliteCommitmentRepository(database.connection()),
        occurrences=SqliteCommitmentOccurrenceRepository(database.connection()),
        prompts=SqliteCommitmentPromptStore(database.connection()),
        expenses=SqliteExpenseRepository(database.connection()),
        categories=SqliteCategoryRepository(database.connection()),
    )
    commitment.add_bill("Квартира 15000 20")
    service = _report_service(database)

    text = service.weekly_summary().text
    assert "Сводка за неделю (10.10–16.10)" in text
    assert "Еда — 3 000 ₽" in text
    assert "Квартира" in text
    database.close()
