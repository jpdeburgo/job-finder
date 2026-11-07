#!/usr/bin/env python3
"""Zip up the project for sharing, leaving secrets and build output behind.

    python3 archive.py                 # writes job-finder-<timestamp>.zip here
    python3 archive.py --list          # show what would be included, write nothing
    python3 archive.py -o ~/Desktop/job-finder.zip
    python3 archive.py --exclude local_firestore.json   # extra patterns

Always excluded (see EXCLUDED_NAMES / EXCLUDED_GLOBS):

* secrets: credentials.json, token.json, .env and .env.* (the committed
  .env.example template is kept), Firebase service-account keys
* version control: .git
* dependencies and build output: node_modules, .next, .venv, __pycache__,
  coverage reports, previous archives, ...

Standard library only, so it runs with any Python 3 and no virtualenv.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

# Exact file or directory names that are never archived.
EXCLUDED_NAMES = frozenset(
    {
        # Secrets
        "credentials.json",
        "token.json",
        ".env",
        "firebase-service-account.json",
        # Version control
        ".git",
        # Dependencies, caches, and build output
        "node_modules",
        ".next",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "coverage",
        ".coverage",
        "htmlcov",
        ".vercel",
        ".turbo",
        "__MACOSX",
        ".DS_Store",
        ".idea",
        # apply_update.py's backups of the files an update replaced
        ".update-backups",
    }
)
# Glob patterns matched against the file/directory name.
EXCLUDED_GLOBS = (
    ".env.*",  # .env.local, .env.production, ...
    "*service-account*.json",
    "*-firebase-adminsdk-*.json",
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.tsbuildinfo",
    "*.zip",  # earlier archives
)
# Names that would otherwise match a glob above but are safe and useful.
ALWAYS_INCLUDED = frozenset({".env.example"})

DEFAULT_ARCHIVE_PREFIX = "job-finder"


def is_excluded(name: str, extra_patterns: Iterable[str] = ()) -> bool:
    """Return True when a file or directory called ``name`` must be left out."""
    if name in ALWAYS_INCLUDED:
        return False
    if name in EXCLUDED_NAMES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in (*EXCLUDED_GLOBS, *extra_patterns))


def iter_files(root: Path, extra_patterns: Iterable[str] = ()) -> Iterator[Path]:
    """Yield every file under ``root`` that should be archived, sorted for
    reproducible output. Excluded directories are never descended into."""
    extra = tuple(extra_patterns)
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not is_excluded(d, extra))
        for filename in sorted(filenames):
            if not is_excluded(filename, extra):
                yield Path(current) / filename


def default_output_path(root: Path, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return root / f"{DEFAULT_ARCHIVE_PREFIX}-{stamp}.zip"


def build_archive(root: Path, output: Path, extra_patterns: Iterable[str] = ()) -> list[str]:
    """Write ``output`` and return the archived paths (relative to ``root``)."""
    root = root.resolve()
    output = output.resolve()
    archived: list[str] = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in iter_files(root, extra_patterns):
            if file.resolve() == output:
                continue  # don't swallow the archive being written
            relative = file.relative_to(root).as_posix()
            archive.write(file, relative)
            archived.append(relative)
    return archived


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--output", type=Path, help="zip file to write (default: job-finder-<timestamp>.zip in the project root)")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent, help="project directory to archive (default: this script's directory)")
    parser.add_argument("--exclude", action="append", default=[], metavar="PATTERN", help="extra file/directory name pattern to leave out (repeatable)")
    parser.add_argument("--list", action="store_true", help="print the files that would be archived and exit")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        print(f"{root} is not a directory", file=sys.stderr)
        return 1

    if args.list:
        files = [file.relative_to(root).as_posix() for file in iter_files(root, args.exclude)]
        print("\n".join(files))
        print(f"\n{len(files)} file(s) would be archived from {root}", file=sys.stderr)
        return 0

    output = args.output or default_output_path(root)
    archived = build_archive(root, output, args.exclude)
    size_kb = output.stat().st_size / 1024
    print(f"Wrote {output} ({len(archived)} files, {size_kb:,.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
