"""Shared test setup for the backend suite."""

import pytest

import job_search
from job_sites import InsightGlobalSite


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_boards: search the boards in job_boards.py instead of the test pair"
    )
    config.addinivalue_line(
        "markers", "job_pages: let Insight Global read job pages (off otherwise; see below)"
    )


@pytest.fixture(autouse=True)
def no_job_pages(request, monkeypatch):
    """Insight Global reads each matching job's page for On-Site. The fake
    sessions in most tests only serve its API, so that's off unless a test is
    marked ``job_pages``."""
    if not request.node.get_closest_marker("job_pages"):
        monkeypatch.setattr(InsightGlobalSite, "READ_JOB_PAGES", False)


@pytest.fixture(autouse=True)
def two_configured_sites(request, monkeypatch):
    """Search only Insight Global and Accenture unless a test is marked ``real_boards``.

    The tests for searching, site settings, and --site were written against
    these two sites; pinning them keeps those tests independent of the boards
    listed in job_boards.py. tests/test_job_boards.py checks the real list.
    """
    # Re-checking saved jobs loads their postings; tests that want it call
    # recheck_saved_jobs directly with a fake session.
    monkeypatch.setattr(job_search, "RECHECK_SAVED_JOBS", False)
    if request.node.get_closest_marker("real_boards"):
        return
    monkeypatch.setattr(
        job_search,
        "JOB_SEARCH_URLS",
        [job_search.INSIGHT_GLOBAL_URL, job_search.ACCENTURE_SEARCH_URL],
    )
