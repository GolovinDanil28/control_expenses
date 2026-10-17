"""SQLite-реализации портов прикладного слоя."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import date

from control_expenses.application.budgets.state import BudgetState
from control_expenses.application.commitments.prompt import CommitmentPrompt, PromptKind
from control_expenses.application.expenses.draft import DraftStage, ExpenseDraft
from control_expenses.domain.entities import (
    Commitment,
    CommitmentKind,
    CommitmentOccurrence,
    Expense,
    OccurrenceStatus,
)
from control_expenses.domain.money import Money

_PENDING_KIND = "expense_draft"
_PROMPT_KIND = "commitment_prompt"


class SqliteExpenseRepository:
    """Траты в таблице ``expense``."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, expense: Expense) -> Expense:
        cursor = self._connection.execute(
            """
            INSERT INTO expense (amount_kopecks, spent_on, category, source_chat_id, commitment_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                expense.amount.kopecks,
                expense.spent_on.isoformat(),
                expense.category,
                expense.source_chat_id,
                expense.commitment_id,
            ),
        )
        self._connection.commit()
        row_id = cursor.lastrowid
        assert row_id is not None  # AUTOINCREMENT всегда возвращает id
        return replace(expense, id=row_id)

    def last(self, source_chat_id: int) -> Expense | None:
        row = self._connection.execute(
            "SELECT * FROM expense WHERE source_chat_id = ? ORDER BY id DESC LIMIT 1",
            (source_chat_id,),
        ).fetchone()
        return None if row is None else _row_to_expense(row)

    def update(self, expense: Expense) -> Expense:
        if expense.id is None:
            raise ValueError("expense id is required for update")
        self._connection.execute(
            """
            UPDATE expense
            SET amount_kopecks = ?, spent_on = ?, category = ?,
                source_chat_id = ?, commitment_id = ?
            WHERE id = ?
            """,
            (
                expense.amount.kopecks,
                expense.spent_on.isoformat(),
                expense.category,
                expense.source_chat_id,
                expense.commitment_id,
                expense.id,
            ),
        )
        self._connection.commit()
        return expense

    def delete(self, expense_id: int) -> None:
        self._connection.execute("DELETE FROM expense WHERE id = ?", (expense_id,))
        self._connection.commit()

    def spent_between(self, start: date, end: date) -> Money:
        row = self._connection.execute(
            """
            SELECT COALESCE(SUM(amount_kopecks), 0) AS total
            FROM expense
            WHERE spent_on BETWEEN ? AND ?
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        return Money.from_kopecks(int(row["total"]))

    def totals_by_category(self, start: date, end: date) -> tuple[tuple[str | None, Money], ...]:
        rows = self._connection.execute(
            """
            SELECT category, SUM(amount_kopecks) AS total
            FROM expense
            WHERE spent_on BETWEEN ? AND ?
            GROUP BY category
            ORDER BY total DESC
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return tuple((row["category"], Money.from_kopecks(int(row["total"]))) for row in rows)


class SqliteBudgetRepository:
    """Явные месячные лимиты в таблице ``monthly_budget``."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def limit_for(self, period: str) -> Money | None:
        row = self._connection.execute(
            "SELECT limit_kopecks FROM monthly_budget WHERE period = ?", (period,)
        ).fetchone()
        return None if row is None else Money.from_kopecks(int(row["limit_kopecks"]))

    def set_limit(self, period: str, limit: Money) -> None:
        self._connection.execute(
            """
            INSERT INTO monthly_budget (period, limit_kopecks) VALUES (?, ?)
            ON CONFLICT(period) DO UPDATE SET limit_kopecks = excluded.limit_kopecks
            """,
            (period, limit.kopecks),
        )
        self._connection.commit()


class SqliteBudgetStateRepository:
    """Фиксации месяца в таблице ``budget_state``."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, period: str) -> BudgetState:
        row = self._connection.execute(
            "SELECT threshold_fixed, overrun_kopecks FROM budget_state WHERE period = ?",
            (period,),
        ).fetchone()
        if row is None:
            return BudgetState(period=period)
        overrun = row["overrun_kopecks"]
        return BudgetState(
            period=period,
            threshold_fixed=bool(row["threshold_fixed"]),
            overrun_fixed=overrun is not None,
            overrun=Money.zero() if overrun is None else Money.from_kopecks(int(overrun)),
        )

    def save(self, state: BudgetState) -> None:
        overrun = state.overrun.kopecks if state.overrun_fixed else None
        self._connection.execute(
            """
            INSERT INTO budget_state (period, threshold_fixed, overrun_kopecks) VALUES (?, ?, ?)
            ON CONFLICT(period) DO UPDATE SET
                threshold_fixed = excluded.threshold_fixed,
                overrun_kopecks = excluded.overrun_kopecks
            """,
            (state.period, int(state.threshold_fixed), overrun),
        )
        self._connection.commit()


class SqliteCategoryRepository:
    """Категории в таблице ``category``."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def list(self) -> tuple[str, ...]:
        rows = self._connection.execute("SELECT name FROM category ORDER BY id").fetchall()
        return tuple(str(row["name"]) for row in rows)

    def add(self, name: str) -> str:
        self._connection.execute("INSERT OR IGNORE INTO category (name) VALUES (?)", (name,))
        self._connection.commit()
        return name


class SqlitePendingInputStore:
    """Черновики в таблице ``pending_input`` (payload — JSON)."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, chat_id: int) -> ExpenseDraft | None:
        row = self._connection.execute(
            "SELECT payload FROM pending_input WHERE chat_id = ? AND kind = ?",
            (chat_id, _PENDING_KIND),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload"]))
        return ExpenseDraft(
            chat_id=chat_id,
            spent_on=date.fromisoformat(payload["spent_on"]),
            amount=None
            if payload["amount_kopecks"] is None
            else Money.from_kopecks(int(payload["amount_kopecks"])),
            category=payload["category"],
            status=DraftStage(payload["status"]),
            editing_expense_id=payload.get("editing_expense_id"),
        )

    def set(self, chat_id: int, draft: ExpenseDraft) -> None:
        payload = json.dumps(
            {
                "amount_kopecks": None if draft.amount is None else draft.amount.kopecks,
                "category": draft.category,
                "spent_on": draft.spent_on.isoformat(),
                "status": str(draft.status),
                "editing_expense_id": draft.editing_expense_id,
            },
            ensure_ascii=False,
        )
        self._connection.execute(
            """
            INSERT INTO pending_input (chat_id, kind, payload, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(chat_id) DO UPDATE SET
                kind = excluded.kind,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (chat_id, _PENDING_KIND, payload),
        )
        self._connection.commit()

    def clear(self, chat_id: int) -> None:
        self._connection.execute("DELETE FROM pending_input WHERE chat_id = ?", (chat_id,))
        self._connection.commit()


def _row_to_expense(row: sqlite3.Row) -> Expense:
    commitment_id = row["commitment_id"]
    return Expense(
        id=int(row["id"]),
        amount=Money.from_kopecks(int(row["amount_kopecks"])),
        spent_on=date.fromisoformat(str(row["spent_on"])),
        category=row["category"],
        source_chat_id=int(row["source_chat_id"]),
        commitment_id=None if commitment_id is None else int(commitment_id),
    )


class SqliteCommitmentRepository:
    """Обязательства в таблице ``commitment``."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, commitment: Commitment) -> Commitment:
        cursor = self._connection.execute(
            """
            INSERT INTO commitment (title, kind, amount_kopecks, day_of_month, category)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                commitment.title,
                str(commitment.kind),
                None if commitment.amount is None else commitment.amount.kopecks,
                commitment.day_of_month,
                commitment.category,
            ),
        )
        self._connection.commit()
        row_id = cursor.lastrowid
        assert row_id is not None
        return replace(commitment, id=row_id)

    def list(self) -> tuple[Commitment, ...]:
        rows = self._connection.execute("SELECT * FROM commitment ORDER BY id").fetchall()
        return tuple(_row_to_commitment(row) for row in rows)

    def get(self, commitment_id: int) -> Commitment | None:
        row = self._connection.execute(
            "SELECT * FROM commitment WHERE id = ?", (commitment_id,)
        ).fetchone()
        return None if row is None else _row_to_commitment(row)

    def delete(self, commitment_id: int) -> None:
        # экземпляры платежей убираем вместе с расписанием, траты не трогаем
        self._connection.execute(
            "DELETE FROM commitment_occurrence WHERE commitment_id = ?", (commitment_id,)
        )
        self._connection.execute("DELETE FROM commitment WHERE id = ?", (commitment_id,))
        self._connection.commit()


