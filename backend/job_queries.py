"""Read-side helpers behind the jobs endpoints in api.py: normalise, filter,
sort, and count the documents ``FirestoreJobStore.list_jobs()`` returns.

Everything here is a pure function over plain dicts (no I/O), and mirrors
``frontend/src/lib/jobs.ts`` so the dashboard and the API agree on what a
job looks like, what the filters mean, and how each sort orders jobs.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Literal, get_args

from job_store import JOB_STATUSES, STATUS_APPLIED

TIMESTAMP_FIELDS = ("first_seen_at", "last_seen_at", "emailed_at", "applied_at", "status_updated_at")
# Same keys and directions as the dashboard's Sort menu.
SortKey = Literal["last_seen", "posted", "salary", "score", "fit", "title", "status"]
SORT_KEYS: tuple[str, ...] = get_args(SortKey)
RemoteStatus = Literal["remote", "unmarked", "not_remote"]
REMOTE_STATUSES: tuple[str, ...] = get_args(RemoteStatus)
JobStatus = Literal["unemailed", "emailed", "applied", "skipped", "interviewing", "rejected", "offer"]
if get_args(JobStatus) != JOB_STATUSES:  # pragma: no cover - guards against drift
    raise AssertionError("JobStatus in job_queries.py is out of sync with JOB_STATUSES in job_store.py")


# --- Normalising ---------------------------------------------------------------------


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return None


def _string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if isinstance(value, str) and value.strip():
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _breakdown(value: Any) -> dict[str, float | int]:
    """``fit_breakdown`` as ``{part: points}``, dropping anything that isn't a number."""
    if not isinstance(value, dict):
        return {}
    parts = {str(key): _number(points) for key, points in value.items()}
    return {key: points for key, points in parts.items() if points is not None}


