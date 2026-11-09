"""Tests for apply_update.py: finding the downloaded zip and applying it safely."""

import difflib
import os
import shutil
import stat
import subprocess
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
    assert lines[0].startswith("-> ") and str(update_zip) in lines[0]
    assert "(all the code, " in lines[0]
    assert str(older) in lines[1]
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
    assert "Compared with 1 earlier copy of the project" in out
    assert "job-finder-20261107-085423.zip (project," in out
    assert "? backend/job_sites.py (changed in the zip; changed on your side)" in out
    assert "cd frontend && npm install" in out  # package.json changed
    # The zip's version of the conflict is saved to compare.
    (backup,) = (project / ".update-backups").iterdir()
    assert (backup / "incoming/backend/job_sites.py").read_text() == "sites v2"


def test_force_takes_the_zips_version_of_conflicts(project, downloads, update_zip):
    assert run(project, downloads, "--yes", "--force") == 0

    assert read(project, "backend/job_sites.py") == "sites v2"
    assert read(project, "alignerr.txt") == "notes v2 (yours)"  # still only yours


def _known(project, update_zip, downloads=None):
    update = apply_update.read_source(update_zip)
    snapshots = apply_update.find_known_snapshots(project, update, [downloads] if downloads else [])
    return sorted(snapshot.source.name for snapshot in snapshots)


def test_archives_made_after_the_download_are_not_earlier_copies(project, update_zip):
    # Archiving again after downloading the update (say, as a backup) captures
    # your edits; they mustn't count as versions the update replaces.
    archive.build_archive(project, project / "job-finder-20261107-170000.zip")

    assert _known(project, update_zip) == ["job-finder-20261107-085423.zip"]


def test_copies_of_the_update_are_not_earlier_copies(project, update_zip):
    (project / update_zip.name).write_bytes(update_zip.read_bytes())
    touch(project / update_zip.name, 7200)

    assert _known(project, update_zip) == ["job-finder-20261107-085423.zip"]


def test_older_downloads_count_as_earlier_copies(project, downloads, update_zip):
    touch(make_zip(downloads / "job-finder-20261105-120000.zip", BASE_FILES), 86400)

    assert _known(project, update_zip, downloads) == [
        "job-finder-20261105-120000.zip", "job-finder-20261107-085423.zip",
    ]


# --- A second update on top of the first ------------------------------------------------------


def second_update_files():
    """The next round, made on top of the first update."""
    files = updated_files()
    files.update({"backend/job_search.py": "search v3", "backend/job_fit.py": "new module v2"})
    return files


@pytest.fixture
def second_zip(downloads, update_zip):
    touch(update_zip, 3000)
    return make_zip(downloads / "job-finder-20261107-182628.zip", second_update_files())


def test_second_update_after_applying_the_first(project, downloads, update_zip, second_zip, capsys):
    assert run(project, downloads, "--yes", "--zip", str(update_zip)) == 0
    capsys.readouterr()

    assert run(project, downloads, "--yes") == 0  # picks the newest: the second update

    # Files changed in both rounds take the second round's version; they
    # were the first update's, not your edits.
    assert read(project, "backend/job_search.py") == "search v3"
    assert read(project, "backend/job_fit.py") == "new module v2"
    # Your edits are still kept.
    assert read(project, "alignerr.txt") == "notes v2 (yours)"
    assert read(project, "backend/job_sites.py") == "sites (your edit)"
    assert "update applied here" in capsys.readouterr().out


def test_second_update_when_the_first_was_applied_by_hand(project, downloads, update_zip, second_zip):
    # No record of the first update (applied by unzipping, or with an older
    # apply_update.py), but it's still in Downloads.
    for relative, content in updated_files().items():
        if relative not in ("backend/local_firestore.json", "backend/job_sites.py", "alignerr.txt"):
            (project / relative).parent.mkdir(parents=True, exist_ok=True)
            (project / relative).write_text(content)
    (project / "backend/old_module.py").unlink()

    assert run(project, downloads, "--yes") == 0

    assert read(project, "backend/job_search.py") == "search v3"
    assert read(project, "alignerr.txt") == "notes v2 (yours)"
    assert read(project, "backend/job_sites.py") == "sites (your edit)"


