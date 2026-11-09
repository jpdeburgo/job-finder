"""Tests for job_queries.py: normalising, filtering, sorting, and counting jobs."""

from datetime import date, datetime, timezone

import pytest

from job_queries import (
    JobFilters,
    filter_jobs,
    job_stats,
    normalize_job,
    remote_status,
    salary_sort_value,
    sort_jobs,
)


def job(doc_id, **fields):
    """A normalised job with sensible defaults."""
    data = {
        "job_id": doc_id,
        "company": "Insight Global",
        "title": "React Developer",
        "city": "Austin",
        "state": "TX",
        "is_remote": True,
        "job_type": "Contract",
        "salary_low": 55.0,
        "salary_high": 65.0,
        "url": f"https://insightglobal.com/jobs/{doc_id}",
        "track": "Core matches (your main stack)",
        "posted_date": "2026-10-30",
        "matched_skills": ["React", "TypeScript"],
        "score": 2,
        "min_years": 3,
        "status": "emailed",
        "last_seen_at": datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc),
        "first_seen_at": datetime(2026, 10, 31, 13, 0, tzinfo=timezone.utc),
    }
    data.update(fields)
    return normalize_job(doc_id, data)


ids = lambda jobs: [j["id"] for j in jobs]  # noqa: E731


# --- normalize_job ----------------------------------------------------------------------


def test_normalize_job_fills_every_field_and_formats_timestamps():
    result = normalize_job("abc", {"title": "X", "last_seen_at": datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)})
    assert result["id"] == result["job_id"] == "abc"
    assert result["last_seen_at"] == "2026-11-01T13:00:00+00:00"
    assert result["applied_at"] is None
    assert result["matched_skills"] == []
    assert result["status"] == "unknown"
    assert result["is_remote"] is None
    assert set(result) >= {"company", "salary_low", "notes", "gmail_message_id", "status_updated_at"}


def test_normalize_job_tolerates_bad_values():
    result = normalize_job(
        "abc",
        {
            "salary_low": "abc",
            "salary_high": "90",
            "min_years": True,
            "is_remote": "yes",
            "matched_skills": ["Python", 3, None],
            "score": float("nan"),
        },
    )
    assert result["salary_low"] is None
    assert result["salary_high"] == 90.0
    assert result["min_years"] is None  # a bool isn't a number
    assert result["is_remote"] is None
    assert result["matched_skills"] == ["Python"]
    assert result["score"] == 1  # falls back to the number of skills


def test_remote_status_and_salary_sort_value():
    assert [remote_status(job("a", is_remote=v)) for v in (True, False, None)] == ["remote", "not_remote", "unmarked"]
    assert salary_sort_value(job("a", salary_low=140000, salary_high=0)) == 140000
    assert salary_sort_value(job("a", salary_low=0, salary_high=90)) == 90
    assert salary_sort_value(job("a", salary_low=0, salary_high=0)) is None
    assert salary_sort_value(job("a", salary_low=None, salary_high=None)) is None


# --- filtering ----------------------------------------------------------------------------


JOBS = [
    job("react", status="emailed", matched_skills=["React", "TypeScript"], posted_date="2026-11-05"),
    job(
        "python",
        title="Senior Python Engineer",
        company="Accenture",
        status="applied",
        applied_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
        matched_skills=["Python", "AWS"],
        salary_low=140000,
        salary_high=0,
        notes="Recruiter: Sam",
        posted_date="2026-10-01",
        last_seen_at=datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc),
    ),
    job(
        "java",
        title="Junior Java Developer",
        company="Accenture",
        status="interviewing",
        applied_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
        is_remote=None,
        track="Java growth track (entry-level / lower bar)",
        matched_skills=["Java"],
        salary_low=0,
        salary_high=0,
        city="Dallas",
        posted_date=None,
    ),
]


@pytest.mark.parametrize(
    "filters, expected",
    [
        (JobFilters(), ["react", "python", "java"]),
        (JobFilters(statuses=("emailed", "interviewing")), ["react", "java"]),
        (JobFilters(companies=("accenture",)), ["python", "java"]),  # case-insensitive
        (JobFilters(tracks=("java",)), ["java"]),  # the start of the track name
        (JobFilters(tracks=("Core matches (your main stack)",)), ["react", "python"]),
        (JobFilters(remote=("unmarked",)), ["java"]),
        (JobFilters(skills=("python",)), ["python"]),
        (JobFilters(skills=("React", "TypeScript")), ["react"]),  # needs all of them
        (JobFilters(skills=("React", "Python")), []),
        (JobFilters(min_salary=100), ["python"]),  # "Not listed" never passes
        (JobFilters(min_salary=60), ["react", "python"]),
        (JobFilters(posted_since=date(2026, 10, 15)), ["react"]),  # undated excluded
        (JobFilters(seen_since=date(2026, 11, 1)), ["react", "java"]),
        (JobFilters(applied=True), ["python", "java"]),  # applied_at counts
        (JobFilters(applied=False), ["react"]),
        (JobFilters(q="sam"), ["python"]),  # notes
        (JobFilters(q="DALLAS"), ["java"]),  # city, any case
        (JobFilters(q="aws"), ["python"]),  # skills
        (JobFilters(q="nothing like this"), []),
        (JobFilters(companies=("Accenture",), statuses=("applied",)), ["python"]),  # AND
    ],
)
def test_filter_jobs(filters, expected):
    assert ids(filter_jobs(JOBS, filters)) == expected


