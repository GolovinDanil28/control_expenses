# control-expenses

Приватный Telegram-бот учёта личных расходов.

Трату вводят текстом («купил кофе 250») — бот показывает карточку подтверждения,
где сумму и категорию можно поправить или отменить, и только после подтверждения
записывает. Один общий месячный лимит; дневная норма считается как
`(лимит − обязательства − потрачено) ÷ дни до конца месяца` с округлением вниз.
Раз в неделю приходит сводка, отдельно — алерт о превышении лимита и напоминание
в день обязательного платежа.

**ИИ не считает деньги.** Модель только разбирает текст в структуру; все суммы,
остатки и нормы считает Python на `Decimal`, в базе суммы хранятся в копейках.

## Стек

- Python 3.12+ (venv в репозитории: `venv/`)
- [aiogram 3](https://docs.aiogram.dev/) — Telegram-бот, long polling
- SQLite из stdlib (`sqlite3`) + версионируемый `schema.sql`
- `httpx` — клиент к Ollama / OpenAI-совместимому API (опционально)
- `pytest`, `ruff`, `mypy --strict`

## Быстрый старт

```bash
python3 -m venv venv
venv/bin/pip install -e ".[dev]"
cp .env.example .env      # заполнить BOT_TOKEN и ALLOWED_CHAT_IDS
venv/bin/python -m control_expenses.interfaces.bot
```

Либо через entry point после `pip install -e .`:

```bash
venv/bin/control-expenses
```

## Переменные окружения

Все настройки читаются из `.env` (шаблон — `.env.example`, сам `.env` в git не попадает).

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| `BOT_TOKEN` | Токен бота от @BotFather | — (обязательно) |
| `ALLOWED_CHAT_IDS` | Допущенные chat_id через запятую | — (обязательно) |
| `DB_PATH` | Путь к файлу SQLite | `data/control_expenses.db` |
| `TZ` | Таймзона (IANA) | `Europe/Moscow` |
| `MONTHLY_BUDGET_KOPECKS` | Лимит месяца по умолчанию, в копейках | `5000000` |
| `WEEKLY_REPORT_DOW` | День недельной сводки, 0=пн | `0` |
| `WEEKLY_REPORT_TIME` | Время недельной сводки, `HH:MM` | `11:00` |
| `QUIET_START` / `QUIET_END` | Тихий час: оповещения переносятся, а не отбрасываются | `23:00` / `08:00` |
| `LLM_BACKEND` | `none` \| `ollama` \| `openai` | `none` |
| `LLM_BASE_URL` | Адрес модели | `http://localhost:11434` |
| `LLM_MODEL` | Имя модели | `qwen2.5:3b` |
| `LLM_API_KEY` | Ключ для OpenAI-совместимого API | пусто |

При `LLM_BACKEND=none` работает детерминированный парсер: сумма и категория из
текста вида «кофе 250», «250р», «1 250».

## Проверка

```bash
venv/bin/ruff check . && venv/bin/ruff format --check .
venv/bin/mypy src
venv/bin/pytest
```

## Архитектура и спецификация

Источник истины по поведению и решениям —
[`openspec/changes/add-expense-tracker-mvp/`](openspec/changes/add-expense-tracker-mvp/):
`proposal.md` (зачем и что), `design.md` (слои, схема БД, формулы, риски) и
`specs/` (7 возможностей с приемочными сценариями).

Кратко о слоях (`src/control_expenses/`):

| Слой | Содержимое |
| --- | --- |
| `domain/` | Сущности, `Money`, правила бюджета. Без I/O и фреймворков |
| `application/` | Use cases и порты (`Protocol`) |
| `infrastructure/` | SQLite-репозитории, LLM-клиенты, планировщик |
| `interfaces/` | aiogram-бот: хендлеры, карточки, кнопки |

## Статус

Реализация начинается с домена. Текущий объём работ и принятые решения —
в `openspec/changes/add-expense-tracker-mvp/design.md`.