"""Цикл доставки оповещений: периодически спрашивает, что положено отправить.

Свой цикл на ``asyncio`` вместо внешнего планировщика: поведение при пропущенном
тике предсказуемо, потому что каждое оповещение идемпотентно по ключу
дедупликации (``design.md``).
"""

from __future__ import annotations

import asyncio
import logging

from control_expenses.application.ports import Clock, MessageSender
from control_expenses.application.reminders.service import ReminderService

DEFAULT_INTERVAL_SECONDS = 60
logger = logging.getLogger(__name__)


class Scheduler:
    """Тикает по расписанию и отдаёт готовые оповещения отправителю."""

    def __init__(
        self,
        *,
        reminders: ReminderService,
        sender: MessageSender,
        clock: Clock,
        interval: int = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._reminders = reminders
        self._sender = sender
        self._clock = clock
        self._interval = interval

    async def run_once(self) -> int:
        """Одна итерация: доставить всё, что положено на текущий момент."""
        notifications = self._reminders.run_due(self._clock.now())
        for notification in notifications:
            await self._sender.send(notification.chat_id, notification.reply)
        return len(notifications)

    async def run(self) -> None:
        """Бесконечный цикл доставки; отдельная ошибка не убивает планировщик."""
        while True:
            try:
                sent = await self.run_once()
                if sent:
                    logger.info("Отправлено оповещений: %s", sent)
            except Exception:
                logger.exception("Сбой доставки оповещений")
            await asyncio.sleep(self._interval)
