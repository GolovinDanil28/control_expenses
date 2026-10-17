"""Разбор текста о трате через ИИ-бэкенд (Ollama / OpenAI-совместимый API).

Модель только извлекает структуру и возвращает strict-JSON; все проверки — здесь.
В промпт уходят лишь текст сообщения, список категорий и текущая дата
(capability ``ai-insights``): ни истории трат, ни бюджета, ни идентификаторов.
Сбой бэкенда — это ``ParserUnavailableError``: use case решает, деградировать ли
на детерминированный разбор.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from control_expenses.application.intent import (
    FailedIntent,
    IntentParseResult,
    ParsedIntent,
    ParseFailure,
    ParserUnavailableError,
)
from control_expenses.domain.categories import normalize_category
from control_expenses.domain.money import Money
from control_expenses.infrastructure.parsing.deterministic import DeterministicParser

MULTIPLE_NOTE = "Похоже, в сообщении не одна трата — остальные отправьте отдельно."
PROMPT_TEMPLATE = (
    "Разбери сообщение о трате и верни строгий JSON: "
    '{{"kind": "expense" или "none", "amount": число или null, '
    '"category": строка или null, "date": "ГГГГ-ММ-ДД" или null, '
    '"multiple": true или false, "reason": "no_amount" или null}}. '
    "Если в сообщении несколько трат, возьми только первую и поставь multiple=true, "
    "суммы не складывай. Если суммы нет — kind=none и reason=no_amount. "
    "Сегодня {today}. Категории: {categories}. Сообщение: {text}"
)


def build_prompt(text: str, today: date, categories: Iterable[str]) -> str:
    """Промпт с минимальным контекстом: текст, категории и дата."""
    return PROMPT_TEMPLATE.format(
        today=f"{today:%Y-%m-%d}",
        categories=", ".join(categories),
        text=text,
    )


@dataclass(frozen=True)
class LlmConfig:
    """Параметры подключения к ИИ-бэкенду."""

    base_url: str
    model: str
    api_key: str = ""
    timeout: float = 10.0


class LlmIntentParser:
    """Общая часть: запрос к бэкенду, чтение JSON и валидация ответа."""

    def __init__(
        self,
        *,
        client: httpx.Client,
        config: LlmConfig,
        categories: Callable[[], Iterable[str]],
    ) -> None:
        self._client = client
        self._config = config
        self._categories = categories
        self._plain = DeterministicParser(categories)

    def parse_amount(self, text: str) -> Money | None:
        """Сумма из ответа на запрос суммы остаётся детерминированной."""
        return self._plain.parse_amount(text)

    def parse(self, text: str, *, today: date) -> IntentParseResult:
        return self._validate(self._request(text, today), today)

    def _request(self, text: str, today: date) -> dict[str, object]:
        prompt = build_prompt(text, today, self._categories())
        try:
            content = self._call(prompt)
            payload = json.loads(content)
        except (httpx.HTTPError, ValueError) as error:
            raise ParserUnavailableError(f"ИИ-бэкенд недоступен: {error}") from error
        if not isinstance(payload, dict):
            raise ParserUnavailableError("ИИ-бэкенд вернул не объект JSON")
        return payload

    def _call(self, prompt: str) -> str:
        raise NotImplementedError

    def _validate(self, payload: dict[str, object], today: date) -> IntentParseResult:
        if payload.get("kind") != "expense":
            return FailedIntent(_reason(payload.get("reason")))
        amount = _to_money(payload.get("amount"))
        if amount is None or amount.is_zero or amount.is_negative:
            return FailedIntent(ParseFailure.NO_AMOUNT)
        return ParsedIntent(
            amount=amount,
            spent_on=_to_date(payload.get("date"), today),
            category=_to_category(payload.get("category"), self._categories()),
            note=MULTIPLE_NOTE if payload.get("multiple") is True else None,
        )


class OllamaParser(LlmIntentParser):
    """Разбор через локальный Ollama (``/api/generate`` с ``format: json``)."""

    def _call(self, prompt: str) -> str:
        response = self._client.post(
            f"{self._config.base_url.rstrip('/')}/api/generate",
            json={
                "model": self._config.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
        )
        response.raise_for_status()
        content = response.json().get("response")
        if not isinstance(content, str):
            raise ValueError("пустой ответ Ollama")
        return content


class OpenAiParser(LlmIntentParser):
    """Разбор через OpenAI-совместимый API (``/chat/completions``)."""

    def _call(self, prompt: str) -> str:
        headers = (
            {"Authorization": f"Bearer {self._config.api_key}"} if self._config.api_key else {}
        )
        response = self._client.post(
            f"{self._config.base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": self._config.model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        choices = response.json().get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("пустой ответ модели")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ValueError("пустой ответ модели")
        return content


def _to_money(value: object) -> Money | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            return Money.from_rubles(Decimal(str(value)))
        except InvalidOperation:
            return None
    return None


def _to_date(value: object, today: date) -> date:
    """Дата из ответа модели; будущее и мусор сводятся к сегодняшней."""
    if not isinstance(value, str):
        return today
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return today
    return today if parsed > today else parsed


def _to_category(value: object, known: Iterable[str]) -> str | None:
    """Название из справочника независимо от регистра; иначе категории нет."""
    if not isinstance(value, str) or not value.strip():
        return None
    return normalize_category(value, known)


def _reason(value: object) -> ParseFailure:
    if value == ParseFailure.AMBIGUOUS_AMOUNT.value:
        return ParseFailure.AMBIGUOUS_AMOUNT
    return ParseFailure.NO_AMOUNT