class SqliteCommitmentOccurrenceRepository:
    """Экземпляры обязательств по месяцам в ``commitment_occurrence``."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def ensure_period(self, period: str) -> None:
        """Лениво и идемпотентно создать экземпляры месяца для всех обязательств."""
        self._connection.execute(
            """
            INSERT OR IGNORE INTO commitment_occurrence (commitment_id, period, status)
            SELECT id, ?, 'pending' FROM commitment
            """,
            (period,),
        )
        self._connection.commit()

    def get(self, commitment_id: int, period: str) -> CommitmentOccurrence | None:
        row = self._connection.execute(
            "SELECT * FROM commitment_occurrence WHERE commitment_id = ? AND period = ?",
            (commitment_id, period),
        ).fetchone()
        return None if row is None else _row_to_occurrence(row)

    def save(self, occurrence: CommitmentOccurrence) -> CommitmentOccurrence:
        self._connection.execute(
            """
            INSERT INTO commitment_occurrence
                (commitment_id, period, status, actual_amount_kopecks,
                 meter_values, meter_transferred_on)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(commitment_id, period) DO UPDATE SET
                status = excluded.status,
                actual_amount_kopecks = excluded.actual_amount_kopecks,
                meter_values = excluded.meter_values,
                meter_transferred_on = excluded.meter_transferred_on
            """,
            (
                occurrence.commitment_id,
                occurrence.period,
                str(occurrence.status),
                None if occurrence.actual_amount is None else occurrence.actual_amount.kopecks,
                occurrence.meter_values,
                None
                if occurrence.meter_transferred_on is None
                else occurrence.meter_transferred_on.isoformat(),
            ),
        )
        self._connection.commit()
        stored = self.get(occurrence.commitment_id, occurrence.period)
        assert stored is not None
        return stored

    def for_period(self, period: str) -> tuple[CommitmentOccurrence, ...]:
        rows = self._connection.execute(
            "SELECT * FROM commitment_occurrence WHERE period = ? ORDER BY commitment_id",
            (period,),
        ).fetchall()
        return tuple(_row_to_occurrence(row) for row in rows)

    def pending_for_period(self, period: str) -> tuple[CommitmentOccurrence, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM commitment_occurrence
            WHERE period = ? AND status = 'pending'
            ORDER BY commitment_id
            """,
            (period,),
        ).fetchall()
        return tuple(_row_to_occurrence(row) for row in rows)

    def last_actual_amount(self, commitment_id: int) -> Money | None:
        row = self._connection.execute(
            """
            SELECT actual_amount_kopecks FROM commitment_occurrence
            WHERE commitment_id = ? AND actual_amount_kopecks IS NOT NULL
            ORDER BY period DESC LIMIT 1
            """,
            (commitment_id,),
        ).fetchone()
        return None if row is None else Money.from_kopecks(int(row["actual_amount_kopecks"]))


