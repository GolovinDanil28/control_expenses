"""Тесты денежного value object: сценарии expenses «Отображение суммы с копейками»."""

from decimal import Decimal

import pytest

from control_expenses.domain.money import Money


def test_kopecks_roundtrip() -> None:
    assert Money.from_kopecks(25000).kopecks == 25000
    assert Money.from_kopecks(50).rubles == Decimal("0.50")


def test_format_without_kopecks() -> None:
    assert Money.from_rubles("250").format_ru() == "250 ₽"


def test_format_with_kopecks() -> None:
    assert Money.from_rubles("1250.50").format_ru() == "1 250 ₽ 50 коп"


def test_format_groups_thousands() -> None:
    assert Money.from_rubles("3333.33").format_ru() == "3 333 ₽ 33 коп"
    assert Money.from_rubles("50000").format_ru() == "50 000 ₽"


def test_format_negative() -> None:
    assert Money.from_rubles("-500").format_ru() == "-500 ₽"


def test_addition_and_subtraction() -> None:
    assert (Money.from_rubles("250") + Money.from_rubles("100")).format_ru() == "350 ₽"
    assert (Money.from_rubles("250") - Money.from_rubles("100")).format_ru() == "150 ₽"


def test_zero_and_negative_predicates() -> None:
    assert Money.zero().is_zero
    assert Money.from_rubles("0.00").is_zero
    assert Money.from_rubles("-1").is_negative
    assert not Money.from_rubles("1").is_negative


def test_floordiv_rounds_down_to_kopeck() -> None:
    # 10 000 ₽ / 3 дня = 3 333.333… → вниз до 3 333 ₽ 33 коп
    assert (Money.from_rubles("10000") // 3).format_ru() == "3 333 ₽ 33 коп"


def test_floordiv_exact() -> None:
    assert (Money.from_rubles("25000") // 10).format_ru() == "2 500 ₽"
    assert (Money.from_rubles("3000") // 1).format_ru() == "3 000 ₽"


def test_floordiv_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        _ = Money.from_rubles("100") // 0
