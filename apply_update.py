#!/usr/bin/env python3
"""Update the project from a download of it: the chat's "all code" or "changed
files" bundles (e.g. "4411874d-..._4_a_changed_files"), or an archive.py zip.

    python3 apply_update.py               # newest project zip in Downloads; apply what changed
    python3 apply_update.py --dry-run     # show what would change, change nothing
    python3 apply_update.py --all         # take every file from the zip, your edits included
    python3 apply_update.py --zip ~/Downloads/job-finder-20261107-160000.zip
    python3 apply_update.py --candidates  # list the project zips found, newest first
    python3 apply_update.py --undo        # put back what the last update changed

Finding the zip. Your Downloads folder is searched for the most recently
downloaded zip that holds this project's files, whatever it is called:
browsers rename repeat downloads ("... (1).zip"), and Safari unzips downloads
into a folder, so folders count too.

What it does depends on what's in the download:

* changes.diff at its root (the chat's "changed files"): apply just the
  diff. The files it adds, changes, renames, and deletes are updated;
  everything else stays as it is. If you've edited a file, the diff is
  applied to your version, so your edits are kept when they don't overlap.
* The whole project, no diff (the chat's "all code", or an archive.py zip):
  replace the entire project. Files it doesn't have are deleted, except ones
  you created and ones git ignores.
* Some files, no diff: add and update those files; nothing is deleted. Unfinished downloads
(.crdownload, .part) and broken zips are skipped. The chosen zip is shown,
and nothing changes until you confirm.

What gets updated:

* Changed files (default): your own edits are kept, everything else is
  brought up to date. Each file is compared with earlier copies of the
  project: the archives archive.py left in the project root (including the
  one you shared), updates applied here before, and older project zips in
  Downloads (an earlier update, applied or not). If your file matches one of
  those copies, you haven't edited it, so it takes the zip's version (or is
  added, or deleted). If every copy has the zip's version, any difference is
  your own edit and is kept. Otherwise it's possibly yours (or from an update
  that's no longer in Downloads): you're asked whether to take the zip's
  version (--force: yes, --keep-mine: no, --yes alone: keeps yours).
  With no earlier copies at all, every file that differs from the zip is
  updated and nothing is deleted.
* All the code (--all): every file takes the zip's version, your edits
  included, and files the zip removed are deleted. Files you created yourself
  (never in any earlier copy of the project) are kept.

Safety: an update that would delete more than 5 files stops unless you add
--allow-deletes (that many usually means an older copy of the project was
picked). Folders in Downloads that someone has worked in (.git, node_modules,
__pycache__, ...) are never taken for a download. After applying, every
changed file is checked against the zip.

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
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

import archive

# A zip or folder is this project if it has this file (at its top level or
# under one folder).
PROJECT_MARKER = "backend/job_search.py"
# Your data, not code: never overwritten or deleted. Matched against the
# path relative to the project root. Includes the personal files archive.py
# leaves out (alignerr.txt): reading the project skips them (archive.iter_files),
# so without this a download that has one would look like a new file and
# replace yours.
PROTECTED_PATHS = ("backend/local_firestore.json", *archive.PERSONAL_FILES)
BACKUP_DIR_NAME = ".update-backups"
BACKUP_RECORD = "backup.json"
# Each applied update is kept here, inside its backup folder, so the next
# update can tell the files it wrote apart from your edits.
APPLIED_COPY = "applied.zip"
# Changing these means reinstalling dependencies.
DEPENDENCY_FILES = {
    "frontend/package.json": "cd frontend && npm install",
    "frontend/package-lock.json": "cd frontend && npm install",
    "backend/Pipfile": "cd backend && pipenv install --dev",
    "backend/Pipfile.lock": "cd backend && pipenv install --dev",
}

ADD, MODIFY, MERGE, DELETE = "add", "modify", "merge", "delete"
# An update that would delete more files than this is probably an older copy
# of the project (or the wrong zip); it needs --allow-deletes.
MAX_DELETES = 5


class UpdateError(Exception):
    """Something the user needs to fix (no zip found, unreadable zip, ...)."""


# --- Snapshots: a project's files, from a zip, a folder, or the project itself -------------


@dataclass
class Snapshot:
    """Every project file in a zip or folder: relative path -> contents."""

    source: Path
    files: dict[str, bytes]
    executable: set[str] = field(default_factory=set)
    # Only some of the project's files (a "changed files" bundle): a file that
    # isn't in it is unchanged, not deleted.
    partial: bool = False
    # The bundle's changes.diff, parsed; None when it has none.
    diff: "list[FileDiff] | None" = None
    # Changed files as they were before the diff (None: didn't exist yet).
    base: dict[str, bytes | None] = field(default_factory=dict)
    diff_text: str = ""

    @property
    def kind(self) -> str:
        """"diff" (changed files + changes.diff), "full" (all the code), or
        "partial" (changed files without a diff)."""
        if self.diff is not None:
            return "diff"
        return "partial" if self.partial else "full"


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


def _bundle_prefix(
    names: Iterable[str],
    project_paths: Iterable[str] = (),
    read_text: "Callable[[str], str] | None" = None,
) -> str | None:
    """The folder the project's files sit under in a bundle ("" at the top),
    or None if the bundle doesn't hold this project.

    A bundle holds the project if it has ``PROJECT_MARKER`` (a full copy) or if
    most of its files are at paths the project has: a "changed files" bundle
    may not include backend/job_search.py at all.
    """
    names = [name for name in names if not name.endswith("/")]
    known = set(project_paths)
    prefixes = {""}
    for name in names:
        parts = name.split("/")
        for depth in (1, 2):
            if len(parts) > depth:
                prefixes.add("/".join(parts[:depth]) + "/")
    best: tuple[int, int, int, int, str] | None = None
    for prefix in prefixes:
        inside = [name[len(prefix):] for name in names if name.startswith(prefix)]
        inside = [path for path in inside if path and not _is_kept_out(path)]
        if not inside:
            continue
        # A "changed files" download: changes.diff at its root, next to the files.
        has_diff = any(path in DIFF_FILE_NAMES for path in inside)
        has_marker = PROJECT_MARKER in inside
        matches = sum(1 for path in inside if path in known)
        if has_diff and not has_marker and matches == 0 and read_text is not None:
            # Every file in it may be new; the diff also names files it changes,
            # renames, or deletes, which this project should have.
            diff_name = next(path for path in inside if path in DIFF_FILE_NAMES)
            try:
                named = {p for c in parse_diff(read_text(prefix + diff_name)) for p in (c.old_path, c.new_path) if p}
            except (OSError, KeyError, ValueError):
                named = set()
            matches = len(named & known)
        if has_diff and not has_marker and matches == 0:
            continue  # some other project's diff
        if not has_diff and not has_marker and (matches == 0 or matches < 0.4 * len(inside)):
            continue
        key = (int(has_diff), int(has_marker), matches, -len(prefix), prefix)
        if best is None or key > best:
            best = key
    return best[4] if best else None


def _finish_bundle(snapshot: Snapshot, name: str, project_paths: set[str]) -> Snapshot:
    """Read the bundle's changes.diff, if it has one, and decide what it is."""
    diff_name = next((n for n in DIFF_FILE_NAMES if n in snapshot.files), None)
    if diff_name is None:
        snapshot.partial = bundle_is_partial(name, snapshot.files, project_paths)
        return snapshot
    text = snapshot.files.pop(diff_name).decode("utf-8", "surrogateescape")
    snapshot.diff_text = text
    snapshot.diff = parse_diff(text)
    # The changed files may sit next to changes.diff or in a folder beside it
    # (the chat's bundles use files/<path>): find them by the diff's paths.
    root = _diff_files_root(snapshot.files, snapshot.diff)
    if root:
        snapshot.files = {p[len(root):]: d for p, d in snapshot.files.items() if p.startswith(root)}
        snapshot.executable = {p[len(root):] for p in snapshot.executable if p.startswith(root)}
    snapshot.partial = True
    snapshot.base = diff_base_versions(snapshot.diff, snapshot.files)
    for change in snapshot.diff:
        if change.new_mode == "100755" and change.new_path:
            snapshot.executable.add(change.new_path)
    return snapshot


