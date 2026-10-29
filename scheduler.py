"""Foreground alarm scheduler and terminal notifications."""

from __future__ import annotations

import queue
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from alarm_service import complete_alarm, transition_due_alarms
from storage import StorageError, scheduler_instance_lock

POLL_INTERVAL_SECONDS = 1.0


class SchedulerError(Exception):
    """Raised when the scheduler cannot run as requested."""


def _input_reader(events: queue.Queue[object]) -> None:
    while True:
        try:
            line = sys.stdin.readline()
        except OSError as exc:
            events.put(exc)
            return
        if line == "":
            events.put(None)
            return
        events.put("enter")


def _show_notification(alarm_id: str, record: dict) -> None:
    print()
    print("=" * 60)
    print(f"ALARM {alarm_id} — {record['date']} {record['time']}")
    if record["message"]:
        print(record["message"])
    print("Press Enter to dismiss this notification and mark the alarm completed.")
    print("=" * 60, flush=True)


def run_scheduler(path: Path) -> None:
    if not sys.stdin.isatty():
        raise SchedulerError("The scheduler requires an interactive terminal for Enter acknowledgements.")

    try:
        with scheduler_instance_lock(path) as acquired:
            if not acquired:
                raise SchedulerError("A scheduler is already running for this alarm file.")
            _run_scheduler_loop(path)
    except StorageError as exc:
        raise SchedulerError(str(exc)) from exc
    except KeyboardInterrupt:
        print("\nAlarm scheduler stopped.")


def _run_scheduler_loop(path: Path) -> None:
    _, missed_count = transition_due_alarms(path, startup=True)
    if missed_count:
        print(f"Marked {missed_count} overdue alarm(s) as missed.")

    input_events: queue.Queue[object] = queue.Queue()
    reader = threading.Thread(
        target=_input_reader, args=(input_events,), daemon=True, name="alarm-input"
    )
    reader.start()

    pending: deque[tuple[str, dict]] = deque()
    active_notification: str | None = None
    print("Alarm scheduler running. Press Ctrl+C to stop.")

    def display_next() -> None:
        nonlocal active_notification
        if active_notification is not None or not pending:
            return
        alarm_id, record = pending[0]
        _show_notification(alarm_id, record)
        active_notification = alarm_id

    while True:
        events_handled = False
        while True:
            try:
                event = input_events.get_nowait()
            except queue.Empty:
                break
            events_handled = True
            if event is None:
                raise SchedulerError("Terminal input closed; cannot acknowledge alarms.")
            if isinstance(event, OSError):
                raise SchedulerError(f"Unable to read terminal input: {event}")
            if active_notification is not None:
                complete_alarm(path, active_notification)
                pending.popleft()
                active_notification = None
                display_next()

        if not events_handled:
            notifications, _ = transition_due_alarms(path, startup=False)
            pending.extend(notifications)
            display_next()
            time.sleep(POLL_INTERVAL_SECONDS)
