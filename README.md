# CLI Alarm Clock

A small Python command-line alarm clock. Alarms are stored in a local JSON file and can be created, listed, and cancelled from separate terminals. Run the foreground scheduler to receive terminal notifications when alarms become due.

## Features

- Create one-time alarms using `DD-MM-YYYY` dates and 24-hour `HH:MM` times.
- Add an optional message to show in the alarm notification.
- Validate date/time syntax and calendar dates, and reject alarms that are not in the future.
- List alarms and their statuses: `scheduled`, `fired`, `completed`, `cancelled`, or `missed`.
- Cancel alarms that are still scheduled.
- Persist alarm records in JSON across CLI invocations.
- Coordinate concurrent processes with an OS-backed file lock and atomic file replacement.
- Use the system-configured local time zone when creating and scheduling alarms.
- Display due alarms in the scheduler terminal. Press Enter to acknowledge a notification; press Ctrl+C to stop the scheduler.
- Mark alarms that became overdue while the scheduler was not running as `missed` when the scheduler next starts.

## Requirements

- Python 3.10 or later.
- No third-party Python packages are required.
- An interactive terminal is required for the `run` command because notifications are acknowledged by pressing Enter.

## Setup

Open a terminal in the project directory:

```bash
cd cli-alarm-clock-assingement
```

Run the program with Python:

```bash
python3 alarm.py --help
```

On Windows, use `python alarm.py ...` if `python3` is not available. If you have created a virtual environment, activate it first; the application itself has no external package installation step.

## Commands

The global `--data-file` option selects the JSON file used by a command. Put it **before** the subcommand. If omitted, the application uses `alarms.json` beside `alarm.py`.

### Create an alarm

```bash
python3 alarm.py add --date DD-MM-YYYY --time HH:MM [--message "message text"]
```

Example:

```bash
python3 alarm.py add --date 31-12-2026 --time 23:45 --message "Welcome the new year"
```

- `--date` is required and must be a real calendar date in `DD-MM-YYYY` format.
- `--time` is required and must be in 24-hour `HH:MM` format (from `00:00` through `23:59`).
- `--message` is optional. Quote messages containing spaces.
- The date and time are interpreted in the system-configured time zone.
- On success, the command prints the new alarm's ID and scheduled local time. Save the ID to cancel the alarm later.
- Invalid dates, invalid times, past/current times, and dates that cannot be represented in the current system time zone are rejected.

### List alarms

```bash
python3 alarm.py list
```

Shows every record, including alarm ID, date, time, status, and message. An empty store prints `No alarms found.`

### Cancel an alarm

```bash
python3 alarm.py cancel ALARM_ID
```

Replace `ALARM_ID` with the ID printed by `add` or shown by `list`. Only an alarm with `scheduled` status can be cancelled. The record remains in the JSON file with status `cancelled`; it is not deleted.

### Run the scheduler

```bash
python3 alarm.py run
```

Leave this command running in an interactive terminal to receive alarms. The scheduler checks the shared JSON store approximately once per second, so alarms added or cancelled from another terminal are picked up while it is running.

When an alarm is due, the scheduler marks it `fired` and displays its date, time, and optional message in the terminal. Press Enter to dismiss the displayed notification; the alarm status is then persisted as `completed`, and the scheduler continues running. If more alarms become due, notifications are shown one at a time in order. Press Ctrl+C to stop the scheduler.

On `list`, overdue alarms that are still `scheduled` are marked `missed` before they are displayed. On scheduler startup, overdue `scheduled` alarms and unacknowledged `fired` alarms are marked `missed`; completed and cancelled alarms are left unchanged. Missed alarms are not replayed.

### Use a different JSON file

Pass `--data-file` before the subcommand:

```bash
python3 alarm.py --data-file ./data/personal-alarms.json add \
  --date 31-12-2026 --time 23:45 --message "New year"
python3 alarm.py --data-file ./data/personal-alarms.json list
python3 alarm.py --data-file ./data/personal-alarms.json cancel ALARM_ID
python3 alarm.py --data-file ./data/personal-alarms.json run
```

All terminals managing the same alarms must use the same data-file path.

## Folder structure