def _diff_files_root(files: dict[str, bytes], diff: list["FileDiff"]) -> str:
    """The folder in a bundle that holds the diff's files ("" or e.g. "files/")."""
    wanted = [c.new_path for c in diff if c.status != DELETED and c.new_path and not c.binary]
    if not wanted:
        return ""
    roots = {""} | {path.split("/", 1)[0] + "/" for path in files if "/" in path}

    def found(root: str) -> int:
        return sum(1 for path in wanted if root + path in files)

    best = max(sorted(roots), key=lambda root: (found(root), root == ""))
    return best if found(best) else ""


def bundle_is_partial(name: str, files: Iterable[str], project_paths: Iterable[str] = ()) -> bool:
    """Whether a bundle holds only some of the project's files.

    The chat's downloads say so in their names ("..._a_changed_files",
    "..._a_all_code"); otherwise a bundle missing the marker, or most of the
    project's files, is partial.
    """
    lowered = name.lower()
    if "changed" in lowered:
        return True
    if re.search(r"all[_ -]?code|all[_ -]?files", lowered):
        return False
    paths = set(files)
    project = set(project_paths)
    if PROJECT_MARKER not in paths:
        return True
    return bool(project) and len(paths & project) < 0.6 * len(project)


def _folder_files(folder: Path, limit: int = 20000) -> list[str]:
    files = []
    for file in archive.iter_files(folder):
        files.append(file.relative_to(folder).as_posix())
        if len(files) >= limit:
            break
    return files


def _folder_root(folder: Path, project_paths: Iterable[str] = ()) -> Path | None:
    """Where the project's files are inside a folder (itself, or a folder in it)."""
    prefix = _bundle_prefix(
        _folder_files(folder), project_paths,
        lambda name: (folder / name).read_text(encoding="utf-8", errors="surrogateescape"),
    )
    if prefix is None:
        return None
    return folder / prefix if prefix else folder


def read_zip(path: Path, keep: Iterable[str] = (), project_paths: Iterable[str] = ()) -> Snapshot:
    project_paths = set(project_paths)
    try:
        with zipfile.ZipFile(path) as zipped:
            infos = [info for info in zipped.infolist() if not info.is_dir()]
            prefix = _bundle_prefix(
                [info.filename for info in infos], project_paths,
                lambda name: zipped.read(name).decode("utf-8", "surrogateescape"),
            )
            if prefix is None:
                raise UpdateError(f"{path} doesn't contain this project's files.")
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
    return _finish_bundle(Snapshot(path, files, executable), path.name, project_paths)


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


def read_source(path: Path, keep: Iterable[str] = (), project_paths: Iterable[str] = ()) -> Snapshot:
    """A downloaded zip, or a folder a browser unzipped it into."""
    project_paths = set(project_paths)
    if path.is_dir():
        root = _folder_root(path, project_paths)
        if root is None:
            raise UpdateError(f"{path} doesn't contain this project's files.")
        snapshot = read_folder(root, keep)
        snapshot.source = path
        return _finish_bundle(snapshot, path.name, project_paths)
    if not path.is_file():
        raise UpdateError(f"{path} doesn't exist.")
    return read_zip(path, keep, project_paths)


# --- changes.diff: what a "changed files" bundle changed ---------------------------------

# A "changed files" download has the diff of everything that changed at its root.
DIFF_FILE_NAMES = ("changes.diff",)
ADDED, DELETED, MODIFIED, RENAMED = "added", "deleted", "modified", "renamed"


@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    # (" " | "-" | "+", the line as it is in the file, newline included)
    lines: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class FileDiff:
    old_path: str | None
    new_path: str | None
    status: str = MODIFIED
    hunks: list[Hunk] = field(default_factory=list)
    binary: bool = False
    new_mode: str = ""

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""


HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _unquote_git_path(value: str) -> str:
    """git quotes paths with unusual characters: "a/caf\\303\\251.txt"."""
    if not (value.startswith('"') and value.endswith('"')):
        return value
    raw = value[1:-1]
    out = bytearray()
    index = 0
    simple = {"n": 10, "t": 9, '"': 34, "\\": 92, "a": 7, "b": 8, "f": 12, "r": 13, "v": 11}
    while index < len(raw):
        char = raw[index]
        if char == "\\" and index + 1 < len(raw):
            following = raw[index + 1]
            if following in "01234567" and index + 3 < len(raw) + 1:
                out.append(int(raw[index + 1:index + 4], 8))
                index += 4
                continue
            out.append(simple.get(following, ord(following)))
            index += 2
            continue
        out.extend(char.encode("utf-8"))
        index += 1
    return out.decode("utf-8", "surrogateescape")


def _diff_path(value: str) -> str | None:
    """A path from "--- a/x", "+++ b/x", or "rename to x" (None for /dev/null)."""
    value = value.split("\t", 1)[0].strip()
    value = _unquote_git_path(value)
    if value == "/dev/null":
        return None
    if value[:2] in ("a/", "b/"):
        value = value[2:]
    return value


def _git_header_paths(rest: str) -> tuple[str | None, str | None]:
    """Paths from "diff --git a/x b/x" (renames and odd names are fixed up later)."""
    if rest.startswith('"'):
        end = rest.index('"', 1)
        while rest[end - 1] == "\\":
            end = rest.index('"', end + 1)
        first, second = rest[:end + 1], rest[end + 2:]
        return _diff_path(first), _diff_path(second)
    half = (len(rest) - 1) // 2
    if rest[:2] == "a/" and rest[half + 1:half + 3] == "b/" and rest[2:half] == rest[half + 3:]:
        return rest[2:half], rest[half + 3:]
    first, _, second = rest.partition(" b/")
    return _diff_path(first), second or None


def parse_diff(text: str) -> list[FileDiff]:
    """Parse a git (or plain unified) diff into per-file changes."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    files: list[FileDiff] = []
    current: FileDiff | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("diff --git "):
            old, new = _git_header_paths(line[len("diff --git "):])
            current = FileDiff(old, new)
            files.append(current)
        elif line.startswith("--- ") and index + 1 < len(lines) and lines[index + 1].startswith("+++ "):
            old, new = _diff_path(line[4:]), _diff_path(lines[index + 1][4:])
            if current is None or current.hunks:
                current = FileDiff(old, new)  # a plain diff: no "diff --git" line
                files.append(current)
            current.old_path, current.new_path = old, new
            if old is None:
                current.status = ADDED
            elif new is None:
                current.status = DELETED
            index += 1
        elif current is not None and line.startswith("new file mode"):
            current.status, current.new_mode = ADDED, line.split()[-1]
        elif current is not None and line.startswith("deleted file mode"):
            current.status = DELETED
        elif current is not None and line.startswith("new mode"):
            current.new_mode = line.split()[-1]
        elif current is not None and line.startswith("rename from "):
            current.old_path, current.status = _diff_path(line[len("rename from "):]), RENAMED
        elif current is not None and line.startswith("rename to "):
            current.new_path, current.status = _diff_path(line[len("rename to "):]), RENAMED
        elif current is not None and (line.startswith("Binary files ") or line == "GIT binary patch"):
            current.binary = True
        elif current is not None and line.startswith("@@"):
            header = HUNK_HEADER.match(line)
            if header:
                old_start, old_len, new_start, new_len = header.groups()
                hunk = Hunk(int(old_start), int(old_len or 1), int(new_start), int(new_len or 1))
                current.hunks.append(hunk)
                old_seen = new_seen = 0
                while index + 1 < len(lines) and (old_seen < hunk.old_len or new_seen < hunk.new_len):
                    body = lines[index + 1]
                    tag = body[:1] or " "  # some tools strip the space of an empty context line
                    if tag == "\\":  # "\ No newline at end of file"
                        if hunk.lines:
                            previous_tag, previous = hunk.lines[-1]
                            hunk.lines[-1] = (previous_tag, previous.removesuffix("\n"))
                        index += 1
                        continue
                    if tag not in " -+":
                        break
                    hunk.lines.append((tag, body[1:] + "\n"))
                    old_seen += tag in " -"
                    new_seen += tag in " +"
                    index += 1
                if index + 1 < len(lines) and lines[index + 1].startswith("\\"):
                    previous_tag, previous = hunk.lines[-1]
                    hunk.lines[-1] = (previous_tag, previous.removesuffix("\n"))
                    index += 1
        index += 1
    return [diff for diff in files if diff.path]


def apply_hunks(content: bytes | None, hunks: list[Hunk], reverse: bool = False) -> bytes | None:
    """Apply (or undo) a file's hunks. Every context and removed line must match
    exactly, though a hunk may sit at a different line than its header says.
    Returns None when any hunk doesn't fit."""
    text = (content or b"").decode("utf-8", "surrogateescape")
    lines = text.splitlines(keepends=True)
    removed, added = ("+", "-") if reverse else ("-", "+")
    output: list[str] = []
    position = 0
    offset = 0
    for hunk in hunks:
        old = [line for tag, line in hunk.lines if tag in (" ", removed)]
        new = [line for tag, line in hunk.lines if tag in (" ", added)]
        start = hunk.new_start if reverse else hunk.old_start
        expected = (start if not old else start - 1) + offset
        fits = [
            at for at in range(position, len(lines) - len(old) + 1)
            if lines[at:at + len(old)] == old
        ]
        if not fits:
            return None
        at = min(fits, key=lambda candidate: abs(candidate - expected))
        output.extend(lines[position:at])
        output.extend(new)
        position = at + len(old)
        offset = at - (start if not old else start - 1)
    output.extend(lines[position:])
    return "".join(output).encode("utf-8", "surrogateescape")


