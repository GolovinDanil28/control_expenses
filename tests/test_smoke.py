"""Смоук-тест: пакет и точка входа бота импортируются."""

from control_expenses.interfaces import bot
from control_expenses.interfaces.handlers import START_TEXT


def test_entry_point_is_available() -> None:
    assert callable(bot.main)
    assert callable(bot.build_service)
    assert callable(bot.build_dispatcher)


def test_start_text_has_no_markup() -> None:
    # parse_mode не задан: угловые скобки в тексте ломали отправку
    assert "<" not in START_TEXT
    assert ">" not in START_TEXT
