"""Ответы по обязательствам: список платежей с кнопками действий."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from control_expenses.domain.money import Money


@dataclass(frozen=True)
class BillItem:
    """Строка списка обязательств с признаками доступных действий."""

    commitment_id: int
    number: int
    title: str
    label: str
    pay_as_amount: bool = False
    meter: bool = False
    payable: bool = False


@dataclass(frozen=True)
class BillListReply:
    """Список обязательств текущего месяца."""

    items: tuple[BillItem, ...]


@dataclass(frozen=True)
class UpcomingBill:
    """Ближайшее наступление обязательства для сводок."""

    title: str
    due: date
    amount: Money | None
