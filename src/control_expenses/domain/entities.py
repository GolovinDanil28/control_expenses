"""Сущности домена: трата, обязательство, экземпляр обязательства, категория."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from control_expenses.domain.errors import (
    InvalidDayOfMonthError,
    MissingCommitmentAmountError,
)
from control_expenses.domain.money import Money

FIRST_DAY_OF_MONTH = 1
LAST_DAY_OF_MONTH = 31


class CommitmentKind(StrEnum):
    """Вид обязательства."""

    FIXED = "fixed"
    VARIABLE = "variable"
    METER = "meter"


class OccurrenceStatus(StrEnum):
    """Состояние обязательства в конкретном месяце."""

    PENDING = "pending"
    PAID = "paid"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Category:
    """Категория трат."""

    name: str


@dataclass(frozen=True)
class Expense:
    """Подтверждённая трата."""

    amount: Money
    spent_on: date
    source_chat_id: int
    category: str | None = None
    commitment_id: int | None = None
    id: int | None = None


@dataclass(frozen=True)
class Commitment:
    """Обязательный периодический платёж.

    ``amount`` обязателен для ``FIXED`` и отсутствует для ``VARIABLE``/``METER``.
    """

    title: str
    day_of_month: int
    kind: CommitmentKind = CommitmentKind.FIXED
    amount: Money | None = None
    category: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if not FIRST_DAY_OF_MONTH <= self.day_of_month <= LAST_DAY_OF_MONTH:
            raise InvalidDayOfMonthError(f"day_of_month must be 1..31, got {self.day_of_month}")
        if self.kind is CommitmentKind.FIXED and self.amount is None:
            raise MissingCommitmentAmountError("fixed commitment requires an amount")


@dataclass(frozen=True)
class CommitmentOccurrence:
    """Экземпляр обязательства в месяце ``period`` (``YYYY-MM``).

    Для обязательств-счётчиков денег не создаётся: хранятся переданные показания
    и дата передачи.
    """

    commitment_id: int
    period: str
    status: OccurrenceStatus = OccurrenceStatus.PENDING
    actual_amount: Money | None = None
    meter_values: str | None = None
    meter_transferred_on: date | None = None
    id: int | None = None
