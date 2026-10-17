"""Порты прикладного слоя.

Реализации живут в ``infrastructure``; в тестах используются фейки. Порты
описывают только то, что нужно use case'ам, — без деталей БД и Telegram.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from control_expenses.application.budgets.state import BudgetState
from control_expenses.application.commitments.prompt import CommitmentPrompt
from control_expenses.application.commitments.replies import BillItem, UpcomingBill
from control_expenses.application.expenses.draft import ExpenseDraft
from control_expenses.application.replies import TextReply
from control_expenses.application.views import Reply
from control_expenses.domain.budget import BudgetStatus
from control_expenses.domain.entities import Commitment, CommitmentOccurrence, Expense
from control_expenses.domain.money import Money


class Clock(Protocol):
    """Источник текущего времени в настроенной таймзоне."""

    def now(self) -> datetime: ...

    def today(self) -> date: ...


class ExpenseRepository(Protocol):
    """Хранилище подтверждённых трат."""

    def add(self, expense: Expense) -> Expense: ...

    def update(self, expense: Expense) -> Expense: ...

    def last(self, source_chat_id: int) -> Expense | None: ...

    def delete(self, expense_id: int) -> None: ...

    def spent_between(self, start: date, end: date) -> Money: ...

    def totals_by_category(
        self, start: date, end: date
    ) -> tuple[tuple[str | None, Money], ...]: ...


class CategoryRepository(Protocol):
    """Справочник категорий."""

    def list(self) -> tuple[str, ...]: ...

    def add(self, name: str) -> str: ...


class PendingInputStore(Protocol):
    """Черновики, ожидающие действия пользователя (по чату)."""

    def get(self, chat_id: int) -> ExpenseDraft | None: ...

    def set(self, chat_id: int, draft: ExpenseDraft) -> None: ...

    def clear(self, chat_id: int) -> None: ...


class BudgetRepository(Protocol):
    """Явно заданные лимиты по месяцам."""

    def limit_for(self, period: str) -> Money | None: ...

    def set_limit(self, period: str, limit: Money) -> None: ...


class BudgetStateRepository(Protocol):
    """Зафиксированные события месяца: достигнутый порог и превышение."""

    def get(self, period: str) -> BudgetState: ...

    def save(self, state: BudgetState) -> None: ...


class ObligationQuery(Protocol):
    """Неоплаченные обязательства месяца: сумма и признак «оценка грубая»."""

    def month_obligations(self, period: str) -> tuple[Money, bool]: ...


class BudgetStatusQuery(Protocol):
    """Состояние бюджета текущего месяца: период, статус (или ``None``) и траты."""

    def month_status(self) -> tuple[str, BudgetStatus | None, Money]: ...


class UpcomingCommitments(Protocol):
    """Ближайшие обязательства для сводок."""

    def upcoming(self, today: date, limit: int = 3) -> tuple[UpcomingBill, ...]: ...


class CommitmentRepository(Protocol):
    """Справочник обязательств."""

    def add(self, commitment: Commitment) -> Commitment: ...

    def list(self) -> tuple[Commitment, ...]: ...

    def get(self, commitment_id: int) -> Commitment | None: ...

    def delete(self, commitment_id: int) -> None: ...


class CommitmentOccurrenceRepository(Protocol):
    """Экземпляры обязательств по месяцам (создаются лениво и идемпотентно)."""

    def ensure_period(self, period: str) -> None: ...

    def get(self, commitment_id: int, period: str) -> CommitmentOccurrence | None: ...

    def save(self, occurrence: CommitmentOccurrence) -> CommitmentOccurrence: ...

    def for_period(self, period: str) -> tuple[CommitmentOccurrence, ...]: ...

    def pending_for_period(self, period: str) -> tuple[CommitmentOccurrence, ...]: ...

    def last_actual_amount(self, commitment_id: int) -> Money | None: ...


class CommitmentPromptStore(Protocol):
    """Активные ожидания ответа по обязательствам (сумма, показания)."""

    def get(self, chat_id: int) -> CommitmentPrompt | None: ...

    def set(self, chat_id: int, prompt: CommitmentPrompt) -> None: ...

    def clear(self, chat_id: int) -> None: ...


class NotificationLog(Protocol):
    """Дедупликация оповещений по уникальному ключу."""

    def claim(self, dedup_key: str) -> bool:
        """Занять ключ; ``False``, если оповещение с таким ключом уже отправлено."""
        ...


class SettingsRepository(Protocol):
    """Настройки расписания и тихого часа (key/value)."""

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...


class WeeklySummary(Protocol):
    """Содержимое недельной сводки (реализует capability ``reports``)."""

    def weekly_summary(self) -> TextReply: ...


class DueCommitments(Protocol):
    """Обязательства, срок которых наступил и платёж не проведён."""

    def due_bills(self, today: date) -> tuple[BillItem, ...]: ...


class MessageSender(Protocol):
    """Доставка инициативного сообщения в чат."""

    async def send(self, chat_id: int, reply: Reply) -> None: ...


class UnknownChatStore(Protocol):
    """Чаты вне списка допуска, о которых владельцу ещё не сообщили."""

    def register(self, chat_id: int) -> None: ...

    def pending(self) -> tuple[int, ...]: ...

    def resolve(self, chat_id: int) -> None: ...