```text
.
├── alarm.py          # CLI argument parsing and command dispatch
├── alarm_service.py  # Alarm input validation and alarm operations
├── storage.py        # JSON validation, file locking, and atomic persistence
├── scheduler.py      # Foreground polling and terminal notifications
├── alarms.json       # Created on first successful write; persistent alarm data
├── alarms.json.lock  # Created as needed; coordinates processes accessing the store
├── alarms.json.scheduler.lock # Created as needed; prevents overlapping schedulers
├── README.md         # Usage and project documentation
├── REQUIREMENTS.md   # Functional requirements
└── ARCHITECTURE.md   # Component and data-flow design
```

The JSON data file and lock file are runtime files and may not exist until the first command writes an alarm or starts a process that accesses the store.

## Data and status behavior

The JSON file has a top-level `version` and an `alarms` object keyed by alarm ID. Each record contains its display date/time, a timezone-aware ISO 8601 scheduled timestamp, the optional message, status, and creation timestamp.

| Status | Meaning |
|---|---|
| `scheduled` | Waiting for its scheduled time; can be cancelled. Newly created records use this status (there is no separate `created` status). |
| `fired` | The running scheduler detected the due time and displayed a notification, awaiting acknowledgement. |
| `completed` | The notification was acknowledged by pressing Enter. |
| `cancelled` | Cancelled before firing; retained in the record. |
| `missed` | Was overdue when the scheduler started; not replayed. |

Malformed or unsupported JSON data is reported as an error instead of being silently replaced with an empty store. Add, cancel, and scheduler status updates are serialized under a lock and saved using atomic replacement.

## Edge cases and current limitations

- **Scheduler must be running for notifications.** This is a foreground CLI process, not a service. Closing the terminal or stopping the process prevents notifications from being delivered.
- **Overdue status reconciliation occurs when listing or starting the scheduler.** When no scheduler is running, `list` marks overdue `scheduled` alarms as `missed`. While the scheduler is running, `list` leaves its active alarms alone. On scheduler startup, overdue `scheduled` and unacknowledged `fired` alarms are marked `missed`. Other commands do not perform this reconciliation.
- **At-most-once notification trade-off.** The alarm is saved as `fired` before its notification is printed. If the process exits before Enter is pressed, the alarm is marked `missed` at the next scheduler startup and will not be replayed.
- **Interactive input is required.** `run` refuses non-interactive stdin; terminal detachment or input closure while running can prevent acknowledgement and stop the scheduler with an error.
- **DST ambiguity is not selectable.** During a daylight-saving fall-back, a local time that occurs twice cannot be disambiguated by the user. Nonexistent local times during a spring-forward transition are rejected when the system's timezone conversion does not round-trip to the requested wall time.
- **Changing the system time zone after alarms are created does not migrate them.** Existing records retain their saved UTC offset and display date/time; new alarms use the system's current time zone. If the system zone changes, existing alarms will not automatically shift to the new zone.
- **Clock changes are not specially handled.** Manually changing the system clock or changing time-zone configuration while the scheduler is running may affect when alarms are considered due.
- **Messages are terminal text.** There is no speech, desktop notification, sound, or GUI support in the current implementation.
- **No recurrence or snooze.** Alarms are one-time events; there is no repeat schedule, snooze, edit, or delete command.
- **No cross-device synchronization.** The JSON file and lock coordinate local processes on a shared filesystem; remote synchronization and network-filesystem locking guarantees are not provided.
- **Windows locking has not been verified in this environment.** The implementation includes a Windows `msvcrt` locking path, but it should be manually exercised on Windows before relying on it.
- **No automated tests are included.** The project has been manually smoke-checked; a dedicated test suite remains future work.

## Future scope

These are planned enhancements, not features of the current CLI:

1. **Voice notifications** to speak the alarm message using a text-to-speech engine.
2. **A user interface** for creating, viewing, and cancelling alarms.
3. **Background scheduling** that can continue without an open foreground terminal, with suitable platform-specific service or startup integration.
4. **Expanded error handling and recovery**, including actionable diagnostics and recovery guidance for malformed data, platform-specific locking failures, and interrupted scheduler operation.
5. **Automated tests** for validation, persistence, concurrent access, scheduler transitions, and platform-specific behavior.

## Design document

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the architecture and [REQUIREMENTS.md](./REQUIREMENTS.md) for the functional requirements.
