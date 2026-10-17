"""Точка входа Telegram-бота: сборка зависимостей и запуск long polling.

Реализация — по спецификации ``openspec/changes/add-expense-tracker-mvp/``.
Модуль — тонкая обвязка: собирает адаптеры из ``infrastructure`` и связывает их
с хендлерами и планировщиком оповещений.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from aiogram import Bot, Dispatcher

from control_expenses.application.budgets.service import BudgetService
from control_expenses.application.commitments.service import CommitmentService
from control_expenses.application.expenses.service import ExpenseService
from control_expenses.application.intent import IntentParser
from control_expenses.application.reminders.service import ReminderService
from control_expenses.application.reports.service import ReportService
from control_expenses.domain.money import Money
from control_expenses.infrastructure.clock import SystemClock
from control_expenses.infrastructure.config import ConfigError, Settings, load_settings
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
    SqlitePendingInputStore,
    SqliteSettingsRepository,
    SqliteUnknownChatStore,
)
from control_expenses.infrastructure.parsing.deterministic import DeterministicParser
from control_expenses.infrastructure.parsing.fallback import FallbackParser
from control_expenses.infrastructure.parsing.llm import LlmConfig, OllamaParser, OpenAiParser
from control_expenses.infrastructure.runtime_settings import seed_runtime_settings
from control_expenses.infrastructure.scheduler import Scheduler
from control_expenses.interfaces.handlers import build_router
from control_expenses.interfaces.sender import AiogramSender

logger = logging.getLogger(__name__)


def _build_parser(settings: Settings, categories: SqliteCategoryRepository) -> IntentParser:
    """Детерминированный разбор, поверх него — ИИ-бэкенд, если он настроен."""
    deterministic = DeterministicParser(categories.list)
    if settings.llm_backend not in {"ollama", "openai"}:
        return deterministic
    config = LlmConfig(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout_seconds,
    )
    client = httpx.Client(timeout=settings.llm_timeout_seconds)
    llm: IntentParser = (
        OllamaParser(client=client, config=config, categories=categories.list)
        if settings.llm_backend == "ollama"
        else OpenAiParser(client=client, config=config, categories=categories.list)
    )
    logger.info("Разбор текста: %s (%s)", settings.llm_backend, settings.llm_model)
    return FallbackParser(primary=deterministic, secondary=llm)


def build_service(
    settings: Settings,
) -> tuple[
    ExpenseService,
    BudgetService,
    CommitmentService,
    ReportService,
    ReminderService,
    Database,
]:
    """Собрать сервисы со SQLite-адаптерами и парсером без ИИ."""
    database = Database(settings.db_path)
    database.migrate()
    connection = database.connection()
    clock = SystemClock(settings.timezone)
    categories = SqliteCategoryRepository(connection)
    expenses = SqliteExpenseRepository(connection)
    runtime_settings = SqliteSettingsRepository(connection)
    seed_runtime_settings(runtime_settings, settings)
    default_limit = (
        None
        if settings.monthly_budget_kopecks is None
        else Money.from_kopecks(settings.monthly_budget_kopecks)
    )
    expense_service = ExpenseService(
        parser=_build_parser(settings, categories),
        clock=clock,
        expenses=expenses,
        categories=categories,
        pending=SqlitePendingInputStore(connection),
    )
    commitment_service = CommitmentService(
        clock=clock,
        commitments=SqliteCommitmentRepository(connection),
        occurrences=SqliteCommitmentOccurrenceRepository(connection),
        prompts=SqliteCommitmentPromptStore(connection),
        expenses=expenses,
        categories=categories,
    )
    budget_service = BudgetService(
        clock=clock,
        expenses=expenses,
        budgets=SqliteBudgetRepository(connection),
        states=SqliteBudgetStateRepository(connection),
        default_limit=default_limit,
        threshold_ratio=settings.budget_threshold_ratio,
        obligations=commitment_service,
    )
    report_service = ReportService(
        clock=clock,
        expenses=expenses,
        budget=budget_service,
        upcoming=commitment_service,
    )
    reminder_service = ReminderService(
        clock=clock,
        owner_chat_id=settings.owner_chat_id,
        log=SqliteNotificationLog(connection),
        settings=runtime_settings,
        budget_states=SqliteBudgetStateRepository(connection),
        commitments=commitment_service,
        reports=report_service,
        unknown_chats=SqliteUnknownChatStore(connection),
    )
    return (
        expense_service,
        budget_service,
        commitment_service,
        report_service,
        reminder_service,
        database,
    )


def build_dispatcher(
    settings: Settings,
    service: ExpenseService,
    budget: BudgetService,
    commitment: CommitmentService,
    report: ReportService,
    reminders: ReminderService,
) -> Dispatcher:
    dispatcher = Dispatcher()
    router = build_router(
        service,
        budget,
        commitment,
        report,
        reminders,
        frozenset(settings.allowed_chat_ids),
    )
    dispatcher.include_router(router)
    return dispatcher


async def run() -> None:
    settings = load_settings()
    service, budget, commitment, report, reminders, database = build_service(settings)
    bot = Bot(settings.bot_token)
    dispatcher = build_dispatcher(settings, service, budget, commitment, report, reminders)
    scheduler = Scheduler(
        reminders=reminders,
        sender=AiogramSender(bot),
        clock=SystemClock(settings.timezone),
    )
    logger.info("Запуск бота; владелец — чат %s", settings.owner_chat_id)
    polling = asyncio.create_task(dispatcher.start_polling(bot))
    ticking = asyncio.create_task(scheduler.run())
    try:
        await asyncio.gather(polling, ticking)
    finally:
        polling.cancel()
        ticking.cancel()
        await bot.session.close()
        database.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run())
    except ConfigError as error:
        logger.error("Запуск отменён: %s", error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
