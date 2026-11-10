"""HTTP API for the job finder: start searches (the dashboard's Run search
button, ../frontend) and read or update tracked jobs.

    cd backend
    pipenv run uvicorn api:app --reload       # http://127.0.0.1:8000/docs

The cron job doesn't use this: it keeps running ``python job_search.py``. Both
call the same ``job_search.main()``, so a run started here searches, saves,
and emails exactly like a scheduled one.

Endpoints::

    GET  /health          liveness check (never needs the token)
    POST /runs            start a search in the background -> 202 {"run": ...}
                          body (optional): {"sites": ["accenture"], "include_unmarked": false}
                          409 {"error": ..., "run": ...} if a search is already running
    GET  /runs            runs started through this API, newest first (without output)
    GET  /runs/latest     the newest run with its output, or {"run": null}
    GET  /runs/{run_id}   one run with its output so far; poll it until status != "running"

    GET   /jobs           tracked jobs, filtered, sorted, and paged (see list_jobs below)
    GET   /jobs/stats     counts by status, company, track, and remote (same filters)
    POST  /jobs/reassess  re-score every saved job against your current skills -> summary
                          (?fetch=false: only jobs whose description is already saved)
                          409 while a search (or another reassessment) is running
    GET   /jobs/{job_id}  one job                                   404 if it isn't tracked
    PATCH /jobs/{job_id}  {"status": "applied", "notes": "...", "work_arrangement": "on_site"}
                          -> the updated job

Only one search runs at a time, and run history lives in memory, so start
the server with a single worker (uvicorn's default). Set ``IG_API_TOKEN`` to
require ``Authorization: Bearer <token>`` on everything but ``/health``; do
that before exposing the API beyond your own machine.
"""

from __future__ import annotations

import contextlib
import io
import os
import secrets
import sys
import threading
import traceback
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Literal, TextIO

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

import job_search
from job_queries import (
    REMOTE_STATUSES,
    JobFilters,
    JobStatus,
    SortKey,
    filter_jobs,
    job_stats,
    normalize_job,
    sort_jobs,
)
from job_store import JOB_STATUSES, FirestoreJobStore, get_job_store

API_TOKEN_ENV_VAR = "IG_API_TOKEN"
# A run's output is kept in memory for the dashboard; older lines are dropped.
MAX_OUTPUT_LINES = 2000
# How many finished runs GET /runs remembers.
RUN_HISTORY_SIZE = 20
# GET /jobs page size: default and maximum.
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500
# Same limit as the dashboard's notes editor.
MAX_NOTES_LENGTH = 5000