def test_second_update_when_the_first_was_skipped(project, downloads, update_zip, second_zip):
    # Both rounds' changes arrive at once.
    assert run(project, downloads, "--yes") == 0

    assert read(project, "backend/job_search.py") == "search v3"
    assert read(project, "frontend/package.json") == '{"v": 2}'  # first round only
    assert not (project / "backend/old_module.py").exists()  # deleted in the first round
    assert read(project, "alignerr.txt") == "notes v2 (yours)"
    assert read(project, "backend/job_sites.py") == "sites (your edit)"


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
    assert "No earlier copy of the project" in capsys.readouterr().out


# --- All the code (--all) ------------------------------------------------------------------


def test_all_takes_every_file_from_the_zip_but_keeps_files_you_created(project, downloads, update_zip):
    assert run(project, downloads, "--yes", "--all") == 0

    # Every file in the zip, your edits included, is the zip's version.
    for relative, content in updated_files().items():
        if relative != "backend/local_firestore.json":
            assert read(project, relative) == content, relative
    assert read(project, "alignerr.txt") == "notes v1"
    assert read(project, "backend/job_sites.py") == "sites v2"
    # What the update removed is deleted; what you created is kept.
    assert not (project / "backend/old_module.py").exists()
    assert read(project, "backend/my_scratch.py") == "your new file"
    # Still never touched.
    assert "interviewing" in read(project, "backend/local_firestore.json")
    assert (project / "backend/.env").exists()
    assert (project / "frontend/node_modules/react/index.js").exists()
    assert (project / "job-finder-20261107-085423.zip").exists()


# --- Picking the wrong zip, and what stops it --------------------------------------------------


def test_a_working_copy_in_downloads_is_never_taken_for_the_download(tmp_path, downloads, update_zip):
    # An older copy of the project you ran tests in: touched after the real
    # download, so it's "newer", but it isn't a download.
    old_copy = write_tree(downloads / "job-finder-old", BASE_FILES)
    (old_copy / ".pytest_cache").mkdir()
    (old_copy / "backend/__pycache__").mkdir()

    assert [c.path for c in apply_update.find_candidates([downloads])] == [update_zip]
    assert apply_update.is_working_copy(old_copy)
    assert not apply_update.is_working_copy(write_tree(tmp_path / "unzipped", BASE_FILES))


def test_an_update_that_would_delete_many_files_stops(project, downloads, capsys):
    # An old copy of the project: missing everything added since.
    many = {f"backend/module_{n}.py": f"module {n}" for n in range(8)}
    write_tree(project, many)
    archive.build_archive(project, project / "job-finder-20261107-120000.zip")
    touch(project / "job-finder-20261107-120000.zip", 1800)
    stale = make_zip(downloads / "cb354d57_1_a_all_code.zip", BASE_FILES)  # a full copy

    assert run(project, downloads, "--yes", "--all", "--zip", str(stale)) == 1

    assert "STOPPED: this would delete" in capsys.readouterr().out
    assert all((project / path).exists() for path in many)  # nothing touched
    assert run(project, downloads, "--yes", "--all", "--zip", str(stale), "--allow-deletes") == 0
    assert not any((project / path).exists() for path in many)


def test_warns_when_a_zip_built_later_was_downloaded_earlier(project, downloads, capsys):
    touch(make_zip(downloads / "job-finder-20261107-190000.zip", updated_files()), 3000)
    touch(make_zip(downloads / "job-finder-20261101-000000.zip", BASE_FILES), 10)

    assert run(project, downloads, "--dry-run") == 0

    out = capsys.readouterr().out
    assert "job-finder-20261107-190000.zip has a later build time in its name" in out


def test_deleting_never_removes_a_file_the_zip_has_in_different_case(project, downloads):
    update = apply_update.Snapshot(downloads / "u.zip", {"README.MD": b"readme v2", **{
        k: v.encode() for k, v in BASE_FILES.items() if k != "README.md"}})
    local = apply_update.read_folder(project)
    known = [apply_update.read_zip(project / "job-finder-20261107-085423.zip")]

    plan = apply_update.plan_update(local, update, known, mirror=True)

    assert "README.md" not in plan.paths(apply_update.DELETE)


