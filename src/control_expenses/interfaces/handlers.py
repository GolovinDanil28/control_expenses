"""Хендлеры aiogram: текст траты, команды, inline-кнопки.

Слой интерфейса только разбирает апдейт и отрисовывает ответ; решения принимают
сервисы. Сообщения из чатов вне допуска игнорируются без ответа
(capability ``bot-access``). Пока у обязательства открыт запрос (сумма платежа
или показания), обычный ввод траты не обрабатывается — сначала закрывается он.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from control_expenses.application.budgets.service import BudgetService
from control_expenses.application.commitments.service import CommitmentService
from control_expenses.application.expenses.service import ExpenseService
from control_expenses.application.reminders.service import ReminderService
from control_expenses.application.reports.service import ReportService
from control_expenses.application.views import Reply
from control_expenses.interfaces.cards import (
    BILL_METER,
    BILL_PAY,
    BILL_SKIP,
    CALLBACK_AMOUNT,
    CALLBACK_BILL_PREFIX,
    CALLBACK_CANCEL,
    CALLBACK_CATEGORY_PREFIX,
    CALLBACK_CONFIRM,
    CALLBACK_PREFIX,
)
from control_expenses.interfaces.render import render

START_TEXT = (
    "Привет! Напишите трату текстом, например: «кофе 250».\n"
    "Команды: /budget, /report, /bills, /addbill, /delbill, /pay, /skip, "
    "/schedule, /addcategory, /undo, /edit 350."
)


def build_router(
    service: ExpenseService,
    budget: BudgetService,
    commitment: CommitmentService,
    report: ReportService,
    reminders: ReminderService,
    allowed: frozenset[int],
) -> Router:
    """Собрать роутер с проверкой допуска по идентификатору чата."""
    router = Router(name="control_expenses")

    def _allowed(message: Message) -> bool:
        """Допущен ли чат; посторонние чаты запоминаем для уведомления владельцу."""
        if message.chat.id in allowed:
            return True
        reminders.register_unknown_chat(message.chat.id)
        return False

    async def _answer(message: Message, reply: Reply) -> None:
        text, keyboard = render(reply)
        if keyboard is None:
            await message.answer(text)
        else:
            await message.answer(text, reply_markup=keyboard)

    @router.message(Command("start"))
    async def on_start(message: Message) -> None:
        if not _allowed(message):
            return
        await message.answer(START_TEXT)

    @router.message(Command("budget"))
    async def on_budget(message: Message, command: CommandObject) -> None:
        if not _allowed(message):
            return
        await _answer(message, budget.handle_command(command.args or ""))

    @router.message(Command("report"))
    async def on_report(message: Message, command: CommandObject) -> None:
        if not _allowed(message):
            return
        await _answer(message, report.handle_command(command.args or ""))

    @router.message(Command("schedule"))
    async def on_schedule(message: Message, command: CommandObject) -> None:
        if not _allowed(message):
            return
        await _answer(message, reminders.set_schedule(command.args or ""))

    @router.message(Command("addbill"))
    async def on_add_bill(message: Message, command: CommandObject) -> None:
        if not _allowed(message):
            return
        await _answer(message, commitment.add_bill(command.args or ""))

    @router.message(Command("bills"))
    async def on_bills(message: Message) -> None:
        if not _allowed(message):
            return
        await _answer(message, commitment.list_bills())

    @router.message(Command("delbill"))
    async def on_delete_bill(message: Message, command: CommandObject) -> None:
        if not _allowed(message):
            return
        await _answer(message, commitment.delete_bill(command.args or ""))

    @router.message(Command("pay"))
    async def on_pay(message: Message, command: CommandObject) -> None:
        if not _allowed(message):
            return
        await _answer(message, commitment.pay_by_number(message.chat.id, command.args or ""))

    @router.message(Command("skip"))
    async def on_skip(message: Message, command: CommandObject) -> None:
        if not _allowed(message):
            return
        await _answer(message, commitment.skip_by_number(command.args or ""))

    @router.message(Command("addcategory"))
    async def on_add_category(message: Message, command: CommandObject) -> None:
        if not _allowed(message):
            return
        await _answer(message, service.add_category(command.args or ""))

    @router.message(Command("undo"))
    async def on_undo(message: Message) -> None:
        if not _allowed(message):
            return
        await _answer(message, service.undo_last(message.chat.id))

    @router.message(Command("edit"))
    async def on_edit(message: Message, command: CommandObject) -> None:
        if not _allowed(message):
            return
        await _answer(message, service.edit_last(message.chat.id, command.args or ""))

    @router.message(F.text)
    async def on_text(message: Message) -> None:
        if not _allowed(message) or message.text is None:
            return
        chat_id = message.chat.id
        if commitment.has_prompt(chat_id):
            await _answer(message, commitment.handle_prompt_text(chat_id, message.text))
        else:
            await _answer(message, service.handle_text(chat_id, message.text))

    @router.callback_query(F.data.startswith(CALLBACK_PREFIX))
    async def on_expense_callback(callback: CallbackQuery) -> None:
        message = callback.message
        if not isinstance(message, Message) or callback.data is None:
            return
        if not _allowed(message):
            return
        if callback.data == CALLBACK_CONFIRM:
            reply = service.confirm(message.chat.id)
            # фиксация бюджета; оповещение о перерасходе доставит планировщик
            budget.record_after_expense()
        elif callback.data == CALLBACK_CANCEL:
            reply = service.cancel(message.chat.id)
        elif callback.data == CALLBACK_AMOUNT:
            reply = service.request_amount(message.chat.id)
        else:
            name = callback.data.removeprefix(CALLBACK_CATEGORY_PREFIX)
            reply = service.choose_category(message.chat.id, name)
        await callback.answer()
        await _answer(message, reply)

    @router.callback_query(F.data.startswith(CALLBACK_BILL_PREFIX))
    async def on_bill_callback(callback: CallbackQuery) -> None:
        message = callback.message
        if not isinstance(message, Message) or callback.data is None:
            return
        if not _allowed(message):
            return
        data = callback.data
        chat_id = message.chat.id
        if data.startswith(BILL_PAY):
            reply = commitment.pay(chat_id, int(data.removeprefix(BILL_PAY)))
        elif data.startswith(BILL_SKIP):
            reply = commitment.skip(int(data.removeprefix(BILL_SKIP)))
        elif data.startswith(BILL_METER):
            reply = commitment.request_meter(chat_id, int(data.removeprefix(BILL_METER)))
        else:
            return
        await callback.answer()
        await _answer(message, reply)
        # оплата обязательства — тоже трата, бюджет мог уйти в перерасход
        budget.record_after_expense()

    return router
