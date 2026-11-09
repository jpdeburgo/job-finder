"""Shared test setup for the backend suite."""

import pytest

import job_search


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_boards: search the boards in job_boards.py instead of the test pair"
    )


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
