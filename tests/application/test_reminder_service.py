"""Тесты оповещений: тихий час, дедупликация, напоминания и сводка."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import NamedTuple

from control_expenses.application.budgets.state import BudgetState
from control_expenses.application.commitments.replies import BillItem
from control_expenses.application.reminders.replies import NotificationReply
from control_expenses.application.reminders.service import ReminderService
from control_expenses.application.replies import TextReply
from control_expenses.application.views import Reply
from control_expenses.domain.money import Money
from control_expenses.infrastructure.scheduler import Scheduler

MONDAY = date(2026, 10, 19)
MONDAY_NOON = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
OWNER = 42


def _at(hour: int, minute: int = 0, day: date = MONDAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._now.date()


class FakeNotificationLog:
    def __init__(self) -> None:
        self.claimed: set[str] = set()

    def claim(self, dedup_key: str) -> bool:
        if dedup_key in self.claimed:
            return False
        self.claimed.add(dedup_key)
        return True


class FakeSettings:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values if values is not None else {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value


class FakeBudgetStates:
    def __init__(self, state: BudgetState | None = None) -> None:
        self.state = state

    def get(self, period: str) -> BudgetState:
        return self.state if self.state is not None else BudgetState(period=period)

    def save(self, state: BudgetState) -> None:
        self.state = state


class FakeUnknownChats:
    def __init__(self) -> None:
        self.chats: list[int] = []

    def register(self, chat_id: int) -> None:
        if chat_id not in self.chats:
            self.chats.append(chat_id)

    def pending(self) -> tuple[int, ...]:
        return tuple(self.chats)

    def resolve(self, chat_id: int) -> None:
        self.chats = [item for item in self.chats if item != chat_id]


class FakeDueCommitments:
    def __init__(self, items: tuple[BillItem, ...] = ()) -> None:
        self.items = items

    def due_bills(self, today: date) -> tuple[BillItem, ...]:
        return self.items


class FakeReports:
    def weekly_summary(self) -> TextReply:
        return TextReply("Сводка за неделю")


DEFAULT_SCHEDULE = {
    "quiet_start": "23:00",
    "quiet_end": "08:00",
    "weekly_report_dow": "0",
    "weekly_report_time": "11:00",
}


class Env(NamedTuple):
    service: ReminderService
    log: FakeNotificationLog
    settings: FakeSettings
    states: FakeBudgetStates
    commitments: FakeDueCommitments


def _env(
    *,
    now: datetime = MONDAY_NOON,
    settings: dict[str, str] | None = None,
    state: BudgetState | None = None,
    bills: tuple[BillItem, ...] = (),
) -> Env:
    log = FakeNotificationLog()
    settings_repo = FakeSettings({**DEFAULT_SCHEDULE, **(settings or {})})
    states = FakeBudgetStates(state)
    commitments = FakeDueCommitments(bills)
    service = ReminderService(
        clock=FakeClock(now),
        owner_chat_id=OWNER,
        log=log,
        settings=settings_repo,
        budget_states=states,
        commitments=commitments,
        reports=FakeReports(),
        unknown_chats=FakeUnknownChats(),
    )
    return Env(
        service=service,
        log=log,
        settings=settings_repo,
        states=states,
        commitments=commitments,
    )


def _bill() -> BillItem:
    return BillItem(
        commitment_id=1,
        number=1,
        title="Квартира",
        label="Квартира · 15 000 ₽ · 5-е · ожидает",
        payable=True,
    )


def _texts(replies: tuple[Reply, ...]) -> str:
    parts = [reply.text for reply in replies if isinstance(reply, (TextReply, NotificationReply))]
    return "\n".join(parts)


def test_quiet_hours_suppress_everything() -> None:
    state = BudgetState(period="2026-10", overrun_fixed=True, overrun=Money.from_rubles("500"))
    env = _env(now=_at(23, 30), state=state, bills=(_bill(),))
    assert env.service.run_due(_at(23, 30)) == ()


def test_overrun_alert_delivered_once() -> None:
    state = BudgetState(period="2026-10", overrun_fixed=True, overrun=Money.from_rubles("500"))
    env = _env(state=state)
    first = env.service.run_due(MONDAY_NOON)
    assert "превышен на 500 ₽" in _texts(tuple(item.reply for item in first))
    assert env.service.run_due(MONDAY_NOON) == ()


def test_bill_reminder_delivered_once_with_buttons() -> None:
    env = _env(bills=(_bill(),))
    first = env.service.run_due(MONDAY_NOON)
    reminder = next(item.reply for item in first if isinstance(item.reply, NotificationReply))
    assert "Напоминание" in reminder.text
    assert "Квартира" in reminder.text
    assert reminder.items[0].payable is True
    assert env.service.run_due(MONDAY_NOON) == ()


def test_weekly_summary_delivered_after_scheduled_moment() -> None:
    env = _env()
    messages = env.service.run_due(MONDAY_NOON)
    assert len(messages) == 1
    assert messages[0].chat_id == OWNER
    assert env.service.run_due(MONDAY_NOON) == ()


def test_weekly_summary_deferred_through_quiet_hours() -> None:
    env = _env(settings={"quiet_start": "10:00", "quiet_end": "12:00"})
    assert env.service.run_due(_at(11, 30)) == ()
    delivered = env.service.run_due(_at(12, 30))
    assert len(delivered) == 1
    assert env.service.run_due(_at(13, 0)) == ()


def test_weekly_summary_survives_midnight_quiet() -> None:
    env = _env(settings={"weekly_report_dow": "6", "weekly_report_time": "23:30"})
    assert env.service.run_due(_at(8, 30)) != ()


def _unknown_notices(replies: tuple[Reply, ...]) -> list[str]:
    return [
        reply.text
        for reply in replies
        if isinstance(reply, TextReply) and "списке допуска" in reply.text
    ]


def test_unknown_chat_notice_delivered_once() -> None:
    env = _env()
    env.service.register_unknown_chat(777)
    first = _unknown_notices(tuple(item.reply for item in env.service.run_due(_at(12, 0))))
    assert len(first) == 1
    assert "777" in first[0]
    second = _unknown_notices(tuple(item.reply for item in env.service.run_due(_at(12, 1))))
    assert second == []


def test_unknown_chat_notice_deferred_from_quiet_hours() -> None:
    env = _env()
    env.service.register_unknown_chat(777)
    assert env.service.run_due(_at(23, 30)) == ()
    after = _unknown_notices(tuple(item.reply for item in env.service.run_due(_at(8, 30))))
    assert len(after) == 1


def test_set_schedule_validates_and_saves() -> None:
    env = _env()
    ok = env.service.set_schedule("1 09:30")
    assert "вторник" in ok.text
    assert env.settings.get("weekly_report_dow") == "1"
    assert env.settings.get("weekly_report_time") == "09:30"


def test_set_schedule_rejects_bad_values() -> None:
    env = _env()
    assert "0–6" in env.service.set_schedule("9 09:30").text
    assert "ЧЧ:ММ" in env.service.set_schedule("1 25:00").text
    assert "Формат" in env.service.set_schedule("1").text
    assert env.settings.get("weekly_report_dow") == "0"


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, Reply]] = []

    async def send(self, chat_id: int, reply: Reply) -> None:
        self.sent.append((chat_id, reply))


async def test_scheduler_delivers_ready_notifications() -> None:
    env = _env(bills=(_bill(),))
    sender = RecordingSender()
    scheduler = Scheduler(
        reminders=env.service, sender=sender, clock=FakeClock(MONDAY_NOON), interval=1
    )
    sent = await scheduler.run_once()
    assert sent >= 1
    assert sent == len(sender.sent)
    assert any(isinstance(reply, NotificationReply) for _, reply in sender.sent)
    # повторный тик ничего не дублирует
    assert await scheduler.run_once() == 0
