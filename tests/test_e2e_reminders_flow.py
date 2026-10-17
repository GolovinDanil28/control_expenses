"""Сквозной путь оповещений на реальной SQLite: дедупликация и тихий час."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from control_expenses.application.budgets.service import BudgetService
from control_expenses.application.commitments.service import CommitmentService
from control_expenses.application.reminders.replies import NotificationReply
from control_expenses.application.reminders.service import ReminderService
from control_expenses.application.replies import TextReply
from control_expenses.application.reports.service import ReportService
from control_expenses.domain.entities import Expense
from control_expenses.domain.money import Money
from control_expenses.infrastructure.config import Settings
from control_expenses.infrastructure.db.database import Database
from control_expenses.infrastructure.db.repositories import (
    SqliteBudgetRepository,
    SqliteBudgetStateRepository,
    SqliteCategoryRepository,
    SqliteCommitmentOccurrenceRepository,
    SqliteCommitmentPromptStore,
    SqliteCommitmentRepository,
    SqliteExpenseRepository,
    SqliteNotificationLog,
    SqliteSettingsRepository,
    SqliteUnknownChatStore,
)
from control_expenses.infrastructure.runtime_settings import seed_runtime_settings

MONDAY = date(2026, 10, 19)
CHAT = 1234


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._now.date()


def _build(
    database: Database, now: datetime, weekly_dow: str = "0"
) -> tuple[ReminderService, CommitmentService, BudgetService]:
    connection = database.connection()
    clock = FixedClock(now)
    categories = SqliteCategoryRepository(connection)
    expenses = SqliteExpenseRepository(connection)
    commitment = CommitmentService(
        clock=clock,
        commitments=SqliteCommitmentRepository(connection),
        occurrences=SqliteCommitmentOccurrenceRepository(connection),
        prompts=SqliteCommitmentPromptStore(connection),
        expenses=expenses,
        categories=categories,
    )
    budget = BudgetService(
        clock=clock,
        expenses=expenses,
        budgets=SqliteBudgetRepository(connection),
        states=SqliteBudgetStateRepository(connection),
        default_limit=None,
        threshold_ratio=Decimal("0.8"),
        obligations=commitment,
    )
    report = ReportService(clock=clock, expenses=expenses, budget=budget, upcoming=commitment)
    settings = SqliteSettingsRepository(connection)
    settings.set("weekly_report_dow", weekly_dow)
    settings.set("weekly_report_time", "11:00")
    settings.set("quiet_start", "23:00")
    settings.set("quiet_end", "08:00")
    reminders = ReminderService(
        clock=clock,
        owner_chat_id=CHAT,
        log=SqliteNotificationLog(connection),
        settings=settings,
        budget_states=SqliteBudgetStateRepository(connection),
        commitments=commitment,
        reports=report,
        unknown_chats=SqliteUnknownChatStore(connection),
    )
    return reminders, commitment, budget


def _add_expense(database: Database, amount: str) -> None:
    SqliteExpenseRepository(database.connection()).add(
        Expense(
            amount=Money.from_rubles(amount),
            spent_on=MONDAY,
            source_chat_id=CHAT,
            category="Еда",
        )
    )


def test_overrun_alert_sent_once_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "reminders.db"
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    database = Database(path)
    database.migrate()
    reminders, _, budget = _build(database, now, weekly_dow="3")
    budget.handle_command("1000")
    _add_expense(database, "1500")
    budget.record_after_expense()

    delivered = reminders.run_due(now)
    alerts = [
        item
        for item in delivered
        if isinstance(item.reply, TextReply) and "превышен" in item.reply.text
    ]
    assert len(alerts) == 1
    assert "превышен на 500 ₽" in alerts[0].reply.text
    assert reminders.run_due(now) == ()
    database.close()

    # «рестарт»: ключ дедупликации в БД, повторной отправки нет
    restarted = Database(path)
    restarted.migrate()
    restarted_reminders, _, _ = _build(restarted, now, weekly_dow="3")
    assert restarted_reminders.run_due(now) == ()
    restarted.close()


def test_quiet_hours_defer_overrun_alert(tmp_path: Path) -> None:
    path = tmp_path / "quiet.db"
    night = datetime(2026, 10, 19, 23, 30, tzinfo=UTC)
    database = Database(path)
    database.migrate()
    reminders, _, budget = _build(database, night, weekly_dow="3")
    budget.handle_command("1000")
    _add_expense(database, "1500")
    budget.record_after_expense()

    # в тихий час оповещение не уходит и ключ не занимается
    assert reminders.run_due(night) == ()

    morning = datetime(2026, 10, 20, 8, 30, tzinfo=UTC)
    deferred = reminders.run_due(morning)
    alerts = [
        item
        for item in deferred
        if isinstance(item.reply, TextReply) and "превышен" in item.reply.text
    ]
    assert len(alerts) == 1
    assert "превышен" in alerts[0].reply.text
    assert reminders.run_due(morning) == ()
    database.close()


def test_bill_reminder_and_weekly_summary(tmp_path: Path) -> None:
    database = Database(tmp_path / "bills.db")
    database.migrate()
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    reminders, commitment, _ = _build(database, now)
    commitment.add_bill("Квартира 15000 5")

    delivered = reminders.run_due(now)
    assert len(delivered) == 2  # напоминание об обязательстве + недельная сводка
    reminder = next(item.reply for item in delivered if isinstance(item.reply, NotificationReply))
    assert "Квартира" in reminder.text
    assert reminders.run_due(now) == ()
    database.close()


def test_seed_runtime_settings_keeps_existing_value(tmp_path: Path) -> None:
    database = Database(tmp_path / "seed.db")
    database.migrate()
    settings = SqliteSettingsRepository(database.connection())
    settings.set("quiet_start", "22:00")

    seed_runtime_settings(
        settings,
        Settings(
            bot_token="t",
            allowed_chat_ids=(CHAT,),
            db_path=str(tmp_path / "seed.db"),
            timezone="Europe/Moscow",
            monthly_budget_kopecks=None,
            budget_threshold_ratio=Decimal("0.8"),
            weekly_report_dow=0,
            weekly_report_time="11:00",
            quiet_start="23:00",
            quiet_end="08:00",
            llm_backend="none",
            llm_base_url="http://localhost:11434",
            llm_model="qwen2.5:3b",
            llm_api_key="",
            llm_timeout_seconds=10.0,
        ),
    )
    # сохранённое значение не затёрто, отсутствующий ключ заполнен
    assert settings.get("quiet_start") == "22:00"
    assert settings.get("quiet_end") == "08:00"
    database.close()
