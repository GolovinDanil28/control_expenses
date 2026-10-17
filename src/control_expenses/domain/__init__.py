"""Доменный слой: сущности, value objects, бизнес-правила.

Не зависит ни от чего внешнего (ни БД, ни фреймворков, ни CLI).
"""

from __future__ import annotations

from control_expenses.domain.budget import (
    BudgetStatus,
    CommitmentObligation,
    committed_total,
    days_left_in_month,
    month_bounds,
    period_of,
    threshold_reached,
)
from control_expenses.domain.categories import (
    DEFAULT_CATEGORIES,
    clean_category_name,
    is_duplicate_category,
    normalize_category,
)
from control_expenses.domain.commitments import (
    clamp_to_month,
    next_occurrence,
    occurrence_date,
)
from control_expenses.domain.entities import (
    Category,
    Commitment,
    CommitmentKind,
    CommitmentOccurrence,
    Expense,
    OccurrenceStatus,
)
from control_expenses.domain.errors import (
    BudgetNotConfiguredError,
    DomainError,
    DuplicateCategoryError,
    FutureDateError,
    InvalidAmountError,
    InvalidDayOfMonthError,
    MissingCommitmentAmountError,
    UnknownCategoryError,
)
from control_expenses.domain.money import Money

__all__ = [
    "DEFAULT_CATEGORIES",
    "BudgetNotConfiguredError",
    "BudgetStatus",
    "Category",
    "Commitment",
    "CommitmentKind",
    "CommitmentObligation",
    "CommitmentOccurrence",
    "DomainError",
    "DuplicateCategoryError",
    "Expense",
    "FutureDateError",
    "InvalidAmountError",
    "InvalidDayOfMonthError",
    "MissingCommitmentAmountError",
    "Money",
    "OccurrenceStatus",
    "UnknownCategoryError",
    "clamp_to_month",
    "clean_category_name",
    "committed_total",
    "days_left_in_month",
    "is_duplicate_category",
    "month_bounds",
    "next_occurrence",
    "normalize_category",
    "occurrence_date",
    "period_of",
    "threshold_reached",
]
