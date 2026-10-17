"""Отрисовка ответов сервисов в сообщения Telegram."""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from control_expenses.application.commitments.replies import BillListReply
from control_expenses.application.expenses.replies import CardReply
from control_expenses.application.reminders.replies import NotificationReply
from control_expenses.application.views import Reply
from control_expenses.interfaces.cards import (
    bill_keyboard,
    bill_list_text,
    card_keyboard,
    card_text,
)


def render(reply: Reply) -> tuple[str, InlineKeyboardMarkup | None]:
    """Подобрать текст и клавиатуру для ответа сервиса."""
    if isinstance(reply, CardReply):
        return card_text(reply), card_keyboard(reply)
    if isinstance(reply, BillListReply):
        return bill_list_text(reply), bill_keyboard(reply.items)
    if isinstance(reply, NotificationReply):
        return reply.text, bill_keyboard(reply.items)
    return reply.text, None


async def send_reply(bot: Bot, chat_id: int, reply: Reply) -> None:
    """Отправить ответ сервиса в чат."""
    text, keyboard = render(reply)
    if keyboard is None:
        await bot.send_message(chat_id, text)
    else:
        await bot.send_message(chat_id, text, reply_markup=keyboard)
