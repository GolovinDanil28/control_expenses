"""Справочник категорий трат.

Справочник предопределён, но расширяется пользователем (``/addcategory``).
Название из свободного текста приводится к названию из справочника без учёта
регистра и лишних пробелов.
"""

from __future__ import annotations

from collections.abc import Iterable

DEFAULT_CATEGORIES: tuple[str, ...] = (
    "Продукты",
    "Еда",
    "Транспорт",
    "Жильё",
    "Связь",
    "Подписки",
    "Коммунальные",
    "Здоровье",
    "Развлечения",
    "Прочее",
)


def _key(name: str) -> str:
    return name.strip().casefold()


def normalize_category(name: str, known: Iterable[str]) -> str | None:
    """Вернуть название из справочника или ``None``, если его там нет."""
    target = _key(name)
    for candidate in known:
        if _key(candidate) == target:
            return candidate
    return None


def is_duplicate_category(name: str, known: Iterable[str]) -> bool:
    """Есть ли уже категория с таким названием (без учёта регистра)."""
    return normalize_category(name, known) is not None


def clean_category_name(name: str) -> str:
    """Каноническая форма пользовательского названия для добавления."""
    return " ".join(name.split())
