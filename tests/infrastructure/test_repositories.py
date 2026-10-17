"""Интеграционные тесты SQLite-адаптеров на временной БД."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from control_expenses.application.budgets.state import BudgetState
from control_expenses.application.commitments.prompt import CommitmentPrompt, PromptKind
from control_expenses.application.expenses.draft import DraftStage, ExpenseDraft
from control_expenses.domain.categories import DEFAULT_CATEGORIES
from control_expenses.domain.entities import (
    Commitment,
    CommitmentKind,
    Expense,
    OccurrenceStatus,
)
from control_expenses.domain.money import Money
from control_expenses.infrastructure.db.database import SCHEMA_VERSION, Database
from control_expenses.infrastructure.db.repositories import (
    SqliteBudgetRepository,
    SqliteBudgetStateRepository,
    SqliteCategoryRepository,
    SqliteCommitmentOccurrenceRepository,
    SqliteCommitmentPromptStore,
    SqliteCommitmentRepository,
    SqliteExpenseRepository,
    SqliteNotificationLog,
    SqlitePendingInputStore,
    SqliteSettingsRepository,
    SqliteUnknownChatStore,
)


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    db = Database(tmp_path / "control_expenses.db")
    db.migrate()
    yield db
    db.close()


def test_migrate_seeds_default_categories(database: Database) -> None:
    categories = SqliteCategoryRepository(database.connection())
    names = categories.list()
    assert "Продукты" in names
    assert len(names) == len(DEFAULT_CATEGORIES)


def test_migrate_is_idempotent(database: Database) -> None:
    database.migrate()
    row = database.connection().execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    assert row["v"] == SCHEMA_VERSION


def test_migrate_upgrades_v1_database(tmp_path: Path) -> None:
    path = tmp_path / "v1.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (1);
        CREATE TABLE category (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
        INSERT INTO category (name) VALUES ('Еда');
        """
    )
    connection.commit()
    connection.close()

    database = Database(path)
    database.migrate()
    try:
        row = (
            database.connection().execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        )
        assert row["v"] == SCHEMA_VERSION
        tables = {
            str(record["name"])
            for record in database.connection().execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"expense", "pending_input", "monthly_budget", "budget_state"} <= tables
        # ранее заведённая категория не потерялась
        assert "Еда" in SqliteCategoryRepository(database.connection()).list()
    finally:
        database.close()


def test_expense_add_last_delete(database: Database) -> None:
    expenses = SqliteExpenseRepository(database.connection())
    saved = expenses.add(
        Expense(
            amount=Money.from_kopecks(25000),
            spent_on=date(2026, 10, 16),
            source_chat_id=7,
            category="Еда",
        )
    )
    assert saved.id is not None

    last = expenses.last(7)
    assert last is not None
    assert last.amount.format_ru() == "250 ₽"
    assert last.category == "Еда"
    assert last.spent_on == date(2026, 10, 16)
    assert expenses.last(999) is None

    expenses.delete(saved.id)
    assert expenses.last(7) is None


def test_category_add_is_idempotent(database: Database) -> None:
    categories = SqliteCategoryRepository(database.connection())
    categories.add("Ветеринарка")
    categories.add("Ветеринарка")
    assert categories.list().count("Ветеринарка") == 1


def test_expense_update_changes_amount_in_place(database: Database) -> None:
    expenses = SqliteExpenseRepository(database.connection())
    saved = expenses.add(
        Expense(
            amount=Money.from_kopecks(25000),
            spent_on=date(2026, 10, 16),
            source_chat_id=7,
            category="Еда",
        )
    )
    assert saved.id is not None

    updated = expenses.update(replace(saved, amount=Money.from_kopecks(35000)))
    assert updated.id == saved.id

    last = expenses.last(7)
    assert last is not None
    assert last.amount.format_ru() == "350 ₽"
    assert last.id == saved.id


def test_expense_update_requires_id(database: Database) -> None:
    expenses = SqliteExpenseRepository(database.connection())
    with pytest.raises(ValueError, match="id"):
        expenses.update(
            Expense(
                amount=Money.from_kopecks(100),
                spent_on=date(2026, 10, 16),
                source_chat_id=7,
            )
        )


