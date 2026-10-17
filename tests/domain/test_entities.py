"""Тесты сущностей домена: валидации обязательств и трат."""

from datetime import date

import pytest

from control_expenses.domain.entities import (
    Commitment,
    CommitmentKind,
    CommitmentOccurrence,
    Expense,
    OccurrenceStatus,
)
from control_expenses.domain.errors import (
    InvalidDayOfMonthError,
    MissingCommitmentAmountError,
)
from control_expenses.domain.money import Money


def test_fixed_commitment_requires_amount() -> None:
    with pytest.raises(MissingCommitmentAmountError):
        Commitment(title="Квартира", day_of_month=5, kind=CommitmentKind.FIXED)


def test_variable_commitment_needs_no_amount() -> None:
    commitment = Commitment(title="Коммунальные", day_of_month=10, kind=CommitmentKind.VARIABLE)
    assert commitment.amount is None


def test_day_of_month_out_of_range() -> None:
    with pytest.raises(InvalidDayOfMonthError):
        Commitment(title="Квартира", day_of_month=32, amount=Money.from_rubles("1"))
    with pytest.raises(InvalidDayOfMonthError):
        Commitment(title="Квартира", day_of_month=0, amount=Money.from_rubles("1"))


def test_occurrence_defaults_to_pending() -> None:
    occurrence = CommitmentOccurrence(commitment_id=1, period="2026-10")
    assert occurrence.status is OccurrenceStatus.PENDING
    assert occurrence.actual_amount is None


def test_expense_keeps_source_without_exposing_it() -> None:
    expense = Expense(
        amount=Money.from_rubles("250"),
        spent_on=date(2026, 10, 16),
        source_chat_id=123456,
        category="Еда",
    )
    assert expense.source_chat_id == 123456
    assert expense.category == "Еда"
    assert expense.commitment_id is None
