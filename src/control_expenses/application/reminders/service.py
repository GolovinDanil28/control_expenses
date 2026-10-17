"""Сценарии оповещений: напоминания об обязательствах, алерт о превышении,
недельная сводка. Здесь же «тихий час» и дедупликация.

Тихий час не отбрасывает оповещение, а откладывает: пока идёт тихий час,
``run_due`` ничего не отправляет и не занимает ключ дедупликации, поэтому первое
же срабатывание после его окончания доставит оповещение ровно один раз.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from control_expenses.application.ports import (
    BudgetStateRepository,
    Clock,
    DueCommitments,
    NotificationLog,
    SettingsRepository,
    UnknownChatStore,
    WeeklySummary,
)
from control_expenses.application.reminders.notification import Notification
from control_expenses.application.reminders.replies import NotificationReply
from control_expenses.application.replies import TextReply
from control_expenses.domain.budget import period_of

QUIET_START_KEY = "quiet_start"
QUIET_END_KEY = "quiet_end"
WEEKLY_DOW_KEY = "weekly_report_dow"
WEEKLY_TIME_KEY = "weekly_report_time"

DEFAULT_QUIET_START = "23:00"
DEFAULT_QUIET_END = "08:00"
DEFAULT_WEEKLY_DOW = 0
DEFAULT_WEEKLY_TIME = "11:00"

WEEKDAYS = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)
SCHEDULE_USAGE = "Формат: /schedule <день 0–6> <ЧЧ:ММ>, например: /schedule 1 09:30"


class ReminderService:
    """Решает, какие оповещения положено доставить в данный момент."""

    def __init__(
        self,
        *,
        clock: Clock,
        owner_chat_id: int,
        log: NotificationLog,
        settings: SettingsRepository,
        budget_states: BudgetStateRepository,
        commitments: DueCommitments,
        reports: WeeklySummary,
        unknown_chats: UnknownChatStore,
    ) -> None:
        self._clock = clock
        self._owner_chat_id = owner_chat_id
        self._log = log
        self._settings = settings
        self._budget_states = budget_states
        self._commitments = commitments
        self._reports = reports
        self._unknown_chats = unknown_chats

    def register_unknown_chat(self, chat_id: int) -> None:
        """Запомнить чат вне допуска; уведомление владельцу уйдёт из планировщика."""
        self._unknown_chats.register(chat_id)

    def run_due(self, now: datetime) -> tuple[Notification, ...]:
        """Оповещения, положенные на момент ``now`` (с учётом тихого часа)."""
        if self._in_quiet_hours(now):
            return ()
        messages: list[Notification] = []
        messages.extend(self._overrun_alerts(now))
        messages.extend(self._bill_reminders(now))
        messages.extend(self._unknown_chat_alerts())
        weekly = self._weekly_summary(now)
        if weekly is not None:
            messages.append(weekly)
        return tuple(messages)

    def set_schedule(self, arguments: str) -> TextReply:
        """`/schedule <день 0–6> <ЧЧ:ММ>` — день и время недельной сводки."""
        parts = arguments.split()
        if len(parts) != 2:
            return TextReply(SCHEDULE_USAGE)
        dow_token, time_token = parts
        if not dow_token.isdigit() or not 0 <= int(dow_token) <= 6:
            return TextReply("День недели укажите числом 0–6, где 0 — понедельник.")
        if _parse_time(time_token) is None:
            return TextReply("Время укажите как ЧЧ:ММ, например 09:30.")
        dow = int(dow_token)
        self._settings.set(WEEKLY_DOW_KEY, str(dow))
        self._settings.set(WEEKLY_TIME_KEY, time_token)
        return TextReply(f"Сводка будет приходить: {WEEKDAYS[dow]} в {time_token}.")

    def _overrun_alerts(self, now: datetime) -> list[Notification]:
        period = period_of(now.date())
        state = self._budget_states.get(period)
        if not state.overrun_fixed or state.overrun.is_zero:
            return []
        if not self._log.claim(_key("overrun", self._owner_chat_id, period)):
            return []
        return [
            Notification(
                chat_id=self._owner_chat_id,
                reply=TextReply(
                    f"⚠️ Лимит месяца {period} превышен на {state.overrun.format_ru()}."
                ),
            )
        ]

    def _bill_reminders(self, now: datetime) -> list[Notification]:
        period = period_of(now.date())
        due = self._commitments.due_bills(now.date())
        claimed = [
            item
            for item in due
            if self._log.claim(_key("bill", self._owner_chat_id, item.commitment_id, period))
        ]
        if not claimed:
            return []
        text = "🔔 Напоминание об обязательствах:\n" + "\n".join(item.label for item in claimed)
        return [
            Notification(
                chat_id=self._owner_chat_id,
                reply=NotificationReply(text=text, items=tuple(claimed)),
            )
        ]

    def _unknown_chat_alerts(self) -> list[Notification]:
        alerts: list[Notification] = []
        for chat_id in self._unknown_chats.pending():
            self._unknown_chats.resolve(chat_id)
            if not self._log.claim(_key("unknown", chat_id)):
                continue
            alerts.append(
                Notification(
                    chat_id=self._owner_chat_id,
                    reply=TextReply(
                        f"В бота писал чат {chat_id}, которого нет в списке допуска. "
                        "Сообщение не обработано."
                    ),
                )
            )
        return alerts

    def _weekly_summary(self, now: datetime) -> Notification | None:
        dow = _parse_int(self._settings.get(WEEKLY_DOW_KEY), DEFAULT_WEEKLY_DOW)
        at = _time_or_default(self._settings.get(WEEKLY_TIME_KEY), DEFAULT_WEEKLY_TIME)
        moment = _last_scheduled_moment(now, dow, at)
        if not self._log.claim(_key("weekly", self._owner_chat_id, moment.date().isoformat())):
            return None
        return Notification(chat_id=self._owner_chat_id, reply=self._reports.weekly_summary())

    def _in_quiet_hours(self, now: datetime) -> bool:
        start = _time_or_default(self._settings.get(QUIET_START_KEY), DEFAULT_QUIET_START)
        end = _time_or_default(self._settings.get(QUIET_END_KEY), DEFAULT_QUIET_END)
        if start == end:
            return False
        current = now.time()
        if start < end:
            return start <= current < end
        return current >= start or current < end


def _key(*parts: object) -> str:
    return ":".join(str(part) for part in parts)


def _parse_time(raw: str | None) -> time | None:
    if raw is None:
        return None
    parts = raw.strip().split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return time(hour, minute)


def _time_or_default(raw: str | None, default: str) -> time:
    parsed = _parse_time(raw)
    if parsed is not None:
        return parsed
    fallback = _parse_time(default)
    assert fallback is not None  # значения по умолчанию всегда корректны
    return fallback


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _last_scheduled_moment(now: datetime, dow: int, at: time) -> datetime:
    """Последний прошедший момент расписания (с учётом перехода через полночь)."""
    days_since = (now.weekday() - dow) % 7
    candidate = now.date() - timedelta(days=days_since)
    moment = datetime.combine(candidate, at).replace(tzinfo=now.tzinfo)
    if moment > now:
        moment -= timedelta(days=7)
    return moment
