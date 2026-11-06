"""Tests for job_search.py's command line, site selection, and speed-ups."""

import json
import threading
import time

import pytest

import job_search
import jobs_cli
from job_sites import JobSite, Posting, SearchPage


class NoNetworkSession:
    def get(self, *args, **kwargs):
        raise AssertionError(f"unexpected GET {args}")

    def post(self, *args, **kwargs):
        raise AssertionError(f"unexpected POST {args}")


def _names(selectors):
    return [site.name for site in job_search.resolve_sites(NoNetworkSession(), selectors=selectors)]


# --- --site ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "selector, expected",
    [
        ("accenture", ["Accenture"]),
        ("Accenture", ["Accenture"]),
        ("insight global", ["Insight Global"]),
        ("insight-global", ["Insight Global"]),
        ("insightglobal", ["Insight Global"]),
        ("workday", ["Accenture"]),  # by board kind
    ],
)
def test_site_selector_matches_name_kind_or_url(selector, expected):
    assert _names([selector]) == expected


def test_no_selector_means_every_site():
    assert _names(None) == ["Insight Global", "Accenture"]
    assert _names(["accenture", "insight global"]) == ["Insight Global", "Accenture"]


def test_a_url_selector_searches_that_board_even_if_not_configured():
    assert _names(["https://boards.greenhouse.io/acme"]) == ["Acme"]
    assert _names(["accenture", "https://jobs.lever.co/acme"]) == ["Accenture", "Acme"]


def test_unknown_selector_lists_the_available_sites():
    with pytest.raises(job_search.SiteSelectionError, match="Available: Insight Global"):
        _names(["nope"])


def test_cli_rejects_an_unknown_site(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("IG_LOCAL_DB_PATH", str(tmp_path / "db.json"))

    assert job_search.cli(["--local", "--site", "nope"]) == 2
    assert "--site nope matched nothing" in capsys.readouterr().err


def test_cli_list_sites(capsys):
    assert job_search.cli(["--list-sites"]) == 0
    out = capsys.readouterr().out
    assert "Insight Global   insight-global  https://insightglobal.com/jobs/search/all/all" in out
    assert "Accenture        workday         https://www.accenture.com/us-en/careers/jobsearch" in out
    assert "-> https://accenture.wd103.myworkdayjobs.com/AccentureCareers" in out


# --- --local ----------------------------------------------------------------------------


def test_cli_local_uses_the_local_file_even_when_firebase_is_configured(
    monkeypatch, tmp_path
):
    db = tmp_path / "local_firestore.json"
    monkeypatch.setenv("IG_LOCAL_DB_PATH", str(db))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent/key.json")
    monkeypatch.setenv("IG_STATE_BACKEND", "firestore")
    monkeypatch.setenv("IG_EMAIL_TO", "me@example.com")
    monkeypatch.setattr(job_search, "get_gmail_service", lambda: "service")
    monkeypatch.setattr(job_search, "send_email", lambda *a, **k: "msg-1")

    def fake_list(session, site, term):
        if term != "Python Developer":
            return []
        return [
            Posting(
                job_id="accenture-R1",
                title="Python Developer",
                url="https://example.com/R1",
                company="Accenture",
                is_remote=True,
                description="Python and React",
            )
        ]

    monkeypatch.setattr(job_search, "list_postings", fake_list)

    assert job_search.cli(["--local", "--site", "accenture"]) == 0

    saved = json.loads(db.read_text())["jobs"]
    assert list(saved) == ["accenture-R1"]
    assert saved["accenture-R1"]["status"] == "emailed"


def test_cli_include_unmarked_saves_jobs_without_a_remote_status(monkeypatch, tmp_path):
    db = tmp_path / "local_firestore.json"
    monkeypatch.setenv("IG_LOCAL_DB_PATH", str(db))
    monkeypatch.delenv("IG_EMAIL_TO", raising=False)  # email not set up: just skipped

    def fake_list(session, site, term):
        if term != "Python Developer":
            return []
        return [
            Posting(job_id=f"accenture-{req}", title="Python Developer", url="https://example.com",
                    company="Accenture", is_remote=remote, description="Python and React")
            for req, remote in [("R1", True), ("R2", None), ("R3", False)]
        ]

    monkeypatch.setattr(job_search, "list_postings", fake_list)

    assert job_search.cli(["--local", "--site", "accenture"]) == 0
    assert {k: v["is_remote"] for k, v in json.loads(db.read_text())["jobs"].items()} == {
        "accenture-R1": True,
    }

    assert job_search.cli(["--local", "--site", "accenture", "--include-unmarked"]) == 0
    assert {k: v["is_remote"] for k, v in json.loads(db.read_text())["jobs"].items()} == {
        "accenture-R1": True,
        "accenture-R2": None,
    }


@pytest.mark.parametrize("argv", [["list", "--local"], ["--local", "list"]])
def test_jobs_cli_local_flag_before_or_after_the_command(monkeypatch, tmp_path, capsys, argv):
    db = tmp_path / "local_firestore.json"
    db.write_text(json.dumps({"jobs": {"accenture-R1": {"job_id": "accenture-R1",
                                                        "title": "Local job",
                                                        "status": "emailed"}}}))
    monkeypatch.setenv("IG_LOCAL_DB_PATH", str(db))
    monkeypatch.setenv("IG_STATE_BACKEND", "firestore")  # would fail without --local

    assert jobs_cli.main(argv) == 0
    assert "Local job" in capsys.readouterr().out


# --- Speed ------------------------------------------------------------------------------


def test_host_throttle_spaces_requests_per_host():
    throttle = job_search.HostThrottle(lambda: 0.05)
    started = time.monotonic()

    for _ in range(3):
        throttle.wait("a.example.com")
    throttle.wait("b.example.com")  # a different host doesn't wait

    elapsed = time.monotonic() - started
    assert 0.1 <= elapsed < 0.5


def test_build_session_throttles_every_https_request():
    session = job_search.build_session()

    adapter = session.get_adapter("https://www.accenture.com")
    assert isinstance(adapter, job_search.ThrottledAdapter)
    assert set(adapter.max_retries.allowed_methods) == {"GET", "POST"}


class SlowSite(JobSite):
    """Eight postings per term; each description takes 0.1s to load."""

    name = "Slow"
    kind = "test"
    remote_only = False

    def __init__(self):
        self.detail_calls = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.lock = threading.Lock()

    def fetch_page(self, session, term, page):
        postings = [
            Posting(job_id=f"slow-{n}", title="Python Developer",
                    url=f"https://example.com/{n}", company="Slow")
            for n in range(8)
        ]
        return SearchPage(postings, has_more=False)

    def fetch_details(self, session, posting):
        with self.lock:
            self.detail_calls.append(posting.job_id)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        time.sleep(0.1)
        with self.lock:
            self.in_flight -= 1
        return Posting(**{**posting.__dict__, "description": "Python and React"})


def test_search_site_loads_descriptions_in_parallel_and_only_once(monkeypatch):
    monkeypatch.setattr(job_search, "MAX_CONCURRENT_REQUESTS_PER_SITE", 4)
    site = SlowSite()
    core = job_search.TRACKS[0]
    searches = [(core, "Python Developer"), (core, "React Engineer"), (core, "Software Engineer")]
    started = time.monotonic()

    result = job_search.search_site(NoNetworkSession(), site, searches)

    elapsed = time.monotonic() - started
    assert sorted(site.detail_calls) == [f"slow-{n}" for n in range(8)]  # once each
    assert site.max_in_flight == 4
    assert elapsed < 0.5  # one at a time would take 0.8s
    assert len(result.matches) == 8
