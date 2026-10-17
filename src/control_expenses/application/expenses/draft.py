"""Черновик траты — состояние карточки, переживающее рестарт процесса.

FSM aiogram живёт в памяти и не годится: бот перезапускается внешним
планировщиком, а неподтверждённая карточка не должна пропадать. Поэтому черновик
хранится в БД (``pending_input``) через порт ``PendingInputStore``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from control_expenses.domain.money import Money


class DraftStage(StrEnum):
    """Этап работы с черновиком."""

    CARD = "card"
    AWAITING_AMOUNT = "awaiting_amount"


@dataclass
class ExpenseDraft:
    """Неподтверждённая трата, показанная пользователю карточкой.

    ``editing_expense_id`` не ``None``, когда карточка правит уже записанную
    трату (``/edit``) вместо создания новой.
    """

    chat_id: int
    spent_on: date
    amount: Money | None = None
    category: str | None = None
    status: DraftStage = DraftStage.CARD
    editing_expense_id: int | None = None
    note: str | None = None
