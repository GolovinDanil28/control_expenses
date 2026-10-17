-- Схема БД control_expenses. Версия хранится в таблице schema_version.
-- Срез MVP: траты, категории, ожидающий ввод. Остальные таблицы добавятся
-- отдельными миграциями (см. openspec/changes/add-expense-tracker-mvp/tasks.md).

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS category (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS expense (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    amount_kopecks INTEGER NOT NULL,
    spent_on       TEXT    NOT NULL,
    category       TEXT,
    source_chat_id INTEGER NOT NULL,
    commitment_id  INTEGER,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_expense_chat ON expense (source_chat_id, id);

CREATE TABLE IF NOT EXISTS pending_input (
    chat_id    INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    payload    TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS monthly_budget (
    period        TEXT    PRIMARY KEY,
    limit_kopecks INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS budget_state (
    period          TEXT    PRIMARY KEY,
    threshold_fixed INTEGER NOT NULL DEFAULT 0,
    overrun_kopecks INTEGER
);

CREATE TABLE IF NOT EXISTS commitment (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT    NOT NULL,
    kind           TEXT    NOT NULL,
    amount_kopecks INTEGER,
    day_of_month   INTEGER NOT NULL,
    category       TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS commitment_occurrence (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    commitment_id         INTEGER NOT NULL,
    period                TEXT    NOT NULL,
    status                TEXT    NOT NULL DEFAULT 'pending',
    actual_amount_kopecks INTEGER,
    meter_values          TEXT,
    meter_transferred_on  TEXT,
    UNIQUE (commitment_id, period)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Дедупликация оповещений: уникальный ключ не даёт отправить одно и то же дважды
-- даже при перезапуске или одновременной работе двух экземпляров.
CREATE TABLE IF NOT EXISTS notification_log (
    dedup_key  TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Чаты вне списка допуска, о которых владельцу ещё не сообщили.
CREATE TABLE IF NOT EXISTS unknown_chat (
    chat_id    INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