def test_every_change_is_checked_after_applying(project, downloads, update_zip, monkeypatch, capsys):
    real_write = apply_update._write

    def flaky_write(path, data, executable):
        if path.name == "job_fit.py":
            return  # pretend the disk dropped it
        real_write(path, data, executable)

    monkeypatch.setattr(apply_update, "_write", flaky_write)

    assert run(project, downloads, "--yes") == 1

    out = capsys.readouterr().out
    assert "backend/job_fit.py: missing after writing it" in out
    assert "--undo" in out


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


def test_undo_does_not_overwrite_a_deleted_file_you_put_back(project, downloads):
    # A bad --all deleted apply_update.py; you fetched the new one before undoing.
    (project / "apply_update.py").write_text("old script")
    archive.build_archive(project, project / "job-finder-20261107-100000.zip")  # it was shared
    touch(project / "job-finder-20261107-100000.zip", 1000)
    stale = make_zip(downloads / "stale.zip", BASE_FILES)
    assert run(project, downloads, "--yes", "--all", "--zip", str(stale)) == 0
    assert not (project / "apply_update.py").exists()
    (project / "apply_update.py").write_text("new script")

    assert apply_update.main(["--root", str(project), "--undo"]) == 0

    assert read(project, "apply_update.py") == "new script"
    assert read(project, "alignerr.txt") == "notes v2 (yours)"  # the rest is put back


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


# --- The chat's bundles: "all code" and "changed files" -----------------------------------------


def changed_files():
    """A "changed files" bundle: just the files the update changed or added."""
    return {
        "backend/job_sites.py": "sites v2",
        "backend/job_fit.py": "new module",
        "frontend/src/lib/jobs.ts": "jobs v2",
    }


def test_changed_files_bundles_are_recognized_without_the_marker(project, downloads):
    # No backend/job_search.py in it: only files that changed.
    folder = write_tree(downloads / "4411874d_4_a_changed_files", changed_files())
    paths = set(apply_update.read_folder(project).files)

    (candidate,) = apply_update.find_candidates([downloads], project_paths=paths)
    bundle = apply_update.read_source(candidate.path, project_paths=paths)

    assert candidate.path == folder
    assert bundle.partial
    assert set(bundle.files) == set(changed_files())


def test_a_zip_of_some_other_project_is_not_a_bundle(project, downloads):
    make_zip(downloads / "other.zip", {"src/index.js": "x", "README.md": "other", "docs/a.md": "y"})
    paths = set(apply_update.read_folder(project).files)

    assert apply_update.find_candidates([downloads], project_paths=paths) == []


@pytest.mark.parametrize(
    "name, files, partial",
    [
        ("4411874d_4_a_changed_files", {"backend/job_search.py"}, True),  # the name says so
        ("4411874d_1_a_all_code", {"README.md"}, False),
        ("job-finder-20261107.zip", {"backend/job_search.py", "README.md", "a", "b"}, False),
        ("job-finder-20261107.zip", {"README.md", "a"}, True),  # no marker
        ("export.zip", {"backend/job_search.py"}, True),  # a small share of the project
    ],
)
def test_bundle_is_partial(name, files, partial):
    project = {"backend/job_search.py", "README.md", "a", "b", "c"}
    assert apply_update.bundle_is_partial(name, files, project) is partial


def test_a_changed_files_bundle_never_deletes(project, downloads, capsys):
    write_tree(downloads / "4411874d_4_a_changed_files", changed_files())

    assert run(project, downloads, "--yes", "--all") == 0

    out = capsys.readouterr().out
    assert "changed files without a changes.diff" in out and "Deleted" not in out
    assert read(project, "backend/job_sites.py") == "sites v2"  # --all: yours replaced
    assert read(project, "frontend/src/lib/jobs.ts") == "jobs v2"
    assert read(project, "backend/job_fit.py") == "new module"
    # Everything not in the bundle is as it was.
    assert read(project, "backend/job_search.py") == "search v1"
    assert read(project, "backend/old_module.py") == "to be deleted by the update"
    assert read(project, "alignerr.txt") == "notes v2 (yours)"


