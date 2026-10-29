# CLI Alarm Clock — Requirements

## 1. Purpose and scope

Build a basic Python alarm clock operated entirely from the command line. There is no graphical interface or web UI. The scheduler runs only as a foreground process started by an explicit command; it must not install itself as a service or continue running after its terminal/process exits.

## 2. Alarm data

Each alarm is a one-time alarm with:

- A unique, stable ID used to list and cancel it.
- A date entered as `DD-MM-YYYY`.
- A time entered as `HH:MM` in 24-hour format.
- An optional user-provided message to display when the alarm fires.
- A status: `scheduled`, `fired`, `completed`, `cancelled`, or `missed`.
- A creation timestamp.

Use the system-configured time zone for validating, scheduling, and displaying alarms. Store timezone-aware timestamps with the system-local UTC offset in a JSON file (by default, `alarms.json` in the application directory). Preserve records across application restarts; cancellation and completion update an alarm's status rather than deleting its record.

## 3. Functional requirements

### 3.1 Create an alarm

- Provide a CLI command to create an alarm by entering/providing its date, time, and optional message.
- Validate the date's exact format and calendar validity (including leap years).
- Validate the time's exact format and range (`00:00` through `23:59`).
- Reject a date/time that is not in the future, and explain the validation error without creating a record.
- Preserve the message with the alarm record; allow an empty message.
- On success, save the alarm and show its ID and scheduled local date/time.

### 3.2 List alarms

- Provide a CLI command to list saved alarms.
- Show each alarm's ID, date, time, and status.
- When loading the list, mark any overdue `scheduled` alarm as `missed` and persist that status before displaying records.
- Make it possible to list all records, including fired, cancelled, and missed alarms, as well as scheduled alarms.

### 3.3 Cancel an alarm

- Provide a CLI command to cancel an alarm by ID.
- A scheduled alarm can be cancelled; a fired, completed, already-cancelled, or missed alarm cannot be cancelled.
- Report an unknown ID or an alarm that is not cancellable clearly.
- Persist the updated status.

### 3.4 Run the scheduler

- Provide an explicit command to run the scheduler in the foreground.
- While running, the scheduler checks for due scheduled alarms and displays a clear notification in its terminal when one is due. The notification includes the alarm's date, time, and user-provided message (if any). The alarm status changes to `fired` when the notification is displayed. Each alarm fires at most once.
- The user can acknowledge/dismiss a displayed notification by pressing Enter. This changes its status from `fired` to `completed`, persists the change, and does not stop the scheduler; it continues checking for alarms.
- The user can stop the foreground scheduler at any time with Ctrl+C. It must not keep running in the background.
- On scheduler startup, overdue `scheduled` alarms and unacknowledged `fired` alarms are marked `missed`; completed and cancelled alarms remain unchanged. Missed alarms are not replayed.

### 3.5 Share updates with a running scheduler

- CLI commands run in other terminals must be able to create and cancel alarms while the scheduler is running.
- The running scheduler must re-read or otherwise detect changes to the shared JSON store and pick up newly created alarms without needing to restart.
- Use safe coordinated file access so concurrent CLI and scheduler operations do not lose updates or corrupt the JSON file.

## 4. Persistence and error handling

- Load existing records from the JSON file at startup; initialize an empty store if the file does not yet exist.
- Write valid JSON and preserve all existing records when adding or updating an alarm.
- Report unreadable, malformed, or unwritable storage clearly; do not silently discard existing data or report a failed save as successful.
- Keep the data file local to the application unless the user explicitly configures another location.

## 5. Out of scope

- Graphical, web, or mobile interfaces.
- Background services or automatic startup.
- Recurring alarms, snooze, sound playback, and multiple time zones.
- Automated test-case creation; tests will be written and run manually by the user.

## 6. Acceptance criteria

1. A user can create a future alarm using `DD-MM-YYYY` and `HH:MM`, with an optional message; invalid or past values are rejected with a useful message.
2. The alarm is present in the JSON file and remains available after restarting the CLI.
3. The list command shows alarm IDs, scheduled local date/time, and statuses, including `fired` and `completed`.
4. A scheduled alarm can be cancelled by ID, and the cancellation remains persisted.
5. Starting the scheduler keeps it in the foreground and displays a terminal notification containing the alarm's message when a due alarm is reached; its status becomes `fired`. Pressing Enter dismisses the notification, persists the `completed` status, and leaves the scheduler running.
6. Creating or cancelling an alarm from another terminal is reflected by a scheduler that is already running.
7. Listing alarms marks overdue scheduled records as missed. On scheduler startup, alarms that became overdue while it was stopped—including fired but unacknowledged alarms—are recorded as missed rather than replayed.
