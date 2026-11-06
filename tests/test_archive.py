"""Tests for archive.py, the share-safe project zipper.

The backend's own tests live in backend/tests. This directory deliberately
has no __init__.py, so it can't collide with that `tests` package when
`pytest` runs both from the repository root.
"""

import zipfile
from datetime import datetime

import pytest

import archive


@pytest.fixture
def project(tmp_path):
    """A small project tree with secrets and build output mixed in."""
    files = {
        "README.md": "readme",
        "archive.py": "script",
        "backend/job_search.py": "code",
        "backend/.env": "IG_EMAIL_TO=me@example.com",
        "backend/.env.example": "IG_EMAIL_TO=your-email@gmail.com",
        "backend/.env.local": "secret",
        "backend/credentials.json": "{}",
        "backend/token.json": "{}",
        "backend/firebase-service-account.json": "{}",
        "backend/my-project-firebase-adminsdk-abc12.json": "{}",
        "backend/local_firestore.json": '{"jobs": {}}',
        "backend/__pycache__/job_search.cpython-312.pyc": "",
        "backend/tests/test_job_search.py": "tests",
        "frontend/node_modules/react/index.js": "",
        "frontend/.next/build.txt": "",
        "frontend/src/app/page.tsx": "page",
        ".git/HEAD": "ref",
        "job-finder-20260101-000000.zip": "old archive",
        "run.log": "log",
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


def _listed(root, extra=()):
    return sorted(path.relative_to(root).as_posix() for path in archive.iter_files(root, extra))


def test_secrets_build_output_and_old_archives_are_left_out(project):
    assert _listed(project) == [
        "README.md",
        "archive.py",
        "backend/.env.example",
        "backend/job_search.py",
        "backend/local_firestore.json",
        "backend/tests/test_job_search.py",
        "frontend/src/app/page.tsx",
    ]


@pytest.mark.parametrize(
    "name",
    [
        "credentials.json",
        "token.json",
        ".env",
        ".env.production",
        "firebase-service-account.json",
        "acme-service-account.json",
        "acme-firebase-adminsdk-x1y2z.json",
        ".git",
        "node_modules",
        "__pycache__",
        "job-finder-20260101-000000.zip",
    ],
)
def test_is_excluded(name):
    assert archive.is_excluded(name)


def test_env_example_is_kept_even_though_it_matches_env_star():
    assert not archive.is_excluded(".env.example")


def test_extra_exclude_patterns(project):
    listed = _listed(project, extra=("local_firestore.json", "*.tsx"))

    assert "backend/local_firestore.json" not in listed
    assert "frontend/src/app/page.tsx" not in listed
    assert "backend/job_search.py" in listed


def test_build_archive_writes_the_listed_files_and_skips_itself(project):
    output = project / "job-finder-share.zip"

    archived = archive.build_archive(project, output)

    with zipfile.ZipFile(output) as zipped:
        names = sorted(zipped.namelist())
        assert zipped.read("backend/.env.example").decode() == "IG_EMAIL_TO=your-email@gmail.com"
    assert names == sorted(archived) == _listed(project)
    assert "job-finder-share.zip" not in names


def test_default_output_path_is_timestamped(project):
    path = archive.default_output_path(project, datetime(2026, 11, 5, 22, 21, 19))

    assert path == project / "job-finder-20261105-222119.zip"


def test_main_list_writes_nothing(project, capsys):
    zips_before = sorted(project.glob("*.zip"))

    assert archive.main(["--root", str(project), "--list"]) == 0

    out = capsys.readouterr().out
    assert "backend/job_search.py" in out
    assert "credentials.json" not in out
    assert sorted(project.glob("*.zip")) == zips_before


def test_main_rejects_a_missing_root(tmp_path, capsys):
    assert archive.main(["--root", str(tmp_path / "nope")]) == 1
    assert "is not a directory" in capsys.readouterr().err
