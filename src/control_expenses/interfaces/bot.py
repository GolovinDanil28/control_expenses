"""Точка входа Telegram-бота.

Реализация хендлеров — по спецификации
``openspec/changes/add-expense-tracker-mvp/``; этот модуль остаётся тонкой
обёрткой, чтобы entry point ``control-expenses`` работал с первого дня.
"""

from __future__ import annotations


def main() -> None:
    msg = "Бот ещё не реализован: см. openspec/changes/add-expense-tracker-mvp/"
    raise SystemExit(msg)


if __name__ == "__main__":
    main()
