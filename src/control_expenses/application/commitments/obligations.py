"""Сбор обязательств месяца для расчёта остатка бюджета."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from control_expenses.domain.budget import CommitmentObligation, committed_total
from control_expenses.domain.entities import (
    Commitment,
    CommitmentKind,
    CommitmentOccurrence,
)
from control_expenses.domain.money import Money


def build_obligations(
    occurrences: Sequence[CommitmentOccurrence],
    commitments: Mapping[int, Commitment],
    last_amounts: Mapping[int, Money],
) -> tuple[Money, bool]:
    """Сумма неоплаченных обязательств месяца и признак «оценка грубая».

    Фиксированные берутся по известной сумме; плавающие — по последней
    введённой сумме (тогда остаток помечается как оценка) либо не учитываются.
    Счётчики денег не создают и в остаток не входят.
    """
    obligations: list[CommitmentObligation] = []
    for occurrence in occurrences:
        commitment = commitments.get(occurrence.commitment_id)
        if commitment is None or commitment.kind is CommitmentKind.METER:
            continue
        if commitment.kind is CommitmentKind.FIXED:
            obligations.append(CommitmentObligation(commitment.amount, is_estimate=False))
            continue
        last = last_amounts.get(occurrence.commitment_id)
        obligations.append(CommitmentObligation(amount=last, is_estimate=last is not None))
    return committed_total(obligations)
