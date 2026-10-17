"""Проверка сборки зависимостей бота без обращения к сети Telegram."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from control_expenses.infrastructure.config import Settings
from control_expenses.infrastructure.db.repositories import SqliteSettingsRepository
from control_expenses.interfaces import bot


def _settings(db_path: Path) -> Settings:
    return Settings(
        bot_token="123:test",
        allowed_chat_ids=(7,),
        db_path=str(db_path),
        timezone="Europe/Moscow",
        monthly_budget_kopecks=5_000_000,
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
    )


def test_build_service_and_dispatcher(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "wiring.db")
    service, budget, commitment, report, reminders, database = bot.build_service(settings)
    try:
        dispatcher = bot.build_dispatcher(settings, service, budget, commitment, report, reminders)
        assert dispatcher is not None
        # владелец — первый допущенный чат
        assert settings.owner_chat_id == 7
        # настройки расписания перенесены в БД
        runtime = SqliteSettingsRepository(database.connection())
        assert runtime.get("weekly_report_time") == "11:00"
        assert runtime.get("quiet_start") == "23:00"
    finally:
        database.close()
