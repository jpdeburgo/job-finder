"""Persist seen, emailed, and applied jobs in Firebase Firestore.

``FirestoreJobStore`` holds all of the job-tracking logic and talks to a
Firestore client. Two clients are supported:

* the real ``google.cloud.firestore.Client`` (used when Firebase credentials
  are configured), and
* ``LocalFirestoreClient`` -- a drop-in stand-in backed by ``local_firestore.json``
  that mirrors Firestore's collections/documents layout and prints every call
  it would have made. No Firebase setup needed for local runs or tests.

Layout of the ``jobs`` collection (one document per job ID:
``<company>-<the site's own ID>``, e.g. ``accenture-R00212345`` or
``insight-global-6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba``)::

    jobs/insight-global-6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba
        job_id, company, title, url, track, matched_skills, score, salary_low, ...
        status            unemailed | emailed | applied | skipped |
                          interviewing | rejected | offer
        first_seen_at, last_seen_at, emailed_at, applied_at,
        status_updated_at, notes

The ``runs`` collection gets one auto-ID document per script run, and the
``settings`` collection holds your own skill list from the dashboard
(``settings/search_skills``; see search_skills.py).

Each job's description is kept apart from it, in ``job_descriptions`` (same
document ID: ``{"text": ..., "saved_at": ...}``), so saved jobs can be
re-scored when you change your skills without loading every posting again,
and the dashboard's job list stays small.
"""

from __future__ import annotations

import json
import os
import random
import string
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Iterator

from search_skills import SEARCH_SKILLS_DOCUMENT, SearchSkills

if TYPE_CHECKING:  # pragma: no cover - typing only
    from job_search import JobMatch

# Workflow statuses. A job is saved as "unemailed" the moment it matches, flips
# to "emailed" once Gmail accepts the digest, and everything after that is set
# by you (the ../frontend dashboard, jobs_cli.py, or the Firebase console).
# Keep in sync with JOB_STATUSES in ../frontend/src/lib/types.ts.
STATUS_UNEMAILED = "unemailed"  # matched and saved, but the digest wasn't sent yet
STATUS_EMAILED = "emailed"
STATUS_APPLIED = "applied"
STATUS_SKIPPED = "skipped"
STATUS_INTERVIEWING = "interviewing"
STATUS_REJECTED = "rejected"
STATUS_OFFER = "offer"
JOB_STATUSES = (
    STATUS_UNEMAILED,
    STATUS_EMAILED,
    STATUS_APPLIED,
    STATUS_SKIPPED,
    STATUS_INTERVIEWING,
    STATUS_REJECTED,
    STATUS_OFFER,
)

# How you say a job is actually worked, overriding what the site claims
# ("work_arrangement" on the job). Keep in sync with WORK_ARRANGEMENTS in
# ../frontend/src/lib/types.ts.
WORK_ARRANGEMENTS = ("remote", "hybrid", "on_site")