def test_a_changed_files_bundle_keeps_your_edits_by_default(project, downloads, capsys):
    write_tree(downloads / "4411874d_4_a_changed_files", changed_files())

    assert run(project, downloads, "--yes") == 0

    assert read(project, "backend/job_sites.py") == "sites (your edit)"  # a conflict: kept
    assert read(project, "frontend/src/lib/jobs.ts") == "jobs v2"  # you hadn't edited it
    out = capsys.readouterr().out
    assert "? backend/job_sites.py" in out
    assert "Possibly your own edits (1)" in out


def test_earlier_changed_files_bundles_only_vouch_for_their_own_files(project, downloads):
    # Round 2 changed job_search.py; you applied it. Round 4 changes it again.
    touch(write_tree(downloads / "4411874d_2_a_changed_files", {"backend/job_search.py": "search v2"}), 7200)
    (project / "backend/job_search.py").write_text("search v2")
    write_tree(downloads / "4411874d_4_a_changed_files", {"backend/job_search.py": "search v4"})

    assert run(project, downloads, "--yes") == 0

    # Round 2's copy shows you hadn't edited it, and its missing files say nothing:
    assert read(project, "backend/job_search.py") == "search v4"
    assert (project / "backend/old_module.py").exists()


def test_a_gap_in_history_asks_instead_of_leaving_the_project_half_updated(
    project, downloads, monkeypatch, capsys
):
    # Round 2 is in Downloads; round 3 was applied and then deleted; round 4
    # arrives. Your files are round 3's: no copy vouches for them.
    touch(write_tree(downloads / "4411874d_2_a_changed_files", {"backend/job_search.py": "search v2"}), 7200)
    (project / "backend/job_search.py").write_text("search v3")
    write_tree(downloads / "4411874d_4_a_changed_files", {"backend/job_search.py": "search v4"})

    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert run(project, downloads) == 0

    assert read(project, "backend/job_search.py") == "search v4"
    assert "Possibly your own edits (1)" in capsys.readouterr().out


def test_possibly_yours_is_kept_with_yes_or_keep_mine_and_taken_with_force(project, downloads):
    touch(write_tree(downloads / "4411874d_2_a_changed_files", {"backend/job_search.py": "search v2"}), 7200)
    (project / "backend/job_search.py").write_text("search v3")
    write_tree(downloads / "4411874d_4_a_changed_files", {"backend/job_search.py": "search v4"})

    assert run(project, downloads, "--yes") == 0
    assert read(project, "backend/job_search.py") == "search v3"
    assert run(project, downloads, "--keep-mine", "--yes") == 0
    assert read(project, "backend/job_search.py") == "search v3"
    assert run(project, downloads, "--force", "--yes") == 0
    assert read(project, "backend/job_search.py") == "search v4"


def test_a_file_no_copy_ever_changed_is_certainly_yours(project, downloads, update_zip, capsys):
    # alignerr.txt is "notes v1" in every copy; yours says v2: your edit, kept without asking.
    assert run(project, downloads, "--force", "--yes") == 0

    assert read(project, "alignerr.txt") == "notes v2 (yours)"


def test_a_file_created_in_a_missing_update_is_not_certainly_yours(project, downloads):
    # Created in round 3 (gone from Downloads), changed in round 4: the only
    # copy that has it is round 4's, which proves nothing about your version.
    (project / "backend/new_in_round_3.py").write_text("v3")
    write_tree(downloads / "4411874d_4_a_changed_files", {"backend/new_in_round_3.py": "v4"})
    local = apply_update.read_folder(project)
    update = apply_update.read_source(downloads / "4411874d_4_a_changed_files", project_paths=set(local.files))
    known = [apply_update.read_zip(project / "job-finder-20261107-085423.zip")]

    plan = apply_update.plan_update(local, update, known)

    assert [c.path for c in plan.conflicts] == ["backend/new_in_round_3.py"]  # asked, not kept silently



# --- changes.diff: applying just the diff -------------------------------------------------------


