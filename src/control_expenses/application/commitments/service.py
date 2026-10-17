"""Сценарии обязательств: список, оплата, пропуск, счётчики.

Один сценарий спецификации ``commitments`` = одна ветка сервиса. Сервис также
реализует порт ``ObligationQuery``: неоплаченные обязательства месяца уменьшают
остаток бюджета (capability ``budgets``).
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date

from control_expenses.application.commitments.obligations import build_obligations
from control_expenses.application.commitments.prompt import (
    CommitmentPrompt,
    PromptKind,
)
from control_expenses.application.commitments.replies import (
    BillItem,
    BillListReply,
    UpcomingBill,
)
from control_expenses.application.money_text import (
    looks_like_plain_amount,
    parse_amount_text,
)
from control_expenses.application.ports import (
    CategoryRepository,
    Clock,
    CommitmentOccurrenceRepository,
    CommitmentPromptStore,
    CommitmentRepository,
    ExpenseRepository,
)
from control_expenses.application.replies import TextReply
from control_expenses.application.views import Reply
from control_expenses.domain.budget import period_of
from control_expenses.domain.categories import clean_category_name, normalize_category
from control_expenses.domain.commitments import next_occurrence, occurrence_date
from control_expenses.domain.entities import (
    Commitment,
    CommitmentKind,
    CommitmentOccurrence,
    Expense,
    OccurrenceStatus,
)
from control_expenses.domain.errors import DomainError
from control_expenses.domain.money import Money

_VARIABLE_TOKENS = {"var", "variable", "переменное", "плавающее"}
_METER_TOKENS = {"meter", "показания", "счётчик", "счетчик"}
_STATUS_LABELS = {
    OccurrenceStatus.PENDING: "ожидает",
    OccurrenceStatus.PAID: "оплачено",
    OccurrenceStatus.SKIPPED: "пропущено",
}
_READINGS_SPLIT_RE = re.compile(r"[\s,;]+")
_INTEGER_RE = re.compile(r"\d+")
ADD_BILL_USAGE = "Формат: /addbill Название 15000 5 (или var/meter вместо суммы)."
NUMBER_USAGE = "Укажите номер из /bills, например: {command} 1"


class CommitmentService:
    """Сценарии обязательств и поставщик обязательств для бюджета."""

    def __init__(
        self,
        *,
        clock: Clock,
        commitments: CommitmentRepository,
        occurrences: CommitmentOccurrenceRepository,
        prompts: CommitmentPromptStore,
        expenses: ExpenseRepository,
        categories: CategoryRepository,
    ) -> None:
        self._clock = clock
        self._commitments = commitments
        self._occurrences = occurrences
        self._prompts = prompts
        self._expenses = expenses
        self._categories = categories

    # --- порт ObligationQuery -------------------------------------------------

    def month_obligations(self, period: str) -> tuple[Money, bool]:
        """Сумма неоплаченных обязательств месяца и признак «оценка грубая»."""
        self._occurrences.ensure_period(period)
        commitments = {
            commitment.id: commitment
            for commitment in self._commitments.list()
            if commitment.id is not None
        }
        pending = self._occurrences.pending_for_period(period)
        last_amounts: dict[int, Money] = {}
        for commitment_id in {occurrence.commitment_id for occurrence in pending}:
            amount = self._occurrences.last_actual_amount(commitment_id)
            if amount is not None:
                last_amounts[commitment_id] = amount
        return build_obligations(pending, commitments, last_amounts)

    def upcoming(self, today: date, limit: int = 3) -> tuple[UpcomingBill, ...]:
        """Ближайшие наступления обязательств — для сводок и напоминаний."""
        period = period_of(today)
        self._occurrences.ensure_period(period)
        bills: list[UpcomingBill] = []
        for commitment in self._commitments.list():
            if commitment.id is None:
                continue
            occurrence = self._occurrences.get(commitment.id, period)
            pending = occurrence is not None and occurrence.status is OccurrenceStatus.PENDING
            due = (
                occurrence_date(commitment.day_of_month, period)
                if pending
                else next_occurrence(commitment.day_of_month, today)
            )
            bills.append(UpcomingBill(title=commitment.title, due=due, amount=commitment.amount))
        bills.sort(key=lambda bill: bill.due)
        return tuple(bills[:limit])

    def due_bills(self, today: date) -> tuple[BillItem, ...]:
        """Обязательства месяца, срок которых наступил и платёж не проведён."""
        period = period_of(today)
        self._occurrences.ensure_period(period)
        occurrences = {
            occurrence.commitment_id: occurrence
            for occurrence in self._occurrences.for_period(period)
        }
        items: list[BillItem] = []
        for number, commitment in enumerate(self._ordered_commitments(), start=1):
            if commitment.id is None:
                continue
            occurrence = occurrences.get(commitment.id)
            if occurrence is None or occurrence.status is not OccurrenceStatus.PENDING:
                continue
            if occurrence_date(commitment.day_of_month, period) > today:
                continue
            items.append(_bill_item(number, commitment, occurrence))
        return tuple(items)

    # --- команды --------------------------------------------------------------

    def add_bill(self, arguments: str) -> TextReply:
        """`/addbill Название <сумма|var|meter> <день>`."""
        parts = arguments.split()
        if len(parts) < 3:
            return TextReply(ADD_BILL_USAGE)
        title = " ".join(parts[:-2])
        kind, amount, error = _parse_kind(parts[-2])
        if error is not None:
            return TextReply(error)
        if kind is None:
            return TextReply(ADD_BILL_USAGE)
        day_token = parts[-1]
        if not day_token.isdigit():
            return TextReply("День месяца должен быть числом от 1 до 31.")
        day = int(day_token)
        if not 1 <= day <= 31:
            return TextReply("День месяца должен быть в диапазоне 1–31.")
        try:
            commitment = Commitment(
                title=title,
                day_of_month=day,
                kind=kind,
                amount=amount,
                category=self._resolve_category(title),
            )
        except DomainError as error:
            return TextReply(str(error))
        saved = self._commitments.add(commitment)
        nearest = next_occurrence(saved.day_of_month, self._clock.today())
        return TextReply(
            f"Обязательство «{saved.title}» добавлено. Ближайшее наступление: {nearest:%d.%m.%Y}."
        )

    def list_bills(self) -> Reply:
        """`/bills` — список обязательств и статусов текущего месяца."""
        commitments = self._ordered_commitments()
        if not commitments:
            return TextReply("Обязательств нет. Добавьте: /addbill Квартира 15000 5")
        period = period_of(self._clock.today())
        self._occurrences.ensure_period(period)
        occurrences = {
            occurrence.commitment_id: occurrence
            for occurrence in self._occurrences.for_period(period)
        }
        items: list[BillItem] = []
        for number, commitment in enumerate(commitments, start=1):
            assert commitment.id is not None
            items.append(_bill_item(number, commitment, occurrences.get(commitment.id)))
        return BillListReply(items=tuple(items))

    def delete_bill(self, arguments: str) -> TextReply:
        """`/delbill <номер>` — удалить обязательство, сохранив прежние траты."""
        number = _parse_index(arguments)
        commitments = self._ordered_commitments()
        if number is None or not 1 <= number <= len(commitments):
            return TextReply(NUMBER_USAGE.format(command="/delbill"))
        commitment = commitments[number - 1]
        assert commitment.id is not None
        self._commitments.delete(commitment.id)
        return TextReply(
            f"Обязательство «{commitment.title}» удалено из расписания. Прежние траты сохранены."
        )

    def pay_by_number(self, chat_id: int, arguments: str) -> Reply:
        number = _parse_index(arguments)
        commitments = self._ordered_commitments()
        if number is None or not 1 <= number <= len(commitments):
            return TextReply(NUMBER_USAGE.format(command="/pay"))
        commitment = commitments[number - 1]
        assert commitment.id is not None
        return self.pay(chat_id, commitment.id)

    def skip_by_number(self, arguments: str) -> Reply:
        number = _parse_index(arguments)
        commitments = self._ordered_commitments()
        if number is None or not 1 <= number <= len(commitments):
            return TextReply(NUMBER_USAGE.format(command="/skip"))
        commitment = commitments[number - 1]
        assert commitment.id is not None
        return self.skip(commitment.id)

    def pay(self, chat_id: int, commitment_id: int) -> Reply:
        """Оплатить обязательство: фиксированное — сразу, плавающее — по сумме."""
        commitment = self._commitments.get(commitment_id)
        if commitment is None:
            return TextReply("Обязательство не найдено — посмотрите /bills.")
        period = period_of(self._clock.today())
        occurrence = self._ensure_occurrence(commitment, period)
        if occurrence.status is OccurrenceStatus.PAID:
            return TextReply("Этот платёж уже проведён.")
        if occurrence.status is OccurrenceStatus.SKIPPED:
            return TextReply("Обязательство отмечено пропущенным за этот месяц.")
        if commitment.kind is CommitmentKind.METER:
            return self.request_meter(chat_id, commitment_id)
        if commitment.kind is CommitmentKind.FIXED:
            assert commitment.amount is not None
            return self._complete_payment(chat_id, commitment, period, commitment.amount)
        return self._request_amount(chat_id, commitment, period)

    def skip(self, commitment_id: int) -> Reply:
        """Отметить обязательство пропущенным: трата не создаётся."""
        commitment = self._commitments.get(commitment_id)
        if commitment is None:
            return TextReply("Обязательство не найдено — посмотрите /bills.")
        period = period_of(self._clock.today())
        occurrence = self._ensure_occurrence(commitment, period)
        if occurrence.status is OccurrenceStatus.PAID:
            return TextReply("Платёж уже проведён — пропустить нельзя.")
        self._occurrences.save(replace(occurrence, status=OccurrenceStatus.SKIPPED))
        return TextReply(f"«{commitment.title}» пропущено за этот месяц.")

    def request_meter(self, chat_id: int, commitment_id: int) -> Reply:
        """Запросить показания счётчика."""
        commitment = self._commitments.get(commitment_id)
        if commitment is None:
            return TextReply("Обязательство не найдено — посмотрите /bills.")
        self._prompts.set(
            chat_id,
            CommitmentPrompt(
                kind=PromptKind.METER,
                commitment_id=commitment_id,
                period=period_of(self._clock.today()),
            ),
        )
        return TextReply("Пришлите показания счётчиков — одним или несколькими числами.")

    # --- ввод по запросу ------------------------------------------------------

    def has_prompt(self, chat_id: int) -> bool:
        return self._prompts.get(chat_id) is not None

    def handle_prompt_text(self, chat_id: int, text: str) -> Reply:
        """Ответ на активный запрос: сумма платежа или показания счётчика."""
        prompt = self._prompts.get(chat_id)
        if prompt is None:
            return TextReply("Не жду ввода — напишите трату текстом.")
        if prompt.kind is PromptKind.METER:
            return self._apply_meter(chat_id, prompt, text)
        return self._apply_amount(chat_id, prompt, text)

    def _apply_amount(self, chat_id: int, prompt: CommitmentPrompt, text: str) -> Reply:
        if not looks_like_plain_amount(text):
            self._prompts.clear(chat_id)
            return TextReply(
                "Похоже на новую трату, а я ждал сумму платежа. Оплату не проводил — "
                "отправьте трату ещё раз, если хотели именно её."
            )
        amount = parse_amount_text(text)
        if amount is None or amount.is_zero or amount.is_negative:
            return TextReply("Не понял сумму. Пришлите число, например: 3500")
        commitment = self._commitments.get(prompt.commitment_id)
        self._prompts.clear(chat_id)
        if commitment is None:
            return TextReply("Обязательство больше не существует.")
        return self._complete_payment(chat_id, commitment, prompt.period, amount)

    def _apply_meter(self, chat_id: int, prompt: CommitmentPrompt, text: str) -> Reply:
        readings = _parse_readings(text)
        if not readings:
            return TextReply("Не вижу показаний. Пришлите числа, например: 1234 5678")
        commitment = self._commitments.get(prompt.commitment_id)
        self._prompts.clear(chat_id)
        if commitment is None:
            return TextReply("Обязательство больше не существует.")
        period = prompt.period
        occurrence = self._ensure_occurrence(commitment, period)
        self._occurrences.save(
            replace(
                occurrence,
                meter_values=" ".join(readings),
                meter_transferred_on=self._clock.today(),
            )
        )
        return TextReply(f"Показания для «{commitment.title}» приняты: {' '.join(readings)}.")

    # --- внутреннее -----------------------------------------------------------

    def _request_amount(self, chat_id: int, commitment: Commitment, period: str) -> TextReply:
        assert commitment.id is not None
        self._prompts.set(
            chat_id,
            CommitmentPrompt(kind=PromptKind.AMOUNT, commitment_id=commitment.id, period=period),
        )
        last = self._occurrences.last_actual_amount(commitment.id)
        hint = f" Последняя сумма: {last.format_ru()}." if last is not None else ""
        return TextReply(f"Сколько списать за «{commitment.title}»?{hint}\nПришлите сумму числом.")

    def _complete_payment(
        self, chat_id: int, commitment: Commitment, period: str, amount: Money
    ) -> TextReply:
        assert commitment.id is not None
        occurrence = self._ensure_occurrence(commitment, period)
        if occurrence.status is OccurrenceStatus.PAID:
            return TextReply("Этот платёж уже проведён.")
        if occurrence.status is OccurrenceStatus.SKIPPED:
            return TextReply("Обязательство отмечено пропущенным за этот месяц.")
        self._expenses.add(
            Expense(
                amount=amount,
                spent_on=self._clock.today(),
                source_chat_id=chat_id,
                category=commitment.category,
                commitment_id=commitment.id,
            )
        )
        self._occurrences.save(
            replace(occurrence, status=OccurrenceStatus.PAID, actual_amount=amount)
        )
        return TextReply(f"«{commitment.title}» оплачено на {amount.format_ru()}.")

    def _ensure_occurrence(self, commitment: Commitment, period: str) -> CommitmentOccurrence:
        assert commitment.id is not None
        self._occurrences.ensure_period(period)
        occurrence = self._occurrences.get(commitment.id, period)
        assert occurrence is not None  # ensure_period только что создал запись
        return occurrence

    def _ordered_commitments(self) -> list[Commitment]:
        commitments = [
            commitment for commitment in self._commitments.list() if commitment.id is not None
        ]
        return sorted(commitments, key=lambda item: (item.day_of_month, item.id or 0))

    def _resolve_category(self, title: str) -> str:
        known = self._categories.list()
        normalized = normalize_category(title, known)
        if normalized is not None:
            return normalized
        cleaned = clean_category_name(title)
        self._categories.add(cleaned)
        return cleaned


def _parse_kind(token: str) -> tuple[CommitmentKind | None, Money | None, str | None]:
    lowered = token.casefold()
    if lowered in _VARIABLE_TOKENS:
        return CommitmentKind.VARIABLE, None, None
    if lowered in _METER_TOKENS:
        return CommitmentKind.METER, None, None
    amount = parse_amount_text(token)
    if amount is None or amount.is_zero or amount.is_negative:
        return None, None, "Сумма должна быть положительной, либо var, либо meter."
    return CommitmentKind.FIXED, amount, None


def _parse_index(arguments: str) -> int | None:
    stripped = arguments.strip()
    return int(stripped) if stripped.isdigit() else None


def _parse_readings(text: str) -> list[str]:
    tokens = [token for token in _READINGS_SPLIT_RE.split(text.strip()) if token]
    if not tokens:
        return []
    if all(_INTEGER_RE.fullmatch(token) for token in tokens):
        return tokens
    return []


def _bill_item(
    number: int, commitment: Commitment, occurrence: CommitmentOccurrence | None
) -> BillItem:
    assert commitment.id is not None
    status = occurrence.status if occurrence is not None else OccurrenceStatus.PENDING
    pending = status is OccurrenceStatus.PENDING
    if commitment.kind is CommitmentKind.METER:
        transferred = occurrence is not None and occurrence.meter_transferred_on is not None
        state = "показания переданы" if transferred else "нужны показания"
        return BillItem(
            commitment_id=commitment.id,
            number=number,
            title=commitment.title,
            label=f"{commitment.title} · {commitment.day_of_month}-е · {state}",
            meter=not transferred,
        )
    amount = commitment.amount.format_ru() if commitment.amount is not None else "сумма по факту"
    return BillItem(
        commitment_id=commitment.id,
        number=number,
        title=commitment.title,
        label=(
            f"{commitment.title} · {amount} · "
            f"{commitment.day_of_month}-е · {_STATUS_LABELS[status]}"
        ),
        pay_as_amount=pending and commitment.kind is CommitmentKind.VARIABLE,
        payable=pending and commitment.kind is CommitmentKind.FIXED,
    )
