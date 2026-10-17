"""Общие для use case'ов ответы, которые отрисовывает интерфейс."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextReply:
    """Простой текстовый ответ."""

    text: str