DEFAULT_JOBS_COLLECTION = "jobs"
DEFAULT_RUNS_COLLECTION = "runs"
DEFAULT_SETTINGS_COLLECTION = "settings"
DEFAULT_DESCRIPTIONS_COLLECTION = "job_descriptions"
DEFAULT_LOCAL_DB_PATH = Path(__file__).with_name("local_firestore.json")
# Optional override for the stand-in's location. The Next.js dashboard in
# ../frontend reads the same variable, so both sides agree on one file.
LOCAL_DB_PATH_ENV_VAR = "IG_LOCAL_DB_PATH"
# Firestore caps a batched write at 500 operations; stay comfortably under it.
FIRESTORE_BATCH_SIZE = 400
# Environment variables that indicate real Firebase credentials are available.
FIREBASE_ENV_VARS = (
    "GOOGLE_APPLICATION_CREDENTIALS",
    "FIREBASE_SERVICE_ACCOUNT_JSON",
    "FIRESTORE_EMULATOR_HOST",
    "FIREBASE_PROJECT_ID",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def local_db_path(override: Path | str | None = None) -> Path:
    """Return the stand-in's path: explicit argument, then ``IG_LOCAL_DB_PATH``,
    then ``local_firestore.json`` next to this module."""
    if override:
        return Path(override)
    configured = os.environ.get(LOCAL_DB_PATH_ENV_VAR, "").strip()
    return Path(configured) if configured else DEFAULT_LOCAL_DB_PATH


def job_document(job: "JobMatch") -> dict[str, Any]:
    """Return the job's searchable details as a flat, Firestore-friendly dict.
    The description is saved separately (``job_descriptions``)."""
    data = asdict(job)
    data.pop("description", None)
    data["score"] = job.score
    return data


class FirestoreJobStore:
    """Job state in Firestore (real client or ``LocalFirestoreClient``)."""

    def __init__(
        self,
        client: Any,
        jobs_collection: str = DEFAULT_JOBS_COLLECTION,
        runs_collection: str = DEFAULT_RUNS_COLLECTION,
        settings_collection: str = DEFAULT_SETTINGS_COLLECTION,
        descriptions_collection: str = DEFAULT_DESCRIPTIONS_COLLECTION,
    ) -> None:
        self._client = client
        self._jobs = client.collection(jobs_collection)
        self._runs = client.collection(runs_collection)
        self._settings = client.collection(settings_collection)
        self._descriptions = client.collection(descriptions_collection)

    @property
    def description(self) -> str:
        describe = getattr(self._client, "describe", None)
        return describe() if callable(describe) else f"Firestore project {self._client.project!r}"

    # Construction --------------------------------------------------------

    @classmethod
    def from_env(cls) -> "FirestoreJobStore":
        """Connect to real Firestore using environment variables.

        Credentials are resolved in this order:

        1. ``FIREBASE_SERVICE_ACCOUNT_JSON`` -- the service-account JSON pasted
           inline (handy for hosts without secret files).
        2. ``GOOGLE_APPLICATION_CREDENTIALS`` -- path to the service-account
           JSON file (standard Google "application default credentials").
        3. ``FIRESTORE_EMULATOR_HOST`` -- the local emulator, no credentials.
        """
        try:
            from google.auth.exceptions import DefaultCredentialsError
            from google.cloud import firestore
        except ImportError as error:  # pragma: no cover - depends on install
            raise RuntimeError(
                "google-cloud-firestore is not installed. Run "
                "`pipenv install google-cloud-firestore`."
            ) from error

        project = os.environ.get("FIREBASE_PROJECT_ID") or None
        database = os.environ.get("FIRESTORE_DATABASE") or None
        inline_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")

        kwargs: dict[str, Any] = {"project": project, "database": database}
        if inline_json:
            from google.oauth2 import service_account

            info = json.loads(inline_json)
            kwargs["credentials"] = service_account.Credentials.from_service_account_info(
                info
            )
            kwargs["project"] = project or info.get("project_id")

        try:
            client = firestore.Client(**kwargs)
        except DefaultCredentialsError as error:
            raise RuntimeError(
                "No Firebase credentials found. Set GOOGLE_APPLICATION_CREDENTIALS "
                "to your service-account JSON path (or FIREBASE_SERVICE_ACCOUNT_JSON "
                "to its contents), or set IG_STATE_BACKEND=local to use "
                f"{DEFAULT_LOCAL_DB_PATH.name} instead. See README.md for Firebase setup."
            ) from error

        return cls(client, **cls._collection_names())

    @classmethod
    def local(cls, path: Path | None = None, verbose: bool = True) -> "FirestoreJobStore":
        """Use the JSON-file stand-in instead of Firebase."""
        client = LocalFirestoreClient(local_db_path(path), verbose=verbose)
        return cls(client, **cls._collection_names())

    @staticmethod
    def _collection_names() -> dict[str, str]:
        return {
            "jobs_collection": os.environ.get(
                "FIRESTORE_JOBS_COLLECTION", DEFAULT_JOBS_COLLECTION
            ),
            "runs_collection": os.environ.get(
                "FIRESTORE_RUNS_COLLECTION", DEFAULT_RUNS_COLLECTION
            ),
            "settings_collection": os.environ.get(
                "FIRESTORE_SETTINGS_COLLECTION", DEFAULT_SETTINGS_COLLECTION
            ),
            "descriptions_collection": os.environ.get(
                "FIRESTORE_DESCRIPTIONS_COLLECTION", DEFAULT_DESCRIPTIONS_COLLECTION
            ),
        }

    # Reads ----------------------------------------------------------------

    @staticmethod
    def _doc_id(job_id: str | int) -> str:
        return str(job_id)

    def load_seen_ids(self) -> set[str]:
        """Return every job ID in the store (any status)."""
        # list_documents() only transfers document names, not fields.
        return {reference.id for reference in self._jobs.list_documents()}

    def load_unemailed_ids(self) -> set[str]:
        """Return IDs saved by an earlier run whose digest never went out."""
        return {
            doc.id for doc in self._where("status", "==", STATUS_UNEMAILED).stream()
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        snapshot = self._jobs.document(self._doc_id(job_id)).get()
        return snapshot.to_dict() if snapshot.exists else None

    def list_jobs(
        self, status: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Return jobs, newest ``last_seen_at`` first, optionally by status."""
        query = self._where("status", "==", status) if status else self._jobs
        # Sorting client-side avoids needing a composite (status, last_seen_at)
        # index in Firestore; the collection is small.
        jobs = self._sort_newest_first([doc.to_dict() for doc in query.stream()])
        return jobs[:limit] if limit else jobs

    def list_job_documents(self) -> list[tuple[str, dict[str, Any]]]:
        """Every job as ``(document ID, fields)``, in no particular order (api.py
        filters and sorts them; see job_queries.py)."""
        return [(doc.id, doc.to_dict()) for doc in self._jobs.stream()]

    def load_search_skills(self) -> dict[str, Any] | None:
        """The skill list saved from the dashboard (``settings/search_skills``)
        as stored, or None if you haven't saved one (the search then uses the
        defaults in job_search.py). ``search_skills.skills_from_document``
        validates it."""
        snapshot = self._settings.document(SEARCH_SKILLS_DOCUMENT).get()
        return snapshot.to_dict() if snapshot.exists else None

    def load_descriptions(self) -> dict[str, str]:
        """Every saved job description, by job ID."""
        return {
            doc.id: str(data.get("text") or "")
            for doc in self._descriptions.stream()
            if (data := doc.to_dict()) and data.get("text")
        }

    def _where(self, field: str, op: str, value: Any) -> Any:
        try:
            from google.cloud.firestore_v1 import FieldFilter
        except ImportError:  # google-cloud-firestore not installed; local only
            FieldFilter = LocalFieldFilter  # noqa: N806 - mirrors the import
        # Both clients read .field_path / .op_string / .value off the filter.
        return self._jobs.where(filter=FieldFilter(field, op, value))

    # Writes ---------------------------------------------------------------

    def save_matches(self, matches: Iterable["JobMatch"], new_ids: set[str]) -> None:
        """Upsert this run's matches.

        Jobs in ``new_ids`` are created as ``unemailed`` with ``first_seen_at``.
        Jobs seen before only get their details and ``last_seen_at``
        refreshed, so a status you set by hand is never overwritten.
        """
        matches = list(matches)
        now = utcnow()
        self._commit_in_batches(
            [
                (self._doc_id(job.job_id), self._match_fields(job, job.job_id in new_ids, now))
                for job in matches
            ]
        )
        self.save_descriptions({job.job_id: job.description for job in matches if job.description})

    def save_descriptions(self, texts: dict[str, str]) -> None:
        """Keep jobs' descriptions (by job ID), for re-scoring them later."""
        now = utcnow()
        self._commit_in_batches(
            [(self._doc_id(job_id), {"text": text, "saved_at": now}) for job_id, text in sorted(texts.items())],
            self._descriptions,
        )

    def update_jobs(self, fields_by_id: dict[str, dict[str, Any]]) -> None:
        """Merge ``fields`` into each job (batched); used to re-score saved jobs."""
        self._commit_in_batches(
            [(self._doc_id(job_id), fields) for job_id, fields in sorted(fields_by_id.items())]
        )

    def mark_emailed(self, job_ids: Iterable[str], gmail_message_id: str | None) -> None:
        """Flip ``unemailed`` jobs to ``emailed`` after Gmail accepts the digest."""
        now = utcnow()
        fields = {
            "status": STATUS_EMAILED,
            "emailed_at": now,
            "status_updated_at": now,
            "gmail_message_id": gmail_message_id,
        }
        self._commit_in_batches([(self._doc_id(job_id), dict(fields)) for job_id in job_ids])

    def mark_not_remote(self, reasons: dict[str, str]) -> None:
        """Set ``is_remote`` to False on saved jobs whose posting says on-site or
        hybrid, recording why in ``not_remote_reason``. Status is left alone."""
        now = utcnow()
        self._commit_in_batches(
            [
                (
                    self._doc_id(job_id),
                    {"is_remote": False, "not_remote_reason": reason, "remote_checked_at": now},
                )
                for job_id, reason in sorted(reasons.items())
            ]
        )

    def set_status(
        self, job_id: str, status: str, note: str | None = None
    ) -> dict[str, Any]:
        """Update a job's workflow status and return the updated document."""
        reference = self._jobs.document(self._doc_id(job_id))
        if not reference.get().exists:
            raise KeyError(f"Job {job_id} is not in the store")
        reference.update(self._status_fields(status, note, utcnow()))
        return reference.get().to_dict()

    def update_job(
        self,
        job_id: str,
        status: str | None = None,
        notes: str | None = None,
        work_arrangement: str | None = None,
        clear_work_arrangement: bool = False,
    ) -> dict[str, Any]:
        """Change a job's status, notes, and/or work arrangement; return the
        updated document.

        Writes the same fields as the dashboard's PATCH /api/jobs/:id:
        ``status`` sets ``status_updated_at`` (and ``applied_at`` for
        "applied"), ``notes`` replaces the notes (``""`` clears them), and
        ``work_arrangement`` ("remote", "hybrid", "on_site") records how the
        job is really worked, whatever the site says (``clear_work_arrangement``
        goes back to the site's word). Raises ``KeyError`` for an unknown job,
        ``ValueError`` for an unknown value or when there is nothing to change.
        """
        if status is None and notes is None and work_arrangement is None and not clear_work_arrangement:
            raise ValueError("Nothing to update: provide status, notes, and/or work_arrangement")
        now = utcnow()
        fields = self._status_fields(status, None, now) if status is not None else {}
        if notes is not None:
            fields["notes"] = notes
        if work_arrangement is not None or clear_work_arrangement:
            fields.update(self.work_arrangement_fields(work_arrangement, now))
        reference = self._jobs.document(self._doc_id(job_id))
        if not reference.get().exists:
            raise KeyError(f"Job {job_id} is not in the store")
        reference.update(fields)
        return reference.get().to_dict()

    def save_search_skills(self, skills: SearchSkills) -> None:
        """Save your own skill list, exactly as the dashboard's Skills page does."""
        self._settings.document(SEARCH_SKILLS_DOCUMENT).set(
            {**skills.as_document(), "updated_at": utcnow()}
        )

    def log_run(
        self,
        *,
        total_matches: int,
        new_job_ids: list[str],
        email_sent: bool,
        gmail_message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Record a summary of one script run in the ``runs`` collection."""
        self._runs.add(
            {
                "ran_at": utcnow(),
                "total_matches": total_matches,
                "new_matches": len(new_job_ids),
                "new_job_ids": sorted(new_job_ids),
                "email_sent": email_sent,
                "gmail_message_id": gmail_message_id,
                "error": error,
            }
        )

    def import_documents(self, documents: dict[str, dict[str, Any]]) -> int:
        """Copy full job documents (e.g. from local_firestore.json) that aren't
        already present; returns how many were added."""
        existing = {self._doc_id(i) for i in self.load_seen_ids()}
        writes = [
            (doc_id, dict(fields))
            for doc_id, fields in sorted(documents.items())
            if doc_id not in existing
        ]
        self._commit_in_batches(writes)
        return len(writes)

    def _commit_in_batches(
        self, writes: list[tuple[str, dict[str, Any]]], collection: Any = None
    ) -> None:
        collection = self._jobs if collection is None else collection
        for start in range(0, len(writes), FIRESTORE_BATCH_SIZE):
            batch = self._client.batch()
            for doc_id, fields in writes[start : start + FIRESTORE_BATCH_SIZE]:
                batch.set(collection.document(doc_id), fields, merge=True)
            batch.commit()

    # Field helpers ----------------------------------------------------------

    @staticmethod
    def _match_fields(job: "JobMatch", is_new: bool, now: datetime) -> dict[str, Any]:
        fields = job_document(job)
        # The search just matched it on your current skills.
        fields.update(matches_skills=True, skills_mismatch_reason=None)
        fields["last_seen_at"] = now
        if is_new:
            fields.update(first_seen_at=now, status=STATUS_UNEMAILED, status_updated_at=now)
        return fields

    @staticmethod
    def work_arrangement_fields(value: str | None, now: datetime) -> dict[str, Any]:
        """Fields for your say on a job's work arrangement (None clears it).

        It lives next to the site's ``is_remote`` rather than replacing it, so
        searches can keep refreshing the site's value without undoing yours;
        readers use yours when it's set (job_queries.normalize_job).
        """
        if value is not None and value not in WORK_ARRANGEMENTS:
            raise ValueError(
                f"Unknown work arrangement {value!r}; expected one of {', '.join(WORK_ARRANGEMENTS)}"
            )
        return {"work_arrangement": value, "work_arrangement_set_at": now if value else None}

    @staticmethod
    def _status_fields(status: str, note: str | None, now: datetime) -> dict[str, Any]:
        if status not in JOB_STATUSES:
            raise ValueError(
                f"Unknown status {status!r}; expected one of {', '.join(JOB_STATUSES)}"
            )
        fields: dict[str, Any] = {"status": status, "status_updated_at": now}
        if status == STATUS_APPLIED:
            fields["applied_at"] = now
        if note:
            fields["notes"] = note
        return fields

    @staticmethod
    def _sort_newest_first(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def key(job: dict[str, Any]) -> str:
            value = job.get("last_seen_at") or job.get("first_seen_at") or ""
            return value.isoformat() if isinstance(value, datetime) else str(value)

        return sorted(jobs, key=key, reverse=True)


# --- Local stand-in for google.cloud.firestore --------------------------------


class LocalFieldFilter:
    """Mirror of ``google.cloud.firestore_v1.FieldFilter``."""

    def __init__(self, field_path: str, op_string: str, value: Any) -> None:
        self.field_path = field_path
        self.op_string = op_string
        self.value = value


class LocalSnapshot:
    def __init__(self, reference: "LocalDocumentReference", data: dict[str, Any] | None):
        self.reference = reference
        self.id = reference.id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return dict(self._data) if self._data is not None else None


class LocalDocumentReference:
    def __init__(self, collection: "LocalCollectionReference", doc_id: str) -> None:
        self._collection = collection
        self.id = doc_id

    @property
    def path(self) -> str:
        return f"{self._collection.id}/{self.id}"

    def get(self) -> LocalSnapshot:
        return LocalSnapshot(self, self._collection._client._read(self._collection.id).get(self.id))

    def set(self, document_data: dict[str, Any], merge: bool = False) -> None:
        self._collection._client._apply([("set", self, document_data, merge)])

    def update(self, field_updates: dict[str, Any]) -> None:
        self._collection._client._apply([("update", self, field_updates, False)])


class LocalQuery:
    def __init__(self, collection: "LocalCollectionReference", filters: list[LocalFieldFilter]):
        self._collection = collection
        self._filters = filters

    def where(self, *args: Any, filter: Any = None) -> "LocalQuery":  # noqa: A002
        field_filter = filter if filter is not None else LocalFieldFilter(*args)
        return LocalQuery(self._collection, self._filters + [field_filter])

    def stream(self) -> Iterator[LocalSnapshot]:
        client = self._collection._client
        docs = client._read(self._collection.id)
        described = " ".join(f"{f.field_path} {f.op_string} {f.value!r}" for f in self._filters)
        client._log(f"query {self._collection.id}" + (f" where {described}" if described else ""))
        for doc_id, data in docs.items():
            if all(self._matches(data, f) for f in self._filters):
                yield LocalSnapshot(LocalDocumentReference(self._collection, doc_id), data)

    @staticmethod
    def _matches(data: dict[str, Any], field_filter: LocalFieldFilter) -> bool:
        actual = data.get(field_filter.field_path)
        if field_filter.op_string == "==":
            return actual == field_filter.value
        if field_filter.op_string == "!=":
            return field_filter.field_path in data and actual != field_filter.value
        if field_filter.op_string == "in":
            return actual in field_filter.value
        raise NotImplementedError(f"LocalFirestoreClient does not support {field_filter.op_string!r}")


class LocalCollectionReference(LocalQuery):
    def __init__(self, client: "LocalFirestoreClient", collection_id: str) -> None:
        super().__init__(self, [])
        self._client = client
        self.id = collection_id

    def document(self, document_id: str) -> LocalDocumentReference:
        return LocalDocumentReference(self, document_id)

    def list_documents(self) -> Iterator[LocalDocumentReference]:
        self._client._log(f"list_documents {self.id}")
        for doc_id in self._client._read(self.id):
            yield LocalDocumentReference(self, doc_id)

    def add(self, document_data: dict[str, Any]) -> tuple[Any, LocalDocumentReference]:
        reference = self.document(_auto_id())
        reference.set(document_data)
        return None, reference


class LocalWriteBatch:
    def __init__(self, client: "LocalFirestoreClient") -> None:
        self._client = client
        self._ops: list[tuple[str, LocalDocumentReference, dict[str, Any], bool]] = []

    def set(self, reference: LocalDocumentReference, document_data: dict[str, Any], merge: bool = False) -> None:
        self._ops.append(("set", reference, document_data, merge))

    def update(self, reference: LocalDocumentReference, field_updates: dict[str, Any]) -> None:
        self._ops.append(("update", reference, field_updates, False))

    def commit(self) -> list:
        if len(self._ops) > 500:
            raise ValueError("Firestore batches are capped at 500 writes")
        self._client._log(f"batch commit ({len(self._ops)} writes)")
        self._client._apply(self._ops, indent="  ")
        self._ops = []
        return []


class LocalFirestoreClient:
    """File-backed stand-in for the subset of ``google.cloud.firestore.Client``
    that ``FirestoreJobStore`` uses. Prints each call it would have made."""

    def __init__(self, path: Path, verbose: bool = True) -> None:
        self.path = Path(path)
        self.verbose = verbose
        self.project = "local"

    def describe(self) -> str:
        return f"local Firestore stand-in at {self.path}"

    def collection(self, collection_id: str) -> LocalCollectionReference:
        return LocalCollectionReference(self, collection_id)

    def batch(self) -> LocalWriteBatch:
        return LocalWriteBatch(self)

    # Internals ------------------------------------------------------------

    def _log(self, message: str, indent: str = "") -> None:
        if self.verbose:
            print(f"[local firestore] {indent}{message}")

    def _load(self) -> dict[str, dict[str, dict[str, Any]]]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(
                f"{self.path} should map collection names to documents, "
                'e.g. {"jobs": {...}, "runs": {...}}'
            )
        return {
            collection: {doc_id: _decode(fields) for doc_id, fields in docs.items()}
            for collection, docs in data.items()
        }

    def _read(self, collection_id: str) -> dict[str, dict[str, Any]]:
        return self._load().get(collection_id, {})

    def _save(self, data: dict[str, dict[str, dict[str, Any]]]) -> None:
        content = json.dumps(data, indent=2, sort_keys=True, default=_encode) + "\n"
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        temporary_path.replace(self.path)

    def _apply(
        self,
        ops: list[tuple[str, LocalDocumentReference, dict[str, Any], bool]],
        indent: str = "",
    ) -> None:
        data = self._load()
        for kind, reference, fields, merge in ops:
            docs = data.setdefault(reference._collection.id, {})
            existing = docs.get(reference.id)
            if kind == "update":
                if existing is None:
                    raise KeyError(f"No document to update: {reference.path}")
                existing.update(fields)
            elif merge and existing is not None:
                existing.update(fields)
            else:
                docs[reference.id] = dict(fields)
            summary = ", ".join(
                f"{key}={fields[key]!r}" for key in ("status", "title") if key in fields
            )
            self._log(
                f"{kind} {reference.path}"
                + (" (merge)" if kind == "set" and merge else "")
                + (f": {summary}" if summary else ""),
                indent,
            )
        self._save(data)


def _auto_id(length: int = 20) -> str:
    """Random alphanumeric ID like Firestore generates for ``add()``."""
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def _encode(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _decode(fields: dict[str, Any]) -> dict[str, Any]:
    """Turn ISO strings in ``*_at`` fields back into datetimes, like Firestore
    returns Timestamp fields as datetimes."""
    decoded = {}
    for key, value in fields.items():
        if key.endswith("_at") and isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                pass
        decoded[key] = value
    return decoded


# --- Backend selection --------------------------------------------------------


def firebase_configured() -> bool:
    return any(os.environ.get(name) for name in FIREBASE_ENV_VARS)


def get_job_store(local_path: Path | None = None, verbose: bool = True) -> FirestoreJobStore:
    """Return the store selected by ``IG_STATE_BACKEND``.

    * ``auto`` (default): real Firestore when Firebase credentials are
      configured, otherwise the local JSON stand-in.
    * ``firestore``: always real Firestore (fails loudly if unconfigured).
    * ``local``: always the local stand-in.
    """
    backend = os.environ.get("IG_STATE_BACKEND", "auto").strip().lower()
    if backend == "auto":
        backend = "firestore" if firebase_configured() else "local"
        if backend == "local" and verbose:
            print(
                "Firebase is not configured; using the local Firestore stand-in "
                f"({local_db_path(local_path).name}). "
                "Set GOOGLE_APPLICATION_CREDENTIALS to use the real database."
            )
    if backend == "firestore":
        return FirestoreJobStore.from_env()
    if backend == "local":
        return FirestoreJobStore.local(local_path, verbose=verbose)
    raise RuntimeError(
        f"Unknown IG_STATE_BACKEND={backend!r}; expected 'auto', 'firestore', or 'local'"
    )
