"""Смоук-тест: пакет импортируется, заглушка бота отвечает выходом с текстом."""

import pytest

from control_expenses.interfaces import bot


def test_bot_stub_exits_with_pointer_to_spec() -> None:
    with pytest.raises(SystemExit) as exc_info:
        bot.main()
    assert "openspec" in str(exc_info.value)
