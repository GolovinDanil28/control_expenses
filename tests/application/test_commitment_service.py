"""Тесты use case'ов обязательств на фейковых портах.

Сценарии capability ``commitments`` и вклад обязательств в остаток бюджета.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import NamedTuple

import pytest

from control_expenses.application.commitments.prompt import CommitmentPrompt
from control_expenses.application.commitments.replies import BillListReply
from control_expenses.application.commitments.service import CommitmentService
from control_expenses.application.replies import TextReply
from control_expenses.domain.categories import DEFAULT_CATEGORIES
from control_expenses.domain.entities import (
    Commitment,
    CommitmentKind,
    CommitmentOccurrence,
    Expense,
    OccurrenceStatus,
)
from control_expenses.domain.money import Money

TODAY = date(2026, 10, 16)
PERIOD = "2026-10"
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


class FakeCategoryRepository:
    def __init__(self) -> None:
        self.names: list[str] = list(DEFAULT_CATEGORIES)

    def list(self) -> tuple[str, ...]:
        return tuple(self.names)

    def add(self, name: str) -> str:
        self.names.append(name)
        return name


class FakeCommitmentRepository:
    def __init__(self) -> None:
        self.items: dict[int, Commitment] = {}
        self._next_id = 1

    def add(self, commitment: Commitment) -> Commitment:
        saved = replace(commitment, id=self._next_id)
        self.items[self._next_id] = saved
        self._next_id += 1
        return saved

    def list(self) -> tuple[Commitment, ...]:
        return tuple(self.items.values())

    def get(self, commitment_id: int) -> Commitment | None:
        return self.items.get(commitment_id)

    def delete(self, commitment_id: int) -> None:
        self.items.pop(commitment_id, None)


class FakeOccurrenceRepository:
    def __init__(self, commitments: FakeCommitmentRepository) -> None:
        self._commitments = commitments
        self.items: dict[tuple[int, str], CommitmentOccurrence] = {}

    def ensure_period(self, period: str) -> None:
        for commitment in self._commitments.items.values():
            assert commitment.id is not None
            self.items.setdefault(
                (commitment.id, period),
                CommitmentOccurrence(commitment_id=commitment.id, period=period, id=1),
            )

    def get(self, commitment_id: int, period: str) -> CommitmentOccurrence | None:
        return self.items.get((commitment_id, period))

    def save(self, occurrence: CommitmentOccurrence) -> CommitmentOccurrence:
        stored = replace(occurrence, id=1)
        self.items[(occurrence.commitment_id, occurrence.period)] = stored
        return stored

    def for_period(self, period: str) -> tuple[CommitmentOccurrence, ...]:
        return tuple(
            occurrence
            for (_, stored_period), occurrence in self.items.items()
            if stored_period == period
        )

    def pending_for_period(self, period: str) -> tuple[CommitmentOccurrence, ...]:
        return tuple(self._pending(period))

    def last_actual_amount(self, commitment_id: int) -> Money | None:
        amounts = [
            occurrence.actual_amount
            for (cid, _), occurrence in sorted(self.items.items())
            if cid == commitment_id and occurrence.actual_amount is not None
        ]
        return amounts[-1] if amounts else None

    def _pending(self, period: str) -> list[CommitmentOccurrence]:
        return [
            occurrence
            for (_, stored_period), occurrence in self.items.items()
            if stored_period == period and occurrence.status is OccurrenceStatus.PENDING
        ]


class FakePromptStore:
    def __init__(self) -> None:
        self.prompts: dict[int, CommitmentPrompt] = {}

    def get(self, chat_id: int) -> CommitmentPrompt | None:
        return self.prompts.get(chat_id)

    def set(self, chat_id: int, prompt: CommitmentPrompt) -> None:
        self.prompts[chat_id] = prompt

    def clear(self, chat_id: int) -> None:
        self.prompts.pop(chat_id, None)


class Env(NamedTuple):
    service: CommitmentService
    commitments: FakeCommitmentRepository
    occurrences: FakeOccurrenceRepository
    expenses: FakeExpenseRepository
    prompts: FakePromptStore


@pytest.fixture
def env() -> Env:
    commitments = FakeCommitmentRepository()
    occurrences = FakeOccurrenceRepository(commitments)
    expenses = FakeExpenseRepository()
    prompts = FakePromptStore()
    service = CommitmentService(
        clock=FakeClock(),
        commitments=commitments,
        occurrences=occurrences,
        prompts=prompts,
        expenses=expenses,
        categories=FakeCategoryRepository(),
    )
    return Env(
        service=service,
        commitments=commitments,
        occurrences=occurrences,
        expenses=expenses,
        prompts=prompts,
    )


def _text(reply: object) -> str:
    assert isinstance(reply, TextReply), reply
    return reply.text


def _add_fixed(env: Env, title: str = "Квартира", amount: str = "15000", day: str = "5") -> None:
    env.service.add_bill(f"{title} {amount} {day}")


def test_add_fixed_bill_reports_next_date(env: Env) -> None:
    reply = _text(env.service.add_bill("Квартира 15000 5"))
    assert "Квартира" in reply
    assert "05.11.2026" in reply
    commitment = env.commitments.items[1]
    assert commitment.kind is CommitmentKind.FIXED
    assert commitment.amount is not None
    assert commitment.amount.format_ru() == "15 000 ₽"
    assert commitment.category == "Квартира"


def test_add_bill_rejects_bad_day(env: Env) -> None:
    reply = _text(env.service.add_bill("Квартира 15000 32"))
    assert "1–31" in reply
    assert env.commitments.items == {}


def test_add_bill_requires_amount(env: Env) -> None:
    reply = _text(env.service.add_bill("Квартира 5"))
    assert "addbill" in reply
    assert env.commitments.items == {}


def test_add_variable_and_meter_bills(env: Env) -> None:
    _text(env.service.add_bill("Коммунальные var 10"))
    _text(env.service.add_bill("Счётчики meter 15"))
    kinds = {commitment.kind for commitment in env.commitments.items.values()}
    assert kinds == {CommitmentKind.VARIABLE, CommitmentKind.METER}


def test_list_bills_without_commitments(env: Env) -> None:
    assert "Обязательств нет" in _text(env.service.list_bills())


def test_list_bills_shows_flags(env: Env) -> None:
    _add_fixed(env)
    _text(env.service.add_bill("Коммунальные var 10"))
    _text(env.service.add_bill("Счётчики meter 15"))
    reply = env.service.list_bills()
    assert isinstance(reply, BillListReply)
    by_title = {item.title: item for item in reply.items}
    assert by_title["Квартира"].payable is True
    assert by_title["Коммунальные"].pay_as_amount is True
    assert by_title["Счётчики"].meter is True
    assert by_title["Квартира"].label.startswith("Квартира · ")


def test_pay_fixed_creates_expense_once(env: Env) -> None:
    _add_fixed(env)
    reply = _text(env.service.pay(CHAT, 1))
    assert "оплачено" in reply
    assert len(env.expenses.items) == 1
    assert env.expenses.items[0].category == "Квартира"
    assert env.expenses.items[0].commitment_id == 1

    second = _text(env.service.pay(CHAT, 1))
    assert "уже проведён" in second
    assert len(env.expenses.items) == 1
    assert env.occurrences.get(1, PERIOD).status is OccurrenceStatus.PAID


def test_pay_variable_asks_amount_then_pays(env: Env) -> None:
    _text(env.service.add_bill("Коммунальные var 10"))
    prompt_reply = _text(env.service.pay(CHAT, 1))
    assert env.service.has_prompt(CHAT)
    assert prompt_reply

    paid = _text(env.service.handle_prompt_text(CHAT, "3000"))
    assert "оплачено" in paid
    assert env.expenses.items[0].amount.format_ru() == "3 000 ₽"
    occurrence = env.occurrences.get(1, PERIOD)
    assert occurrence.status is OccurrenceStatus.PAID
    assert occurrence.actual_amount is not None
    assert occurrence.actual_amount.format_ru() == "3 000 ₽"
    assert env.service.has_prompt(CHAT) is False


def test_prompt_with_expense_like_message_records_nothing(env: Env) -> None:
    _text(env.service.add_bill("Коммунальные var 10"))
    _text(env.service.pay(CHAT, 1))
    reply = _text(env.service.handle_prompt_text(CHAT, "купил кофе 250"))
    assert "трату" in reply
    assert env.expenses.items == []
    assert env.occurrences.get(1, PERIOD).status is OccurrenceStatus.PENDING
    assert env.service.has_prompt(CHAT) is False


def test_skip_bill_creates_no_expense(env: Env) -> None:
    _add_fixed(env)
    reply = _text(env.service.skip(1))
    assert "пропущено" in reply
    assert env.expenses.items == []
    assert env.occurrences.get(1, PERIOD).status is OccurrenceStatus.SKIPPED


def test_skip_then_pay_is_rejected(env: Env) -> None:
    _add_fixed(env)
    _text(env.service.skip(1))
    assert "пропущенным" in _text(env.service.pay(CHAT, 1))


def test_meter_readings_accepted_without_expense(env: Env) -> None:
    _text(env.service.add_bill("Счётчики meter 15"))
    _text(env.service.request_meter(CHAT, 1))
    reply = _text(env.service.handle_prompt_text(CHAT, "1234 5678"))
    assert "приняты" in reply
    assert env.expenses.items == []
    occurrence = env.occurrences.get(1, PERIOD)
    assert occurrence.meter_values == "1234 5678"
    assert occurrence.meter_transferred_on == TODAY


def test_meter_readings_rejected_when_not_numbers(env: Env) -> None:
    _text(env.service.add_bill("Счётчики meter 15"))
    _text(env.service.request_meter(CHAT, 1))
    reply = _text(env.service.handle_prompt_text(CHAT, "не знаю"))
    assert "показани" in reply.lower()
    assert env.service.has_prompt(CHAT) is True
    occurrence = env.occurrences.get(1, PERIOD)
    assert occurrence is None or occurrence.meter_values is None


def test_delete_bill_keeps_expenses(env: Env) -> None:
    _add_fixed(env)
    _text(env.service.pay(CHAT, 1))
    reply = _text(env.service.delete_bill("1"))
    assert "удалено" in reply
    assert env.commitments.items == {}
    assert len(env.expenses.items) == 1


def test_month_obligations_counts_pending_fixed(env: Env) -> None:
    _add_fixed(env)
    total, rough = env.service.month_obligations(PERIOD)
    assert total.format_ru() == "15 000 ₽"
    assert rough is False


def test_month_obligations_estimates_variable_from_history(env: Env) -> None:
    _text(env.service.add_bill("Коммунальные var 10"))
    _text(env.service.pay(CHAT, 1))
    _text(env.service.handle_prompt_text(CHAT, "3000"))
    # следующий месяц: сумма ещё не введена, берём прошлую и помечаем как оценку
    total, rough = env.service.month_obligations("2026-11")
    assert total.format_ru() == "3 000 ₽"
    assert rough is True


def test_month_obligations_excludes_variable_without_history(env: Env) -> None:
    _text(env.service.add_bill("Коммунальные var 10"))
    total, rough = env.service.month_obligations(PERIOD)
    assert total.is_zero
    assert rough is True


def test_month_obligations_excludes_paid_and_meter(env: Env) -> None:
    _add_fixed(env)
    _text(env.service.add_bill("Счётчики meter 15"))
    _text(env.service.pay(CHAT, 1))
    total, rough = env.service.month_obligations(PERIOD)
    assert total.is_zero
    assert rough is False