def test_spent_between_sums_only_period(database: Database) -> None:
    expenses = SqliteExpenseRepository(database.connection())
    expenses.add(
        Expense(amount=Money.from_kopecks(20000), spent_on=date(2026, 10, 5), source_chat_id=1)
    )
    expenses.add(
        Expense(amount=Money.from_kopecks(30000), spent_on=date(2026, 10, 20), source_chat_id=2)
    )
    expenses.add(
        Expense(amount=Money.from_kopecks(99900), spent_on=date(2026, 9, 30), source_chat_id=1)
    )
    assert expenses.spent_between(date(2026, 10, 1), date(2026, 10, 31)).format_ru() == "500 ₽"


def test_totals_by_category_groups_and_orders(database: Database) -> None:
    expenses = SqliteExpenseRepository(database.connection())
    expenses.add(
        Expense(
            amount=Money.from_kopecks(400000),
            spent_on=date(2026, 10, 2),
            source_chat_id=1,
            category="Еда",
        )
    )
    expenses.add(
        Expense(
            amount=Money.from_kopecks(100000),
            spent_on=date(2026, 10, 3),
            source_chat_id=1,
            category="Еда",
        )
    )
    expenses.add(
        Expense(
            amount=Money.from_kopecks(140000),
            spent_on=date(2026, 10, 5),
            source_chat_id=2,
            category="Транспорт",
        )
    )
    expenses.add(
        Expense(
            amount=Money.from_kopecks(999900),
            spent_on=date(2026, 9, 30),
            source_chat_id=1,
            category="Еда",
        )
    )
    totals = expenses.totals_by_category(date(2026, 10, 1), date(2026, 10, 31))
    assert [(name, amount.format_ru()) for name, amount in totals] == [
        ("Еда", "5 000 ₽"),
        ("Транспорт", "1 400 ₽"),
    ]


def test_budget_limit_roundtrip(database: Database) -> None:
    budgets = SqliteBudgetRepository(database.connection())
    assert budgets.limit_for("2026-10") is None

    budgets.set_limit("2026-10", Money.from_rubles("60000"))
    assert budgets.limit_for("2026-10").format_ru() == "60 000 ₽"

    budgets.set_limit("2026-10", Money.from_rubles("65000"))
    assert budgets.limit_for("2026-10").format_ru() == "65 000 ₽"


def test_budget_state_roundtrip(database: Database) -> None:
    states = SqliteBudgetStateRepository(database.connection())
    empty = states.get("2026-10")
    assert empty.threshold_fixed is False
    assert empty.overrun_fixed is False

    states.save(BudgetState(period="2026-10", threshold_fixed=True))
    threshold = states.get("2026-10")
    assert threshold.threshold_fixed is True
    assert threshold.overrun_fixed is False

    states.save(
        BudgetState(
            period="2026-10",
            threshold_fixed=True,
            overrun_fixed=True,
            overrun=Money.from_rubles("500"),
        )
    )
    overrun = states.get("2026-10")
    assert overrun.overrun_fixed is True
    assert overrun.overrun.format_ru() == "500 ₽"


def test_pending_store_keeps_editing_target(database: Database) -> None:
    store = SqlitePendingInputStore(database.connection())
    store.set(
        7,
        ExpenseDraft(
            chat_id=7,
            spent_on=date(2026, 10, 16),
            amount=Money.from_kopecks(35000),
            category="Еда",
            editing_expense_id=5,
        ),
    )
    draft = store.get(7)
    assert draft is not None
    assert draft.editing_expense_id == 5


def test_pending_store_roundtrip_with_amount(database: Database) -> None:
    store = SqlitePendingInputStore(database.connection())
    store.set(
        7,
        ExpenseDraft(
            chat_id=7,
            spent_on=date(2026, 10, 16),
            amount=Money.from_kopecks(35000),
            category="Еда",
            status=DraftStage.AWAITING_AMOUNT,
        ),
    )
    draft = store.get(7)
    assert draft is not None
    assert draft.amount is not None
    assert draft.amount.format_ru() == "350 ₽"
    assert draft.category == "Еда"
    assert draft.status is DraftStage.AWAITING_AMOUNT

    store.clear(7)
    assert store.get(7) is None


def test_pending_store_roundtrip_without_amount(database: Database) -> None:
    store = SqlitePendingInputStore(database.connection())
    store.set(9, ExpenseDraft(chat_id=9, spent_on=date(2026, 10, 1)))
    draft = store.get(9)
    assert draft is not None
    assert draft.amount is None
    assert draft.category is None
    assert draft.status is DraftStage.CARD


