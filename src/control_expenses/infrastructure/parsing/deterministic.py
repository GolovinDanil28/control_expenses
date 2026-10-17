"""Детерминированный разбор сообщения о трате — деградация без ИИ.

Понимает «кофе 250», «250р», «1 250», «1 250 ₽ 50 коп», явные категории и даты
(«вчера», «12.10», «12.10.2026»). Работает без сети и без модели; если разобрать
нельзя — сообщает причину, чтобы use case задал уточняющий вопрос.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from control_expenses.application.intent import (
    FailedIntent,
    IntentParseResult,
    ParsedIntent,
    ParseFailure,
)
from control_expenses.domain.categories import normalize_category
from control_expenses.domain.money import Money

_GROUPED_OR_PLAIN = r"\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_NUMBER_RE = re.compile(_GROUPED_OR_PLAIN)
_RUB_KOP_RE = re.compile(
    rf"({_GROUPED_OR_PLAIN})\s*(?:₽|руб(?:\.|ля|лей)?|р\.?)?\s*(\d{{1,2}})\s*коп",
    re.IGNORECASE,
)
_CURRENCY_RE = re.compile(r"^\s*(?:₽|руб|р\.?\b)", re.IGNORECASE)
_DATE_TOKEN_RE = re.compile(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?")

_SYNONYMS: dict[str, str] = {
    "кофе": "Еда",
    "обед": "Еда",
    "кафе": "Еда",
    "ресторан": "Еда",
    "продукт": "Продукты",
    "магазин": "Продукты",
    "такси": "Транспорт",
    "метро": "Транспорт",
    "автобус": "Транспорт",
    "бензин": "Транспорт",
    "аптек": "Здоровье",
    "врач": "Здоровье",
    "кино": "Развлечения",
}

_RELATIVE_DATES: dict[str, int] = {
    "позавчера": -2,
    "вчера": -1,
    "сегодня": 0,
}

MAX_DAY = 31
MAX_MONTH = 12


@dataclass(frozen=True)
class _Amount:
    money: Money
    explicit: bool
    start: int
    end: int


def _normalize_number(token: str) -> str:
    return token.replace(" ", "").replace("\u00a0", "").replace(",", ".")


def _date_from_match(match: re.Match[str], default_year: int) -> date | None:
    day = int(match.group(1))
    month = int(match.group(2))
    if not 1 <= day <= MAX_DAY or not 1 <= month <= MAX_MONTH:
        return None
    year = int(match.group(3)) if match.group(3) is not None else default_year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _blank_dates(text: str, year: int) -> str:
    """Затереть валидные даты пробелами, сохранив позиции остальных чисел.

    Иначе «05.09.2026» распадается на отдельные числа и сумма ищется неверно.
    """
    chars = list(text)
    for match in _DATE_TOKEN_RE.finditer(text):
        if _date_from_match(match, year) is not None:
            for index in range(match.start(), match.end()):
                chars[index] = " "
    return "".join(chars)


class DeterministicParser:
    """Парсер на регулярных выражениях и словаре синонимов категорий."""

    def __init__(self, categories: Callable[[], Iterable[str]]) -> None:
        self._categories = categories

    def parse_amount(self, text: str) -> Money | None:
        """Сумма из аргумента команды или ответа на запрос суммы (год не важен)."""
        match = self._amount_match(text, year=0)
        return None if match is None else match[0]

    def parse(self, text: str, *, today: date) -> IntentParseResult:
        match = self._amount_match(text, today.year)
        if match is None:
            return FailedIntent(self._failure_reason(text))
        amount, start, end = match
        return ParsedIntent(
            amount=amount,
            spent_on=self._extract_date(text, today, start, end),
            category=self._extract_category(text),
        )

    def _amount_match(self, text: str, year: int) -> tuple[Money, int, int] | None:
        """Сумма и её позиция в тексте; даты-числа по возможности исключаются."""
        combo = _RUB_KOP_RE.search(text)
        if combo is not None:
            rubles = int(_normalize_number(combo.group(1)).split(".")[0])
            kopecks = int(combo.group(2))
            return (
                Money.from_kopecks(rubles * 100 + kopecks),
                combo.start(),
                combo.end(),
            )
        # числа, похожие на дату, не считаем суммой, если есть другая сумма
        chosen = self._choose_amount(text, year, exclude_dates=True)
        if chosen is None and _DATE_TOKEN_RE.search(text) is not None:
            chosen = self._choose_amount(text, year, exclude_dates=False)
        if chosen is None:
            return None
        money, span = chosen
        return money, span[0], span[1]

    def _choose_amount(
        self, text: str, year: int, *, exclude_dates: bool
    ) -> tuple[Money, tuple[int, int]] | None:
        candidates = self._amount_candidates(text, year, exclude_dates=exclude_dates)
        explicit = [candidate for candidate in candidates if candidate.explicit]
        if explicit:
            return explicit[0].money, (explicit[0].start, explicit[0].end)
        if len(candidates) == 1:
            return candidates[0].money, (candidates[0].start, candidates[0].end)
        return None

    def _failure_reason(self, text: str) -> ParseFailure:
        candidates = self._amount_candidates(text, 0, exclude_dates=False)
        if not candidates:
            return ParseFailure.NO_AMOUNT
        return ParseFailure.AMBIGUOUS_AMOUNT

    def _amount_candidates(self, text: str, year: int, *, exclude_dates: bool) -> list[_Amount]:
        source = _blank_dates(text, year) if exclude_dates else text
        candidates: list[_Amount] = []
        for match in _NUMBER_RE.finditer(source):
            tail = text[match.end() : match.end() + 5]
            candidates.append(
                _Amount(
                    money=Money.from_rubles(_normalize_number(match.group(0))),
                    explicit=bool(_CURRENCY_RE.match(tail)),
                    start=match.start(),
                    end=match.end(),
                )
            )
        return candidates

    def _extract_date(self, text: str, today: date, amount_start: int, amount_end: int) -> date:
        relative = self._relative_date(text, today)
        if relative is not None:
            return relative
        for match in _DATE_TOKEN_RE.finditer(text):
            if amount_start <= match.start() and match.end() <= amount_end:
                continue  # это распознанная сумма, а не дата
            parsed = _date_from_match(match, today.year)
            if parsed is not None:
                return parsed
        return today

    def _relative_date(self, text: str, today: date) -> date | None:
        lowered = text.casefold()
        for word, delta in _RELATIVE_DATES.items():
            if word in lowered:
                return today + timedelta(days=delta)
        return None

    def _extract_category(self, text: str) -> str | None:
        lowered = text.casefold()
        for word, category in _SYNONYMS.items():
            if word in lowered:
                return normalize_category(category, self._categories())
        for candidate in self._categories():
            if candidate.casefold() in lowered:
                return candidate
        return None
