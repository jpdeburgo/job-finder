"""Tests for FirestoreJobStore, run against the LocalFirestoreClient stand-in.

The stand-in implements the same slice of the google-cloud-firestore API the
store uses, so the persistence logic exercised here is exactly what runs
against the real database.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

import job_store
from job_search import JobMatch
from job_store import (
    STATUS_APPLIED,
    STATUS_EMAILED,
    STATUS_SEEN,
    STATUS_SKIPPED,
    STATUS_UNEMAILED,
    FirestoreJobStore,
    LocalFirestoreClient,
    get_job_store,
)


def make_job(job_id: str, title: str = "Python Engineer", **overrides) -> JobMatch:
    fields = dict(
        job_id=job_id,
        title=title,
        city="Austin",
        state="TX",
        is_remote=True,
        job_type="Contract",
        salary_low=100000,
        salary_high=120000,
        url=f"https://insightglobal.com/jobs/{job_id}",
        track="Core matches (your main stack)",
        posted_date="2026-08-15",
        matched_skills=["Python", "React"],
        min_years=3,
    )
    fields.update(overrides)
    return JobMatch(**fields)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "local_firestore.json"


@pytest.fixture
def store(db_path):
    return FirestoreJobStore.local(db_path, verbose=False)


def read_db(db_path):
    return json.loads(db_path.read_text())


# --- Saving matches -----------------------------------------------------------


def test_empty_store_has_no_seen_ids(store):
    assert store.load_seen_ids() == set()
    assert store.load_unemailed_ids() == set()


def test_save_matches_creates_unemailed_docs_with_details(store, db_path):
    store.save_matches([make_job("1"), make_job("2", title="React Dev")], new_ids={"1", "2"})

    docs = read_db(db_path)["jobs"]
    assert set(docs) == {"1", "2"}
    assert docs["1"]["status"] == STATUS_UNEMAILED
    assert docs["1"]["title"] == "Python Engineer"
    assert docs["1"]["matched_skills"] == ["Python", "React"]
    assert docs["1"]["score"] == 2
    assert "emailed_at" not in docs["1"]
    assert store.load_seen_ids() == {"1", "2"}
    assert store.load_unemailed_ids() == {"1", "2"}


def test_mark_emailed_flips_status_and_records_message_id(store):
    store.save_matches([make_job("1"), make_job("2")], new_ids={"1", "2"})

    store.mark_emailed(["1"], "msg-1")

    job = store.get_job("1")
    assert job["status"] == STATUS_EMAILED
    assert job["gmail_message_id"] == "msg-1"
    assert isinstance(job["emailed_at"], datetime)
    assert store.load_unemailed_ids() == {"2"}


def test_reseen_job_keeps_manual_status_and_first_seen(store):
    store.save_matches([make_job("1")], new_ids={"1"})
    store.mark_emailed(["1"], "msg-1")
    first_seen = store.get_job("1")["first_seen_at"]
    store.set_status("1", STATUS_APPLIED, note="sent resume")

    # The same job shows up in a later run; it's not "new" anymore.
    store.save_matches([make_job("1", salary_high=130000)], new_ids=set())

    job = store.get_job("1")
    assert job["status"] == STATUS_APPLIED
    assert job["notes"] == "sent resume"
    assert job["first_seen_at"] == first_seen
    assert job["last_seen_at"] >= first_seen
    assert job["salary_high"] == 130000  # details refresh


def test_save_matches_batches_large_runs(db_path, monkeypatch):
    monkeypatch.setattr(job_store, "FIRESTORE_BATCH_SIZE", 3)
    commits = []
    client = LocalFirestoreClient(db_path, verbose=False)
    original_batch = client.batch

    def counting_batch():
        batch = original_batch()
        commits.append(batch)
        return batch

    monkeypatch.setattr(client, "batch", counting_batch)
    store = FirestoreJobStore(client)

    ids = {str(i) for i in range(7)}
    store.save_matches([make_job(i) for i in sorted(ids)], new_ids=ids)

    assert len(commits) == 3
    assert store.load_seen_ids() == ids


# --- Status management ---------------------------------------------------------


def test_set_status_records_applied_at_and_rejects_unknown(store):
    store.save_matches([make_job("1")], new_ids={"1"})

    updated = store.set_status("1", STATUS_APPLIED)

    assert updated["status"] == STATUS_APPLIED
    assert isinstance(updated["applied_at"], datetime)
    with pytest.raises(KeyError):
        store.set_status("999", STATUS_APPLIED)
    with pytest.raises(ValueError, match="Unknown status"):
        store.set_status("1", "bogus")


def test_list_jobs_filters_by_status_and_sorts_newest_first(store):
    store.save_matches([make_job("1")], new_ids={"1"})
    store.save_matches([make_job("2")], new_ids={"2"})
    store.set_status("1", STATUS_SKIPPED)

    assert [j["job_id"] for j in store.list_jobs()] == ["2", "1"]
    assert [j["job_id"] for j in store.list_jobs(status=STATUS_SKIPPED)] == ["1"]
    assert [j["job_id"] for j in store.list_jobs(limit=1)] == ["2"]


def test_get_job(store):
    store.save_matches([make_job("1")], new_ids={"1"})

    assert store.get_job("1")["title"] == "Python Engineer"
    assert store.get_job("2") is None


# --- Imports & run log -----------------------------------------------------------


def test_import_legacy_ids_skips_existing(store):
    store.save_matches([make_job("1")], new_ids={"1"})
    store.set_status("1", STATUS_APPLIED)

    added = store.import_legacy_ids([1, 2, 3])

    assert added == 2
    assert store.get_job("1")["status"] == STATUS_APPLIED  # not clobbered
    assert store.get_job("2")["status"] == STATUS_SEEN
    assert store.load_seen_ids() == {"1", "2", "3"}


def test_import_documents_copies_local_snapshot_into_another_store(store, tmp_path):
    store.save_matches([make_job("1"), make_job("2")], new_ids={"1", "2"})
    store.set_status("1", STATUS_APPLIED, note="done")
    other = FirestoreJobStore.local(tmp_path / "other.json", verbose=False)
    other.save_matches([make_job("2", title="already here")], new_ids={"2"})

    added = other.import_documents(read_db(store._client.path)["jobs"])

    assert added == 1
    assert other.get_job("1")["status"] == STATUS_APPLIED
    assert other.get_job("1")["notes"] == "done"
    assert isinstance(other.get_job("1")["applied_at"], datetime)
    assert other.get_job("2")["title"] == "already here"


def test_log_run_writes_runs_collection(store, db_path):
    store.log_run(
        total_matches=5, new_job_ids=["3", "1"], email_sent=True, gmail_message_id="m-1"
    )

    runs = read_db(db_path)["runs"]
    (run,) = runs.values()
    assert run["total_matches"] == 5
    assert run["new_matches"] == 2
    assert run["new_job_ids"] == ["1", "3"]
    assert run["email_sent"] is True
    assert run["gmail_message_id"] == "m-1"
    assert run["error"] is None


# --- LocalFirestoreClient -----------------------------------------------------------


def test_local_file_mirrors_firestore_layout(store, db_path):
    store.save_matches([make_job("1")], new_ids={"1"})
    store.log_run(total_matches=1, new_job_ids=["1"], email_sent=False)

    data = read_db(db_path)
    assert set(data) == {"jobs", "runs"}
    assert list(data["jobs"]) == ["1"]
    (run_id,) = data["runs"]
    assert len(run_id) == 20 and run_id.isalnum()  # Firestore-style auto ID
    assert data["jobs"]["1"]["first_seen_at"].endswith("+00:00")  # ISO timestamps


def test_local_client_prints_the_calls_it_would_make(db_path, capsys):
    store = FirestoreJobStore.local(db_path, verbose=True)

    store.save_matches([make_job("1")], new_ids={"1"})
    store.set_status("1", STATUS_APPLIED)
    store.list_jobs(status=STATUS_APPLIED)
    store.load_seen_ids()

    out = capsys.readouterr().out
    assert "[local firestore] batch commit (1 writes)" in out
    assert "set jobs/1 (merge): status='unemailed', title='Python Engineer'" in out
    assert "[local firestore] update jobs/1: status='applied'" in out
    assert "[local firestore] query jobs where status == 'applied'" in out
    assert "[local firestore] list_documents jobs" in out


def test_local_client_rejects_legacy_list_file(tmp_path):
    path = tmp_path / "local_firestore.json"
    path.write_text("[1, 2, 3]\n")

    with pytest.raises(ValueError, match="migrate"):
        FirestoreJobStore.local(path, verbose=False).load_seen_ids()


def test_local_client_update_missing_document_fails(db_path):
    client = LocalFirestoreClient(db_path, verbose=False)

    with pytest.raises(KeyError):
        client.collection("jobs").document("404").update({"status": "x"})


def test_reads_status_update_written_by_frontend(db_path):
    """The Next.js dashboard (../frontend) edits local_firestore.json directly.

    It writes `+00:00` ISO timestamps, so `*_at` fields must round-trip to
    aware datetimes here exactly as if this store had written them.
    """
    db_path.write_text(
        json.dumps(
            {
                "jobs": {
                    "abc": {
                        "applied_at": "2026-11-02T10:15:30.123+00:00",
                        "job_id": "abc",
                        "notes": "Applied from the dashboard",
                        "status": "applied",
                        "status_updated_at": "2026-11-02T10:15:30.123+00:00",
                        "title": "Python Engineer",
                    }
                }
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    store = FirestoreJobStore.local(db_path, verbose=False)

    job = store.get_job("abc")

    assert job["status"] == STATUS_APPLIED
    assert isinstance(job["applied_at"], datetime)
    assert job["applied_at"].tzinfo is not None
    assert job["applied_at"].isoformat() == "2026-11-02T10:15:30.123000+00:00"
    # And the store can keep editing the document afterwards.
    store.set_status("abc", STATUS_SKIPPED)
    assert read_db(db_path)["jobs"]["abc"]["status"] == STATUS_SKIPPED
    assert read_db(db_path)["jobs"]["abc"]["notes"] == "Applied from the dashboard"


# --- Backend selection ----------------------------------------------------------------


@pytest.fixture
def no_firebase_env(monkeypatch):
    for name in job_store.FIREBASE_ENV_VARS + ("IG_STATE_BACKEND", "IG_LOCAL_DB_PATH"):
        monkeypatch.delenv(name, raising=False)


def test_get_job_store_defaults_to_local_without_firebase(no_firebase_env, tmp_path, capsys):
    store = get_job_store(tmp_path / "state.json")

    assert isinstance(store._client, LocalFirestoreClient)
    assert "Firebase is not configured" in capsys.readouterr().out


def test_local_db_path_precedence(no_firebase_env, monkeypatch, tmp_path):
    assert job_store.local_db_path() == job_store.DEFAULT_LOCAL_DB_PATH

    monkeypatch.setenv("IG_LOCAL_DB_PATH", str(tmp_path / "shared.json"))
    assert job_store.local_db_path() == tmp_path / "shared.json"
    # An explicit argument always wins over the environment.
    assert job_store.local_db_path(tmp_path / "explicit.json") == tmp_path / "explicit.json"

    monkeypatch.setenv("IG_LOCAL_DB_PATH", "   ")
    assert job_store.local_db_path() == job_store.DEFAULT_LOCAL_DB_PATH


def test_get_job_store_honours_ig_local_db_path(no_firebase_env, monkeypatch, tmp_path):
    monkeypatch.setenv("IG_LOCAL_DB_PATH", str(tmp_path / "shared.json"))

    store = get_job_store(verbose=False)

    assert store._client.path == tmp_path / "shared.json"
    assert FirestoreJobStore.local(verbose=False)._client.path == tmp_path / "shared.json"


def test_get_job_store_uses_firestore_when_credentials_present(no_firebase_env, monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/key.json")
    monkeypatch.setattr(FirestoreJobStore, "from_env", classmethod(lambda cls: "real"))

    assert get_job_store() == "real"


def test_get_job_store_explicit_backends(no_firebase_env, monkeypatch, tmp_path):
    monkeypatch.setattr(FirestoreJobStore, "from_env", classmethod(lambda cls: "real"))

    monkeypatch.setenv("IG_STATE_BACKEND", "firestore")
    assert get_job_store() == "real"

    monkeypatch.setenv("IG_STATE_BACKEND", "local")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/key.json")
    assert isinstance(get_job_store(tmp_path / "x.json")._client, LocalFirestoreClient)

    monkeypatch.setenv("IG_STATE_BACKEND", "sqlite")
    with pytest.raises(RuntimeError, match="Unknown IG_STATE_BACKEND"):
        get_job_store()


def test_from_env_without_credentials_gives_helpful_error(no_firebase_env, monkeypatch):
    pytest.importorskip("google.cloud.firestore")
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError

    def no_credentials(*args, **kwargs):
        raise DefaultCredentialsError("none")

    monkeypatch.setattr(google.auth, "default", no_credentials)

    with pytest.raises(RuntimeError, match="No Firebase credentials found"):
        FirestoreJobStore.from_env()


def test_from_env_uses_inline_service_account(no_firebase_env, monkeypatch):
    pytest.importorskip("google.cloud.firestore")
    from google.cloud import firestore
    from google.oauth2 import service_account

    captured = {}

    class StubClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def collection(self, name):
            return name

    class StubCredentials:
        pass

    monkeypatch.setattr(firestore, "Client", StubClient)
    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_info",
        classmethod(lambda cls, info: StubCredentials()),
    )
    monkeypatch.setenv(
        "FIREBASE_SERVICE_ACCOUNT_JSON", json.dumps({"project_id": "my-proj"})
    )
    monkeypatch.setenv("FIRESTORE_JOBS_COLLECTION", "ig_jobs")

    store = FirestoreJobStore.from_env()

    assert captured["project"] == "my-proj"
    assert isinstance(captured["credentials"], StubCredentials)
    assert store._jobs == "ig_jobs"
