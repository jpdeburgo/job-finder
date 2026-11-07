#!/usr/bin/env python3
"""Update the project from a zip of it, such as one you downloaded after sharing
an archive.py zip.

    python3 apply_update.py               # newest project zip in Downloads; apply what changed
    python3 apply_update.py --dry-run     # show what would change, change nothing
    python3 apply_update.py --all         # make the project match the zip exactly
    python3 apply_update.py --zip ~/Downloads/job-finder-20261107-160000.zip
    python3 apply_update.py --candidates  # list the project zips found, newest first
    python3 apply_update.py --undo        # put back what the last update changed

Finding the zip. Your Downloads folder is searched for the most recently
downloaded zip that contains this project (backend/job_search.py), whatever it
is called: browsers rename repeat downloads ("... (1).zip"), and Safari
unzips downloads into a folder, so folders count too. Unfinished downloads
(.crdownload, .part) and broken zips are skipped. The chosen zip is shown,
and nothing changes until you confirm.

What gets updated:

* Changed files (default): only what the zip changed. archive.py leaves the
  zip you shared in the project root, so that zip tells the update's changes
  apart from edits you made afterwards. A file changed in the zip is updated
  (or added, or deleted). A file only you changed is left alone. A file you
  both changed is a conflict: yours is kept, and the zip's version is saved
  next to the backup for comparison. Use --force to take the zip's version.
  Without an earlier archive to compare against, every file that differs from
  the zip is updated and nothing is deleted.
* All the code (--all): the project ends up matching the zip exactly. Every
  file in it is written, and project files that aren't in it are deleted.

Never touched: secrets, dependencies, and build output (the same list
archive.py leaves out, so .env, credentials.json, node_modules, .git, ...),
and your job-tracking data (backend/local_firestore.json). Add more with
--keep.

Every file that is overwritten or deleted is copied to
.update-backups/<timestamp>/ first, and --undo restores the latest update.

Standard library only, so it runs with any Python 3 and no virtualenv.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable

import archive

# A zip or folder is this project if it has this file (at its top level or
# under one folder).
PROJECT_MARKER = "backend/job_search.py"
# Your data, not code: never overwritten or deleted. Matched against the
# path relative to the project root.
PROTECTED_PATHS = ("backend/local_firestore.json",)
BACKUP_DIR_NAME = ".update-backups"
BACKUP_RECORD = "backup.json"
# Changing these means reinstalling dependencies.
DEPENDENCY_FILES = {
    "frontend/package.json": "cd frontend && npm install",
    "frontend/package-lock.json": "cd frontend && npm install",
    "backend/Pipfile": "cd backend && pipenv install --dev",
    "backend/Pipfile.lock": "cd backend && pipenv install --dev",
}

ADD, MODIFY, DELETE = "add", "modify", "delete"


class UpdateError(Exception):
    """Something the user needs to fix (no zip found, unreadable zip, ...)."""


# --- Snapshots: a project's files, from a zip, a folder, or the project itself -------------


@dataclass
class Snapshot:
    """Every project file in a zip or folder: relative path -> contents."""

    source: Path
    files: dict[str, bytes]
    executable: set[str] = field(default_factory=set)


def _is_kept_out(relative: str, keep: Iterable[str] = ()) -> bool:
    """True for paths an update must never write or delete."""
    parts = PurePosixPath(relative).parts
    if any(archive.is_excluded(part) for part in parts):
        return True
    if parts and parts[0] == BACKUP_DIR_NAME:
        return True
    return any(fnmatch.fnmatch(relative, pattern) for pattern in (*PROTECTED_PATHS, *keep))


def _safe_relative(name: str) -> str | None:
    """The zip entry as a clean relative path, or None if it tries to escape."""
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return None
    if ":" in path.parts[0]:  # a Windows drive ("C:")
        return None
    return path.as_posix()


def _zip_prefix(names: Iterable[str]) -> str | None:
    """The folder the project sits in inside the zip ("" at the top level), or
    None if the zip doesn't hold the project."""
    prefixes = [
        name[: -len(PROJECT_MARKER)]
        for name in names
        if name.endswith(PROJECT_MARKER)
        and (name == PROJECT_MARKER or name[: -len(PROJECT_MARKER)].endswith("/"))
        and not any(archive.is_excluded(part) for part in PurePosixPath(name).parts)
    ]
    return min(prefixes, key=len) if prefixes else None


