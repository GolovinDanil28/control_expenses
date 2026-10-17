"""Доменные исключения.

Правила бизнес-логики сообщают о себе типами, а не строками: интерфейсы
переводят эти исключения в понятные пользователю сообщения.
"""

from __future__ import annotations


class DomainError(Exception):
    """Базовое исключение доменного слоя."""


class InvalidAmountError(DomainError):
    """Сумма отсутствует, отрицательна или равна нулю."""


class UnknownCategoryError(DomainError):
    """Категория отсутствует в справочнике."""


class DuplicateCategoryError(DomainError):
    """Категория с таким названием уже есть в справочнике."""


class FutureDateError(DomainError):
    """Дата траты позже текущей."""


class InvalidDayOfMonthError(DomainError):
    """День месяца вне диапазона 1–31."""


class MissingCommitmentAmountError(DomainError):
    """Фиксированному обязательству не задана сумма."""


class BudgetNotConfiguredError(DomainError):
    """Лимит месяца не задан и лимит по умолчанию не настроен."""
