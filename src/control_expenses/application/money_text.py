"""Разбор денежного текста из аргументов команд.

Свободный текст трат разбирает ``IntentParser``; здесь — «сухие» суммы вида
«60000», «1 250», «250.50» и проверка, что сообщение похоже на голое число.
"""

from __future__ import annotations

import re

from control_expenses.domain.money import Money

_MONEY_RE = re.compile(r"\d+(?:[.,]\d{1,2})?")
_BARE_RE = re.compile(r"[\d\s\u00a0]+(?:[.,]\d{1,2})?")
_CURRENCY_WORDS_RE = re.compile(r"(₽|руб\.?|р\.?|коп\.?)", re.IGNORECASE)


def parse_amount_text(text: str) -> Money | None:
    """«60000», «1 250», «250.50» → ``Money``; иначе ``None``."""
    normalized = text.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    if not _MONEY_RE.fullmatch(normalized):
        return None
    return Money.from_rubles(normalized)


def looks_like_plain_amount(text: str) -> bool:
    """Похоже ли сообщение на голую сумму без слов (например «350» или «350р»)."""
    stripped = _CURRENCY_WORDS_RE.sub("", text.strip())
    return bool(_BARE_RE.fullmatch(stripped.strip()))