def test_commitment_roundtrip(database: Database) -> None:
    commitments = SqliteCommitmentRepository(database.connection())
    saved = commitments.add(
        Commitment(
            title="Квартира",
            day_of_month=5,
            kind=CommitmentKind.FIXED,
            amount=Money.from_rubles("15000"),
            category="Жильё",
        )
    )
    assert saved.id is not None

    loaded = commitments.get(saved.id)
    assert loaded is not None
    assert loaded.title == "Квартира"
    assert loaded.kind is CommitmentKind.FIXED
    assert loaded.amount is not None
    assert loaded.amount.format_ru() == "15 000 ₽"
    assert commitments.list()[0].day_of_month == 5

    commitments.delete(saved.id)
    assert commitments.get(saved.id) is None
    assert commitments.list() == ()


def test_ensure_period_is_idempotent_and_lists_pending(database: Database) -> None:
    commitments = SqliteCommitmentRepository(database.connection())
    occurrences = SqliteCommitmentOccurrenceRepository(database.connection())
    commitments.add(Commitment(title="Связь", day_of_month=20, amount=Money.from_rubles("500")))

    occurrences.ensure_period("2026-10")
    occurrences.ensure_period("2026-10")
    assert len(occurrences.for_period("2026-10")) == 1

    pending = occurrences.pending_for_period("2026-10")
    assert len(pending) == 1
    assert pending[0].status is OccurrenceStatus.PENDING


def test_occurrence_save_upsert_and_last_actual_amount(database: Database) -> None:
    commitments = SqliteCommitmentRepository(database.connection())
    occurrences = SqliteCommitmentOccurrenceRepository(database.connection())
    commitment = commitments.add(
        Commitment(
            title="Коммунальные",
            day_of_month=10,
            kind=CommitmentKind.VARIABLE,
        )
    )
    assert commitment.id is not None
    occurrences.ensure_period("2026-10")

    occurrence = occurrences.get(commitment.id, "2026-10")
    assert occurrence is not None
    saved = occurrences.save(
        replace(
            occurrence,
            status=OccurrenceStatus.PAID,
            actual_amount=Money.from_rubles("3000"),
        )
    )
    assert saved.id == occurrence.id
    assert saved.status is OccurrenceStatus.PAID
    assert occurrences.get(commitment.id, "2026-10").status is OccurrenceStatus.PAID
    assert occurrences.last_actual_amount(commitment.id) is not None
    assert occurrences.last_actual_amount(commitment.id).format_ru() == "3 000 ₽"


def test_delete_commitment_keeps_expenses(database: Database) -> None:
    commitments = SqliteCommitmentRepository(database.connection())
    expenses = SqliteExpenseRepository(database.connection())
    commitment = commitments.add(
        Commitment(title="Квартира", day_of_month=5, amount=Money.from_rubles("15000"))
    )
    assert commitment.id is not None
    expenses.add(
        Expense(
            amount=Money.from_rubles("15000"),
            spent_on=date(2026, 10, 5),
            source_chat_id=7,
            category="Квартира",
            commitment_id=commitment.id,
        )
    )

    commitments.delete(commitment.id)
    assert commitments.list() == ()
    assert expenses.last(7) is not None


def test_commitment_prompt_store_roundtrip(database: Database) -> None:
    store = SqliteCommitmentPromptStore(database.connection())
    assert store.get(7) is None

    store.set(7, CommitmentPrompt(kind=PromptKind.METER, commitment_id=3, period="2026-10"))
    prompt = store.get(7)
    assert prompt is not None
    assert prompt.kind is PromptKind.METER
    assert prompt.commitment_id == 3

    store.clear(7)
    assert store.get(7) is None


def test_settings_roundtrip(database: Database) -> None:
    settings = SqliteSettingsRepository(database.connection())
    assert settings.get("quiet_start") is None

    settings.set("quiet_start", "22:00")
    settings.set("quiet_start", "23:00")
    assert settings.get("quiet_start") == "23:00"


def test_notification_log_claims_key_once(database: Database) -> None:
    log = SqliteNotificationLog(database.connection())
    assert log.claim("weekly:7:2026-10-19") is True
    assert log.claim("weekly:7:2026-10-19") is False
    assert log.claim("weekly:7:2026-10-26") is True


def test_unknown_chat_store_roundtrip(database: Database) -> None:
    store = SqliteUnknownChatStore(database.connection())
    assert store.pending() == ()

    store.register(111)
    store.register(222)
    store.register(111)
    assert store.pending() == (111, 222)

    store.resolve(111)
    assert store.pending() == (222,)