def diff_base_versions(diff: list[FileDiff], files: dict[str, bytes]) -> dict[str, bytes | None]:
    """Each changed file as it was before the diff (None: it didn't exist),
    worked out by undoing the diff on the bundle's version."""
    base: dict[str, bytes | None] = {}
    for change in diff:
        if change.binary:
            continue
        if change.status == ADDED and change.new_path:
            base[change.new_path] = None
        elif change.status == DELETED and change.old_path:
            restored = apply_hunks(b"", change.hunks, reverse=True)
            if restored is not None:
                base[change.old_path] = restored
        elif change.new_path in files:
            after = files[change.new_path]
            before = apply_hunks(after, change.hunks, reverse=True) if change.hunks else after
            if before is not None and change.old_path:
                base[change.old_path] = before
            if change.status == RENAMED:
                base[change.new_path] = None
    return base


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


def is_working_copy(folder: Path) -> bool:
    """True when a folder has things an archive never holds (.git, node_modules,
    __pycache__, .env, ...): it's a copy someone worked in, not an unzipped
    download, even if it was touched more recently than the real download."""
    for _current, dirnames, filenames in os.walk(folder):
        if any(archive.is_excluded(name) for name in (*dirnames, *filenames)):
            return True
        if BACKUP_DIR_NAME in dirnames:
            return True
    return False


def _holds_project(path: Path, skip: set[Path], project_paths: set[str]) -> bool:
    if path.is_dir():
        found = _folder_root(path, project_paths)
        # Not the project being updated (it may live in Downloads itself), and
        # not another working copy of it.
        return found is not None and found.resolve() not in skip and not is_working_copy(found)
    try:
        with zipfile.ZipFile(path) as zipped:
            return _bundle_prefix(
                zipped.namelist(), project_paths,
                lambda name: zipped.read(name).decode("utf-8", "surrogateescape"),
            ) is not None
    except (zipfile.BadZipFile, OSError):
        return False  # a broken or half-written download


def find_candidates(
    folders: Iterable[Path], exclude: Iterable[Path] = (), project_paths: Iterable[str] = ()
) -> list[Candidate]:
    """Zips (and unzipped folders) in ``folders`` holding this project's files,
    whole or only the changed ones, newest first."""
    skip = {path.resolve() for path in exclude}
    project_paths = set(project_paths)
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
            if _holds_project(entry, skip, project_paths):
                found.append(Candidate(entry, entry.stat().st_mtime))
    return sorted(found, key=lambda candidate: candidate.modified, reverse=True)


ARCHIVE_STAMP = re.compile(r"(\d{8}-\d{6})")


def archive_stamp(path: Path) -> str | None:
    """The build time in an archive.py name ("job-finder-20261107-184628.zip")."""
    match = ARCHIVE_STAMP.search(path.name)
    return match.group(1) if match else None


def newer_named(chosen: Candidate, candidates: list[Candidate]) -> Candidate | None:
    """A candidate whose name says it was built after the chosen one, if any."""
    stamp = archive_stamp(chosen.path)
    if stamp is None:
        return None
    later = [c for c in candidates if (archive_stamp(c.path) or "") > stamp]
    return max(later, key=lambda c: archive_stamp(c.path) or "") if later else None


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _difference_count(a: Snapshot, b: Snapshot) -> int:
    return sum(1 for path in a.files.keys() | b.files.keys() if a.files.get(path) != b.files.get(path))


def _mtime(path: Path) -> float:
    return path.stat().st_mtime


def find_known_snapshots(
    root: Path, update: Snapshot, folders: Iterable[Path] = (), keep: Iterable[str] = (),
    project_paths: Iterable[str] = (),
) -> list[Snapshot]:
    """Earlier copies of the project, to tell your edits apart from old versions.

    * archives in the project root (archive.py writes them there; the one you
      shared is the copy the update was made from),
    * updates applied here before (saved in .update-backups/; undone ones
      too, since their versions weren't your edits either), and
    * project zips and unzipped folders in ``folders`` (Downloads), such as
      an earlier update, whether or not you applied it.

    Only copies from before the update was downloaded count: an archive made
    afterwards may hold edits the update doesn't know about. The update itself
    (or a copy of it) is skipped.
    """
    cutoff = _mtime(update.source)
    update_path = update.source.resolve()
    update_digest = _file_digest(update.source) if update.source.is_file() else None
    paths: list[Path] = sorted(root.glob("*.zip"))
    for record in sorted((root / BACKUP_DIR_NAME).glob(f"*/{BACKUP_RECORD}")):
        applied = record.parent / APPLIED_COPY
        if applied.is_file():
            paths.append(applied)
    project_paths = set(project_paths)
    paths += [c.path for c in find_candidates(folders, exclude=[root], project_paths=project_paths)]

    snapshots = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen or resolved == update_path or _mtime(path) > cutoff:
            continue
        seen.add(resolved)
        if update_digest and path.is_file() and _file_digest(path) == update_digest:
            continue  # a copy of the update
        try:
            snapshot = read_source(path, keep, project_paths)
        except UpdateError:
            continue
        if path.name == APPLIED_COPY:
            snapshot.partial = json.loads((path.parent / BACKUP_RECORD).read_text()).get(
                "partial", snapshot.partial
            )
        if snapshot.files != update.files:  # not another copy of the update
            snapshots.append(snapshot)
    return snapshots


