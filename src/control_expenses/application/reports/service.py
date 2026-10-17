"""Сценарии отчётов: за период, за месяц, сравнение и недельная сводка.

Один сценарий спецификации ``reports`` = одна ветка сервиса. Приватность
обеспечена самой природой данных: агрегаты считаются по категориям и датам, а
идентификаторы чатов в выборку не попадают.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from control_expenses.application.ports import (
    BudgetStatusQuery,
    Clock,
    ExpenseRepository,
    UpcomingCommitments,
)
from control_expenses.application.replies import TextReply
from control_expenses.domain.budget import month_bounds
from control_expenses.domain.money import Money

WEEK_DAYS = 7
HUNDRED = Decimal(100)
UNCATEGORIZED = "Без категории"
REPORT_USAGE = (
    "Формат: /report 01.10 07.10 — за период, либо /report без аргументов — за текущий месяц."
)
_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?")


class ReportService:
    """Отчёты по тратам и наполнение недельной сводки."""

    def __init__(
        self,
        *,
        clock: Clock,
        expenses: ExpenseRepository,
        budget: BudgetStatusQuery,
        upcoming: UpcomingCommitments,
    ) -> None:
        self._clock = clock
        self._expenses = expenses
        self._budget = budget
        self._upcoming = upcoming

    def handle_command(self, arguments: str) -> TextReply:
        """`/report` без аргументов — месяц; с двумя датами — период."""
        tokens = arguments.split()
        if not tokens:
            return self._month_report()
        if len(tokens) != 2:
            return TextReply(REPORT_USAGE)
        today = self._clock.today()
        start = _parse_date(tokens[0], today)
        end = _parse_date(tokens[1], today)
        if start is None or end is None:
            return TextReply("Не понял даты. Пример: /report 01.10 07.10")
        if end < start:
            return TextReply("Конец периода раньше начала — проверьте даты.")
        return self._period_report(start, end)

    def weekly_summary(self) -> TextReply:
        """Сводка за последнюю неделю: категории, план, дневная норма, обязательства."""
        today = self._clock.today()
        start = today - timedelta(days=WEEK_DAYS - 1)
        period, status, _spent = self._budget.month_status()
        totals = self._expenses.totals_by_category(start, today)
        if not totals and status is None:
            return TextReply(
                "Недостаточно данных для сводки: за неделю трат не было и бюджет не настроен.\n"
                "Задайте лимит: /budget 60000 — и запишите первую трату текстом."
            )
        lines = [f"Сводка за неделю ({start:%d.%m}–{today:%d.%m})"]
        if totals:
            lines += [f"{name or UNCATEGORIZED} — {amount.format_ru()}" for name, amount in totals]
            lines.append(f"Всего: {_total(totals).format_ru()}")
        else:
            lines.append("Трат за неделю не было.")
        if status is not None:
            lines += [
                "",
                f"Бюджет на {period}: {status.limit.format_ru()}",
                f"Дневная норма: {status.daily.format_ru()}",
            ]
        bills = self._upcoming.upcoming(today)
        if bills:
            lines += ["", "Ближайшие обязательства:"]
            lines += [_bill_line(bill.due, bill.title, bill.amount) for bill in bills]
        return TextReply("\n".join(lines))

    def _month_report(self) -> TextReply:
        today = self._clock.today()
        period, status, spent = self._budget.month_status()
        start, end = month_bounds(today)
        totals = self._expenses.totals_by_category(start, end)
        lines: list[str] = []
        if status is None:
            lines.append(f"Бюджет на {period} не настроен. Потрачено: {spent.format_ru()}.")
        else:
            lines += [
                f"Бюджет на {period}: {status.limit.format_ru()}",
                f"Потрачено: {status.spent.format_ru()}",
                f"Остаток: {status.remaining.format_ru()}",
                f"Дневная норма: {status.daily.format_ru()}",
            ]
            if status.is_over:
                lines.append(f"Перебор: {status.overrun.format_ru()}")
        if not totals:
            lines += ["", "Трат за текущий месяц не было."]
            return TextReply("\n".join(lines))
        lines += ["", "По категориям:"]
        lines += [f"{name or UNCATEGORIZED} — {amount.format_ru()}" for name, amount in totals]
        previous = self._expenses.spent_between(*_previous_month(today))
        comparison = _comparison_text(spent, previous)
        if comparison is not None:
            lines += ["", comparison]
        return TextReply("\n".join(lines))

    def _period_report(self, start: date, end: date) -> TextReply:
        totals = self._expenses.totals_by_category(start, end)
        header = f"Отчёт за {start:%d.%m}–{end:%d.%m}"
        if not totals:
            return TextReply(f"{header}\nТрат за период не было.")
        current = _total(totals)
        lines = [header, f"Всего: {current.format_ru()}", ""]
        lines += [f"{name or UNCATEGORIZED} — {amount.format_ru()}" for name, amount in totals]
        previous = self._expenses.spent_between(*_previous_period(start, end))
        comparison = _comparison_text(current, previous)
        if comparison is not None:
            lines += ["", comparison]
        return TextReply("\n".join(lines))


def _parse_date(token: str, today: date) -> date | None:
    match = _DATE_RE.fullmatch(token.strip())
    if match is None:
        return None
    day = int(match.group(1))
    month = int(match.group(2))
    year = int(match.group(3)) if match.group(3) is not None else today.year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _total(totals: tuple[tuple[str | None, Money], ...]) -> Money:
    return sum((amount for _, amount in totals), Money.zero())


def _previous_month(today: date) -> tuple[date, date]:
    first_day = date(today.year, today.month, 1)
    return month_bounds(first_day - timedelta(days=1))


def _previous_period(start: date, end: date) -> tuple[date, date]:
    previous_end = start - timedelta(days=1)
    length = (end - start).days
    return previous_end - timedelta(days=length), previous_end


def _comparison_text(current: Money, previous: Money) -> str | None:
    """Изменение к предыдущему периоду; ``None``, если данных за него не было."""
    if previous.is_zero:
        return None
    diff = current - previous
    if diff.is_zero:
        return "К предыдущему периоду: без изменений."
    magnitude = -diff if diff.is_negative else diff
    percent = (diff.rubles / previous.rubles * HUNDRED).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    sign = "-" if diff.is_negative else "+"
    return f"К предыдущему периоду: {sign}{magnitude.format_ru()} ({sign}{abs(percent)}%)"


def _bill_line(due: date, title: str, amount: Money | None) -> str:
    value = amount.format_ru() if amount is not None else "сумма по факту"
    return f"{due:%d.%m} — {title} — {value}"
