import json

import jobs_cli
from job_store import FirestoreJobStore
from tests.test_job_store import make_job


def test_cli_help_lists_every_command(capsys):
    assert jobs_cli.main(["help"]) == 0
    out = capsys.readouterr().out
    for name in ("list", "show", "applied", "skip", "status", "migrate"):
        assert f"\n  {name:<9}" in out
    assert "jobs_cli.py applied [-h] [--note NOTE] [--local] job_id" in out

    assert jobs_cli.main([]) == 0  # no command at all also prints help
    assert "Commands:" in capsys.readouterr().out


def test_cli_list_applied_show(tmp_path, capsys):
    store = FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)
    store.save_matches([make_job("12", title="React Dev")], new_ids={"12"})
    store.mark_emailed(["12"], "m")

    assert jobs_cli.main(["list"], store) == 0
    out = capsys.readouterr().out
    assert "React Dev" in out
    assert "unemailed" not in out

    assert jobs_cli.main(["applied", "12", "--note", "done"], store) == 0
    assert "Job 12 -> applied: React Dev" in capsys.readouterr().out

    assert jobs_cli.main(["list", "--status", "applied"], store) == 0
    assert "12" in capsys.readouterr().out

    assert jobs_cli.main(["show", "12"], store) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["status"] == "applied" and shown["notes"] == "done"


def test_cli_migrate_copies_local_snapshot(tmp_path, capsys):
    source = FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)
    source.save_matches([make_job("1")], new_ids={"1"})
    source.set_status("1", "applied")
    target = FirestoreJobStore.local(tmp_path / "target.json", verbose=False)

    assert jobs_cli.main(["migrate", str(tmp_path / "local_firestore.json")], target) == 0

    assert "Imported 1 job document(s)" in capsys.readouterr().out
    assert target.get_job("1")["status"] == "applied"


def test_cli_migrate_rejects_an_old_id_list(tmp_path, capsys):
    old = tmp_path / "seen_jobs.json"
    old.write_text("[10, 11]\n")
    store = FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)

    assert jobs_cli.main(["migrate", str(old)], store) == 1

    assert "is not a local_firestore.json file" in capsys.readouterr().err
    assert store.load_seen_ids() == set()


def test_cli_list_flags_unemailed_jobs(tmp_path, capsys):
    store = FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)
    store.save_matches([make_job("1")], new_ids={"1"})

    assert jobs_cli.main(["list"], store) == 0

    assert "1 job(s) are 'unemailed'" in capsys.readouterr().out


def test_cli_unknown_job_returns_error(tmp_path, capsys):
    store = FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)

    assert jobs_cli.main(["skip", "404"], store) == 1
    assert "not in the store" in capsys.readouterr().err
    assert jobs_cli.main(["show", "404"], store) == 1