def git_diff(old_files, new_files, renames=()):
    """A git-style diff between two {path: text} trees (for bundles built in tests)."""
    out = []
    rename_map = dict(renames)
    for path in sorted(set(old_files) | set(new_files) | set(rename_map.values())):
        if path in rename_map:
            continue
        old_path = next((o for o, n in renames if n == path), path)
        before, after = old_files.get(old_path), new_files.get(path)
        if before == after and old_path == path:
            continue
        out.append(f"diff --git a/{old_path} b/{path}\n")
        if before is None:
            out.append("new file mode 100644\n")
        elif after is None:
            out.append("deleted file mode 100644\n")
        if old_path != path:
            out += [f"rename from {old_path}\n", f"rename to {path}\n"]
        body = list(difflib.unified_diff(
            (before or "").splitlines(keepends=True), (after or "").splitlines(keepends=True),
            "/dev/null" if before is None else f"a/{old_path}",
            "/dev/null" if after is None else f"b/{path}", n=3,
        ))
        for line in body:
            out.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(out)


ORIGINAL = {
    "backend/job_search.py": "".join(f"line {n}\n" for n in range(1, 41)),
    "backend/old_name.py": "def helper():\n    return 1\n",
    "backend/gone.py": "print('bye')\n",
}
UPDATED = {
    "backend/job_search.py": ORIGINAL["backend/job_search.py"].replace("line 30\n", "line 30 (updated)\n"),
    "backend/new_name.py": "def helper():\n    return 2\n",
    "backend/brand_new.py": "NEW = True\n",
}


@pytest.fixture
def diff_project(tmp_path):
    root = write_tree(tmp_path / "project", {**BASE_FILES, **ORIGINAL})
    (root / "job-finder-20261107-085423.zip").unlink(missing_ok=True)
    return root


def diff_bundle(downloads, files=UPDATED, original=ORIGINAL, name="4411874d_5_a_changed_files"):
    diff = git_diff(original, files, renames=[("backend/old_name.py", "backend/new_name.py")])
    return write_tree(downloads / name, {**files, "changes.diff": diff})


def test_a_bundle_with_changes_diff_applies_just_the_diff(diff_project, downloads, capsys):
    diff_bundle(downloads)

    assert run(diff_project, downloads, "--yes") == 0

    assert read(diff_project, "backend/job_search.py") == UPDATED["backend/job_search.py"]
    assert read(diff_project, "backend/new_name.py") == UPDATED["backend/new_name.py"]
    assert read(diff_project, "backend/brand_new.py") == "NEW = True\n"
    assert not (diff_project / "backend/old_name.py").exists()  # renamed
    assert not (diff_project / "backend/gone.py").exists()  # deleted by the diff
    assert not (diff_project / "changes.diff").exists()  # the diff isn't a project file
    assert read(diff_project, "backend/job_sites.py") == "sites v1"  # not mentioned: untouched
    out = capsys.readouterr().out
    assert "changed files with changes.diff (1 added, 1 modified, 1 renamed, 1 deleted)" in out
    assert "Applying just the diff" in out


def test_your_edits_elsewhere_in_a_file_are_merged(diff_project, downloads, capsys):
    diff_bundle(downloads)
    edited = ORIGINAL["backend/job_search.py"].replace("line 3\n", "line 3 (your edit)\n")
    (diff_project / "backend/job_search.py").write_text(edited)

    assert run(diff_project, downloads, "--yes") == 0

    merged = read(diff_project, "backend/job_search.py")
    assert "line 3 (your edit)" in merged and "line 30 (updated)" in merged
    assert "Merged: your edits kept" in capsys.readouterr().out


def test_your_edits_on_the_same_lines_are_asked_about(diff_project, downloads, monkeypatch, capsys):
    diff_bundle(downloads)
    edited = ORIGINAL["backend/job_search.py"].replace("line 30\n", "line 30 (your edit)\n")
    (diff_project / "backend/job_search.py").write_text(edited)

    assert run(diff_project, downloads, "--yes") == 0
    assert read(diff_project, "backend/job_search.py") == edited  # --yes keeps yours
    assert "? backend/job_search.py" in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert run(diff_project, downloads) == 0
    assert read(diff_project, "backend/job_search.py") == UPDATED["backend/job_search.py"]