RunStatus = Literal["running", "succeeded", "failed"]
# (site selectors, include_unmarked) -> summary. Defaults to job_search.main.
SearchFunction = Callable[[list[str], bool], "job_search.RunSummary"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# --- Runs ------------------------------------------------------------------------------


@dataclass
class SearchRun:
    """One search started through the API, and everything it printed."""

    id: str
    sites: list[str]
    include_unmarked: bool
    started_at: datetime = field(default_factory=utcnow)
    status: RunStatus = "running"
    finished_at: datetime | None = None
    summary: job_search.RunSummary | None = None
    error: str | None = None
    # Set once the run has finished (tests and callers can wait on it).
    done: threading.Event = field(default_factory=threading.Event, repr=False)
    _output: deque[str] = field(
        default_factory=lambda: deque(maxlen=MAX_OUTPUT_LINES), repr=False
    )
    _dropped_lines: int = field(default=0, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_output(self, line: str) -> None:
        with self._lock:
            if len(self._output) == self._output.maxlen:
                self._dropped_lines += 1
            self._output.append(line)

    def finish(
        self,
        summary: job_search.RunSummary | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self.summary = summary
            self.error = error
            self.status = "failed" if error is not None else "succeeded"
            self.finished_at = utcnow()

    def to_dict(self, include_output: bool = True) -> dict[str, Any]:
        with self._lock:
            data: dict[str, Any] = {
                "id": self.id,
                "status": self.status,
                "sites": list(self.sites),
                "include_unmarked": self.include_unmarked,
                "started_at": _iso(self.started_at),
                "finished_at": _iso(self.finished_at),
                "summary": asdict(self.summary) if self.summary else None,
                "error": self.error,
            }
            if include_output:
                data["output"] = list(self._output)
                data["output_truncated"] = self._dropped_lines
        return data


class _OutputTee(io.TextIOBase):
    """Stands in for ``sys.stdout`` during a run: every line goes to the
    server's console as usual *and* into the run's output.

    ``sys.stdout`` is process-wide, so this also catches the lines printed by
    the search's worker threads. That's safe because only one run is active.
    """

    def __init__(self, run: SearchRun, passthrough: TextIO) -> None:
        super().__init__()
        self._run = run
        self._passthrough = passthrough
        self._partial = ""
        self._lock = threading.Lock()

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self._passthrough.write(text)
        with self._lock:
            *lines, self._partial = (self._partial + text).split("\n")
        for line in lines:
            self._run.add_output(line)
        return len(text)

    def flush(self) -> None:
        self._passthrough.flush()

    def flush_partial_line(self) -> None:
        with self._lock:
            partial, self._partial = self._partial, ""
        if partial:
            self._run.add_output(partial)


class RunInProgressError(RuntimeError):
    def __init__(self, run: SearchRun) -> None:
        super().__init__(f"A search is already running (run {run.id}).")
        self.run = run


class ReassessInProgressError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Saved jobs are being reassessed against your skills; try again in a moment.")


def _default_search(sites: list[str], include_unmarked: bool) -> job_search.RunSummary:
    # Looked up at call time, so tests can monkeypatch job_search.main.
    return job_search.main(site_selectors=sites or None, include_unmarked=include_unmarked)


class RunManager:
    """Starts searches on a background thread, one at a time, and remembers
    the last ``RUN_HISTORY_SIZE`` of them."""

    def __init__(self, search: SearchFunction = _default_search) -> None:
        self._search = search
        self._lock = threading.Lock()
        self._runs: deque[SearchRun] = deque(maxlen=RUN_HISTORY_SIZE)
        self._active: SearchRun | None = None
        self._reassessing = False

    @contextlib.contextmanager
    def reassessing(self) -> Any:
        """Hold while reassessing saved jobs: a search and a reassessment both
        rewrite jobs, so they never run at once. Raises ``RunInProgressError``
        or ``ReassessInProgressError`` if something else already is."""
        with self._lock:
            if self._active is not None:
                raise RunInProgressError(self._active)
            if self._reassessing:
                raise ReassessInProgressError()
            self._reassessing = True
        try:
            yield
        finally:
            with self._lock:
                self._reassessing = False

    def start(self, sites: list[str], include_unmarked: bool) -> SearchRun:
        with self._lock:
            if self._reassessing:
                raise ReassessInProgressError()
            if self._active is not None:
                raise RunInProgressError(self._active)
            run = SearchRun(
                id=uuid.uuid4().hex[:12], sites=sites, include_unmarked=include_unmarked
            )
            self._active = run
            self._runs.append(run)
        threading.Thread(
            target=self._execute, args=(run,), name=f"search-run-{run.id}", daemon=True
        ).start()
        return run

    def _execute(self, run: SearchRun) -> None:
        tee = _OutputTee(run, sys.stdout)
        summary: job_search.RunSummary | None = None
        error: str | None = None
        try:
            with contextlib.redirect_stdout(tee):
                print(f"Run {run.id} started from the API.")
                summary = self._search(list(run.sites), run.include_unmarked)
        except Exception as caught:  # a failed run is reported, not raised
            error = f"{type(caught).__name__}: {caught}"
            traceback.print_exc()  # the full traceback goes to the server log
        finally:
            tee.flush_partial_line()
            if error is not None:
                run.add_output(f"Run failed: {error}")
            run.finish(summary, error)
            with self._lock:
                self._active = None
            run.done.set()

    def get(self, run_id: str) -> SearchRun | None:
        with self._lock:
            return next((run for run in self._runs if run.id == run_id), None)

    def latest(self) -> SearchRun | None:
        with self._lock:
            return self._runs[-1] if self._runs else None

    def recent(self) -> list[SearchRun]:
        with self._lock:
            return list(reversed(self._runs))


# --- HTTP ------------------------------------------------------------------------------


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sites: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Same as job_search.py --site: a site name (accenture), a board "
        "kind (workday), or a careers page / job board URL. Empty means every "
        "site in JOB_SEARCH_URLS.",
    )
    include_unmarked: bool = Field(
        default=False,
        description="Same as --include-unmarked: also keep jobs whose site doesn't "
        "say whether they're remote.",
    )

    @field_validator("sites")
    @classmethod
    def _drop_blank_sites(cls, sites: list[str]) -> list[str]:
        return [site.strip() for site in sites if site.strip()]


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Require ``Authorization: Bearer $IG_API_TOKEN`` when that variable is set."""
    expected = os.environ.get(API_TOKEN_ENV_VAR, "").strip()
    if not expected:
        return
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        supplied.strip().encode(), expected.encode()
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing or wrong API token (see {API_TOKEN_ENV_VAR}).",
            headers={"WWW-Authenticate": "Bearer"},
        )


# --- Jobs ----------------------------------------------------------------------------


class StoreProvider:
    """Opens the job store on first use and keeps it (one Firestore client per
    process). A store that can't be opened is reported on every request and
    retried, so fixing the configuration doesn't need a restart."""

    def __init__(self, factory: Callable[[], FirestoreJobStore]) -> None:
        self._factory = factory
        self._store: FirestoreJobStore | None = None
        self._lock = threading.Lock()

    def __call__(self) -> FirestoreJobStore:
        with self._lock:
            if self._store is None:
                try:
                    self._store = self._factory()
                except Exception as error:
                    raise HTTPException(
                        status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Could not open the job store: {error}",
                    ) from error
            return self._store


def _default_store() -> FirestoreJobStore:
    # Quiet: the local stand-in would otherwise print every read.
    return get_job_store(verbose=False)


class Job(BaseModel):
    """A tracked job. Same shape as ``Job`` in frontend/src/lib/types.ts."""

    id: str = Field(description="Document ID, e.g. accenture-R00212345")
    job_id: str
    company: str | None
    title: str | None
    city: str | None
    state: str | None
    is_remote: bool | None = Field(
        description="null when the site doesn't say; follows work_arrangement when you've set it"
    )
    work_arrangement: str | None = Field(
        description='How you say the job is worked: "remote", "hybrid", "on_site"; null if you haven\'t'
    )
    site_is_remote: bool | None = Field(description="What the site says, before your work_arrangement")
    job_type: str | None
    salary_low: float | None
    salary_high: float | None
    url: str | None
    track: str | None
    posted_date: str | None
    matched_skills: list[str]
    score: int | float | None = Field(description="Number of matched skills")
    min_years: int | float | None
    fit_score: int | float | None = Field(
        description="How well the job fits you, 0-100 (job_fit.py); null on jobs saved before it existed"
    )
    fit_breakdown: dict[str, int | float] = Field(
        description='Points behind fit_score, e.g. {"skills": 48, "role": 30, "experience": -8}; they add up to it'
    )
    fit_reasons: list[str] = Field(description="The same breakdown in words")
    matches_skills: bool | None = Field(
        description="Whether the job still matches your skills; null until it's been (re)assessed"
    )
    skills_mismatch_reason: str | None = Field(
        description="Why it no longer matches, e.g. \"it doesn't mention any of your skills\""
    )
    not_remote_reason: str | None = Field(
        description="Why the job was marked not remote although its site said remote, "
        'e.g. \'its description: "must be onsite in Dallas"\''
    )
    status: str
    notes: str | None
    first_seen_at: str | None
    last_seen_at: str | None
    emailed_at: str | None
    applied_at: str | None
    status_updated_at: str | None
    work_arrangement_set_at: str | None
    gmail_message_id: str | None


class JobPage(BaseModel):
    jobs: list[Job]
    total: int = Field(description="Jobs matching the filters, before paging")
    limit: int
    offset: int


class JobStats(BaseModel):
    total: int
    applied: int = Field(description="Jobs you've applied to (status applied, or applied_at set)")
    by_status: dict[str, int]
    by_company: dict[str, int]
    by_track: dict[str, int]
    by_remote: dict[str, int]


class JobUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: JobStatus | None = None
    notes: str | None = Field(
        default=None,
        max_length=MAX_NOTES_LENGTH,
        description='Replaces the notes; "" or null clears them.',
    )
    work_arrangement: Literal["remote", "hybrid", "on_site"] | None = Field(
        default=None,
        description="How the job is really worked, whatever the site says; null goes back to the site's word.",
    )


class JobResponse(BaseModel):
    job: Job


class ReassessResult(BaseModel):
    """Mirrors ``job_search.ReassessSummary``."""

    total_jobs: int = Field(description="Every saved job")
    reassessed: int = Field(description="Jobs re-scored (those with a description)")
    changed: int = Field(description="Re-scored jobs whose skills, fit score, or match changed")
    no_longer_match: int = Field(description="Re-scored jobs that wouldn't match your skills now")
    fetched: int = Field(description="Descriptions loaded from the job sites this time")
    unavailable: int = Field(description="Jobs left as they were: their posting couldn't be loaded")
    skills_source: Literal["saved", "default"]


def _split(values: list[str] | None) -> tuple[str, ...]:
    """Repeated and comma-separated values: ?status=emailed&status=applied or ?status=emailed,applied."""
    return tuple(part.strip() for value in values or [] for part in value.split(",") if part.strip())


def _check_choices(name: str, values: tuple[str, ...], allowed: tuple[str, ...]) -> None:
    unknown = [value for value in values if value not in allowed]
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown {name} {', '.join(map(repr, unknown))}; expected one of {', '.join(allowed)}",
        )


def job_filters(
    q: str | None = Query(
        None, description="Text to find in the title, company, skills, location, job type, notes, track, or ID"
    ),
    status_: list[str] | None = Query(
        None,
        alias="status",
        description=f"Any of these statuses (repeat or comma-separate): {', '.join(JOB_STATUSES)}",
    ),
    company: list[str] | None = Query(None, description="Any of these companies (repeat for several)"),
    track: list[str] | None = Query(
        None, description='Track name or its start: "core", "java", "ios", ".net" (repeat for several)'
    ),
    remote: list[str] | None = Query(
        None, description=f"Any of: {', '.join(REMOTE_STATUSES)} (unmarked: the site didn't say)"
    ),
    skill: list[str] | None = Query(
        None, description="Matched skills the job must have; repeat for several (all are required)"
    ),
    min_salary: float | None = Query(
        None, ge=0, description='Highest listed amount at least this. Excludes "Not listed"'
    ),
    posted_since: date | None = Query(None, description="Posted on or after this date (YYYY-MM-DD)"),
    seen_since: date | None = Query(None, description="Last seen by the search on or after this date"),
    applied: bool | None = Query(None, description="Only jobs you have (true) or haven't (false) applied to"),
) -> JobFilters:
    statuses = _split(status_)
    remote_values = _split(remote)
    _check_choices("status", statuses, JOB_STATUSES)
    _check_choices("remote", remote_values, REMOTE_STATUSES)
    return JobFilters(
        q=q.strip() if q and q.strip() else None,
        statuses=statuses,
        companies=tuple(c.strip() for c in company or [] if c.strip()),
        tracks=tuple(t.strip() for t in track or [] if t.strip()),
        remote=remote_values,
        skills=tuple(s.strip() for s in skill or [] if s.strip()),
        min_salary=min_salary,
        posted_since=posted_since,
        seen_since=seen_since,
        applied=applied,
    )


def _all_jobs(store: FirestoreJobStore) -> list[dict[str, Any]]:
    return [normalize_job(doc_id, data) for doc_id, data in store.list_job_documents()]


def _job_not_found(job_id: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} is not in the store")


def _default_reassess(store: FirestoreJobStore, fetch: bool) -> "job_search.ReassessSummary":
    # Looked up at call time, so tests can monkeypatch it.
    return job_search.reassess_saved_jobs(store, fetch_missing=fetch)


def create_app(
    manager: RunManager | None = None,
    store_factory: Callable[[], FirestoreJobStore] = _default_store,
    reassess: Callable[[FirestoreJobStore, bool], "job_search.ReassessSummary"] = _default_reassess,
) -> FastAPI:
    manager = manager or RunManager()
    open_store = StoreProvider(store_factory)
    app = FastAPI(
        title="Job Finder API",
        summary="Start job searches from the dashboard. The cron job runs job_search.py directly.",
    )
    app.state.runs = manager

    # Errors look like the dashboard's own API: {"error": "..."}.
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Any, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {"error": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Any, exc: RequestValidationError) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'][1:]) or 'body'}: {error['msg']}"
            for error in exc.errors()
        )
        return JSONResponse({"error": f"Invalid request: {problems}"}, status_code=422)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    authorized = [Depends(require_token)]

    @app.post("/runs", status_code=status.HTTP_202_ACCEPTED, dependencies=authorized)
    def start_run(body: RunRequest | None = None) -> Any:
        body = body or RunRequest()
        try:
            run = manager.start(body.sites, body.include_unmarked)
        except ReassessInProgressError as busy:
            return JSONResponse({"error": str(busy)}, status_code=status.HTTP_409_CONFLICT)
        except RunInProgressError as busy:
            return JSONResponse(
                {"error": str(busy), "run": busy.run.to_dict()},
                status_code=status.HTTP_409_CONFLICT,
            )
        return {"run": run.to_dict()}

    @app.get("/runs", dependencies=authorized)
    def list_runs() -> dict[str, Any]:
        return {"runs": [run.to_dict(include_output=False) for run in manager.recent()]}

    @app.get("/runs/latest", dependencies=authorized)
    def latest_run() -> dict[str, Any]:
        run = manager.latest()
        return {"run": run.to_dict() if run else None}

    @app.get("/runs/{run_id}", dependencies=authorized)
    def get_run(run_id: str) -> dict[str, Any]:
        run = manager.get(run_id)
        if run is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"No run {run_id} (runs are kept in memory until the API restarts).",
            )
        return {"run": run.to_dict()}

    @app.get("/jobs", response_model=JobPage, dependencies=authorized)
    def list_jobs(
        filters: JobFilters = Depends(job_filters),
        sort: SortKey = Query("last_seen", description="Same as the dashboard's Sort menu"),
        limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        offset: int = Query(0, ge=0),
        store: FirestoreJobStore = Depends(open_store),
    ) -> dict[str, Any]:
        """Tracked jobs, filtered and sorted. Filters combine with AND; a filter
        given several values matches any of them (except `skill`: all needed)."""
        jobs = sort_jobs(filter_jobs(_all_jobs(store), filters), sort)
        return {"jobs": jobs[offset : offset + limit], "total": len(jobs), "limit": limit, "offset": offset}

    # Declared before /jobs/{job_id} so "stats" isn't taken for a job ID.
    @app.get("/jobs/stats", response_model=JobStats, dependencies=authorized)
    def jobs_stats(
        filters: JobFilters = Depends(job_filters),
        store: FirestoreJobStore = Depends(open_store),
    ) -> dict[str, Any]:
        """Counts of the jobs matching the filters (all jobs without any)."""
        return job_stats(filter_jobs(_all_jobs(store), filters))

    @app.post("/jobs/reassess", response_model=ReassessResult, dependencies=authorized)
    def reassess_jobs(
        fetch: bool = Query(
            True,
            description="Load descriptions not saved yet from the job sites (false: re-score "
            "only the jobs whose description is already saved)",
        ),
        store: FirestoreJobStore = Depends(open_store),
    ) -> Any:
        """Re-score every saved job against your current skills (the dashboard's
        Skills page): matched skills, fit score, and whether it still matches.
        Jobs that no longer match are flagged, never deleted. The first time,
        descriptions are loaded from the job sites, which can take a minute;
        after that it's quick. The dashboard's Refresh button calls this."""
        try:
            with manager.reassessing():
                summary = reassess(store, fetch)
        except RunInProgressError as busy:
            return JSONResponse(
                {"error": f"{busy} It reassesses saved jobs when it finishes.", "run": busy.run.to_dict()},
                status_code=status.HTTP_409_CONFLICT,
            )
        except ReassessInProgressError as busy:
            return JSONResponse({"error": str(busy)}, status_code=status.HTTP_409_CONFLICT)
        return asdict(summary)

    @app.get("/jobs/{job_id}", response_model=JobResponse, dependencies=authorized)
    def get_job(job_id: str, store: FirestoreJobStore = Depends(open_store)) -> dict[str, Any]:
        data = store.get_job(job_id)
        if data is None:
            raise _job_not_found(job_id)
        return {"job": normalize_job(job_id, data)}

    @app.patch("/jobs/{job_id}", response_model=JobResponse, dependencies=authorized)
    def update_job(
        job_id: str, body: JobUpdate, store: FirestoreJobStore = Depends(open_store)
    ) -> dict[str, Any]:
        """Change a job's status and/or notes, exactly like the dashboard does
        (status also sets status_updated_at, and applied_at for "applied")."""
        notes = (body.notes or "").strip() if "notes" in body.model_fields_set else None
        arrangement_given = "work_arrangement" in body.model_fields_set
        if body.status is None and notes is None and not arrangement_given:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Nothing to update: provide status, notes, and/or work_arrangement",
            )
        try:
            data = store.update_job(
                job_id,
                status=body.status,
                notes=notes,
                work_arrangement=body.work_arrangement,
                clear_work_arrangement=arrangement_given and body.work_arrangement is None,
            )
        except KeyError:
            raise _job_not_found(job_id) from None
        return {"job": normalize_job(job_id, data)}

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("IG_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT") or os.environ.get("IG_API_PORT") or 8000),
    )