def _folder_root(folder: Path) -> Path | None:
    """The project inside a folder: the folder itself or one level down."""
    if (folder / PROJECT_MARKER).is_file():
        return folder
    try:
        children = sorted(child for child in folder.iterdir() if child.is_dir())
    except OSError:
        return None
    return next((child for child in children if (child / PROJECT_MARKER).is_file()), None)


def read_zip(path: Path, keep: Iterable[str] = ()) -> Snapshot:
    try:
        with zipfile.ZipFile(path) as zipped:
            infos = [info for info in zipped.infolist() if not info.is_dir()]
            prefix = _zip_prefix(info.filename for info in infos)
            if prefix is None:
                raise UpdateError(f"{path} doesn't contain this project (no {PROJECT_MARKER}).")
            files: dict[str, bytes] = {}
            executable: set[str] = set()
            for info in infos:
                if not info.filename.startswith(prefix):
                    continue
                relative = _safe_relative(info.filename[len(prefix):])
                if relative is None or _is_kept_out(relative, keep):
                    continue
                files[relative] = zipped.read(info)
                if (info.external_attr >> 16) & 0o111:
                    executable.add(relative)
    except zipfile.BadZipFile as error:
        raise UpdateError(f"{path} isn't a readable zip ({error}); download it again.") from error
    return Snapshot(path, files, executable)


def read_folder(folder: Path, keep: Iterable[str] = ()) -> Snapshot:
    """Every project file under ``folder`` (skipping what archive.py skips)."""
    files: dict[str, bytes] = {}
    executable: set[str] = set()
    for file in archive.iter_files(folder):
        relative = file.relative_to(folder).as_posix()
        if _is_kept_out(relative, keep):
            continue
        files[relative] = file.read_bytes()
        if os.access(file, os.X_OK):
            executable.add(relative)
    return Snapshot(folder, files, executable)


def read_source(path: Path, keep: Iterable[str] = ()) -> Snapshot:
    """A downloaded zip, or a folder a browser unzipped it into."""
    if path.is_dir():
        root = _folder_root(path)
        if root is None:
            raise UpdateError(f"{path} doesn't contain this project (no {PROJECT_MARKER}).")
        return read_folder(root, keep)
    if not path.is_file():
        raise UpdateError(f"{path} doesn't exist.")
    return read_zip(path, keep)


# --- Finding the download ------------------------------------------------------------------


def downloads_folders() -> list[Path]:
    """Where browsers save downloads: XDG_DOWNLOAD_DIR on Linux, else ~/Downloads."""
    home = Path.home()
    folders = []
    user_dirs = home / ".config" / "user-dirs.dirs"
    if user_dirs.is_file():
        for line in user_dirs.read_text(errors="replace").splitlines():
            if line.startswith("XDG_DOWNLOAD_DIR="):
                value = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(home))
                folders.append(Path(value))
    folders.append(home / "Downloads")
    unique = []
    for folder in folders:
        if folder.is_dir() and folder.resolve() not in {f.resolve() for f in unique}:
            unique.append(folder)
    return unique


@dataclass(frozen=True)
class Candidate:
    path: Path
    modified: float

    @property
    def kind(self) -> str:
        return "folder" if self.path.is_dir() else "zip"


def _holds_project(path: Path, skip: set[Path]) -> bool:
    if path.is_dir():
        found = _folder_root(path)
        # Not the project being updated (it may live in Downloads itself).
        return found is not None and found.resolve() not in skip
    try:
        with zipfile.ZipFile(path) as zipped:
            return _zip_prefix(zipped.namelist()) is not None
    except (zipfile.BadZipFile, OSError):
        return False  # a broken or half-written download


def find_candidates(folders: Iterable[Path], exclude: Iterable[Path] = ()) -> list[Candidate]:
    """Project zips (and unzipped folders) in ``folders``, newest first."""
    skip = {path.resolve() for path in exclude}
    found = []
    for folder in folders:
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            is_zip = entry.is_file() and entry.suffix.lower() == ".zip"
            if not (is_zip or entry.is_dir()) or entry.resolve() in skip:
                continue
            if _holds_project(entry, skip):
                found.append(Candidate(entry, entry.stat().st_mtime))
    return sorted(found, key=lambda candidate: candidate.modified, reverse=True)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _difference_count(a: Snapshot, b: Snapshot) -> int:
    return sum(1 for path in a.files.keys() | b.files.keys() if a.files.get(path) != b.files.get(path))