def normalize_job(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """One job document as the API returns it: every field present (missing
    ones are ``None``), timestamps as ISO strings. Same shape as ``Job`` in
    frontend/src/lib/types.ts."""
    skills = [skill for skill in data.get("matched_skills") or [] if isinstance(skill, str)]
    is_remote = data.get("is_remote")
    score = _number(data.get("score"))
    job = {
        "id": doc_id,
        "job_id": _string(data.get("job_id")) or doc_id,
        "company": _string(data.get("company")),
        "title": _string(data.get("title")),
        "city": _string(data.get("city")),
        "state": _string(data.get("state")),
        "is_remote": is_remote if isinstance(is_remote, bool) else None,
        "job_type": _string(data.get("job_type")),
        "salary_low": _number(data.get("salary_low")),
        "salary_high": _number(data.get("salary_high")),
        "url": _string(data.get("url")),
        "track": _string(data.get("track")),
        "posted_date": _string(data.get("posted_date")),
        "matched_skills": skills,
        "score": score if score is not None else (len(skills) or None),
        "min_years": _number(data.get("min_years")),
        # None on jobs saved before the fit score existed (see job_fit.py).
        "fit_score": _number(data.get("fit_score")),
        "fit_breakdown": _breakdown(data.get("fit_breakdown")),
        "fit_reasons": [r for r in data.get("fit_reasons") or [] if isinstance(r, str)],
        "status": _string(data.get("status")) or "unknown",
        "notes": _string(data.get("notes")),
        "gmail_message_id": _string(data.get("gmail_message_id")),
    }
    for field in TIMESTAMP_FIELDS:
        job[field] = _iso(data.get(field))
    return job


def remote_status(job: dict[str, Any]) -> str:
    """``remote``, ``not_remote``, or ``unmarked`` (the site didn't say)."""
    if job.get("is_remote") is True:
        return "remote"
    if job.get("is_remote") is False:
        return "not_remote"
    return "unmarked"


def has_applied(job: dict[str, Any]) -> bool:
    return job.get("status") == STATUS_APPLIED or job.get("applied_at") is not None


def salary_sort_value(job: dict[str, Any]) -> float | None:
    """The higher of the amounts actually listed. The search script saves a
    missing amount as 0, so 0 and ``None`` both mean "not listed" (``None``)."""
    amounts = [
        value
        for value in (job.get("salary_high"), job.get("salary_low"))
        if isinstance(value, (int, float)) and value > 0
    ]
    return max(amounts) if amounts else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _seen_date(job: dict[str, Any]) -> date | None:
    value = job.get("last_seen_at") or job.get("first_seen_at")
    if not value:
        return None
    try:
        seen = datetime.fromisoformat(value)
    except ValueError:
        return _parse_date(value)
    if seen.tzinfo is not None:
        seen = seen.astimezone(timezone.utc)
    return seen.date()


# --- Filtering -----------------------------------------------------------------------


def _search_text(job: dict[str, Any]) -> str:
    parts = [
        job.get(field)
        for field in ("title", "company", "city", "state", "job_type", "notes", "job_id", "track")
    ]
    return " ".join(part for part in [*parts, *job["matched_skills"]] if part).lower()


@dataclass(frozen=True)
class JobFilters:
    """Which jobs to keep. Every filter given must match (AND); a filter with
    several values matches any of them (OR), except ``skills``, where the job
    needs every skill listed."""

    q: str | None = None
    statuses: tuple[str, ...] = ()
    companies: tuple[str, ...] = ()
    # Case-insensitive prefix of the track name: "core", "java", ".net", ...
    tracks: tuple[str, ...] = ()
    remote: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    min_salary: float | None = None
    posted_since: date | None = None
    seen_since: date | None = None
    applied: bool | None = None

    def matches(self, job: dict[str, Any]) -> bool:
        if self.statuses and job["status"] not in self.statuses:
            return False
        if self.companies and (job["company"] or "").lower() not in {c.lower() for c in self.companies}:
            return False
        if self.tracks and not any(
            (job["track"] or "").lower().startswith(track.lower()) for track in self.tracks
        ):
            return False
        if self.remote and remote_status(job) not in self.remote:
            return False
        if self.skills:
            have = {skill.lower() for skill in job["matched_skills"]}
            if not all(skill.lower() in have for skill in self.skills):
                return False
        if self.min_salary is not None:
            salary = salary_sort_value(job)
            if salary is None or salary < self.min_salary:
                return False
        if self.posted_since is not None:
            posted = _parse_date(job["posted_date"])
            if posted is None or posted < self.posted_since:
                return False
        if self.seen_since is not None:
            seen = _seen_date(job)
            if seen is None or seen < self.seen_since:
                return False
        if self.applied is not None and has_applied(job) != self.applied:
            return False
        if self.q and self.q.strip().lower() not in _search_text(job):
            return False
        return True


def filter_jobs(jobs: Iterable[dict[str, Any]], filters: JobFilters) -> list[dict[str, Any]]:
    return [job for job in jobs if filters.matches(job)]


# --- Sorting -------------------------------------------------------------------------


def _seen_key(job: dict[str, Any]) -> str:
    return job.get("last_seen_at") or job.get("first_seen_at") or ""


def _status_order(status: str) -> int:
    return JOB_STATUSES.index(status) if status in JOB_STATUSES else len(JOB_STATUSES)


def sort_jobs(jobs: Iterable[dict[str, Any]], key: str = "last_seen") -> list[dict[str, Any]]:
    """Sort like the dashboard: newest ``last_seen_at`` first, then by ``key``
    (Python's sort is stable, so ties stay newest first).

    ``posted``/``score``/``fit``/``salary`` are highest first, ``title`` A-Z, ``status``
    in workflow order. Jobs missing the value always go last.
    """
    if key not in SORT_KEYS:
        raise ValueError(f"Unknown sort {key!r}; expected one of {', '.join(SORT_KEYS)}")
    ordered = sorted(jobs, key=_seen_key, reverse=True)
    if key == "posted":
        # reverse=True keeps the sort stable; undated jobs ("") end up last.
        ordered.sort(key=lambda job: job["posted_date"] or "", reverse=True)
    elif key == "salary":
        ordered.sort(key=lambda job: (salary_sort_value(job) is None, -(salary_sort_value(job) or 0)))
    elif key == "score":
        ordered.sort(key=lambda job: (job["score"] is None, -(job["score"] or 0)))
    elif key == "fit":
        ordered.sort(key=lambda job: (job["fit_score"] is None, -(job["fit_score"] or 0)))
    elif key == "title":
        ordered.sort(key=lambda job: (job["title"] is None, (job["title"] or "").lower()))
    elif key == "status":
        ordered.sort(key=lambda job: _status_order(job["status"]))
    return ordered


# --- Counting ------------------------------------------------------------------------


def job_stats(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for a dashboard or a script: by status (every workflow status,
    zeros included, in workflow order), company, track, and remote status."""
    by_status = {status: 0 for status in JOB_STATUSES}
    for job in jobs:
        by_status[job["status"]] = by_status.get(job["status"], 0) + 1

    def most_common(values: Iterable[str | None]) -> dict[str, int]:
        counts = Counter(value for value in values if value)
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

    return {
        "total": len(jobs),
        "applied": sum(1 for job in jobs if has_applied(job)),
        "by_status": by_status,
        "by_company": most_common(job["company"] for job in jobs),
        "by_track": most_common(job["track"] for job in jobs),
        "by_remote": {status: sum(1 for job in jobs if remote_status(job) == status) for status in REMOTE_STATUSES},
    }