def test_a_version_from_an_earlier_bundle_is_brought_up_to_date(diff_project, downloads):
    # Round 4 changed line 10; you applied it. Round 5's diff (from the original)
    # changes lines 10 and 30; your file is round 4's, which round 4's bundle vouches for.
    round_4 = ORIGINAL["backend/job_search.py"].replace("line 10\n", "line 10 (round 4)\n")
    round_5 = round_4.replace("line 30\n", "line 30 (round 5)\n")
    touch(diff_bundle(downloads, {"backend/job_search.py": round_4}, name="x_4_a_changed_files"), 3600)
    diff_bundle(downloads, {"backend/job_search.py": round_5}, name="x_5_a_changed_files")
    (diff_project / "backend/job_search.py").write_text(round_4)

    assert run(diff_project, downloads, "--yes") == 0

    assert read(diff_project, "backend/job_search.py") == round_5


def test_a_file_deleted_by_the_diff_but_edited_by_you_is_asked_about(diff_project, downloads, capsys):
    diff_bundle(downloads)
    (diff_project / "backend/gone.py").write_text("print('my change')\n")

    assert run(diff_project, downloads, "--yes") == 0

    assert (diff_project / "backend/gone.py").exists()
    assert "? backend/gone.py (deleted in the update; changed on your side)" in capsys.readouterr().out


def test_a_changed_file_missing_from_the_bundle_is_rebuilt_from_the_diff(diff_project, downloads):
    folder = diff_bundle(downloads)
    (folder / "backend/job_search.py").unlink()  # only in the diff

    assert run(diff_project, downloads, "--yes") == 0

    assert read(diff_project, "backend/job_search.py") == UPDATED["backend/job_search.py"]


def test_diff_from_another_project_is_not_a_candidate(diff_project, downloads):
    write_tree(downloads / "other_1_a_changed_files", {
        "src/app.js": "x", "changes.diff": "diff --git a/src/app.js b/src/app.js\n",
    })
    paths = set(apply_update.read_folder(diff_project).files)

    assert apply_update.find_candidates([downloads], project_paths=paths) == []


def test_undo_after_applying_a_diff(diff_project, downloads):
    diff_bundle(downloads)
    before = apply_update.read_folder(diff_project).files

    assert run(diff_project, downloads, "--yes") == 0
    assert apply_update.main(["--root", str(diff_project), "--undo"]) == 0

    assert apply_update.read_folder(diff_project).files == before


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_parse_and_apply_real_git_output(tmp_path):
    repo = tmp_path / "repo"
    original = {
        "a.py": "".join(f"a{n}\n" for n in range(30)),
        "old name.py": "".join(f"r{n}\n" for n in range(20)),
        "gone.txt": "bye\n",
        "no_newline.txt": "one\ntwo",
        "café.md": "hello\n",
        "script.sh": "echo hi\n",
    }
    write_tree(repo, original)
    git = lambda *args: subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)  # noqa: E731
    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    (repo / "a.py").write_text(original["a.py"].replace("a5\n", "a5!\n").replace("a25\n", ""))
    (repo / "old name.py").rename(repo / "new name.py")
    (repo / "new name.py").write_text(original["old name.py"].replace("r10\n", "r10 changed\n"))
    (repo / "gone.txt").unlink()
    (repo / "no_newline.txt").write_text("one\ntwo\nthree")
    (repo / "café.md").write_text("hello\nwörld\n")
    (repo / "added.txt").write_text("new\n")
    (repo / "script.sh").chmod(0o755)
    git("add", "-A")
    diff = subprocess.run(["git", "diff", "--cached", "-M", "HEAD"], cwd=repo, capture_output=True).stdout

    changes = {c.path: c for c in apply_update.parse_diff(diff.decode("utf-8"))}

    assert changes["gone.txt"].status == apply_update.DELETED
    assert changes["added.txt"].status == apply_update.ADDED
    assert changes["new name.py"].status == apply_update.RENAMED
    assert changes["new name.py"].old_path == "old name.py"
    assert changes["script.sh"].new_mode == "100755"
    assert "café.md" in changes
    for path, change in changes.items():
        if change.status == apply_update.DELETED:
            assert apply_update.apply_hunks(b"", change.hunks, reverse=True) == original[path].encode()
            continue
        after = (repo / path).read_bytes()
        before = original.get(change.old_path or path, "").encode()
        assert apply_update.apply_hunks(after, change.hunks, reverse=True) == before, path
        assert apply_update.apply_hunks(before, change.hunks) == after, path