def choose_base(
    root: Path, update: Snapshot, keep: Iterable[str] = ()
) -> tuple[Snapshot, int] | None:
    """The archive in the project root the update was most likely made from.

    archive.py writes its zips to the project root. The one you shared
    differs from the update only by the update's changes, so the closest one
    wins (newest on a tie). Returns ``(snapshot, differences)``.
    """
    update_digest = _file_digest(update.source) if update.source.is_file() else None
    best: tuple[int, float, Snapshot] | None = None
    for path in root.glob("*.zip"):
        if update_digest and _file_digest(path) == update_digest:
            continue  # the update itself, saved into the project
        try:
            snapshot = read_zip(path, keep)
        except UpdateError:
            continue
        differences = _difference_count(snapshot, update)
        key = (differences, -path.stat().st_mtime)
        if best is None or key < (best[0], best[1]):
            best = (differences, -path.stat().st_mtime, snapshot)
    return (best[2], best[0]) if best else None


# --- Planning ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    path: str
    action: str  # add | modify | delete
    # For conflicts: what each side did, e.g. "changed in the zip; you deleted it".
    note: str = ""


@dataclass
class Plan:
    changes: list[Change] = field(default_factory=list)
    # Changed in the zip and by you: kept as yours unless --force.
    conflicts: list[Change] = field(default_factory=list)
    # Files you changed (or added) that the zip didn't: left alone.
    local_only: list[str] = field(default_factory=list)
    # Files already matching the zip.
    unchanged: int = 0

    def paths(self, action: str) -> list[str]:
        return [change.path for change in self.changes if change.action == action]


def plan_update(
    local: Snapshot, update: Snapshot, base: Snapshot | None = None, *, mirror: bool = False,
    force: bool = False,
) -> Plan:
    """Work out what to add, overwrite, and delete.

    ``mirror`` (--all): make the project match ``update`` exactly.
    With ``base``: apply only what changed between ``base`` and ``update``.
    Without: write every file that differs from ``update``; delete nothing.
    """
    plan = Plan()
    loc, upd = local.files, update.files

    def change(path: str) -> Change:
        if path not in upd:
            return Change(path, DELETE)
        return Change(path, MODIFY if path in loc else ADD)

    if mirror or base is None:
        for path in sorted(loc.keys() | upd.keys()):
            if loc.get(path) == upd.get(path):
                plan.unchanged += 1
            elif path in upd or mirror:
                plan.changes.append(change(path))
            else:
                plan.local_only.append(path)
        return plan

    old = base.files
    for path in sorted(loc.keys() | upd.keys() | old.keys()):
        before, incoming, mine = old.get(path), upd.get(path), loc.get(path)
        if mine == incoming:
            if mine is not None:
                plan.unchanged += 1
        elif before == incoming:
            plan.local_only.append(path)  # only you changed it
        elif mine == before or force:
            plan.changes.append(change(path))
        else:
            theirs = "added" if before is None else "deleted" if incoming is None else "changed"
            yours = "added" if before is None else "deleted" if mine is None else "changed"
            conflict = change(path)
            plan.conflicts.append(
                Change(conflict.path, conflict.action, f"{theirs} in the zip; you {yours} it")
            )
    return plan


# --- Applying and undoing --------------------------------------------------------------------


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes, executable: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.update-tmp")
    temporary.write_bytes(data)
    if path.exists():
        shutil.copymode(path, temporary)
    if executable:
        temporary.chmod(temporary.stat().st_mode | 0o111)
    temporary.replace(path)


