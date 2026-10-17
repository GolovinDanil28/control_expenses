"""Чтение настроек из окружения и ``.env``.

Секреты приходят только из переменных окружения и никогда не попадают в БД и
журнал. Пустой список допуска — отказ запускаться: бот без допущенных чатов
бессмысленен и опасен.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEFAULT_ENV_PATH = Path(".env")
DEFAULT_DB_PATH = "data/control_expenses.db"
DEFAULT_TIMEZONE = "Europe/Moscow"
DEFAULT_THRESHOLD_RATIO = Decimal("0.8")
DEFAULT_LLM_TIMEOUT_SECONDS = 10.0


class ConfigError(RuntimeError):
    """Настройки отсутствуют или некорректны — запускаться нельзя."""


@dataclass(frozen=True)
class Settings:
    """Настройки процесса, собранные из окружения."""

    bot_token: str
    allowed_chat_ids: tuple[int, ...]
    db_path: str
    timezone: str
    monthly_budget_kopecks: int | None
    budget_threshold_ratio: Decimal
    weekly_report_dow: int
    weekly_report_time: str
    quiet_start: str
    quiet_end: str
    llm_backend: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout_seconds: float

    @property
    def owner_chat_id(self) -> int:
        """Первый допущенный чат — владелец, ему уходят инициативные оповещения."""
        return self.allowed_chat_ids[0]


def load_settings(env_path: Path | None = None) -> Settings:
    """Прочитать ``.env`` (если есть) и собрать настройки из окружения."""
    _load_dotenv(DEFAULT_ENV_PATH if env_path is None else env_path)
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("BOT_TOKEN не задан: заполните .env по образцу .env.example")
    allowed = _parse_chat_ids(os.environ.get("ALLOWED_CHAT_IDS", ""))
    if not allowed:
        raise ConfigError("ALLOWED_CHAT_IDS пуст: запуск без допущенных чатов запрещён")
    return Settings(
        bot_token=token,
        allowed_chat_ids=allowed,
        db_path=os.environ.get("DB_PATH", DEFAULT_DB_PATH),
        timezone=os.environ.get("TZ", DEFAULT_TIMEZONE),
        monthly_budget_kopecks=_parse_optional_int("MONTHLY_BUDGET_KOPECKS"),
        budget_threshold_ratio=_parse_ratio("BUDGET_THRESHOLD_RATIO"),
        weekly_report_dow=_parse_int("WEEKLY_REPORT_DOW", 0),
        weekly_report_time=os.environ.get("WEEKLY_REPORT_TIME", "11:00"),
        quiet_start=os.environ.get("QUIET_START", "23:00"),
        quiet_end=os.environ.get("QUIET_END", "08:00"),
        llm_backend=os.environ.get("LLM_BACKEND", "none").strip().lower(),
        llm_base_url=os.environ.get("LLM_BASE_URL", "http://localhost:11434"),
        llm_model=os.environ.get("LLM_MODEL", "qwen2.5:3b"),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_timeout_seconds=_parse_float("LLM_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS),
    )


def _parse_chat_ids(raw: str) -> tuple[int, ...]:
    ids: list[int] = []
    for chunk in raw.split(","):
        candidate = chunk.strip()
        if not candidate:
            continue
        try:
            ids.append(int(candidate))
        except ValueError as error:
            raise ConfigError(f"ALLOWED_CHAT_IDS: «{candidate}» не число") from error
    return tuple(ids)


def _parse_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ConfigError(f"{name}: «{raw}» не число") from error


def _parse_optional_int(name: str) -> int | None:
    """Целое из окружения; пусто/отсутствует — ``None`` (значение не задано)."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError as error:
        raise ConfigError(f"{name}: «{raw}» не число") from error


def _parse_ratio(name: str) -> Decimal:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return DEFAULT_THRESHOLD_RATIO
    try:
        ratio = Decimal(raw)
    except InvalidOperation as error:
        raise ConfigError(f"{name}: «{raw}» не число") from error
    if not Decimal(0) < ratio <= Decimal(1):
        raise ConfigError(f"{name}: доля должна быть в диапазоне (0, 1]")
    return ratio


def _parse_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ConfigError(f"{name}: «{raw}» не число") from error
    if value <= 0:
        raise ConfigError(f"{name}: значение должно быть положительным")
    return value


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
