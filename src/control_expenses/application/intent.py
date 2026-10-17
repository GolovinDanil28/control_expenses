"""Разбор свободного текста о трате: DTO результата и порт парсера.

Модуль описывает то, что нужно обеим реализациям парсера — детерминированной
(``infrastructure/parsing``) и LLM-адаптерам. Модель только извлекает структуру;
расчёты и карточка подтверждения принадлежат другим capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol, runtime_checkable

from control_expenses.domain.money import Money


class ParseFailure(StrEnum):
    """Причина, по которой текст не удалось разобрать."""

    NO_AMOUNT = "no_amount"
    AMBIGUOUS_AMOUNT = "ambiguous_amount"


@dataclass(frozen=True)
class ParsedIntent:
    """Извлечённые из текста сумма, категория и дата.

    ``note`` — подсказка пользователю (например, что в сообщении была не одна
    трата); отображается вместе с карточкой.
    """

    amount: Money
    spent_on: date
    category: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class FailedIntent:
    """Разбор не удался; ``reason`` объясняет, чего не хватило."""

    reason: ParseFailure


class ParserUnavailableError(RuntimeError):
    """ИИ-бэкенд не настроен, недоступен или ответил мусором."""


IntentParseResult = ParsedIntent | FailedIntent


@runtime_checkable
class IntentParser(Protocol):
    """Порт разбора текста о трате в структуру."""

    def parse(self, text: str, *, today: date) -> IntentParseResult:
        """Разобрать ``text`` относительно даты ``today``."""
        ...

    def parse_amount(self, text: str) -> Money | None:
        """Извлечь сумму из сообщения, введённого в ответ на запрос суммы."""
        ...
