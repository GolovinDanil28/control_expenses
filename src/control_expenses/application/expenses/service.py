"""Use case'ы фиксации траты: карточка → подтверждение/правка → запись.

Один сценарий спецификации ``expenses`` = одна ветка этого сервиса. Сервис не
знает ни про aiogram, ни про SQLite: работает через порты и возвращает
``Reply``, который интерфейс отрисовывает.
"""

from __future__ import annotations

from control_expenses.application.expenses.draft import DraftStage, ExpenseDraft
from control_expenses.application.expenses.replies import (
    CardReply,
    Reply,
    TextReply,
)
from control_expenses.application.intent import FailedIntent, IntentParser, ParseFailure
from control_expenses.application.ports import (
    CategoryRepository,
    Clock,
    ExpenseRepository,
    PendingInputStore,
)
from control_expenses.domain.categories import (
    clean_category_name,
    is_duplicate_category,
    normalize_category,
)
from control_expenses.domain.entities import Expense

COMMANDS_HINT = "Отчёт: /report, бюджет: /budget."


class ExpenseService:
    """Сценарии ввода, правки и отмены траты."""

    def __init__(
        self,
        *,
        parser: IntentParser,
        clock: Clock,
        expenses: ExpenseRepository,
        categories: CategoryRepository,
        pending: PendingInputStore,
    ) -> None:
        self._parser = parser
        self._clock = clock
        self._expenses = expenses
        self._categories = categories
        self._pending = pending

    def handle_text(self, chat_id: int, text: str) -> Reply:
        """Обработать свободный текст: показать карточку или уточнить ввод."""
        draft = self._pending.get(chat_id)
        if draft is not None and draft.status is DraftStage.AWAITING_AMOUNT:
            return self._apply_amount(chat_id, draft, text)
        # Новое сообщение о трате аннулирует предыдущую неподтверждённую карточку.
        self._pending.clear(chat_id)
        return self._start_new(chat_id, text)

    def confirm(self, chat_id: int) -> Reply:
        """Записать трату из карточки. Повторное подтверждение не дублирует запись."""
        draft = self._pending.get(chat_id)
        if draft is None or draft.amount is None:
            return TextReply("Нет карточки для подтверждения.")
        if draft.editing_expense_id is not None:
            saved = self._expenses.update(
                Expense(
                    id=draft.editing_expense_id,
                    amount=draft.amount,
                    spent_on=draft.spent_on,
                    source_chat_id=chat_id,
                    category=draft.category,
                )
            )
            action = "Исправлено"
        else:
            saved = self._expenses.add(
                Expense(
                    amount=draft.amount,
                    spent_on=draft.spent_on,
                    source_chat_id=chat_id,
                    category=draft.category,
                )
            )
            action = "Записано"
        self._pending.clear(chat_id)
        category = saved.category or "без категории"
        spent_on = f"{saved.spent_on:%d.%m}"
        return TextReply(f"{action}: {saved.amount.format_ru()} · {category} · {spent_on}")

    def cancel(self, chat_id: int) -> Reply:
        """Отменить карточку, ничего не записывая."""
        self._pending.clear(chat_id)
        return TextReply("Отменил — трата не записана.")

    def undo_last(self, chat_id: int) -> Reply:
        """Удалить последнюю записанную трату."""
        last = self._expenses.last(chat_id)
        if last is None or last.id is None:
            return TextReply("Удалять нечего.")
        self._expenses.delete(last.id)
        category = last.category or "без категории"
        return TextReply(f"Удалил: {last.amount.format_ru()} · {category}")

    def edit_last(self, chat_id: int, arguments: str) -> Reply:
        """Карточка правки последней траты; без суммы — сначала её запросить."""
        last = self._expenses.last(chat_id)
        if last is None or last.id is None:
            return TextReply("Нет траты для правки.")
        arguments = arguments.strip()
        if not arguments:
            self._pending.set(
                chat_id,
                ExpenseDraft(
                    chat_id=chat_id,
                    spent_on=last.spent_on,
                    amount=last.amount,
                    category=last.category,
                    status=DraftStage.AWAITING_AMOUNT,
                    editing_expense_id=last.id,
                ),
            )
            return TextReply("Пришлите новую сумму числом, например: 350")
        amount = self._parser.parse_amount(arguments)
        if amount is None or amount.is_zero or amount.is_negative:
            return TextReply("Не понял сумму. Пример: /edit 350")
        draft = ExpenseDraft(
            chat_id=chat_id,
            spent_on=last.spent_on,
            amount=amount,
            category=last.category,
            editing_expense_id=last.id,
        )
        self._pending.set(chat_id, draft)
        return self._card(draft)

    def choose_category(self, chat_id: int, name: str) -> Reply:
        """Сменить категорию в карточке, сохранив остальные поля."""
        draft = self._pending.get(chat_id)
        if draft is None:
            return TextReply("Карточка уже неактуальна — отправьте трату заново.")
        normalized = normalize_category(name, self._categories.list())
        if normalized is None:
            return TextReply(f"Категории «{name}» нет. Добавьте: /addcategory {name}")
        draft.category = normalized
        self._pending.set(chat_id, draft)
        return self._card(draft)

    def request_amount(self, chat_id: int) -> Reply:
        """Перевести карточку в ожидание суммы."""
        draft = self._pending.get(chat_id)
        if draft is None:
            return TextReply("Сначала напишите трату, например: «кофе 250».")
        draft.status = DraftStage.AWAITING_AMOUNT
        self._pending.set(chat_id, draft)
        return TextReply("Пришлите сумму числом, например: 350")

    def add_category(self, name: str) -> Reply:
        """Добавить пользовательскую категорию."""
        cleaned = clean_category_name(name)
        if not cleaned:
            return TextReply("Укажите название: /addcategory Ветеринарка")
        if is_duplicate_category(cleaned, self._categories.list()):
            return TextReply(f"Категория «{cleaned}» уже есть.")
        self._categories.add(cleaned)
        return TextReply(f"Категория «{cleaned}» добавлена.")

    def _start_new(self, chat_id: int, text: str) -> Reply:
        today = self._clock.today()
        result = self._parser.parse(text, today=today)
        if isinstance(result, FailedIntent):
            return TextReply(self._failure_message(result.reason))
        if result.amount.is_zero or result.amount.is_negative:
            return TextReply("Сумма должна быть больше нуля — например: «кофе 250».")
        if result.spent_on > today:
            return TextReply(
                "Дата в будущем — записать не могу. Укажите прошедшую дату или сегодняшнюю."
            )
        draft = ExpenseDraft(
            chat_id=chat_id,
            spent_on=result.spent_on,
            amount=result.amount,
            category=result.category,
            note=result.note,
        )
        self._pending.set(chat_id, draft)
        return self._card(draft)

    def _apply_amount(self, chat_id: int, draft: ExpenseDraft, text: str) -> Reply:
        amount = self._parser.parse_amount(text)
        if amount is None or amount.is_zero or amount.is_negative:
            return TextReply("Не понял сумму. Пришлите число, например: 350")
        draft.amount = amount
        draft.status = DraftStage.CARD
        self._pending.set(chat_id, draft)
        return self._card(draft)

    def _card(self, draft: ExpenseDraft) -> CardReply:
        return CardReply(
            amount=draft.amount,
            spent_on=draft.spent_on,
            category=draft.category,
            categories=self._categories.list(),
            is_edit=draft.editing_expense_id is not None,
            note=draft.note,
        )

    @staticmethod
    def _failure_message(reason: ParseFailure) -> str:
        if reason is ParseFailure.AMBIGUOUS_AMOUNT:
            return (
                f"В сообщении несколько чисел — уточните сумму, например: «250».\n{COMMANDS_HINT}"
            )
        return f"Не вижу сумму. Напишите, например: «кофе 250».\n{COMMANDS_HINT}"