# --- All the code: replacing the entire project --------------------------------------------------


def test_all_code_replaces_the_project_but_leaves_what_git_ignores(project, downloads, capsys):
    files = {k: v for k, v in updated_files().items() if k != "backend/local_firestore.json"}
    files[".gitignore"] = "*.log\nnext-env.d.ts\n/lib/\n"
    (project / "frontend/next-env.d.ts").write_text("generated")
    archive.build_archive(project, project / "job-finder-20261107-090000.zip")  # has next-env.d.ts
    touch(project / "job-finder-20261107-090000.zip", 1800)
    (project / "backend/written_after.py").write_text("your new file")  # in no copy: yours
    write_tree(downloads / "4411874d_6_a_all_code", files)

    assert run(project, downloads, "--yes") == 0

    assert not (project / "backend/old_module.py").exists()  # removed from the project
    assert read(project, "frontend/next-env.d.ts") == "generated"  # git ignores it: kept
    assert read(project, "backend/written_after.py") == "your new file"  # yours: kept
    assert "Replacing the entire project" in capsys.readouterr().out


@pytest.mark.parametrize(
    "path, ignored",
    [
        ("lib/x.py", True),
        ("frontend/src/lib/jobs.ts", False),  # /lib/ is anchored to the root
        ("backend/__pycache__/a.pyc", True),
        ("backend/a.pyc", True),
        ("backend/.env.local", True),
        ("backend/.env.example", False),  # !.env.example
        ("backend/local_firestore.json", True),
        ("frontend/src/test/fixtures/local_firestore.json", False),  # negated
        ("frontend/next-env.d.ts", True),
        ("backend/job_search.py", False),
    ],
)
def test_gitignore_matching(path, ignored):
    rules = (pathlib_root() / ".gitignore").read_text()
    assert apply_update.GitIgnore(rules).ignored(path) is ignored


def pathlib_root():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent



# --- The chat's layout: changes.diff at the root, the files under files/ ---------------------------


def files_layout_zip(downloads, name="4411874d_8_a_changed_files.zip", files=UPDATED, extra=None):
    downloads.mkdir(parents=True, exist_ok=True)
    path = downloads / name
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr("changes.diff", git_diff(ORIGINAL, files, renames=[("backend/old_name.py", "backend/new_name.py")]))
        for relative, text in {**files, **(extra or {})}.items():
            zipped.writestr(f"files/{relative}", text)
    return path


def test_changed_files_under_a_files_folder_are_found(diff_project, downloads, capsys):
    files_layout_zip(downloads)

    assert run(diff_project, downloads, "--yes") == 0

    assert read(diff_project, "backend/job_search.py") == UPDATED["backend/job_search.py"]
    assert read(diff_project, "backend/new_name.py") == UPDATED["backend/new_name.py"]
    assert not (diff_project / "backend/old_name.py").exists()
    assert not (diff_project / "backend/gone.py").exists()
    assert not (diff_project / "files").exists()  # never a folder in the project
    assert "No earlier copy" not in capsys.readouterr().out


def test_files_folder_layout_unzipped_by_the_browser(diff_project, downloads):
    folder = downloads / "4411874d_8_a_changed_files"
    write_tree(folder / "files", UPDATED)
    (folder / "changes.diff").write_text(git_diff(ORIGINAL, UPDATED, renames=[("backend/old_name.py", "backend/new_name.py")]))
    paths = set(apply_update.read_folder(diff_project).files)

    bundle = apply_update.read_source(folder, project_paths=paths)

    assert set(bundle.files) == set(UPDATED)
    assert bundle.base["backend/job_search.py"] == ORIGINAL["backend/job_search.py"].encode()


def test_bundle_files_the_diff_doesnt_mention_are_not_applied(diff_project, downloads, capsys):
    files_layout_zip(downloads, extra={"backend/stray.py": "not in the diff"})

    assert run(diff_project, downloads, "--yes") == 0

    assert not (diff_project / "backend/stray.py").exists()
    assert "In the bundle but not in its changes.diff, so not applied (1)" in capsys.readouterr().out


