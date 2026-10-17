"""Тесты чтения настроек из окружения."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from control_expenses.infrastructure.config import ConfigError, Settings, load_settings

_ENV_KEYS = [
    "BOT_TOKEN",
    "ALLOWED_CHAT_IDS",
    "DB_PATH",
    "TZ",
    "MONTHLY_BUDGET_KOPECKS",
    "BUDGET_THRESHOLD_RATIO",
    "WEEKLY_REPORT_DOW",
    "WEEKLY_REPORT_TIME",
    "QUIET_START",
    "QUIET_END",
    "LLM_BACKEND",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_API_KEY",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _load(tmp_path: Path) -> Settings:
    # .env рядом с тестом отсутствует — читаем только окружение
    return load_settings(env_path=tmp_path / "absent.env")


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "7")


def test_requires_token(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="BOT_TOKEN"):
        _load(tmp_path)


def test_requires_allowed_chats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test")
    with pytest.raises(ConfigError, match="ALLOWED_CHAT_IDS"):
        _load(tmp_path)


def test_parses_allowed_chat_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "7, 8")
    settings = _load(tmp_path)
    assert settings.allowed_chat_ids == (7, 8)
    assert settings.owner_chat_id == 7


def test_invalid_chat_id_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "abc")
    with pytest.raises(ConfigError, match="ALLOWED_CHAT_IDS"):
        _load(tmp_path)


def test_monthly_budget_is_optional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    assert _load(tmp_path).monthly_budget_kopecks is None

    monkeypatch.setenv("MONTHLY_BUDGET_KOPECKS", "5000000")
    assert _load(tmp_path).monthly_budget_kopecks == 5_000_000


def test_threshold_ratio_default_and_custom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_required(monkeypatch)
    assert _load(tmp_path).budget_threshold_ratio == Decimal("0.8")

    monkeypatch.setenv("BUDGET_THRESHOLD_RATIO", "0.5")
    assert _load(tmp_path).budget_threshold_ratio == Decimal("0.5")


def test_threshold_ratio_out_of_range(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("BUDGET_THRESHOLD_RATIO", "2")
    with pytest.raises(ConfigError, match="BUDGET_THRESHOLD_RATIO"):
        _load(tmp_path)