class SqliteCommitmentPromptStore:
    """Ожидания ответа по обязательствам в таблице ``pending_input``."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, chat_id: int) -> CommitmentPrompt | None:
        row = self._connection.execute(
            "SELECT payload FROM pending_input WHERE chat_id = ? AND kind = ?",
            (chat_id, _PROMPT_KIND),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload"]))
        return CommitmentPrompt(
            kind=PromptKind(payload["kind"]),
            commitment_id=int(payload["commitment_id"]),
            period=str(payload["period"]),
        )

    def set(self, chat_id: int, prompt: CommitmentPrompt) -> None:
        payload = json.dumps(
            {
                "kind": str(prompt.kind),
                "commitment_id": prompt.commitment_id,
                "period": prompt.period,
            },
            ensure_ascii=False,
        )
        self._connection.execute(
            """
            INSERT INTO pending_input (chat_id, kind, payload, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(chat_id) DO UPDATE SET
                kind = excluded.kind,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (chat_id, _PROMPT_KIND, payload),
        )
        self._connection.commit()

    def clear(self, chat_id: int) -> None:
        self._connection.execute(
            "DELETE FROM pending_input WHERE chat_id = ? AND kind = ?",
            (chat_id, _PROMPT_KIND),
        )
        self._connection.commit()


def _row_to_commitment(row: sqlite3.Row) -> Commitment:
    amount = row["amount_kopecks"]
    return Commitment(
        id=int(row["id"]),
        title=str(row["title"]),
        kind=CommitmentKind(str(row["kind"])),
        amount=None if amount is None else Money.from_kopecks(int(amount)),
        day_of_month=int(row["day_of_month"]),
        category=row["category"],
    )


def _row_to_occurrence(row: sqlite3.Row) -> CommitmentOccurrence:
    actual = row["actual_amount_kopecks"]
    transferred = row["meter_transferred_on"]
    return CommitmentOccurrence(
        id=int(row["id"]),
        commitment_id=int(row["commitment_id"]),
        period=str(row["period"]),
        status=OccurrenceStatus(str(row["status"])),
        actual_amount=None if actual is None else Money.from_kopecks(int(actual)),
        meter_values=row["meter_values"],
        meter_transferred_on=None if transferred is None else date.fromisoformat(str(transferred)),
    )


class SqliteSettingsRepository:
    """Настройки key/value в таблице ``settings``."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else str(row["value"])

    def set(self, key: str, value: str) -> None:
        self._connection.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self._connection.commit()


class SqliteNotificationLog:
    """Дедупликация оповещений в таблице ``notification_log``."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def claim(self, dedup_key: str) -> bool:
        """Занять ключ; ``False``, если такой ключ уже занят (оповещение ушло)."""
        cursor = self._connection.execute(
            "INSERT OR IGNORE INTO notification_log (dedup_key) VALUES (?)",
            (dedup_key,),
        )
        self._connection.commit()
        return cursor.rowcount == 1


class SqliteUnknownChatStore:
    """Чаты вне допуска, ожидающие уведомления владельцу (``unknown_chat``)."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def register(self, chat_id: int) -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO unknown_chat (chat_id) VALUES (?)", (chat_id,)
        )
        self._connection.commit()

    def pending(self) -> tuple[int, ...]:
        rows = self._connection.execute(
            "SELECT chat_id FROM unknown_chat ORDER BY created_at, chat_id"
        ).fetchall()
        return tuple(int(row["chat_id"]) for row in rows)

    def resolve(self, chat_id: int) -> None:
        self._connection.execute("DELETE FROM unknown_chat WHERE chat_id = ?", (chat_id,))
        self._connection.commit()
