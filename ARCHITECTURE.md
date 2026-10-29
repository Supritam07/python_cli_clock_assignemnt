# CLI Alarm Clock — Architecture

## 1. Overview

The application is a small, single-machine Python CLI. It has no UI, daemon, or background service. Users run individual commands to manage alarms; a separate foreground `run` command checks for due alarms until stopped with Ctrl+C.

All commands share a local JSON file. A short-lived inter-process lock protects every read-modify-write operation, and writes use a temporary file followed by an atomic replacement. The running scheduler periodically reloads the file, so changes made by commands in other terminals are picked up without restarting it.

```text
 Terminal A                         Terminal B
┌────────────────────┐             ┌───────────────────┐
│ python alarm.py run│             │ add / list / cancel│
│ Scheduler loop     │             │ CLI command        │
│ Reloads JSON       │             └─────────┬─────────┘
│ Displays due alarm │                       │
│ Enter acknowledges│                       │
│ Ctrl+C stops       │                       │
└─────────┬──────────┘                       │
          └──────────────┬──────────────────┘
                         ▼
             ┌────────────────────────┐
             │ alarms.json.lock       │
             │ alarms.json.scheduler.lock │
             │ alarms.json            │
             │ Shared persistent data │
             └────────────────────────┘
```

## 2. Proposed project structure

```text
.
├── alarm.py          # CLI entry point and argument parsing
├── alarm_service.py  # Create, list, cancel, and status-transition rules
├── storage.py        # JSON serialization, locking, atomic writes
├── scheduler.py      # Foreground polling loop and notification handling
├── alarms.json       # Persistent alarm records; created on first use
├── alarms.json.lock  # Inter-process data lock; created as needed
└── alarms.json.scheduler.lock # Single-scheduler lock; created as needed
```

Keep the initial implementation in a few modules and use Python's standard library where practical. `storage.py` uses OS-backed standard-library locking (`fcntl` on Unix-like systems and `msvcrt` on Windows); do not implement locking as a check-then-create operation, which is race-prone.

## 3. CLI interface

Proposed command shape (exact names and options can be adjusted during implementation):

```text
python alarm.py add --date DD-MM-YYYY --time HH:MM [--message "text"]
python alarm.py list
python alarm.py cancel ALARM_ID
python alarm.py run
```

- `add` validates input, creates a unique ID, persists the alarm, and prints its ID and scheduled local time.
- `list` displays all records, including their status and optional message.
- `cancel` changes a scheduled alarm's status to `cancelled`; it does not delete the record.
- `run` starts the foreground scheduler. Ctrl+C exits it cleanly.
- Invalid input, unknown IDs, malformed storage, and failed writes produce a non-zero command result and a useful error on stderr.

## 4. Alarm record and JSON format

Use an object keyed by stable alarm ID to make lookup and status updates direct:

```json
{
  "version": 1,
  "alarms": {
    "a1b2c3d4": {
      "date": "29-10-2026",
      "time": "17:30",
      "scheduled_at": "2026-10-29T17:30:00+05:30",
      "message": "Call home",
      "status": "scheduled",
      "created_at": "2026-10-29T17:18:00+05:30"
    }
  }
}
```

- `scheduled_at` and `created_at` are ISO 8601 timestamps that include the system-local UTC offset. Convert the entered local date/time using the system time zone and use timezone-aware values when validating and comparing alarm instants.
- `date` and `time` retain the requested display format.
- `message` is always present as a string; it may be empty.
- Valid statuses are `scheduled`, `fired`, `completed`, `cancelled`, and `missed`.
- `version` allows a future format migration. Unsupported versions or invalid JSON must be reported; never replace unreadable data with an empty store.

## 5. Storage and concurrent access

Every command that accesses alarm data follows the same storage contract:

1. Acquire the inter-process lock on `alarms.lock`.
2. Read and validate the current JSON file. If it does not exist, treat it as a new empty store.
3. Perform the operation against the latest records while holding the lock.
4. For a change, serialize to a temporary file in the same directory, flush and close it, then atomically replace `alarms.json`.
5. Release the lock, including on errors.

Holding the lock across read-modify-write prevents an `add`, `cancel`, or scheduler status update from overwriting another process's newer change. Keeping the temporary file in the same directory allows atomic replacement on the same filesystem. The lock file is coordination metadata and is not an alarm record.

`list` reads under the lock as well, so it does not observe a partially written file. Storage errors are surfaced to the caller; no operation should report success before its data has been saved.

## 6. Scheduler and notification flow

The scheduler is a foreground loop with a short configurable polling interval (for example, one second):

1. Acquire the storage lock, reload and validate the JSON file, and inspect scheduled records.
2. On scheduler startup, transition overdue `scheduled` alarms and unacknowledged `fired` alarms to `missed`. Do not replay them. The list operation also marks overdue `scheduled` records `missed` before returning them.
3. For each scheduled alarm whose time is now due, transition it to `fired` and persist that transition before displaying the notification. This makes the alarm fire at most once, including across scheduler restarts.
4. Display the alarm's date, time, and message (if non-empty) in the terminal. Its persisted status is `fired` while its notification awaits acknowledgement.
5. Wait for Enter to acknowledge the displayed notification. On Enter, persist the status as `completed`. A dedicated input reader can wait for Enter while the main scheduler loop continues polling the JSON file for new or cancelled alarms. Keep only one notification prompt active at a time; queue additional due notifications and display them in order.
6. Continue polling until Ctrl+C. Handle Ctrl+C in the main thread, stop cleanly, and leave the JSON file valid.

The scheduler checks current status from storage before acting, so an alarm cancelled in another terminal is not displayed. Once an alarm has transitioned to `fired`, it is no longer cancellable. If the scheduler stops after saving `fired` but before Enter is pressed, the alarm is marked `missed` on scheduler startup and will not notify again; this is the deliberate trade-off for at-most-once behavior.

## 7. Validation and service boundaries

- `alarm.py` parses arguments and reports results; it does not own persistence rules.
- `alarm_service.py` validates exact date/time formats, verifies calendar validity and future scheduling, applies cancellation rules, and creates IDs/timestamps.
- `storage.py` owns locking, JSON validation, atomic writes, and data-format version checks.
- `scheduler.py` owns polling, overdue-on-start handling, due-alarm state transitions, and terminal notifications.

Validate a requested date/time as one datetime in the system-configured time zone and compare it with the current system-local datetime. Reject past or current times. Validate status transitions in the service layer, not just in CLI argument handling.

## 8. Failure behavior

- If JSON is malformed, unreadable, or has an unsupported version, stop the requested operation and explain the problem. Do not initialize over or delete the file.
- If locking or saving fails, report the error; do not claim the alarm was added, cancelled, or fired.
- If the scheduler encounters a storage error, print the error and exit rather than continuing with stale alarm data.
- On Ctrl+C, stop polling and exit without corrupting or partially rewriting the JSON file.
