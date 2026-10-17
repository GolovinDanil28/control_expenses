"""Тесты use case'ов расходов на фейковых портах: сценарии capability ``expenses``."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import NamedTuple

import pytest

from control_expenses.application.expenses.draft import DraftStage, ExpenseDraft
from control_expenses.application.expenses.replies import CardReply, Reply, TextReply
from control_expenses.application.expenses.service import ExpenseService
from control_expenses.domain.categories import DEFAULT_CATEGORIES
from control_expenses.domain.entities import Expense
from control_expenses.infrastructure.parsing.deterministic import DeterministicParser

TODAY = date(2026, 10, 16)
CHAT = 42


class FakeClock:
    def now(self) -> datetime:
        return datetime.combine(TODAY, time(12, 0), tzinfo=UTC)

    def today(self) -> date:
        return TODAY


class FakeExpenseRepository:
    def __init__(self) -> None:
        self.items: list[Expense] = []

    def add(self, expense: Expense) -> Expense:
        saved = replace(expense, id=len(self.items) + 1)
        self.items.append(saved)
        return saved

    def update(self, expense: Expense) -> Expense:
        for index, item in enumerate(self.items):
            if item.id == expense.id:
                self.items[index] = expense
                return expense
        raise AssertionError("нет траты для правки")

    def last(self, source_chat_id: int) -> Expense | None:
        for item in reversed(self.items):
            if item.source_chat_id == source_chat_id:
                return item
        return None

    def delete(self, expense_id: int) -> None:
        self.items = [item for item in self.items if item.id != expense_id]


class FakeCategoryRepository:
    def __init__(self, names: tuple[str, ...] = DEFAULT_CATEGORIES) -> None:
        self.names: list[str] = list(names)

    def list(self) -> tuple[str, ...]:
        return tuple(self.names)

    def add(self, name: str) -> str:
        self.names.append(name)
        return name


class FakePendingInputStore:
    def __init__(self) -> None:
        self.drafts: dict[int, ExpenseDraft] = {}

    def get(self, chat_id: int) -> ExpenseDraft | None:
        return self.drafts.get(chat_id)

    def set(self, chat_id: int, draft: ExpenseDraft) -> None:
        self.drafts[chat_id] = draft

    def clear(self, chat_id: int) -> None:
        self.drafts.pop(chat_id, None)


class Env(NamedTuple):
    service: ExpenseService
    expenses: FakeExpenseRepository
    categories: FakeCategoryRepository
    pending: FakePendingInputStore


@pytest.fixture
def env() -> Env:
    categories = FakeCategoryRepository()
    expenses = FakeExpenseRepository()
    pending = FakePendingInputStore()
    service = ExpenseService(
        parser=DeterministicParser(categories.list),
        clock=FakeClock(),
        expenses=expenses,
        categories=categories,
        pending=pending,
    )
    return Env(service=service, expenses=expenses, categories=categories, pending=pending)


def _card(reply: Reply) -> CardReply:
    assert isinstance(reply, CardReply), reply
    return reply


def test_text_shows_card_without_persisting(env: Env) -> None:
    card = _card(env.service.handle_text(CHAT, "купил кофе 250"))
    assert card.amount is not None
    assert card.amount.format_ru() == "250 ₽"
    assert card.category == "Еда"
    assert env.expenses.items == []


def test_confirm_writes_expense_once(env: Env) -> None:
    env.service.handle_text(CHAT, "купил кофе 250")
    reply = env.service.confirm(CHAT)
    assert isinstance(reply, TextReply)
    assert len(env.expenses.items) == 1
    saved = env.expenses.items[0]
    assert saved.amount.format_ru() == "250 ₽"
    assert saved.category == "Еда"
    assert saved.source_chat_id == CHAT
    # повторное подтверждение не создаёт вторую трату
    env.service.confirm(CHAT)
    assert len(env.expenses.items) == 1


def test_cancel_writes_nothing(env: Env) -> None:
    env.service.handle_text(CHAT, "купил кофе 250")
    reply = env.service.cancel(CHAT)
    assert isinstance(reply, TextReply)
    assert env.expenses.items == []
    assert env.pending.get(CHAT) is None


def test_new_message_discards_previous_card(env: Env) -> None:
    env.service.handle_text(CHAT, "купил кофе 250")
    card = _card(env.service.handle_text(CHAT, "такси 800"))
    assert card.category == "Транспорт"
    assert card.amount is not None
    assert card.amount.format_ru() == "800 ₽"
    assert len(env.pending.drafts) == 1


def test_choose_category_keeps_amount(env: Env) -> None:
    env.service.handle_text(CHAT, "купил кофе 250")
    card = _card(env.service.choose_category(CHAT, "Транспорт"))
    assert card.category == "Транспорт"
    assert card.amount is not None
    assert card.amount.format_ru() == "250 ₽"
    assert env.expenses.items == []


def test_choose_unknown_category_is_rejected(env: Env) -> None:
    env.service.handle_text(CHAT, "купил кофе 250")
    reply = env.service.choose_category(CHAT, "Космос")
    assert isinstance(reply, TextReply)
    draft = env.pending.get(CHAT)
    assert draft is not None
    assert draft.category == "Еда"


def test_amount_edit_preserves_other_fields(env: Env) -> None:
    env.service.handle_text(CHAT, "купил кофе 250")
    env.service.request_amount(CHAT)
    card = _card(env.service.handle_text(CHAT, "350"))
    assert card.amount is not None
    assert card.amount.format_ru() == "350 ₽"
    assert card.category == "Еда"


def test_missing_amount_asks_for_it(env: Env) -> None:
    reply = env.service.handle_text(CHAT, "потратил немного на обед")
    assert isinstance(reply, TextReply)
    assert "сумм" in reply.text.lower()
    # подсказка про команды, иначе свободный текст кажется единственным входом
    assert "/report" in reply.text


def test_ambiguous_amount_asks_for_clarification(env: Env) -> None:
    reply = env.service.handle_text(CHAT, "перевёл 500 и 300")
    assert isinstance(reply, TextReply)
    assert env.pending.get(CHAT) is None


def test_add_category_and_duplicate(env: Env) -> None:
    assert isinstance(env.service.add_category("Ветеринарка"), TextReply)
    assert "Ветеринарка" in env.categories.list()
    duplicate = env.service.add_category("ветеринарка")
    assert isinstance(duplicate, TextReply)
    assert "уже есть" in duplicate.text
    assert env.categories.list().count("Ветеринарка") == 1


def test_confirm_without_card(env: Env) -> None:
    reply = env.service.confirm(CHAT)
    assert isinstance(reply, TextReply)
    assert env.expenses.items == []


def test_pending_draft_survives_store_roundtrip(env: Env) -> None:
    env.service.handle_text(CHAT, "купил кофе 250")
    draft = env.pending.get(CHAT)
    assert draft is not None
    assert draft.status is DraftStage.CARD


def test_undo_last_deletes_expense(env: Env) -> None:
    env.service.handle_text(CHAT, "купил кофе 250")
    env.service.confirm(CHAT)
    reply = env.service.undo_last(CHAT)
    assert isinstance(reply, TextReply)
    assert "Удалил" in reply.text
    assert env.expenses.items == []


def test_undo_without_expenses_does_nothing(env: Env) -> None:
    reply = env.service.undo_last(CHAT)
    assert isinstance(reply, TextReply)
    assert env.expenses.items == []


def test_edit_last_updates_amount_without_duplicate(env: Env) -> None:
    env.service.handle_text(CHAT, "купил кофе 250")
    env.service.confirm(CHAT)
    assert len(env.expenses.items) == 1

    card = _card(env.service.edit_last(CHAT, "350"))
    assert card.is_edit is True
    assert card.amount is not None
    assert card.amount.format_ru() == "350 ₽"

    env.service.confirm(CHAT)
    assert len(env.expenses.items) == 1
    assert env.expenses.items[0].amount.format_ru() == "350 ₽"
    assert env.expenses.items[0].category == "Еда"


def test_edit_last_awaits_amount_when_argument_missing(env: Env) -> None:
    env.service.handle_text(CHAT, "купил кофе 250")
    env.service.confirm(CHAT)
    reply = env.service.edit_last(CHAT, "")
    assert isinstance(reply, TextReply)

    card = _card(env.service.handle_text(CHAT, "999"))
    assert card.amount is not None
    assert card.amount.format_ru() == "999 ₽"

    env.service.confirm(CHAT)
    assert len(env.expenses.items) == 1
    assert env.expenses.items[0].amount.format_ru() == "999 ₽"


def test_edit_last_without_expense(env: Env) -> None:
    reply = env.service.edit_last(CHAT, "350")
    assert isinstance(reply, TextReply)
    assert env.expenses.items == []


def test_edit_last_rejects_bad_amount(env: Env) -> None:
    env.service.handle_text(CHAT, "купил кофе 250")
    env.service.confirm(CHAT)
    reply = env.service.edit_last(CHAT, "abc")
    assert isinstance(reply, TextReply)
    assert env.expenses.items[0].amount.format_ru() == "250 ₽"


def test_explicit_past_date_lands_in_card(env: Env) -> None:
    card = _card(env.service.handle_text(CHAT, "такси 800 12.10"))
    assert card.spent_on == date(2026, 10, 12)
    assert env.pending.get(CHAT) is not None


def test_future_date_is_rejected(env: Env) -> None:
    reply = env.service.handle_text(CHAT, "кофе 250 25.12")
    assert isinstance(reply, TextReply)
    assert "будущем" in reply.text
    assert env.expenses.items == []
    assert env.pending.get(CHAT) is None
