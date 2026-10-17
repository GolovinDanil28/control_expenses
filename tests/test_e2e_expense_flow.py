"""Сквозной путь среза: текст → карточка → подтверждение → строка в SQLite."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path

from control_expenses.application.expenses.replies import CardReply, TextReply
from control_expenses.application.expenses.service import ExpenseService
from control_expenses.infrastructure.db.database import Database
from control_expenses.infrastructure.db.repositories import (
    SqliteCategoryRepository,
    SqliteExpenseRepository,
    SqlitePendingInputStore,
)
from control_expenses.infrastructure.parsing.deterministic import DeterministicParser

CHAT = 1234


class FixedClock:
    def __init__(self, today: date) -> None:
        self._today = today

    def now(self) -> datetime:
        return datetime.combine(self._today, time(12, 0), tzinfo=UTC)

    def today(self) -> date:
        return self._today


def _service(database: Database) -> tuple[ExpenseService, SqliteExpenseRepository]:
    connection = database.connection()
    categories = SqliteCategoryRepository(connection)
    expenses = SqliteExpenseRepository(connection)
    service = ExpenseService(
        parser=DeterministicParser(lambda: categories.list()),
        clock=FixedClock(date(2026, 10, 16)),
        expenses=expenses,
        categories=categories,
        pending=SqlitePendingInputStore(connection),
    )
    return service, expenses


def _count(database: Database) -> int:
    row = database.connection().execute("SELECT COUNT(*) AS total FROM expense").fetchone()
    return int(row["total"])


def test_text_to_confirmation_writes_row(tmp_path: Path) -> None:
    database = Database(tmp_path / "e2e.db")
    database.migrate()
    service, expenses = _service(database)

    card = service.handle_text(CHAT, "купил кофе 250")
    assert isinstance(card, CardReply)
    assert _count(database) == 0

    confirmed = service.confirm(CHAT)
    assert isinstance(confirmed, TextReply)

    stored = expenses.last(CHAT)
    assert stored is not None
    assert stored.amount.format_ru() == "250 ₽"
    assert stored.category == "Еда"
    assert stored.spent_on == date(2026, 10, 16)
    assert _count(database) == 1

    # повторное подтверждение не создаёт вторую строку
    service.confirm(CHAT)
    assert _count(database) == 1
    database.close()


def test_card_state_survives_new_service_instance(tmp_path: Path) -> None:
    database = Database(tmp_path / "restart.db")
    database.migrate()

    first, _ = _service(database)
    assert isinstance(first.handle_text(CHAT, "купил кофе 250"), CardReply)

    # «рестарт»: новый сервис на том же файле БД видит сохранённый черновик
    database.close()
    restarted = Database(tmp_path / "restart.db")
    restarted.migrate()
    second, expenses = _service(restarted)

    confirmed = second.confirm(CHAT)
    assert isinstance(confirmed, TextReply)
    stored = expenses.last(CHAT)
    assert stored is not None
    assert stored.amount.format_ru() == "250 ₽"
    restarted.close()


def test_edit_and_undo_last_expense(tmp_path: Path) -> None:
    database = Database(tmp_path / "edit.db")
    database.migrate()
    service, expenses = _service(database)

    service.handle_text(CHAT, "купил кофе 250")
    service.confirm(CHAT)

    card = service.edit_last(CHAT, "350")
    assert isinstance(card, CardReply)
    service.confirm(CHAT)

    stored = expenses.last(CHAT)
    assert stored is not None
    assert stored.amount.format_ru() == "350 ₽"
    assert _count(database) == 1

    service.undo_last(CHAT)
    assert _count(database) == 0
    assert expenses.last(CHAT) is None
    database.close()


def test_edit_target_survives_restart(tmp_path: Path) -> None:
    database = Database(tmp_path / "edit_restart.db")
    database.migrate()
    first, _ = _service(database)
    first.handle_text(CHAT, "купил кофе 250")
    first.confirm(CHAT)
    assert isinstance(first.edit_last(CHAT, "350"), CardReply)

    # «рестарт»: незавершённая правка должна остаться правкой, а не новой тратой
    database.close()
    restarted = Database(tmp_path / "edit_restart.db")
    restarted.migrate()
    second, expenses = _service(restarted)
    second.confirm(CHAT)

    stored = expenses.last(CHAT)
    assert stored is not None
    assert stored.amount.format_ru() == "350 ₽"
    assert _count(restarted) == 1
    restarted.close()
