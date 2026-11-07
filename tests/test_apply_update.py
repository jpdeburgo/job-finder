"""Tests for apply_update.py: finding the downloaded zip and applying it safely."""

import os
import stat
import time
import zipfile

import pytest

import apply_update
import archive

BASE_FILES = {
    "README.md": "readme v1",
    "archive.py": "archive",
    "backend/job_search.py": "search v1",
    "backend/job_sites.py": "sites v1",
    "backend/old_module.py": "to be deleted by the update",
    "backend/local_firestore.json": '{"jobs": {"mine": {"status": "applied"}}}',
    "frontend/src/lib/jobs.ts": "jobs v1",
    "frontend/package.json": '{"v": 1}',
    "alignerr.txt": "notes v1",
}


def write_tree(root, files):
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


def make_zip(path, files, prefix=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zipped:
        for relative, content in files.items():
            zipped.writestr(prefix + relative, content)
    return path


def touch(path, seconds_ago):
    stamp = time.time() - seconds_ago
    os.utime(path, (stamp, stamp))
    return path


def read(root, relative):
    return (root / relative).read_text()


@pytest.fixture
def project(tmp_path):
    """The project as you have it: the archive you shared still in its root,
    plus edits you made after sharing it, plus secrets and dependencies."""
    root = write_tree(tmp_path / "project", BASE_FILES)
    archive.build_archive(root, root / "job-finder-20261107-085423.zip")
    touch(root / "job-finder-20261107-085423.zip", 3600)
    write_tree(root, {
        "alignerr.txt": "notes v2 (yours)",  # only you changed it
        "backend/job_sites.py": "sites (your edit)",  # the zip changes it too: conflict
        "backend/my_scratch.py": "your new file",
        "backend/.env": "IG_EMAIL_TO=me@example.com",
        "frontend/node_modules/react/index.js": "dependency",
        "backend/local_firestore.json": '{"jobs": {"mine": {"status": "interviewing"}}}',
    })
    return root


def updated_files():
    """What the update zip holds: BASE_FILES plus the update's changes."""
    files = dict(BASE_FILES)
    files.update({
        "backend/job_search.py": "search v2",
        "backend/job_sites.py": "sites v2",
        "backend/job_fit.py": "new module",
        "frontend/package.json": '{"v": 2}',
        # The sandbox's copy of your data: must never replace yours.
        "backend/local_firestore.json": '{"jobs": {}}',
    })
    del files["backend/old_module.py"]
    return files


@pytest.fixture
def downloads(tmp_path):
    return tmp_path / "Downloads"


@pytest.fixture
def update_zip(downloads):
    return make_zip(downloads / "job-finder-20261107-160000.zip", updated_files())


def run(project, downloads, *args):
    return apply_update.main(["--root", str(project), "--downloads", str(downloads), *args])


# --- Finding the download --------------------------------------------------------------------


def test_picks_the_most_recently_downloaded_project_zip(tmp_path, downloads):
    newest = touch(make_zip(downloads / "job-finder-20261107-160000 (1).zip", updated_files()), 10)
    touch(make_zip(downloads / "job-finder-20261101-120000.zip", updated_files()), 5000)
    touch(make_zip(downloads / "holiday-photos.zip", {"a.jpg": "x"}), 1)  # newer, not the project
    (downloads / "broken.zip").write_bytes(b"PK\x03\x04 not really")  # half-written
    (downloads / "job-finder-next.zip.crdownload").write_bytes(b"")  # still downloading
    (downloads / "notes").mkdir()  # a folder without the project

    candidates = apply_update.find_candidates([downloads])

    assert [c.path for c in candidates] == [newest, downloads / "job-finder-20261101-120000.zip"]


def test_a_folder_the_browser_unzipped_counts(downloads):
    # Safari unzips downloads (and bins the zip); the folder is the download.
    folder = write_tree(downloads / "job-finder-20261107-160000", updated_files())
    touch(make_zip(downloads / "older.zip", updated_files()), 5000)

    (first, _) = apply_update.find_candidates([downloads])

    assert first.path == folder and first.kind == "folder"
    assert apply_update.read_source(folder).files["backend/job_search.py"] == b"search v2"


def test_zips_with_the_project_inside_a_folder_work(downloads):
    path = make_zip(downloads / "export.zip", updated_files(), prefix="job-finder/")

    snapshot = apply_update.read_source(path)

    assert snapshot.files["backend/job_fit.py"] == b"new module"
    assert not any(name.startswith("job-finder/") for name in snapshot.files)


def test_the_project_itself_is_never_a_candidate(tmp_path):
    # Projects often live in Downloads (that's where they were unzipped).
    downloads = tmp_path / "Downloads"
    project = write_tree(downloads / "job-finder", BASE_FILES)
    nested = write_tree(downloads / "work" / "job-finder", BASE_FILES)

    assert apply_update.find_candidates([downloads], exclude=[project, nested]) == []


def test_zip_entries_that_escape_the_project_are_ignored(downloads):
    files = updated_files()
    files.update({"../evil.py": "x", "/etc/passwd": "x", "backend/../../evil2.py": "x"})
    snapshot = apply_update.read_source(make_zip(downloads / "u.zip", files))

    assert not any("evil" in name or "passwd" in name for name in snapshot.files)


def test_candidates_lists_what_was_found(project, downloads, update_zip, capsys):
    older = touch(make_zip(downloads / "older.zip", updated_files()), 5000)

    assert run(project, downloads, "--candidates") == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("-> ") and lines[0].endswith(str(update_zip))
    assert lines[1].endswith(str(older))
    assert read(project, "backend/job_search.py") == "search v1"  # nothing applied


def test_no_download_found_explains_what_to_do(project, tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()

    assert run(project, empty) == 1
    assert "No zip containing this project was found" in capsys.readouterr().err


# --- Changed files (default) ------------------------------------------------------------------


def test_applies_only_what_the_zip_changed(project, downloads, update_zip, capsys):
    assert run(project, downloads, "--yes") == 0

    # The update's changes.
    assert read(project, "backend/job_search.py") == "search v2"
    assert read(project, "backend/job_fit.py") == "new module"
    assert not (project / "backend/old_module.py").exists()
    # Your edits since sharing are kept, including the conflicting one.
    assert read(project, "alignerr.txt") == "notes v2 (yours)"
    assert read(project, "backend/job_sites.py") == "sites (your edit)"
    assert read(project, "backend/my_scratch.py") == "your new file"
    # Never touched: data, secrets, dependencies.
    assert "interviewing" in read(project, "backend/local_firestore.json")
    assert read(project, "backend/.env") == "IG_EMAIL_TO=me@example.com"
    assert read(project, "frontend/node_modules/react/index.js") == "dependency"

    out = capsys.readouterr().out
    assert "Compared with: job-finder-20261107-085423.zip" in out
    assert "! backend/job_sites.py (changed in the zip; you changed it)" in out
    assert "cd frontend && npm install" in out  # package.json changed
    # The zip's version of the conflict is saved to compare.
    (backup,) = (project / ".update-backups").iterdir()
    assert (backup / "incoming/backend/job_sites.py").read_text() == "sites v2"


def test_force_takes_the_zips_version_of_conflicts(project, downloads, update_zip):
    assert run(project, downloads, "--yes", "--force") == 0

    assert read(project, "backend/job_sites.py") == "sites v2"
    assert read(project, "alignerr.txt") == "notes v2 (yours)"  # still only yours


def test_base_is_the_closest_archive_not_the_newest(project, downloads, update_zip):
    # You archived again later with more edits; the update wasn't made from that one.
    (project / "README.md").write_text("readme (yours)")
    archive.build_archive(project, project / "job-finder-20261107-170000.zip")
    (project / "README.md").write_text("readme v1")

    base, differences = apply_update.choose_base(project, apply_update.read_source(update_zip))

    assert base.source.name == "job-finder-20261107-085423.zip"
    assert differences == 5  # the update's own changes


def test_the_update_saved_into_the_project_is_not_its_own_base(project, update_zip):
    (project / update_zip.name).write_bytes(update_zip.read_bytes())

    base, _ = apply_update.choose_base(project, apply_update.read_source(update_zip))

    assert base.source.name == "job-finder-20261107-085423.zip"


def test_without_an_earlier_archive_every_difference_is_updated_and_nothing_deleted(
    project, downloads, update_zip, capsys
):
    (project / "job-finder-20261107-085423.zip").unlink()

    assert run(project, downloads, "--yes") == 0

    assert read(project, "backend/job_sites.py") == "sites v2"
    assert read(project, "alignerr.txt") == "notes v1"  # can't tell it was yours
    assert (project / "backend/old_module.py").exists()
    assert (project / "backend/my_scratch.py").exists()
    assert "interviewing" in read(project, "backend/local_firestore.json")
    assert "No earlier archive in the project" in capsys.readouterr().out


# --- All the code (--all) ------------------------------------------------------------------


def test_all_makes_the_project_match_the_zip(project, downloads, update_zip):
    assert run(project, downloads, "--yes", "--all") == 0

    expected = {k: v for k, v in updated_files().items() if k != "backend/local_firestore.json"}
    local = apply_update.read_folder(project).files
    assert {k: v.decode() for k, v in local.items()} == expected
    # Still never touched.
    assert "interviewing" in read(project, "backend/local_firestore.json")
    assert (project / "backend/.env").exists()
    assert (project / "frontend/node_modules/react/index.js").exists()
    assert (project / "job-finder-20261107-085423.zip").exists()


# --- Confirming, dry runs, undo ----------------------------------------------------------------


def test_dry_run_changes_nothing(project, downloads, update_zip, capsys):
    before = apply_update.read_folder(project).files

    assert run(project, downloads, "--dry-run") == 0

    assert apply_update.read_folder(project).files == before
    out = capsys.readouterr().out
    assert "+ backend/job_fit.py" in out and "- backend/old_module.py" in out
    assert "Dry run" in out


def test_asks_before_changing_anything(project, downloads, update_zip, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    assert run(project, downloads) == 1
    assert read(project, "backend/job_search.py") == "search v1"

    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert run(project, downloads) == 0
    assert read(project, "backend/job_search.py") == "search v2"


def test_nothing_to_do_when_already_up_to_date(project, downloads, update_zip, capsys):
    assert run(project, downloads, "--yes") == 0
    capsys.readouterr()

    assert run(project, downloads, "--yes") == 0
    assert "Nothing else to update." in capsys.readouterr().out  # only the kept conflict left


def test_undo_restores_the_project(project, downloads, update_zip):
    before = apply_update.read_folder(project).files
    assert run(project, downloads, "--yes", "--all") == 0
    assert apply_update.read_folder(project).files != before

    assert apply_update.main(["--root", str(project), "--undo"]) == 0

    assert apply_update.read_folder(project).files == before
    assert not (project / "backend/job_fit.py").exists()
    # Already undone.
    assert apply_update.main(["--root", str(project), "--undo"]) == 1


def test_undo_leaves_files_you_edited_after_the_update(project, downloads, update_zip, capsys):
    assert run(project, downloads, "--yes") == 0
    (project / "backend/job_search.py").write_text("search v2 + your fix")

    assert apply_update.main(["--root", str(project), "--undo"]) == 0

    assert read(project, "backend/job_search.py") == "search v2 + your fix"
    assert not (project / "backend/job_fit.py").exists()
    assert "backend/job_search.py" in capsys.readouterr().out


def test_executable_bit_is_kept(project, downloads):
    downloads.mkdir()
    path = downloads / "u.zip"
    with zipfile.ZipFile(path, "w") as zipped:
        for relative, content in updated_files().items():
            info = zipfile.ZipInfo(relative)
            info.external_attr = (0o755 if relative == "archive.py" else 0o644) << 16
            zipped.writestr(info, content)
    (project / "archive.py").write_text("differs from the zip")
    (project / "job-finder-20261107-085423.zip").unlink()

    assert run(project, downloads, "--yes", "--zip", str(path)) == 0

    assert (project / "archive.py").stat().st_mode & stat.S_IXUSR


def test_backups_and_archives_stay_out_of_each_other(project, downloads, update_zip):
    assert run(project, downloads, "--yes") == 0
    assert (project / ".update-backups").is_dir()

    listed = [p.relative_to(project).as_posix() for p in archive.iter_files(project)]

    assert not any(path.startswith(".update-backups") for path in listed)
    assert archive.is_excluded(".update-backups")


def test_rejects_a_root_that_isnt_the_project(tmp_path, capsys):
    assert apply_update.main(["--root", str(tmp_path)]) == 1
    assert "isn't the project" in capsys.readouterr().err
