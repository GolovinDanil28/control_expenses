"""Отрисовка карточки предпросмотра и клавиатуры в терминах aiogram."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from control_expenses.application.commitments.replies import BillItem, BillListReply
from control_expenses.application.expenses.replies import CardReply

CATEGORY_PER_ROW = 3
CALLBACK_CONFIRM = "expense:confirm"
CALLBACK_AMOUNT = "expense:amount"
CALLBACK_CANCEL = "expense:cancel"
CALLBACK_CATEGORY_PREFIX = "expense:cat:"
CALLBACK_PREFIX = "expense:"
CALLBACK_BILL_PREFIX = "bill:"
BILL_PAY = "bill:pay:"
BILL_SKIP = "bill:skip:"
BILL_METER = "bill:meter:"


def card_text(card: CardReply) -> str:
    """Текст карточки: категория · сумма · дата."""
    amount = card.amount.format_ru() if card.amount is not None else "—"
    category = card.category or "без категории"
    question = "Исправить трату?" if card.is_edit else "Записать трату?"
    lines = [f"{category} · {amount} · {card.spent_on:%d.%m}"]
    if card.note is not None:
        lines.append(card.note)
    lines.append("")
    lines.append(question)
    return "\n".join(lines)


def card_keyboard(card: CardReply) -> InlineKeyboardMarkup:
    """Клавиатура карточки: подтверждение, выбор категории, сумма, отмена."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="✅ Записать", callback_data=CALLBACK_CONFIRM)]
    ]
    category_row: list[InlineKeyboardButton] = []
    for name in card.categories:
        category_row.append(
            InlineKeyboardButton(text=name, callback_data=f"{CALLBACK_CATEGORY_PREFIX}{name}")
        )
        if len(category_row) == CATEGORY_PER_ROW:
            rows.append(category_row)
            category_row = []
    if category_row:
        rows.append(category_row)
    rows.append(
        [
            InlineKeyboardButton(text="✏️ Сумму", callback_data=CALLBACK_AMOUNT),
            InlineKeyboardButton(text="❌ Отмена", callback_data=CALLBACK_CANCEL),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bill_list_text(reply: BillListReply) -> str:
    """Текст списка обязательств."""
    lines = [f"{item.number}. {item.label}" for item in reply.items]
    return "\n".join(["Обязательства:", *lines, "", "Оплата и пропуск — кнопкой или /pay, /skip."])


def bill_keyboard(items: Sequence[BillItem]) -> InlineKeyboardMarkup | None:
    """Кнопки действий по обязательствам; ``None``, если действий нет."""
    numbered = len(items) > 1

    def label(prefix: str, number: int) -> str:
        return f"{prefix} {number}" if numbered else prefix

    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        if item.meter:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=label("📟 Показания", item.number),
                        callback_data=f"{BILL_METER}{item.commitment_id}",
                    )
                ]
            )
        elif item.pay_as_amount:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=label("✏️ Сумма", item.number),
                        callback_data=f"{BILL_PAY}{item.commitment_id}",
                    )
                ]
            )
        elif item.payable:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=label("✅ Оплатить", item.number),
                        callback_data=f"{BILL_PAY}{item.commitment_id}",
                    ),
                    InlineKeyboardButton(
                        text=label("⏭ Пропустить", item.number),
                        callback_data=f"{BILL_SKIP}{item.commitment_id}",
                    ),
                ]
            )
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)
