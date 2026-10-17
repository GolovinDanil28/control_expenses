"""Композитный разбор: детерминированный первый, ИИ — только при неудаче.

Дорогой разбор зовётся лишь тогда, когда детерминированный не справился.
Деградация обязательна: если ИИ-бэкенд недоступен или ответил мусором, работа не
прерывается — возвращается результат детерминированного парсера.
"""

from __future__ import annotations

from datetime import date

from control_expenses.application.intent import (
    FailedIntent,
    IntentParser,
    IntentParseResult,
    ParserUnavailableError,
)
from control_expenses.domain.money import Money


class FallbackParser:
    """Сначала ``primary``; ``secondary`` — запасной вариант при неудаче."""

    def __init__(self, *, primary: IntentParser, secondary: IntentParser) -> None:
        self._primary = primary
        self._secondary = secondary

    def parse(self, text: str, *, today: date) -> IntentParseResult:
        primary = self._primary.parse(text, today=today)
        if not isinstance(primary, FailedIntent):
            return primary
        try:
            return self._secondary.parse(text, today=today)
        except ParserUnavailableError:
            return primary

    def parse_amount(self, text: str) -> Money | None:
        return self._primary.parse_amount(text)
