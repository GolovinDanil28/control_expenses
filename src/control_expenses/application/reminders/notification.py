"""Адресованное оповещение: в какой чат и что отправить."""

from __future__ import annotations

from dataclasses import dataclass

from control_expenses.application.views import Reply


@dataclass(frozen=True)
class Notification:
    """Готовое к отправке оповещение владельцу."""

    chat_id: int
    reply: Reply
