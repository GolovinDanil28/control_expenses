"""Тесты справочника категорий: сценарии expenses «Справочник категорий»."""

from control_expenses.domain.categories import (
    DEFAULT_CATEGORIES,
    clean_category_name,
    is_duplicate_category,
    normalize_category,
)


def test_default_categories_present() -> None:
    assert "Продукты" in DEFAULT_CATEGORIES
    assert "Еда" in DEFAULT_CATEGORIES
    assert "Транспорт" in DEFAULT_CATEGORIES


def test_normalize_is_case_insensitive() -> None:
    assert normalize_category("еда", DEFAULT_CATEGORIES) == "Еда"
    assert normalize_category("  ЕДА ", DEFAULT_CATEGORIES) == "Еда"


def test_normalize_unknown_returns_none() -> None:
    assert normalize_category("Космос", DEFAULT_CATEGORIES) is None


def test_duplicate_detection_ignores_case() -> None:
    known = [*DEFAULT_CATEGORIES, "Ветеринарка"]
    assert is_duplicate_category("ветеринарка", known) is True
    assert is_duplicate_category("Ветеринарка", known) is True
    assert is_duplicate_category("Аптека", known) is False


def test_clean_category_name_collapses_spaces() -> None:
    assert clean_category_name("  Ветеринарка   кота ") == "Ветеринарка кота"
