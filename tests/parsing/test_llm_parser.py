"""Тесты LLM-адаптеров: разбор, валидация, минимальный контекст, деградация."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from control_expenses.application.intent import (
    FailedIntent,
    IntentParseResult,
    ParsedIntent,
    ParseFailure,
    ParserUnavailableError,
)
from control_expenses.domain.categories import DEFAULT_CATEGORIES
from control_expenses.domain.money import Money
from control_expenses.infrastructure.parsing.deterministic import DeterministicParser
from control_expenses.infrastructure.parsing.fallback import FallbackParser
from control_expenses.infrastructure.parsing.llm import (
    MULTIPLE_NOTE,
    LlmConfig,
    OllamaParser,
    OpenAiParser,
    build_prompt,
)

TODAY = date(2026, 10, 16)


def _config(base_url: str = "http://localhost:11434", api_key: str = "") -> LlmConfig:
    return LlmConfig(base_url=base_url, model="qwen2.5-coder:7b", api_key=api_key, timeout=1.0)


def _payload(**overrides: object) -> str:
    base: dict[str, object] = {
        "kind": "expense",
        "amount": 250,
        "category": "еда",
        "date": None,
        "multiple": False,
        "reason": None,
    }
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


def _ollama(content: str, captured: list[dict[str, object]] | None = None) -> OllamaParser:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(json.loads(request.content))
        return httpx.Response(200, json={"response": content})

    return OllamaParser(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        config=_config(),
        categories=lambda: DEFAULT_CATEGORIES,
    )


def _openai(content: str, captured: list[httpx.Request] | None = None) -> OpenAiParser:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return OpenAiParser(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        config=_config(base_url="https://api.example.com/v1", api_key="secret"),
        categories=lambda: DEFAULT_CATEGORIES,
    )


def test_ollama_parses_and_normalizes() -> None:
    captured: list[dict[str, object]] = []
    result = _ollama(_payload(amount=250), captured).parse("купил кофе 250", today=TODAY)
    assert isinstance(result, ParsedIntent)
    assert result.amount.format_ru() == "250 ₽"
    assert result.category == "Еда"  # «еда» → «Еда»
    assert result.spent_on == TODAY
    assert result.note is None
    assert captured[0]["model"] == "qwen2.5-coder:7b"
    assert captured[0]["format"] == "json"


def test_openai_parses_and_sends_key() -> None:
    captured: list[httpx.Request] = []
    result = _openai(_payload(amount="1250.50"), captured).parse("обед", today=TODAY)
    assert isinstance(result, ParsedIntent)
    assert result.amount.format_ru() == "1 250 ₽ 50 коп"
    assert captured[0].headers["Authorization"] == "Bearer secret"
    assert "/chat/completions" in str(captured[0].url)


def test_zero_amount_is_rejected() -> None:
    result = _ollama(_payload(amount=0)).parse("кофе", today=TODAY)
    assert isinstance(result, FailedIntent)
    assert result.reason is ParseFailure.NO_AMOUNT


def test_negative_amount_is_rejected() -> None:
    result = _ollama(_payload(amount=-100)).parse("кофе", today=TODAY)
    assert isinstance(result, FailedIntent)


def test_category_outside_reference_is_dropped() -> None:
    result = _ollama(_payload(category="Космос")).parse("кофе 250", today=TODAY)
    assert isinstance(result, ParsedIntent)
    assert result.category is None
    assert result.amount.format_ru() == "250 ₽"


def test_future_date_is_clamped_to_today() -> None:
    result = _ollama(_payload(date="2026-12-25")).parse("кофе 250", today=TODAY)
    assert isinstance(result, ParsedIntent)
    assert result.spent_on == TODAY


def test_past_date_is_kept() -> None:
    result = _ollama(_payload(date="2026-10-01")).parse("кофе 250", today=TODAY)
    assert isinstance(result, ParsedIntent)
    assert result.spent_on == date(2026, 10, 1)


def test_unparseable_date_falls_back_to_today() -> None:
    result = _ollama(_payload(date="вчера")).parse("кофе 250", today=TODAY)
    assert isinstance(result, ParsedIntent)
    assert result.spent_on == TODAY


def test_multiple_expenses_produce_note() -> None:
    result = _ollama(_payload(amount=400, multiple=True)).parse("обед 400, такси 300", today=TODAY)
    assert isinstance(result, ParsedIntent)
    assert result.note == MULTIPLE_NOTE


def test_non_expense_reports_reason() -> None:
    result = _ollama(_payload(kind="none", amount=None, reason="no_amount")).parse(
        "потратил немного на обед", today=TODAY
    )
    assert isinstance(result, FailedIntent)
    assert result.reason is ParseFailure.NO_AMOUNT


def test_ambiguous_reason_is_mapped() -> None:
    result = _ollama(_payload(kind="none", reason="ambiguous_amount")).parse("что-то", today=TODAY)
    assert isinstance(result, FailedIntent)
    assert result.reason is ParseFailure.AMBIGUOUS_AMOUNT


def test_transport_error_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет связи", request=request)

    parser = OllamaParser(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        config=_config(),
        categories=lambda: DEFAULT_CATEGORIES,
    )
    with pytest.raises(ParserUnavailableError):
        parser.parse("кофе 250", today=TODAY)


def test_http_error_raises_unavailable() -> None:
    parser = OllamaParser(
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
        config=_config(),
        categories=lambda: DEFAULT_CATEGORIES,
    )
    with pytest.raises(ParserUnavailableError):
        parser.parse("кофе 250", today=TODAY)


def test_non_json_answer_raises_unavailable() -> None:
    with pytest.raises(ParserUnavailableError):
        _ollama("это не json").parse("кофе 250", today=TODAY)


def test_prompt_contains_only_minimal_context() -> None:
    prompt = build_prompt("кофе 250", TODAY, ("Еда", "Продукты"))
    assert "кофе 250" in prompt
    assert "2026-10-16" in prompt
    assert "Еда, Продукты" in prompt
    # ни бюджета, ни истории трат, ни идентификаторов чатов
    assert "50000" not in prompt
    assert "chat" not in prompt.lower()


class _StubParser:
    def __init__(self, result: IntentParseResult) -> None:
        self.result = result
        self.calls = 0

    def parse(self, text: str, *, today: date) -> IntentParseResult:
        self.calls += 1
        return self.result

    def parse_amount(self, text: str) -> Money | None:
        return None


class _UnavailableParser:
    def parse(self, text: str, *, today: date) -> IntentParseResult:
        raise ParserUnavailableError("нет связи")

    def parse_amount(self, text: str) -> Money | None:
        return None


def _deterministic() -> DeterministicParser:
    return DeterministicParser(lambda: DEFAULT_CATEGORIES)


def test_fallback_skips_secondary_when_primary_succeeds() -> None:
    secondary = _StubParser(FailedIntent(ParseFailure.NO_AMOUNT))
    parser = FallbackParser(primary=_deterministic(), secondary=secondary)
    result = parser.parse("продукты 1200", today=TODAY)
    assert isinstance(result, ParsedIntent)
    assert result.amount.format_ru() == "1 200 ₽"
    assert result.category == "Продукты"
    assert secondary.calls == 0


def test_fallback_uses_secondary_when_primary_fails() -> None:
    llm = _StubParser(ParsedIntent(amount=Money.from_rubles("400"), spent_on=TODAY, category="Еда"))
    parser = FallbackParser(primary=_deterministic(), secondary=llm)
    result = parser.parse("обед 400, такси 300", today=TODAY)
    assert isinstance(result, ParsedIntent)
    assert result.amount.format_ru() == "400 ₽"
    assert llm.calls == 1


def test_fallback_degrades_when_backend_unavailable() -> None:
    parser = FallbackParser(primary=_deterministic(), secondary=_UnavailableParser())
    result = parser.parse("потратил немного на обед", today=TODAY)
    assert isinstance(result, FailedIntent)
    assert result.reason is ParseFailure.NO_AMOUNT


def test_fallback_amount_uses_primary() -> None:
    parser = FallbackParser(primary=_deterministic(), secondary=_UnavailableParser())
    amount = parser.parse_amount("350")
    assert amount is not None
    assert amount.format_ru() == "350 ₽"