def test_an_update_that_cant_be_fully_applied_changes_nothing(diff_project, downloads, capsys):
    # job_search.py's change is in the diff but not the bundle, and the diff
    # doesn't fit your version of it, so it can't be applied.
    files_layout_zip(downloads, files=UPDATED)
    path = downloads / "4411874d_8_a_changed_files.zip"
    with zipfile.ZipFile(path) as zipped:
        entries = {name: zipped.read(name) for name in zipped.namelist() if name != "files/backend/job_search.py"}
    with zipfile.ZipFile(path, "w") as zipped:
        for name, data in entries.items():
            zipped.writestr(name, data)
    (diff_project / "backend/job_search.py").write_text("something else entirely\n")
    before = apply_update.read_folder(diff_project).files

    assert run(diff_project, downloads, "--yes") == 1

    assert apply_update.read_folder(diff_project).files == before
    out = capsys.readouterr().out
    assert "STOPPED: 1 file(s) in the update couldn't be applied" in out
    assert run(diff_project, downloads, "--yes", "--allow-partial") == 0
    assert (diff_project / "backend/new_name.py").exists()



# --- Cleaning up after an older apply_update.py -------------------------------------------------


def misplace(project, files, tmp_path, name="8.zip"):
    """Do what an older apply_update.py did with a files/ bundle: copy the
    folder into the project as-is, recorded as added by that update."""
    (tmp_path / name).write_bytes(b"bundle")
    update = apply_update.Snapshot(tmp_path / name, {k: v.encode() for k, v in files.items()})
    plan = apply_update.Plan(changes=[apply_update.Change(p, apply_update.ADD) for p in sorted(files)])
    return apply_update.apply_plan(project, plan, update)


def test_files_an_earlier_update_misplaced_are_cleaned_up(project, downloads, tmp_path, capsys):
    many = {f"backend/module_{n}.py": f"m{n}" for n in range(8)}
    write_tree(project, many)
    misplace(project, {f"files/{p}": v for p, v in {**BASE_FILES, **many}.items() if p != "backend/local_firestore.json"}, tmp_path)
    (project / "files/alignerr.txt").write_text("edited after")  # yours now: kept
    write_tree(downloads / "x_10_a_changed_files", {"files/backend/job_sites.py": "sites v2"})
    (downloads / "x_10_a_changed_files/changes.diff").write_text(git_diff(
        {"backend/job_sites.py": "sites (your edit)\n"}, {"backend/job_sites.py": "sites v2"}))

    assert run(project, downloads, "--yes") == 0

    left = sorted(p.relative_to(project).as_posix() for p in (project / "files").rglob("*") if p.is_file())
    assert left == ["files/alignerr.txt"]
    out = capsys.readouterr().out
    assert "Cleanup: copies an earlier update put in the wrong place, in files/ (15)" in out
    assert "= files/alignerr.txt" in out
    assert "STOPPED" not in out  # not held to the deletion limit
    assert read(project, "backend/module_3.py") == "m3"  # the real files are untouched


def test_new_folders_an_update_meant_to_add_are_not_cleaned_up(project, tmp_path):
    misplace(project, {"scripts/deploy.sh": "echo", "scripts/setup.py": "x"}, tmp_path)
    local = apply_update.read_folder(project)

    assert apply_update.stray_files(project, local) == ([], [])


def test_real_project_folders_are_never_cleaned_up(project, tmp_path):
    # backend/ has files no update added, so it's part of the project.
    misplace(project, {"backend/job_search.py": "search v2"}, tmp_path)
    local = apply_update.read_folder(project)

    assert apply_update.stray_files(project, local) == ([], [])


def test_undone_updates_leave_nothing_to_clean_up(project, tmp_path):
    misplace(project, {"files/README.md": "readme v1", "files/backend/job_search.py": "search v1"}, tmp_path)
    assert apply_update.main(["--root", str(project), "--undo"]) == 0

    assert apply_update.stray_files(project, apply_update.read_folder(project)) == ([], [])
