"""Тесты детерминированного парсера: сценарии expenses и ai-insights."""

from datetime import date

from control_expenses.application.intent import FailedIntent, ParsedIntent, ParseFailure
from control_expenses.domain.categories import DEFAULT_CATEGORIES
from control_expenses.infrastructure.parsing.deterministic import DeterministicParser

TODAY = date(2026, 10, 16)


def _parser() -> DeterministicParser:
    return DeterministicParser(lambda: DEFAULT_CATEGORIES)


def _ok(text: str) -> ParsedIntent:
    result = _parser().parse(text, today=TODAY)
    assert isinstance(result, ParsedIntent), result
    return result


def test_recognizes_amount_and_category() -> None:
    intent = _ok("купил кофе 250")
    assert intent.amount.format_ru() == "250 ₽"
    assert intent.category == "Еда"
    assert intent.spent_on == TODAY


def test_recognizes_amount_without_category() -> None:
    intent = _ok("кофе 250")
    assert intent.category == "Еда"


def test_plain_amount_and_currency_suffix() -> None:
    assert _ok("250").amount.format_ru() == "250 ₽"
    assert _ok("заплатил 250р").amount.format_ru() == "250 ₽"
    assert _ok("1250руб").amount.format_ru() == "1 250 ₽"


def test_grouped_thousands() -> None:
    assert _ok("продукты 1 250").amount.format_ru() == "1 250 ₽"


def test_rubles_and_kopecks() -> None:
    intent = _ok("1 250 ₽ 50 коп")
    assert intent.amount.format_ru() == "1 250 ₽ 50 коп"


def test_explicit_amount_wins_over_stray_numbers() -> None:
    intent = _ok("сдача 100, чек 300р")
    assert intent.amount.format_ru() == "300 ₽"


def test_relative_date_yesterday() -> None:
    intent = _ok("такси 800 вчера")
    assert intent.spent_on == date(2026, 10, 15)
    assert intent.category == "Транспорт"


def test_no_amount() -> None:
    result = _parser().parse("потратил немного на обед", today=TODAY)
    assert isinstance(result, FailedIntent)
    assert result.reason is ParseFailure.NO_AMOUNT


def test_ambiguous_amount() -> None:
    result = _parser().parse("перевёл 500 и 300", today=TODAY)
    assert isinstance(result, FailedIntent)
    assert result.reason is ParseFailure.AMBIGUOUS_AMOUNT


def test_category_outside_reference_is_dropped() -> None:
    intent = _ok("нечто 100")
    assert intent.amount.format_ru() == "100 ₽"
    assert intent.category is None


def test_unknown_category_word_is_none() -> None:
    assert _ok("сходил за 500").category is None


def test_explicit_numeric_date() -> None:
    intent = _ok("такси 800 12.10")
    assert intent.amount.format_ru() == "800 ₽"
    assert intent.spent_on == date(2026, 10, 12)


def test_explicit_date_with_year() -> None:
    intent = _ok("кофе 250 05.09.2026")
    assert intent.spent_on == date(2026, 9, 5)


def test_sole_date_like_number_is_amount() -> None:
    intent = _ok("кофе 12.10")
    assert intent.amount.format_ru() == "12 ₽ 10 коп"
    assert intent.spent_on == TODAY


def test_future_date_is_parsed_not_rejected_here() -> None:
    intent = _ok("кофе 250 25.12")
    assert intent.spent_on == date(2026, 12, 25)


def test_invalid_date_is_not_a_date() -> None:
    result = _parser().parse("кофе 250 32.10", today=TODAY)
    assert isinstance(result, FailedIntent)
    assert result.reason is ParseFailure.AMBIGUOUS_AMOUNT
