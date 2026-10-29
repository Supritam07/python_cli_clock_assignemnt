"""Command-line entry point for the alarm clock."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from alarm_service import AlarmError, cancel_alarm, create_alarm, list_alarms
from scheduler import SchedulerError, run_scheduler
from storage import StorageError

DEFAULT_DATA_FILE = Path(__file__).resolve().with_name("alarms.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage one-time command-line alarms.")
    parser.add_argument(
        "--data-file",
        type=Path,
        default=DEFAULT_DATA_FILE,
        help=f"JSON alarm store (default: {DEFAULT_DATA_FILE})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Create an alarm.")
    add_parser.add_argument("--date", required=True, help="Alarm date in DD-MM-YYYY format.")
    add_parser.add_argument("--time", required=True, help="Alarm time in 24-hour HH:MM format.")
    add_parser.add_argument("--message", default="", help="Optional notification message.")

    subparsers.add_parser("list", help="List all alarm records.")

    cancel_parser = subparsers.add_parser("cancel", help="Cancel a scheduled alarm.")
    cancel_parser.add_argument("alarm_id", help="ID of the alarm to cancel.")

    subparsers.add_parser("run", help="Run the foreground alarm scheduler.")
    return parser


def _print_alarms(alarms: list[tuple[str, dict]]) -> None:
    if not alarms:
        print("No alarms found.")
        return
    print(f"{'ID':<10} {'DATE':<12} {'TIME':<8} {'STATUS':<10} MESSAGE")
    for alarm_id, record in alarms:
        message = record["message"].replace("\n", " ")
        print(
            f"{alarm_id:<10} {record['date']:<12} {record['time']:<8} "
            f"{record['status']:<10} {message}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "add":
            alarm_id, record = create_alarm(
                args.data_file, args.date, args.time, args.message
            )
            local_time = datetime.fromisoformat(record["scheduled_at"])
            print(f"Created alarm {alarm_id} for {local_time:%d-%m-%Y %H:%M}.")
        elif args.command == "list":
            _print_alarms(list_alarms(args.data_file))
        elif args.command == "cancel":
            cancel_alarm(args.data_file, args.alarm_id)
            print(f"Cancelled alarm {args.alarm_id}.")
        elif args.command == "run":
            run_scheduler(args.data_file)
        return 0
    except (AlarmError, SchedulerError, StorageError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
