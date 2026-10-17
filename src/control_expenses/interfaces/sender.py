"""Адаптер доставки: реализация порта ``MessageSender`` поверх aiogram-бота."""

from __future__ import annotations

from aiogram import Bot

from control_expenses.application.views import Reply
from control_expenses.interfaces.render import send_reply


class AiogramSender:
    """Отправляет оповещения планировщика в Telegram."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send(self, chat_id: int, reply: Reply) -> None:
        await send_reply(self._bot, chat_id, reply)
