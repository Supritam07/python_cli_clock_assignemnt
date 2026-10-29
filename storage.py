"""Coordinated JSON storage for alarm records."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from errno import EACCES, EDEADLK
from pathlib import Path
from typing import Callable, Iterator, TypeVar

if os.name == "nt":
    import msvcrt
else:
    import fcntl

T = TypeVar("T")
STORE_VERSION = 1
VALID_STATUSES = {"scheduled", "fired", "completed", "cancelled", "missed"}


class StorageError(Exception):
    """Raised when the alarm store cannot safely be read or written."""


def _empty_store() -> dict:
    return {"version": STORE_VERSION, "alarms": {}}


def _validate_store(data: object) -> dict:
    if not isinstance(data, dict) or set(data) != {"version", "alarms"}:
        raise StorageError("Alarm file must contain 'version' and 'alarms'.")
    if type(data["version"]) is not int or data["version"] != STORE_VERSION:
        raise StorageError(f"Unsupported alarm file version: {data['version']!r}.")
    alarms = data["alarms"]
    if not isinstance(alarms, dict):
        raise StorageError("'alarms' must be a JSON object.")

    required_fields = {
        "date", "time", "scheduled_at", "message", "status", "created_at"
    }
    for alarm_id, record in alarms.items():
        if not isinstance(alarm_id, str) or not alarm_id:
            raise StorageError("Alarm IDs must be non-empty strings.")
        if not isinstance(record, dict) or set(record) != required_fields:
            raise StorageError(f"Alarm {alarm_id!r} has an invalid record shape.")
        for field in ("date", "time", "scheduled_at", "message", "status", "created_at"):
            if not isinstance(record[field], str):
                raise StorageError(f"Alarm {alarm_id!r} has an invalid {field!r} value.")
        if record["status"] not in VALID_STATUSES:
            raise StorageError(f"Alarm {alarm_id!r} has an invalid status.")
        try:
            scheduled_at = datetime.fromisoformat(record["scheduled_at"])
            created_at = datetime.fromisoformat(record["created_at"])
            display_datetime = datetime.strptime(
                f"{record['date']} {record['time']}", "%d-%m-%Y %H:%M"
            )
        except ValueError as exc:
            raise StorageError(f"Alarm {alarm_id!r} has an invalid date or timestamp.") from exc
        if scheduled_at.tzinfo is None or created_at.tzinfo is None:
            raise StorageError(f"Alarm {alarm_id!r} timestamps must include the system timezone offset.")
        if (
            display_datetime.strftime("%d-%m-%Y") != record["date"]
            or display_datetime.strftime("%H:%M") != record["time"]
            or scheduled_at.strftime("%d-%m-%Y") != record["date"]
            or scheduled_at.strftime("%H:%M") != record["time"]
            or scheduled_at.second != 0
            or scheduled_at.microsecond != 0
        ):
            raise StorageError(f"Alarm {alarm_id!r} date/time fields do not match its timestamp.")
    return data


@contextmanager
def _file_lock(lock_path: Path, *, blocking: bool = True) -> Iterator[bool]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_file = lock_path.open("a+b")
    except OSError as exc:
        raise StorageError(f"Unable to open lock file {lock_path}: {exc}") from exc

    acquired = False
    try:
        if os.name == "nt":
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            while True:
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError as exc:
                    if exc.errno not in (EACCES, EDEADLK):
                        raise
                    if not blocking:
                        yield False
                        return
                    time.sleep(0.05)
        else:
            mode = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
            try:
                fcntl.flock(lock_file.fileno(), mode)
            except BlockingIOError:
                yield False
                return
            acquired = True
        yield True
    except OSError as exc:
        raise StorageError(f"Unable to lock alarm data: {exc}") from exc
    finally:
        try:
            if acquired:
                if os.name == "nt":
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


def _read_unlocked(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return _empty_store()
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageError(f"Unable to read valid alarm data from {path}: {exc}") from exc
    return _validate_store(data)


def _write_unlocked(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = file.name
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError as exc:
        raise StorageError(f"Unable to save alarm data to {path}: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def read_store(path: Path) -> dict:
    """Read the latest validated store while excluding concurrent writers."""
    path = path.expanduser().resolve()
    with _file_lock(path.with_name(path.name + ".lock")):
        return _read_unlocked(path)


@contextmanager
def scheduler_instance_lock(path: Path) -> Iterator[bool]:
    """Prevent overlapping schedulers; yield False when one is already active."""
    path = path.expanduser().resolve()
    with _file_lock(path.with_name(path.name + ".scheduler.lock"), blocking=False) as acquired:
        yield acquired


def modify_store(path: Path, operation: Callable[[dict], tuple[T, bool]]) -> T:
    """Run an operation under lock and persist only when it reports a change."""
    path = path.expanduser().resolve()
    with _file_lock(path.with_name(path.name + ".lock")):
        store = _read_unlocked(path)
        result, changed = operation(store)
        if changed:
            _write_unlocked(path, store)
        return result
