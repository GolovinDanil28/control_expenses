"""Состояние фиксаций бюджета за месяц.

Порог приближения к лимиту и превышение фиксируются **однократно** за месяц
(capability ``budgets``); запись живёт в БД, поэтому переживает рестарт и не
зависит от памяти процесса.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from control_expenses.domain.money import Money


@dataclass(frozen=True)
class BudgetState:
    """Что уже зафиксировано по месяцу ``period``."""

    period: str
    threshold_fixed: bool = False
    overrun_fixed: bool = False
    overrun: Money = field(default_factory=Money.zero)
