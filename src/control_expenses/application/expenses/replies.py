"""Ответы use case'ов расходов для интерфейса: текст или карточка предпросмотра."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from control_expenses.application.replies import TextReply
from control_expenses.domain.money import Money

__all__ = ["CardReply", "Reply", "TextReply"]


@dataclass(frozen=True)
class CardReply:
    """Карточка предпросмотра траты с доступными категориями."""

    amount: Money | None
    spent_on: date
    category: str | None
    categories: tuple[str, ...]
    is_edit: bool = False
    note: str | None = None


Reply = TextReply | CardReply
