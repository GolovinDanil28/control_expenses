"""Подключение к SQLite и применение версионируемой схемы.

Одно ленивое соединение на процесс; миграции применяются один раз при старте.
Версия схемы хранится в таблице ``schema_version``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from control_expenses.domain.categories import DEFAULT_CATEGORIES

SCHEMA_VERSION = 5
MEMORY_PATH = ":memory:"


class Database:
    """Владеет соединением с SQLite и знает, как привести схему к актуальной."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._connection: sqlite3.Connection | None = None

    @property
    def path(self) -> str:
        return self._path

    def connection(self) -> sqlite3.Connection:
        """Вернуть соединение, открыв его при первом обращении."""
        if self._connection is None:
            if self._path != MEMORY_PATH:
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._path, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            self._connection = connection
        return self._connection

    def migrate(self) -> None:
        """Создать схему и наполнить справочник, если версия устарела."""
        connection = self.connection()
        if self._current_version(connection) >= SCHEMA_VERSION:
            return
        connection.executescript(_schema_sql())
        connection.executemany(
            "INSERT OR IGNORE INTO category (name) VALUES (?)",
            [(name,) for name in DEFAULT_CATEGORIES],
        )
        connection.execute("DELETE FROM schema_version")
        connection.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        connection.commit()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @staticmethod
    def _current_version(connection: sqlite3.Connection) -> int:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
        ).fetchone()
        if table is None:
            return 0
        row = connection.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
        value = row["version"]
        return int(value) if value is not None else 0


def _schema_sql() -> str:
    return Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