def test_seen_since_uses_the_utc_date_and_falls_back_to_first_seen():
    late = job("late", last_seen_at="2026-11-01T23:30:00-05:00")  # Nov 2 in UTC
    unseen = job("unseen", last_seen_at=None, first_seen_at=datetime(2026, 11, 3, tzinfo=timezone.utc))
    never = job("never", last_seen_at=None, first_seen_at=None)
    assert ids(filter_jobs([late, unseen, never], JobFilters(seen_since=date(2026, 11, 2)))) == ["late", "unseen"]


def test_normalize_job_reads_the_fit_score():
    result = normalize_job(
        "abc",
        {
            "fit_score": 72,
            "fit_breakdown": {"skills": 48, "role": 30, "experience": -6, "bad": "x"},
            "fit_reasons": ["Skills: Python", 3],
        },
    )
    assert result["fit_score"] == 72
    assert result["not_remote_reason"] is None
    assert result["fit_breakdown"] == {"skills": 48, "role": 30, "experience": -6}
    assert result["fit_reasons"] == ["Skills: Python"]


def test_normalize_job_without_a_fit_score():
    # Jobs saved before the fit score existed.
    result = normalize_job("abc", {"title": "X"})
    assert (result["fit_score"], result["fit_breakdown"], result["fit_reasons"]) == (None, {}, [])


# --- sorting ------------------------------------------------------------------------------


def seen(day):
    return datetime(2026, 11, day, 13, 0, tzinfo=timezone.utc)


SORTABLE = [
    job("a", title="zeta", last_seen_at=seen(1), posted_date="2026-10-20", salary_low=55, salary_high=65, score=1, fit_score=62, status="offer"),
    job("b", title="Alpha", last_seen_at=seen(5), posted_date="2026-10-01", salary_low=140000, salary_high=0, score=5, fit_score=30, status="weird"),
    job("c", title=None, last_seen_at=seen(3), posted_date=None, salary_low=0, salary_high=0, score=None, matched_skills=[], status="unemailed"),
    job("d", title="beta", last_seen_at=seen(4), posted_date="2026-10-20", salary_low=None, salary_high=None, score=2, fit_score=88, status="applied"),
]


@pytest.mark.parametrize(
    "key, expected",
    [
        ("last_seen", ["b", "d", "c", "a"]),
        ("posted", ["d", "a", "b", "c"]),  # ties stay newest-seen first; undated last
        ("salary", ["b", "a", "d", "c"]),  # "Not listed" (0/0 and null) last, newest first
        ("score", ["b", "d", "a", "c"]),
        ("fit", ["d", "a", "b", "c"]),  # best fit first; unscored (older jobs) last
        ("title", ["b", "d", "a", "c"]),  # case-insensitive, untitled last
        ("status", ["c", "d", "a", "b"]),  # workflow order, unknown statuses last
    ],
)
def test_sort_jobs(key, expected):
    assert ids(sort_jobs(SORTABLE, key)) == expected


def test_sort_jobs_rejects_unknown_keys_and_leaves_input_alone():
    before = ids(SORTABLE)
    sort_jobs(SORTABLE, "salary")
    assert ids(SORTABLE) == before
    with pytest.raises(ValueError, match="Unknown sort 'nope'"):
        sort_jobs(SORTABLE, "nope")


# --- counting -----------------------------------------------------------------------------


def test_job_stats():
    stats = job_stats(JOBS + [job("weird", status="weird", company=None, track=None)])
    assert stats["total"] == 4
    assert stats["applied"] == 2
    assert stats["by_status"] == {
        "unemailed": 0,
        "emailed": 1,
        "applied": 1,
        "skipped": 0,
        "interviewing": 1,
        "rejected": 0,
        "offer": 0,
        "weird": 1,  # unknown statuses are still counted, after the known ones
    }
    assert list(stats["by_company"].items()) == [("Accenture", 2), ("Insight Global", 1)]  # most first
    assert stats["by_track"] == {"Core matches (your main stack)": 2, "Java growth track (entry-level / lower bar)": 1}
    assert stats["by_remote"] == {"remote": 3, "unmarked": 1, "not_remote": 0}


def test_job_stats_of_nothing():
    assert job_stats([])["by_status"]["emailed"] == 0
    assert job_stats([])["total"] == 0
