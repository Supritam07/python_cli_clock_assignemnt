"""Alarm validation and operations."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

from storage import modify_store, read_store, scheduler_instance_lock

DATE_PATTERN = re.compile(r"\d{2}-\d{2}-\d{4}\Z")
TIME_PATTERN = re.compile(r"\d{2}:\d{2}\Z")


class AlarmError(Exception):
    """Raised for invalid alarm operations or input."""


def parse_schedule(date_text: str, time_text: str) -> datetime:
    if not DATE_PATTERN.fullmatch(date_text):
        raise AlarmError("Date must use the exact format DD-MM-YYYY.")
    if not TIME_PATTERN.fullmatch(time_text):
        raise AlarmError("Time must use the exact 24-hour format HH:MM.")
    try:
        scheduled_at = datetime.strptime(
            f"{date_text} {time_text}", "%d-%m-%Y %H:%M"
        )
    except ValueError as exc:
        raise AlarmError(f"Invalid date or time: {exc}.") from exc
    scheduled_at = scheduled_at.astimezone()
    if (
        scheduled_at.strftime("%d-%m-%Y") != date_text
        or scheduled_at.strftime("%H:%M") != time_text
    ):
        raise AlarmError("That date and time does not exist in the system time zone.")
    if scheduled_at <= datetime.now().astimezone():
        raise AlarmError("Alarm date and time must be in the future.")
    return scheduled_at


def create_alarm(path: Path, date_text: str, time_text: str, message: str) -> tuple[str, dict]:
    scheduled_at = parse_schedule(date_text, time_text)
    created_at = datetime.now().astimezone()
    record = {
        "date": date_text,
        "time": time_text,
        "scheduled_at": scheduled_at.isoformat(timespec="seconds"),
        "message": message,
        "status": "scheduled",
        "created_at": created_at.isoformat(timespec="seconds"),
    }

    def add(store: dict) -> tuple[tuple[str, dict], bool]:
        alarm_id = uuid.uuid4().hex[:8]
        while alarm_id in store["alarms"]:
            alarm_id = uuid.uuid4().hex[:8]
        store["alarms"][alarm_id] = record
        return (alarm_id, record), True

    return modify_store(path, add)


def list_alarms(path: Path) -> list[tuple[str, dict]]:
    with scheduler_instance_lock(path) as scheduler_stopped:
        if scheduler_stopped:
            mark_overdue_alarms(path)
        store = read_store(path)
        return sorted(
            store["alarms"].items(),
            key=lambda item: (item[1]["scheduled_at"], item[0]),
        )


def cancel_alarm(path: Path, alarm_id: str) -> dict:
    def cancel(store: dict) -> tuple[dict, bool]:
        record = store["alarms"].get(alarm_id)
        if record is None:
            raise AlarmError(f"No alarm exists with ID {alarm_id!r}.")
        if record["status"] != "scheduled":
            raise AlarmError(
                f"Alarm {alarm_id!r} cannot be cancelled because its status is "
                f"{record['status']!r}."
            )
        record["status"] = "cancelled"
        return record, True

    return modify_store(path, cancel)


def complete_alarm(path: Path, alarm_id: str) -> dict:
    def complete(store: dict) -> tuple[dict, bool]:
        record = store["alarms"].get(alarm_id)
        if record is None:
            raise AlarmError(f"No alarm exists with ID {alarm_id!r}.")
        if record["status"] != "fired":
            raise AlarmError(
                f"Alarm {alarm_id!r} cannot be completed because its status is "
                f"{record['status']!r}."
            )
        record["status"] = "completed"
        return record, True

    return modify_store(path, complete)


def mark_overdue_alarms(path: Path, *, include_fired: bool = False) -> int:
    """Mark past scheduled alarms, and optionally unacknowledged fired alarms, missed."""
    now = datetime.now().astimezone()
    statuses_to_mark = {"scheduled"}
    if include_fired:
        statuses_to_mark.add("fired")

    def mark_missed(store: dict) -> tuple[int, bool]:
        missed_count = 0
        for record in store["alarms"].values():
            if record["status"] not in statuses_to_mark:
                continue
            if datetime.fromisoformat(record["scheduled_at"]) <= now:
                record["status"] = "missed"
                missed_count += 1
        return missed_count, missed_count > 0

    return modify_store(path, mark_missed)


def transition_due_alarms(path: Path, *, startup: bool) -> tuple[list[tuple[str, dict]], int]:
    """Persist due/missed transitions and return alarms to notify and missed count."""
    now = datetime.now().astimezone()

    if startup:
        return [], mark_overdue_alarms(path, include_fired=True)

    def transition(store: dict) -> tuple[tuple[list[tuple[str, dict]], int], bool]:
        notifications: list[tuple[str, dict]] = []
        changed = False
        for alarm_id, record in store["alarms"].items():
            if record["status"] != "scheduled":
                continue
            scheduled_at = datetime.fromisoformat(record["scheduled_at"])
            if scheduled_at > now:
                continue
            record["status"] = "fired"
            notifications.append((alarm_id, dict(record)))
            changed = True
        return (notifications, 0), changed

    return modify_store(path, transition)
