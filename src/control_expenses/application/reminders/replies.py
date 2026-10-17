"""Ответы оповещений: текст с кнопками по обязательствам."""

from __future__ import annotations

from dataclasses import dataclass

from control_expenses.application.commitments.replies import BillItem


@dataclass(frozen=True)
class NotificationReply:
    """Инициативное сообщение владельцу, при необходимости — с кнопками."""

    text: str
    items: tuple[BillItem, ...] = ()