def _remove(root: Path, relative: str) -> None:
    path = root / relative
    path.unlink(missing_ok=True)
    # Tidy up folders the update emptied.
    parent = path.parent
    while parent != root and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def apply_plan(root: Path, plan: Plan, update: Snapshot, now: datetime | None = None) -> Path:
    """Back up, then apply ``plan``. Returns the backup folder."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup = root / BACKUP_DIR_NAME / stamp
    suffix = 1
    while backup.exists():
        suffix += 1
        backup = root / BACKUP_DIR_NAME / f"{stamp}-{suffix}"
    (backup / "files").mkdir(parents=True)

    for change in plan.changes:
        if change.action in (MODIFY, DELETE):
            target = backup / "files" / change.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / change.path, target)
    # The zip's version of each conflict, to compare with yours.
    for conflict in plan.conflicts:
        if conflict.path in update.files:
            target = backup / "incoming" / conflict.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(update.files[conflict.path])

    record = {
        "source": str(update.source),
        "applied_at": datetime.now().isoformat(timespec="seconds"),
        "backed_up": [c.path for c in plan.changes if c.action in (MODIFY, DELETE)],
        "added": [c.path for c in plan.changes if c.action == ADD],
        # What the update wrote, so --undo can tell if you've edited it since.
        "written": {
            c.path: _sha(update.files[c.path]) for c in plan.changes if c.action != DELETE
        },
        "conflicts": [c.path for c in plan.conflicts],
    }
    (backup / BACKUP_RECORD).write_text(json.dumps(record, indent=2) + "\n")

    for change in plan.changes:
        if change.action == DELETE:
            _remove(root, change.path)
        else:
            _write(root / change.path, update.files[change.path], change.path in update.executable)
    return backup


def _latest_backup(root: Path) -> Path | None:
    folder = root / BACKUP_DIR_NAME
    if not folder.is_dir():
        return None
    for backup in sorted(folder.iterdir(), reverse=True):
        record = backup / BACKUP_RECORD
        if record.is_file() and "undone_at" not in json.loads(record.read_text()):
            return backup
    return None


def undo(root: Path, force: bool = False) -> int:
    backup = _latest_backup(root)
    if backup is None:
        print("Nothing to undo: no update has been applied here (or it was already undone).")
        return 1
    record = json.loads((backup / BACKUP_RECORD).read_text())
    written = record.get("written", {})
    skipped = []

    def edited_since(relative: str) -> bool:
        path = root / relative
        expected = written.get(relative)
        return expected is not None and path.is_file() and _sha(path.read_bytes()) != expected

    for relative in record["added"]:
        if edited_since(relative) and not force:
            skipped.append(relative)
        else:
            _remove(root, relative)
    for relative in record["backed_up"]:
        if edited_since(relative) and not force:
            skipped.append(relative)
            continue
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup / "files" / relative, target)

    record["undone_at"] = datetime.now().isoformat(timespec="seconds")
    (backup / BACKUP_RECORD).write_text(json.dumps(record, indent=2) + "\n")
    restored = len(record["added"]) + len(record["backed_up"]) - len(skipped)
    print(f"Undid the update from {record['source']} ({restored} file(s) put back).")
    if skipped:
        print("Left alone because you've edited them since (use --undo --force to revert anyway):")
        for relative in skipped:
            print(f"  {relative}")
    return 0


# --- Command line --------------------------------------------------------------------------


def _when(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def print_plan(plan: Plan, *, mirror: bool, has_base: bool) -> None:
    labels = ((ADD, "New", "+"), (MODIFY, "Updated", "~"), (DELETE, "Deleted", "-"))
    for action, label, mark in labels:
        paths = plan.paths(action)
        if paths:
            print(f"\n{label} ({len(paths)}):")
            for path in paths:
                print(f"  {mark} {path}")
    if plan.conflicts:
        print(f"\nConflicts: changed in the zip and by you; keeping yours ({len(plan.conflicts)}):")
        for conflict in plan.conflicts:
            print(f"  ! {conflict.path} ({conflict.note})")
        print("  The zip's versions are saved in the backup folder to compare; "
              "--force takes them instead.")
    if plan.local_only:
        reason = (
            "changed only by you" if has_base and not mirror
            else "not in the zip"
        )
        print(f"\nLeft alone, {reason} ({len(plan.local_only)}):")
        for path in plan.local_only[:15]:
            print(f"  = {path}")
        if len(plan.local_only) > 15:
            print(f"  ... and {len(plan.local_only) - 15} more")
    print(f"\n{len(plan.changes)} file(s) to change, {plan.unchanged} already up to date.")


def _confirm(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--zip", type=Path, metavar="PATH",
                        help="zip (or unzipped folder) to update from, instead of the newest download")
    parser.add_argument("--downloads", type=Path, action="append", metavar="DIR",
                        help="folder to look for downloads in (default: your Downloads folder); repeatable")
    parser.add_argument("--all", action="store_true",
                        help="make the project match the zip exactly: write every file, delete files not in it")
    parser.add_argument("--dry-run", action="store_true", help="show what would change and exit")
    parser.add_argument("--yes", "-y", action="store_true", help="don't ask before changing files")
    parser.add_argument("--force", action="store_true",
                        help="take the zip's version of conflicting files (or, with --undo, revert files edited since)")
    parser.add_argument("--base", type=Path, metavar="ZIP",
                        help="the zip the update was made from (default: the closest archive in the project root)")
    parser.add_argument("--no-base", action="store_true",
                        help="don't compare with an earlier archive: update every file that differs")
    parser.add_argument("--keep", action="append", default=[], metavar="PATTERN",
                        help="another path pattern never to touch, e.g. 'alignerr.txt' (repeatable)")
    parser.add_argument("--candidates", action="store_true", help="list the project zips found and exit")
    parser.add_argument("--undo", action="store_true", help="restore the files the last update changed")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent,
                        help="project directory to update (default: this script's directory)")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not (root / PROJECT_MARKER).is_file():
        print(f"{root} isn't the project (no {PROJECT_MARKER}).", file=sys.stderr)
        return 1
    if args.undo:
        return undo(root, force=args.force)

    try:
        if args.zip:
            source = args.zip.expanduser().resolve()
        else:
            folders = [f.expanduser() for f in args.downloads] if args.downloads else downloads_folders()
            candidates = find_candidates(folders, exclude=[root])
            if args.candidates:
                if not candidates:
                    print(f"No project zips in {', '.join(map(str, folders)) or 'your Downloads folder'}.")
                for index, candidate in enumerate(candidates):
                    mark = "->" if index == 0 else "  "
                    print(f"{mark} {_when(candidate.modified)}  {candidate.kind:<6}  {candidate.path}")
                return 0
            if not candidates:
                searched = ", ".join(str(folder) for folder in folders) or "~/Downloads (missing)"
                raise UpdateError(
                    f"No zip containing this project was found in {searched}. "
                    "Pass it with --zip PATH, or point --downloads at the folder it's in."
                )
            source = candidates[0].path

        update = read_source(source, args.keep)
        print(f"Update: {source}")
        print(f"        downloaded {_when(source.stat().st_mtime)}, {len(update.files)} project files")

        local = read_folder(root, args.keep)
        base: Snapshot | None = None
        if args.all or args.no_base:
            pass
        elif args.base:
            base = read_source(args.base.expanduser().resolve(), args.keep)
            print(f"Compared with: {args.base}")
        else:
            chosen = choose_base(root, update, args.keep)
            if chosen:
                base, differences = chosen
                print(f"Compared with: {base.source.name} in the project (the archive it was made "
                      f"from; {differences} file(s) differ)")
            else:
                print("No earlier archive in the project to compare with, so your own edits can't be "
                      "told apart from the zip's:\nevery file that differs from the zip will be "
                      "updated (after a backup), and nothing will be deleted.")
    except UpdateError as error:
        print(error, file=sys.stderr)
        return 1

    plan = plan_update(local, update, base, mirror=args.all, force=args.force)
    print_plan(plan, mirror=args.all, has_base=base is not None)

    if not plan.changes:
        print("Nothing to update." if not plan.conflicts else "Nothing else to update.")
        return 0
    if args.dry_run:
        print("Dry run: nothing was changed.")
        return 0
    if not args.yes and not _confirm(f"Apply {len(plan.changes)} change(s) to {root}?"):
        print("Cancelled; nothing was changed.")
        return 1

    backup = apply_plan(root, plan, update)
    print(f"\nUpdated {len(plan.changes)} file(s). Backup: {backup.relative_to(root)} "
          "(python3 apply_update.py --undo to revert).")
    reinstall = sorted({DEPENDENCY_FILES[c.path] for c in plan.changes if c.path in DEPENDENCY_FILES})
    if reinstall:
        print("Dependencies changed; run:")
        for command in reinstall:
            print(f"  {command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
