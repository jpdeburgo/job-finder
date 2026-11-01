"""Manage the job tracker from the command line.

Examples::

    python jobs_cli.py help                    # every command and its usage
    python jobs_cli.py list                    # newest jobs first
    python jobs_cli.py list --status emailed   # jobs you haven't acted on yet
    python jobs_cli.py show 6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba
    python jobs_cli.py applied 6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba --note "Applied via IG site"
    python jobs_cli.py skip 6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba
    python jobs_cli.py status 6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba interviewing
    python jobs_cli.py migrate seen_jobs.json          # import the old ID list
    python jobs_cli.py migrate local_firestore.json    # copy local data to Firebase

Without Firebase credentials, everything is read from and written to
local_firestore.json (see job_store.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from job_store import (
    DEFAULT_JOBS_COLLECTION,
    JOB_STATUSES,
    STATUS_APPLIED,
    STATUS_SKIPPED,
    STATUS_UNEMAILED,
    FirestoreJobStore,
    get_job_store,
)

load_dotenv()

DEFAULT_LEGACY_FILE = Path(__file__).with_name("seen_jobs.json")
Command = Callable[[FirestoreJobStore, argparse.Namespace], int]


# --- Output helpers -----------------------------------------------------------


def _fmt_time(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str) and value:
        return value[:10]
    return "-"


def _print_table(jobs: list[dict[str, Any]]) -> None:
    if not jobs:
        print("No jobs found.")
        return
    header = f"{'Job ID':<36}  {'Status':<12} {'Seen':<10} {'Posted':<10} Title"
    print(header)
    print("-" * len(header))
    for job in jobs:
        print(
            f"{str(job.get('job_id', '?')):<36}  "
            f"{str(job.get('status', '-')):<12} "
            f"{_fmt_time(job.get('last_seen_at')):<10} "
            f"{str(job.get('posted_date') or '-'):<10} "
            f"{job.get('title') or '(no details - imported ID)'}"
        )


# --- Commands -------------------------------------------------------------------


def cmd_list(store: FirestoreJobStore, args: argparse.Namespace) -> int:
    jobs = store.list_jobs(status=args.status, limit=args.limit)
    _print_table(jobs)
    if args.status is None:
        pending = sum(1 for job in jobs if job.get("status") == STATUS_UNEMAILED)
        if pending:
            print(f"\n{pending} job(s) are 'unemailed' (saved, but the digest failed to send).")
    return 0


def cmd_show(store: FirestoreJobStore, args: argparse.Namespace) -> int:
    job = store.get_job(args.job_id)
    if job is None:
        print(f"Job {args.job_id} is not in the store.", file=sys.stderr)
        return 1
    print(json.dumps(job, indent=2, sort_keys=True, default=str))
    return 0


def _set_status(store: FirestoreJobStore, job_id: str, status: str, note: str | None) -> int:
    try:
        job = store.set_status(job_id, status, note)
    except KeyError as error:
        print(error.args[0], file=sys.stderr)
        return 1
    print(f"Job {job_id} -> {status}: {job.get('title') or '(no title)'}")
    return 0


def cmd_applied(store: FirestoreJobStore, args: argparse.Namespace) -> int:
    return _set_status(store, args.job_id, STATUS_APPLIED, args.note)


def cmd_skip(store: FirestoreJobStore, args: argparse.Namespace) -> int:
    return _set_status(store, args.job_id, STATUS_SKIPPED, args.note)


def cmd_status(store: FirestoreJobStore, args: argparse.Namespace) -> int:
    return _set_status(store, args.job_id, args.status, args.note)


def cmd_migrate(store: FirestoreJobStore, args: argparse.Namespace) -> int:
    """Import an old seen_jobs.json ID list or a local_firestore.json snapshot."""
    path = Path(args.path)
    if not path.exists():
        print(f"{path} does not exist.", file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, list):  # legacy seen_jobs.json: bare job IDs
        ids = [str(item) for item in data]
        added = store.import_legacy_ids(ids)
        print(f"Imported {added} new job ID(s) from {path.name} ({len(ids) - added} already present).")
        return 0

    if isinstance(data, dict) and isinstance(data.get(DEFAULT_JOBS_COLLECTION), dict):
        documents = data[DEFAULT_JOBS_COLLECTION]
        added = store.import_documents(documents)
        print(
            f"Imported {added} job document(s) from {path.name} "
            f"({len(documents) - added} already present)."
        )
        return 0

    print(
        f"{path} is neither a list of job IDs nor a local_firestore.json file.",
        file=sys.stderr,
    )
    return 1


# --- Parser ---------------------------------------------------------------------


def build_parser() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    parser = argparse.ArgumentParser(
        prog="jobs_cli.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    commands: dict[str, argparse.ArgumentParser] = {}

    def add(name: str, help_text: str, func: Command | None) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(func=func)
        commands[name] = p
        return p

    add("help", "show every command and its usage", None)

    p = add("list", "list tracked jobs, newest first", cmd_list)
    p.add_argument("--status", choices=JOB_STATUSES)
    p.add_argument("--limit", type=int, default=50)

    p = add("show", "print one job's full record", cmd_show)
    p.add_argument("job_id")

    p = add("applied", "mark a job as applied", cmd_applied)
    p.add_argument("job_id")
    p.add_argument("--note")

    p = add("skip", "mark a job as skipped (not applying)", cmd_skip)
    p.add_argument("job_id")
    p.add_argument("--note")

    p = add("status", "set any status", cmd_status)
    p.add_argument("job_id")
    p.add_argument("status", choices=JOB_STATUSES)
    p.add_argument("--note")

    p = add("migrate", "import seen_jobs.json IDs or a local_firestore.json file", cmd_migrate)
    p.add_argument("path", nargs="?", default=str(DEFAULT_LEGACY_FILE))

    return parser, commands


def print_help(parser: argparse.ArgumentParser, commands: dict[str, argparse.ArgumentParser]) -> None:
    print(parser.format_help().rstrip())
    print("\nCommands:")
    for name, subparser in commands.items():
        usage = " ".join(subparser.format_usage().replace("usage: ", "").split())
        print(f"\n  {name:<9}{subparser.description}")
        print(f"           {usage}")
    print(f"\nStatuses: {', '.join(JOB_STATUSES)}")


def main(argv: list[str] | None = None, store: FirestoreJobStore | None = None) -> int:
    parser, commands = build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "help"):
        print_help(parser, commands)
        return 0
    if store is None:
        # Quiet mode: the per-call "[local firestore] ..." trace is for the
        # search script; here one line saying which database is enough.
        store = get_job_store(verbose=False)
        print(f"# {store.description}", file=sys.stderr)
    return args.func(store, args)


if __name__ == "__main__":
    sys.exit(main())
