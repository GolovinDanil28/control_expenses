"""Общие виды ответов use case'ов, которые умеет отрисовать интерфейс."""

from __future__ import annotations

from control_expenses.application.commitments.replies import BillListReply
from control_expenses.application.expenses.replies import CardReply
from control_expenses.application.reminders.replies import NotificationReply
from control_expenses.application.replies import TextReply

Reply = TextReply | CardReply | BillListReply | NotificationReply

__all__ = ["BillListReply", "CardReply", "NotificationReply", "Reply", "TextReply"]
