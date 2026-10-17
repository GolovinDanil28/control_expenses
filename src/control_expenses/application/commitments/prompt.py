"""Ожидание ответа по обязательству: фактическая сумма или показания счётчика."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PromptKind(StrEnum):
    """Что бот ждёт от пользователя по обязательству."""

    AMOUNT = "amount"
    METER = "meter"


@dataclass(frozen=True)
class CommitmentPrompt:
    """Активное ожидание ответа по конкретному обязательству месяца."""

    kind: PromptKind
    commitment_id: int
    period: str