# --- Planning ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    """One file to add, modify, merge, or delete. Pass content and note by
    keyword: Change(path, MERGE, content=...)."""

    path: str
    action: str  # add | modify | merge | delete
    # What to write, when it isn't the bundle's file (a merge, or a file
    # rebuilt from the diff).
    content: bytes | None = None
    # For conflicts: what each side did, e.g. "changed in the zip; you deleted it".
    note: str = ""


@dataclass
class Plan:
    changes: list[Change] = field(default_factory=list)
    # Possibly your own edits: your version matches no earlier copy, and the
    # file has changed over time, so it could also be from an update that's
    # no longer around. Kept unless you say otherwise (--force, or the prompt).
    conflicts: list[Change] = field(default_factory=list)
    # Certainly yours (the zip's version is every copy's version), or files
    # the update doesn't cover: left alone.
    local_only: list[str] = field(default_factory=list)
    # Files already matching the zip.
    unchanged: int = 0
    # Things that couldn't be done at all (reported, not applied).
    problems: list[str] = field(default_factory=list)
    # Files in a diff bundle that its changes.diff doesn't mention (not applied).
    ignored: list[str] = field(default_factory=list)
    # Files an earlier update put in the wrong place (see stray_files): deleted,
    # and kept out of the deletion limit because they're known exactly.
    cleanup: list[str] = field(default_factory=list)
    cleanup_edited: list[str] = field(default_factory=list)

    def paths(self, action: str) -> list[str]:
        return [change.path for change in self.changes if change.action == action]


def known_versions(path: str, known: list[Snapshot], update: Snapshot) -> list[bytes | None]:
    """Every version of a file that didn't come from your editing: each earlier
    copy's (a partial one only for the files it has), plus the version before
    each diff (the update's own, and earlier bundles')."""
    versions: list[bytes | None] = []
    for snapshot in known:
        if not snapshot.partial or path in snapshot.files:
            versions.append(snapshot.files.get(path))
        if path in snapshot.base:
            versions.append(snapshot.base[path])
    if path in update.base:
        versions.append(update.base[path])
    return versions


class GitIgnore:
    """Enough of .gitignore to tell which files git leaves out of a bundle."""

    def __init__(self, text: str) -> None:
        self.rules: list[tuple[str, bool, bool, bool]] = []
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line or line.startswith("#"):
                continue
            negate = line.startswith("!")
            line = line[1:] if negate else line
            line = line[1:] if line.startswith("\\") else line
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            anchored = "/" in line
            self.rules.append((line.lstrip("/"), negate, dir_only, anchored))

    def ignored(self, path: str) -> bool:
        parts = path.split("/")
        targets = [("/".join(parts[:i]), True) for i in range(1, len(parts))] + [(path, False)]
        result = False
        for pattern, negate, dir_only, anchored in self.rules:
            for target, is_dir in targets:
                if dir_only and not is_dir:
                    continue
                name = target if anchored else target.rsplit("/", 1)[-1]
                if fnmatch.fnmatchcase(name, pattern):
                    result = not negate
                    break
        return result


def _plan_from_diff(
    local: Snapshot, update: Snapshot, known: list[Snapshot], *, mirror: bool, force: bool
) -> Plan:
    """Apply just the diff: the files it adds, changes, renames, and deletes.
    Everything it doesn't mention stays as it is.

    Your file is brought up to date when it's the version before the diff or
    any other version from an earlier copy. If it isn't (your own edits, or a
    version from an update that's no longer around), the diff is applied to
    your version: if every change fits, that's a merge that keeps your edits.
    If not, it's possibly yours and you're asked (--force: take the bundle's).
    """
    plan = Plan()
    loc = local.files
    handled: set[str] = set()

    def vouched(path: str, mine: bytes | None) -> bool:
        return mine in known_versions(path, known, update)

    def ask(path: str, action: str, note: str, content: bytes | None = None) -> None:
        if force:
            plan.changes.append(Change(path, action, content=content))
        else:
            plan.conflicts.append(Change(path, action, content=content, note=note))

    for change in update.diff or []:
        if change.status == DELETED:
            path = change.old_path or ""
            handled.add(path)
            if _is_kept_out(path) or path not in loc:
                continue
            if mirror or vouched(path, loc[path]):
                plan.changes.append(Change(path, DELETE))
            else:
                ask(path, DELETE, "deleted in the update; changed on your side")
            continue

        path = change.new_path or ""
        handled.add(path)
        if _is_kept_out(path):
            continue
        mine = loc.get(path)
        after = update.files.get(path)
        if after is None:
            # Not in the bundle (say, a binary file): rebuild it from the diff.
            source = b"" if change.status == ADDED else loc.get(change.old_path or path)
            after = apply_hunks(source, change.hunks) if source is not None and not change.binary else None
            if after is None:
                plan.problems.append(f"{path}: changed in the diff but not in the bundle, and the "
                                     "diff doesn't fit your version; not updated")
                continue
        if mine == after:
            plan.unchanged += 1
        elif mirror or vouched(path, mine) or (mine is None and change.status in (ADDED, RENAMED)):
            plan.changes.append(Change(path, MODIFY if mine is not None else ADD, content=after))
        else:
            merged = None
            if mine is not None and change.status in (MODIFIED, RENAMED) and change.hunks:
                merged = apply_hunks(mine, change.hunks)
            if merged is not None:
                plan.changes.append(Change(path, MERGE, content=merged))
            else:
                ask(path, MODIFY if mine is not None else ADD,
                    "changed in the update; " + ("deleted" if mine is None else "changed") + " on your side",
                    content=after)

        old = change.old_path
        if change.status == RENAMED and old and old != path and old in loc and not _is_kept_out(old):
            handled.add(old)
            if mirror or vouched(old, loc[old]):
                plan.changes.append(Change(old, DELETE, note=f"renamed to {path}"))
            else:
                ask(old, DELETE, f"renamed to {path} in the update; changed on your side")

    # The diff says what changed; anything else in the bundle isn't applied.
    plan.ignored = sorted(set(update.files) - handled)
    return plan


def _never_changed(path: str, incoming: bytes, known: list[Snapshot]) -> bool:
    """True when the file has had the zip's version all along: in every full
    copy of the project (so it existed, unchanged, since the oldest one) and
    in every partial one that has it. Then a different local version can only
    be your own edit; it can't be from an update that's missing."""
    full = [snapshot for snapshot in known if not snapshot.partial]
    partial = [snapshot.files[path] for snapshot in known if snapshot.partial and path in snapshot.files]
    return (
        bool(full)
        and all(snapshot.files.get(path) == incoming for snapshot in full)
        and all(version == incoming for version in partial)
    )


def plan_update(
    local: Snapshot, update: Snapshot, known: list[Snapshot] | None = None, *,
    mirror: bool = False, force: bool = False,
) -> Plan:
    """Work out what to add, overwrite, and delete.

    ``mirror`` (--all): every file takes the update's version; files the
    update removed (ones an earlier copy had) are deleted, files you created
    are kept.

    Otherwise each file is compared with the ``known`` earlier copies of the
    project. If your copy matches one of them (or is missing where one of them
    lacks the file), you haven't edited it, so it takes the update's version,
    including deletion. If it matches none, it has your edits and is kept:
    reported as a conflict when the update's version is new too, else as
    changed only by you. With no earlier copies, every file that differs from
    the update is written and nothing is deleted.

    A partial update (a "changed files" bundle) only adds and updates: a file
    that isn't in it is unchanged, so nothing is ever deleted.
    """
    plan = Plan()
    loc, upd = local.files, update.files
    known = known or []

    def change(path: str) -> Change:
        if path not in upd:
            return Change(path, DELETE)
        return Change(path, MODIFY if path in loc else ADD)

    if update.diff is not None:
        return _plan_from_diff(local, update, known, mirror=mirror, force=force)

    def versions_of(path: str) -> list[bytes | None]:
        return known_versions(path, known, update)

    earlier_paths = set().union(*(s.files for s in known if not s.partial))
    # On a case-insensitive disk (macOS, Windows), "Readme.md" and "README.md"
    # are one file: writing one and deleting the other would lose it.
    incoming_lower = {path.lower(): path for path in upd}

    # A bundle of all the code comes from git, so files git ignores aren't in
    # it; that doesn't mean they should go.
    ignore = GitIgnore(
        (update.files.get(".gitignore") or local.files.get(".gitignore") or b"").decode("utf-8", "replace")
    )

    def deletable(path: str) -> bool:
        return (
            not update.partial
            and incoming_lower.get(path.lower(), path) == path
            and not ignore.ignored(path)
        )

    if update.partial:
        paths = sorted(upd)
    else:
        paths = sorted(set().union(loc, upd, *(s.files for s in known)))
    for path in paths:
        mine, incoming = loc.get(path), upd.get(path)
        versions = versions_of(path)
        if mine == incoming:
            if mine is not None:
                plan.unchanged += 1
        elif incoming is None and (not deletable(path) or path not in earlier_paths):
            if mine is not None:
                plan.local_only.append(path)  # yours, or an update can't tell
        elif mirror or not known:
            if incoming is None and not mirror:
                plan.local_only.append(path)  # without history, nothing is deleted
            else:
                plan.changes.append(change(path))
        elif mine in versions:
            plan.changes.append(change(path))  # you hadn't edited it
        elif incoming is not None and _never_changed(path, incoming, known):
            # Every copy ever seen has the zip's version, so the difference
            # can only be your own edit.
            plan.local_only.append(path)
        elif force:
            plan.changes.append(change(path))  # possibly yours; --force takes the zip's
        else:
            # Your version matches no copy: your edit, or a version from an
            # update that's no longer around. Asked about (see main).
            new_file = all(version is None for version in versions)
            theirs = "deleted" if incoming is None else "added" if new_file else "changed"
            yours = "deleted" if mine is None else "added" if new_file else "changed"
            conflict = change(path)
            plan.conflicts.append(
                Change(conflict.path, conflict.action, note=f"{theirs} in the zip; {yours} on your side")
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


def _content(change: Change, update: Snapshot) -> bytes:
    """What a change writes: a merge or rebuilt file, else the bundle's file."""
    return change.content if change.content is not None else update.files[change.path]


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
        if change.action in (MODIFY, MERGE, DELETE) and (root / change.path).exists():
            target = backup / "files" / change.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / change.path, target)
    # The zip's version of each conflict, to compare with yours.
    for conflict in plan.conflicts:
        incoming = conflict.content if conflict.content is not None else update.files.get(conflict.path)
        if incoming is not None:
            target = backup / "incoming" / conflict.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(incoming)

    record = {
        "source": str(update.source),
        "applied_at": datetime.now().isoformat(timespec="seconds"),
        "backed_up": [c.path for c in plan.changes
                      if c.action in (MODIFY, MERGE, DELETE) and (backup / "files" / c.path).exists()],
        "added": [c.path for c in plan.changes if c.action == ADD],
        # What the update wrote, so --undo can tell if you've edited it since.
        "written": {
            c.path: _sha(_content(c, update)) for c in plan.changes if c.action != DELETE
        },
        "conflicts": [c.path for c in plan.conflicts],
        "partial": update.partial,
        "kind": update.kind,
    }
    (backup / BACKUP_RECORD).write_text(json.dumps(record, indent=2) + "\n")
    applied = backup / APPLIED_COPY
    with zipfile.ZipFile(applied, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for relative, data in sorted(update.files.items()):
            zipped.writestr(relative, data)
        if update.diff_text:
            zipped.writestr(DIFF_FILE_NAMES[0], update.diff_text.encode("utf-8", "surrogateescape"))
    # Dated like the download, so later updates count it as an earlier copy.
    source_time = _mtime(update.source)
    os.utime(applied, (source_time, source_time))

    for change in plan.changes:
        if change.action == DELETE:
            _remove(root, change.path)
        else:
            _write(root / change.path, _content(change, update), change.path in update.executable)
    return backup


def stray_files(root: Path, local: Snapshot) -> tuple[list[str], list[str]]:
    """Files an earlier update put in the wrong place, as ``(removable, edited)``.

    An older apply_update.py copied a bundle's files/ folder into the project
    as-is (files/backend/api.py next to backend/api.py). Those files are found
    from the updates' own records: added by an update, in a top-level folder
    that is otherwise not part of the project, mirroring project paths. The
    ones unchanged since are removable; ones you've edited are left alone.
    """
    added: dict[str, str | None] = {}
    for record_path in sorted((root / BACKUP_DIR_NAME).glob(f"*/{BACKUP_RECORD}")):
        record = json.loads(record_path.read_text())
        if "undone_at" in record:
            continue
        written = record.get("written", {})
        for path in record.get("added", []):
            added[path] = written.get(path)
    groups: dict[str, list[str]] = {}
    for path in added:
        if "/" in path and path in local.files:
            groups.setdefault(path.split("/", 1)[0], []).append(path)
    removable: list[str] = []
    edited: list[str] = []
    for top, paths in groups.items():
        if any(p.startswith(top + "/") and p not in added for p in local.files):
            continue  # a real folder of the project
        mirrored = [p for p in paths if p.split("/", 1)[1] in local.files]
        if len(mirrored) < 0.8 * len(paths):
            continue  # a new folder the update meant to add
        for path in paths:
            unchanged = added[path] is not None and _sha(local.files[path]) == added[path]
            (removable if unchanged else edited).append(path)
    return sorted(removable), sorted(edited)


def verify(root: Path, plan: Plan, update: Snapshot) -> list[str]:
    """Problems left after applying: files that didn't end up as the zip has them."""
    problems = []
    for change in plan.changes:
        path = root / change.path
        if change.action == DELETE:
            if path.exists() and change.path not in {p for p in update.files if p.lower() == change.path.lower()}:
                problems.append(f"{change.path}: still there after deleting it")
        elif not path.is_file():
            problems.append(f"{change.path}: missing after writing it")
        elif path.read_bytes() != _content(change, update):
            problems.append(f"{change.path}: contents differ from the zip")
    return problems


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
        if expected is None:
            # The update deleted it; if it's back, someone put it back on purpose
            # (e.g. a newer apply_update.py), so don't overwrite it.
            return path.exists()
        return path.is_file() and _sha(path.read_bytes()) != expected

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


def print_plan(plan: Plan, *, mirror: bool, compared: bool) -> None:
    labels = (
        (ADD, "New", "+"), (MODIFY, "Updated", "~"),
        (MERGE, "Merged: your edits kept, the update's changes applied", "&"),
        (DELETE, "Deleted", "-"),
    )
    for action, label, mark in labels:
        paths = [path for path in plan.paths(action) if path not in plan.cleanup]
        if paths:
            print(f"\n{label} ({len(paths)}):")
            for path in paths:
                print(f"  {mark} {path}")
    if plan.conflicts:
        print(f"\nPossibly your own edits ({len(plan.conflicts)}): your version matches no earlier "
              "copy of the project,\nso it's either yours or from an update that's no longer "
              "in Downloads:")
        for conflict in plan.conflicts:
            print(f"  ? {conflict.path} ({conflict.note})")
    if plan.local_only:
        reason = (
            "your own changes" if compared and not mirror
            else "not in the zip" if not mirror
            else "your own files, not in the zip"
        )
        print(f"\nLeft alone, {reason} ({len(plan.local_only)}):")
        for path in plan.local_only[:15]:
            print(f"  = {path}")
        if mirror:
            print("  (never in an earlier copy of the project, so they're yours: kept)")
        if len(plan.local_only) > 15:
            print(f"  ... and {len(plan.local_only) - 15} more")
    if plan.cleanup:
        folders = sorted({path.split("/", 1)[0] + "/" for path in plan.cleanup})
        print(f"\nCleanup: copies an earlier update put in the wrong place, in {', '.join(folders)} "
              f"({len(plan.cleanup)}):")
        for path in plan.cleanup[:10]:
            print(f"  - {path}")
        if len(plan.cleanup) > 10:
            print(f"  ... and {len(plan.cleanup) - 10} more")
    if plan.cleanup_edited:
        print(f"\nLeft alone: put in the wrong place by an earlier update, but edited since "
              f"({len(plan.cleanup_edited)}):")
        for path in plan.cleanup_edited:
            print(f"  = {path}")
    if plan.problems:
        print(f"\nCouldn't update ({len(plan.problems)}):")
        for problem in plan.problems:
            print(f"  ! {problem}")
    if plan.ignored:
        print(f"\nIn the bundle but not in its changes.diff, so not applied ({len(plan.ignored)}):")
        for path in plan.ignored[:10]:
            print(f"  . {path}")
        if len(plan.ignored) > 10:
            print(f"  ... and {len(plan.ignored) - 10} more")
    print(f"\n{len(plan.changes)} file(s) to change, {plan.unchanged} already up to date.")


def describe_bundle(update: Snapshot) -> str:
    """What kind of download this is, and so what applying it does."""
    if update.kind == "diff":
        counts = {status: 0 for status in (ADDED, MODIFIED, RENAMED, DELETED)}
        for change in update.diff or []:
            counts[change.status] += 1
        summary = ", ".join(f"{n} {status}" for status, n in counts.items() if n)
        return (f"changed files with changes.diff ({summary}).\n        Applying just the "
                "diff: files it doesn't mention stay as they are.")
    if update.kind == "full":
        return (f"all the code ({len(update.files)} files).\n        Replacing the entire "
                "project: files it doesn't have are deleted, except ones you created and "
                "ones git ignores.")
    return (f"changed files without a changes.diff ({len(update.files)} files).\n        Adding "
            "and updating those files; nothing is deleted.")


def _add_cleanup(root: Path, local: Snapshot, plan: Plan) -> None:
    """Add the removal of files an earlier update misplaced to ``plan``."""
    removable, edited = stray_files(root, local)
    planned = {change.path for change in plan.changes}
    plan.cleanup = [path for path in removable if path not in planned]
    plan.cleanup_edited = edited
    plan.changes += [Change(path, DELETE, note="misplaced by an earlier update") for path in plan.cleanup]


def _describe(root: Path, path: Path) -> str:
    """"job-finder-....zip (project)", "applied update of 2026-11-07 18:24", ..."""
    when = _when(_mtime(path))
    if path.name == APPLIED_COPY:
        return f"update applied here, downloaded {when}"
    where = "project" if path.parent.resolve() == root else str(path.parent)
    return f"{path.name} ({where}, {when})"


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
                        help="take every file from the zip, your edits included; delete what the zip removed "
                        "(files you created yourself are kept)")
    parser.add_argument("--allow-partial", action="store_true",
                        help="apply an update even when some of its files can't be applied")
    parser.add_argument("--allow-deletes", action="store_true",
                        help=f"allow an update that deletes more than {MAX_DELETES} files")
    parser.add_argument("--dry-run", action="store_true", help="show what would change and exit")
    parser.add_argument("--yes", "-y", action="store_true", help="don't ask before changing files")
    parser.add_argument("--force", action="store_true",
                        help="take the zip's version of files that are possibly your edits without asking "
                        "(or, with --undo, revert files edited since)")
    parser.add_argument("--keep-mine", action="store_true",
                        help="keep your version of files that are possibly your edits without asking")
    parser.add_argument("--base", type=Path, action="append", default=[], metavar="ZIP",
                        help="another earlier copy of the project (zip or folder) to compare with; repeatable")
    parser.add_argument("--no-base", action="store_true",
                        help="don't compare with earlier copies: update every file that differs")
    parser.add_argument("--keep", action="append", default=[], metavar="PATTERN",
                        help="another path pattern never to touch, e.g. 'docs/my-notes.md' (repeatable)")
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

    folders = [f.expanduser() for f in args.downloads] if args.downloads else downloads_folders()
    local = read_folder(root, args.keep)
    project_paths = set(local.files)
    try:
        if args.zip:
            source = args.zip.expanduser().resolve()
        else:
            candidates = find_candidates(folders, exclude=[root], project_paths=project_paths)
            if args.candidates:
                if not candidates:
                    print(f"No project zips in {', '.join(map(str, folders)) or 'your Downloads folder'}.")
                for index, candidate in enumerate(candidates):
                    mark = "->" if index == 0 else "  "
                    try:
                        bundle = read_source(candidate.path, args.keep, project_paths)
                        what = {
                            "diff": "changed files + changes.diff",
                            "full": "all the code",
                            "partial": "changed files, no diff",
                        }[bundle.kind] + f", {len(bundle.files)} files"
                    except UpdateError as error:
                        what = str(error)
                    print(f"{mark} {_when(candidate.modified)}  {candidate.kind:<6}  {candidate.path}  ({what})")
                return 0
            if not candidates:
                searched = ", ".join(str(folder) for folder in folders) or "~/Downloads (missing)"
                raise UpdateError(
                    f"No zip containing this project was found in {searched}. "
                    "Pass it with --zip PATH, or point --downloads at the folder it's in."
                )
            source = candidates[0].path
            newer = newer_named(candidates[0], candidates)
            if newer:
                print(f"NOTE: picked the most recently downloaded zip, {source.name}, but "
                      f"{newer.path.name} has a later build time in its name. If that's the one "
                      f"you want: python3 apply_update.py --zip \"{newer.path}\"")

        update = read_source(source, args.keep, project_paths)
        print(f"Update: {source}")
        print(f"        downloaded {_when(source.stat().st_mtime)}; {describe_bundle(update)}")

        known: list[Snapshot] = []
        if not args.no_base:
            known = [read_source(p.expanduser().resolve(), args.keep, project_paths) for p in args.base]
            known += find_known_snapshots(root, update, folders, args.keep, project_paths)
            if known:
                print(f"Compared with {len(known)} earlier cop{'y' if len(known) == 1 else 'ies'} "
                      "of the project, to keep your own edits:")
                for snapshot in known:
                    print(f"        {_describe(root, snapshot.source)}")
            elif not args.all and update.diff is None:
                print("No earlier copy of the project to compare with, so your own edits can't be "
                      "told apart from the zip's:\nevery file that differs from the zip will be "
                      "updated (after a backup), and nothing will be deleted.")
    except UpdateError as error:
        print(error, file=sys.stderr)
        return 1

    plan = plan_update(local, update, known, mirror=args.all, force=args.force)
    _add_cleanup(root, local, plan)
    print_plan(plan, mirror=args.all, compared=bool(known))
    if plan.problems and not args.allow_partial:
        print(f"\nSTOPPED: {len(plan.problems)} file(s) in the update couldn't be applied, and "
              "applying the rest would leave\nthe project half-updated. Nothing was changed. "
              "Check you have the right download (--candidates),\nor use a bundle of all the "
              "code. To apply what can be applied anyway, add --allow-partial.")
        return 1
    if plan.conflicts and not args.keep_mine and not args.dry_run:
        if not args.yes and _confirm(
            f"\nTake the zip's versions of these {len(plan.conflicts)} file(s)? "
            "Yours are backed up first. (No keeps yours.)"
        ):
            plan = plan_update(local, update, known, mirror=args.all, force=True)
            _add_cleanup(root, local, plan)
        else:
            print(f"Keeping your version of {len(plan.conflicts)} file(s) (--force takes the zip's).")
    elif plan.conflicts and args.dry_run:
        print("  When you run it, you'll be asked whether to take the zip's versions "
              "(--force: yes, --keep-mine: no).")

    if not plan.changes:
        print("Nothing to update." if not plan.conflicts else "Nothing else to update.")
        return 0
    deletions = [path for path in plan.paths(DELETE) if path not in plan.cleanup]
    if len(deletions) > MAX_DELETES and not args.allow_deletes:
        print(f"\nSTOPPED: this would delete {len(deletions)} files. An update rarely deletes "
              "more than a few, so this zip is probably an older copy of the project than yours "
              "(or not the one you meant).\nCheck which zips were found with --candidates and "
              "pick one with --zip PATH. If the deletions are right, add --allow-deletes.")
        return 1
    if args.dry_run:
        print("Dry run: nothing was changed.")
        return 0
    if not args.yes and not _confirm(f"Apply {len(plan.changes)} change(s) to {root}?"):
        print("Cancelled; nothing was changed.")
        return 1

    backup = apply_plan(root, plan, update)
    problems = verify(root, plan, update)
    if problems:
        print(f"\nWARNING: {len(problems)} file(s) didn't end up as the zip has them:")
        for problem in problems:
            print(f"  {problem}")
        print(f"Everything changed is backed up in {backup.relative_to(root)}; "
              "python3 apply_update.py --undo puts it back.")
        return 1
    print(f"\nChanged {len(plan.changes)} file(s) and checked every one against the zip. "
          f"Backup: {backup.relative_to(root)} (python3 apply_update.py --undo to revert).")
    reinstall = sorted({DEPENDENCY_FILES[c.path] for c in plan.changes if c.path in DEPENDENCY_FILES})
    if reinstall:
        print("Dependencies changed; run:")
        for command in reinstall:
            print(f"  {command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
