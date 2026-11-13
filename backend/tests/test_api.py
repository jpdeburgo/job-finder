"""Tests for api.py: starting searches over HTTP for the dashboard."""

import threading

import pytest
from fastapi.testclient import TestClient

import api
import job_search

SUMMARY = job_search.RunSummary(
    total_matches=5, new_matches=2, emailed_matches=2, email_sent=True, gmail_message_id="msg-1"
)


class FakeSearch:
    """Stands in for job_search.main; blocks until released so tests can
    look at a run while it's still going."""

    def __init__(self, result=SUMMARY, error=None, block=False):
        self.result = result
        self.error = error
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        if not block:
            self.release.set()

    def __call__(self, sites, include_unmarked):
        self.calls.append((sites, include_unmarked))
        print("Searching Accenture (workday) for 25 term(s) ...")
        self.started.set()
        assert self.release.wait(5), "test never released the search"
        print("no newline at the end", end="")
        if self.error:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def no_token(monkeypatch):
    monkeypatch.delenv(api.API_TOKEN_ENV_VAR, raising=False)


def make_client(search):
    manager = api.RunManager(search)
    return TestClient(api.create_app(manager)), manager


def wait_for(manager, run_id):
    assert manager.get(run_id).done.wait(5), "run never finished"


def test_health():
    client, _ = make_client(FakeSearch())
    assert client.get("/health").json() == {"status": "ok"}


def test_start_run_returns_202_and_runs_the_search_in_the_background():
    search = FakeSearch(block=True)
    client, manager = make_client(search)

    response = client.post("/runs", json={"sites": ["accenture", "  "], "include_unmarked": True})

    assert response.status_code == 202
    run = response.json()["run"]
    assert run["status"] == "running"
    assert run["sites"] == ["accenture"]  # blanks dropped
    assert run["finished_at"] is None and run["summary"] is None

    assert search.started.wait(5)
    assert client.get(f"/runs/{run['id']}").json()["run"]["status"] == "running"
    search.release.set()
    wait_for(manager, run["id"])

    finished = client.get(f"/runs/{run['id']}").json()["run"]
    assert search.calls == [(["accenture"], True)]
    assert finished["status"] == "succeeded"
    assert finished["finished_at"] is not None
    assert finished["summary"] == {
        "total_matches": 5,
        "new_matches": 2,
        "emailed_matches": 2,
        "email_sent": True,
        "gmail_message_id": "msg-1",
        "email_skipped_reason": None,
    }
    assert finished["error"] is None
    # Everything the search printed, including a last line without a newline.
    assert finished["output"][1:] == [
        "Searching Accenture (workday) for 25 term(s) ...",
        "no newline at the end",
    ]


def test_a_body_is_optional_and_means_every_site():
    search = FakeSearch()
    client, manager = make_client(search)

    run = client.post("/runs").json()["run"]
    wait_for(manager, run["id"])

    assert search.calls == [([], False)]


def test_only_one_search_runs_at_a_time():
    search = FakeSearch(block=True)
    client, manager = make_client(search)
    first = client.post("/runs").json()["run"]
    assert search.started.wait(5)

    busy = client.post("/runs")

    assert busy.status_code == 409
    assert busy.json()["error"] == f"A search is already running (run {first['id']})."
    assert busy.json()["run"]["id"] == first["id"]

    search.release.set()
    wait_for(manager, first["id"])
    second = client.post("/runs")
    assert second.status_code == 202
    wait_for(manager, second.json()["run"]["id"])


def test_a_failed_search_is_reported_not_raised():
    search = FakeSearch(error=job_search.SiteSelectionError("--site nope matched nothing."))
    client, manager = make_client(search)

    run_id = client.post("/runs", json={"sites": ["nope"]}).json()["run"]["id"]
    wait_for(manager, run_id)

    run = client.get(f"/runs/{run_id}").json()["run"]
    assert run["status"] == "failed"
    assert run["error"] == "SiteSelectionError: --site nope matched nothing."
    assert run["summary"] is None
    assert run["output"][-1] == "Run failed: SiteSelectionError: --site nope matched nothing."
    # The API keeps working afterwards.
    assert client.post("/runs").status_code == 202


def test_latest_and_list_runs():
    client, manager = make_client(FakeSearch())
    assert client.get("/runs/latest").json() == {"run": None}
    assert client.get("/runs").json() == {"runs": []}

    ids = []
    for _ in range(2):
        ids.append(client.post("/runs").json()["run"]["id"])
        wait_for(manager, ids[-1])

    latest = client.get("/runs/latest").json()["run"]
    assert latest["id"] == ids[-1] and "output" in latest
    runs = client.get("/runs").json()["runs"]
    assert [run["id"] for run in runs] == ids[::-1]  # newest first
    assert "output" not in runs[0]  # the list stays small


def test_unknown_run_is_404():
    client, _ = make_client(FakeSearch())
    response = client.get("/runs/nope")
    assert response.status_code == 404
    assert "No run nope" in response.json()["error"]


@pytest.mark.parametrize(
    "body",
    [{"sites": "accenture"}, {"include_unmarked": "maybe"}, {"local": True}],
)
def test_invalid_bodies_are_rejected(body):
    search = FakeSearch()
    client, _ = make_client(search)
    response = client.post("/runs", json=body)
    assert response.status_code == 422
    assert response.json()["error"].startswith("Invalid request: ")
    assert search.calls == []


def test_output_keeps_only_the_newest_lines(monkeypatch):
    monkeypatch.setattr(api, "MAX_OUTPUT_LINES", 3)

    def chatty(sites, include_unmarked):
        for number in range(10):
            print(f"line {number}")
        return SUMMARY

    client, manager = make_client(chatty)
    run_id = client.post("/runs").json()["run"]["id"]
    wait_for(manager, run_id)

    run = client.get(f"/runs/{run_id}").json()["run"]
    assert run["output"] == ["line 7", "line 8", "line 9"]
    assert run["output_truncated"] == 8  # the "started" line and lines 0-6


def test_output_from_the_searchs_worker_threads_is_captured():
    def threaded(sites, include_unmarked):
        # Sites are searched on a thread pool and log through job_sites.log.
        from job_sites import log

        worker = threading.Thread(target=log, args=("Accenture: 3 qualifying match(es)",))
        worker.start()
        worker.join()
        return SUMMARY

    client, manager = make_client(threaded)
    run_id = client.post("/runs").json()["run"]["id"]
    wait_for(manager, run_id)

    assert "Accenture: 3 qualifying match(es)" in client.get(f"/runs/{run_id}").json()["run"]["output"]


def test_the_default_search_is_job_search_main(monkeypatch):
    calls = []

    def fake_main(store=None, site_selectors=None, include_unmarked=False):
        calls.append((site_selectors, include_unmarked))
        return SUMMARY

    monkeypatch.setattr(job_search, "main", fake_main)
    client, manager = make_client(api._default_search)

    for sites in ([], ["accenture"]):
        run_id = client.post("/runs", json={"sites": sites}).json()["run"]["id"]
        wait_for(manager, run_id)

    # No sites means "every site", just like running job_search.py without --site.
    assert calls == [(None, False), (["accenture"], False)]


# --- IG_API_TOKEN ------------------------------------------------------------------------


@pytest.fixture
def with_token(monkeypatch):
    monkeypatch.setenv(api.API_TOKEN_ENV_VAR, "s3cret")


@pytest.mark.parametrize("path", ["/runs", "/runs/latest", "/runs/abc"])
def test_token_is_required_when_configured(with_token, path):
    client, _ = make_client(FakeSearch())
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "s3cret"}):
        response = client.get(path, headers=headers)
        assert response.status_code == 401
        assert response.json() == {"error": "Missing or wrong API token (see IG_API_TOKEN)."}
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_a_rejected_token_starts_nothing(with_token):
    search = FakeSearch()
    client, _ = make_client(search)
    assert client.post("/runs").status_code == 401
    assert search.calls == []


def test_the_right_token_is_accepted(with_token):
    client, manager = make_client(FakeSearch())
    headers = {"Authorization": "Bearer s3cret"}
    run_id = client.post("/runs", headers=headers).json()["run"]["id"]
    wait_for(manager, run_id)
    assert client.get(f"/runs/{run_id}", headers=headers).status_code == 200


def test_health_never_needs_the_token(with_token):
    client, _ = make_client(FakeSearch())
    assert client.get("/health").status_code == 200


# --- Jobs -------------------------------------------------------------------------------

from datetime import datetime, timezone  # noqa: E402

from job_store import FirestoreJobStore  # noqa: E402


def _doc(job_id, day, **fields):
    seen = datetime(2026, 11, day, 13, 0, tzinfo=timezone.utc)
    data = {
        "job_id": job_id,
        "company": "Insight Global",
        "title": "React Developer",
        "is_remote": True,
        "salary_low": 55.0,
        "salary_high": 65.0,
        "track": "Core matches (your main stack)",
        "posted_date": f"2026-10-{day:02d}",
        "matched_skills": ["React", "TypeScript"],
        "score": 2,
        "status": "emailed",
        "first_seen_at": seen,
        "last_seen_at": seen,
        "status_updated_at": seen,
    }
    data.update(fields)
    return data


@pytest.fixture
def job_store(tmp_path):
    store = FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)
    store.import_documents(
        {
            "ig-react": _doc(
                "ig-react", 5, fit_score=81, fit_breakdown={"skills": 51, "role": 30}, fit_reasons=["Skills: React"]
            ),
            "acn-python": _doc(
                "acn-python",
                3,
                company="Accenture",
                title="Senior Python Engineer",
                status="applied",
                salary_low=140000.0,
                salary_high=0.0,
                matched_skills=["Python", "AWS"],
                notes="Recruiter: Sam",
                fit_score=64,
            ),
            "acn-java": _doc(
                "acn-java",
                4,
                company="Accenture",
                title="Junior Java Developer",
                status="interviewing",
                is_remote=None,
                salary_low=0.0,
                salary_high=0.0,
                track="Java growth track (entry-level / lower bar)",
                matched_skills=["Java"],
            ),
        }
    )
    return store


@pytest.fixture
def jobs_client(job_store):
    return TestClient(api.create_app(api.RunManager(FakeSearch()), store_factory=lambda: job_store))


def job_ids(response):
    assert response.status_code == 200, response.json()
    return [job["id"] for job in response.json()["jobs"]]


def test_list_jobs_returns_every_job_newest_first(jobs_client):
    response = jobs_client.get("/jobs")
    body = response.json()
    assert job_ids(response) == ["ig-react", "acn-java", "acn-python"]
    assert (body["total"], body["limit"], body["offset"]) == (3, 100, 0)
    react = body["jobs"][0]
    assert react["last_seen_at"] == "2026-11-05T13:00:00+00:00"
    assert react["score"] == 2 and react["applied_at"] is None
    assert react["fit_score"] == 81
    assert react["fit_breakdown"] == {"skills": 51, "role": 30}
    assert react["fit_reasons"] == ["Skills: React"]
    assert react["not_remote_reason"] is None
    java = body["jobs"][1]
    assert (java["fit_score"], java["fit_breakdown"], java["fit_reasons"]) == (None, {}, [])


@pytest.mark.parametrize(
    "params, expected",
    [
        ({"status": "applied"}, ["acn-python"]),
        ({"status": "applied,interviewing"}, ["acn-java", "acn-python"]),
        ([("status", "applied"), ("status", "emailed")], ["ig-react", "acn-python"]),
        ({"company": "accenture"}, ["acn-java", "acn-python"]),
        ({"track": "java"}, ["acn-java"]),
        ({"remote": "unmarked"}, ["acn-java"]),
        ({"skill": "python"}, ["acn-python"]),
        ([("skill", "React"), ("skill", "TypeScript")], ["ig-react"]),
        ({"min_salary": 140000}, ["acn-python"]),  # per year: ig-react's $65/hr is $135,200
        ({"salary_listed": "true"}, ["ig-react", "acn-python"]),
        ({"salary_listed": "false"}, ["acn-java"]),
        ({"posted_since": "2026-10-04"}, ["ig-react", "acn-java"]),
        ({"seen_since": "2026-11-04"}, ["ig-react", "acn-java"]),
        ({"applied": "true"}, ["acn-python"]),
        ({"q": "sam"}, ["acn-python"]),
        ({"q": "  "}, ["ig-react", "acn-java", "acn-python"]),  # blank means no search
        ({"company": "Accenture", "remote": "remote"}, ["acn-python"]),
    ],
)
def test_list_jobs_filters(jobs_client, params, expected):
    assert job_ids(jobs_client.get("/jobs", params=params)) == expected


def test_list_jobs_sorts_and_pages(jobs_client):
    assert job_ids(jobs_client.get("/jobs", params={"sort": "salary"})) == ["acn-python", "ig-react", "acn-java"]
    # ig-react's $55/hr is $114,400 a year; "Not listed" stays last.
    assert job_ids(jobs_client.get("/jobs", params={"sort": "salary_lowest"})) == ["ig-react", "acn-python", "acn-java"]
    assert job_ids(jobs_client.get("/jobs", params={"sort": "title"})) == ["acn-java", "ig-react", "acn-python"]
    assert job_ids(jobs_client.get("/jobs", params={"sort": "fit"})) == ["ig-react", "acn-python", "acn-java"]

    # Several keys: the first decides, the next orders its ties. ig-react and
    # acn-python both match 2 skills; acn-java matches 1.
    assert job_ids(jobs_client.get("/jobs", params={"sort": "score,salary"})) == ["acn-python", "ig-react", "acn-java"]
    assert job_ids(jobs_client.get("/jobs", params={"sort": "score,salary_lowest"})) == ["ig-react", "acn-python", "acn-java"]
    assert job_ids(jobs_client.get("/jobs", params=[("sort", "score"), ("sort", "salary_lowest")])) == [
        "ig-react", "acn-python", "acn-java",
    ]

    page = jobs_client.get("/jobs", params={"sort": "salary", "limit": 2, "offset": 1}).json()
    assert [job["id"] for job in page["jobs"]] == ["ig-react", "acn-java"]
    assert (page["total"], page["limit"], page["offset"]) == (3, 2, 1)
    assert jobs_client.get("/jobs", params={"offset": 10}).json()["jobs"] == []


@pytest.mark.parametrize(
    "params, message",
    [
        ({"status": "bogus"}, "Unknown status 'bogus'; expected one of unemailed, emailed"),
        ({"remote": "maybe"}, "Unknown remote 'maybe'; expected one of remote, unmarked, not_remote"),
        ({"sort": "nope"}, "Unknown sort 'nope'; expected one of last_seen, posted, salary"),
        ({"sort": "score,nope"}, "Unknown sort 'nope'"),
        ({"limit": 0}, "Invalid request: limit:"),
        ({"limit": 501}, "Invalid request: limit:"),
        ({"min_salary": -1}, "Invalid request: min_salary:"),
        ({"posted_since": "yesterday"}, "Invalid request: posted_since:"),
    ],
)
def test_list_jobs_rejects_bad_parameters(jobs_client, params, message):
    response = jobs_client.get("/jobs", params=params)
    assert response.status_code == 422
    assert response.json()["error"].startswith(message)


def test_job_stats_counts_everything_or_the_filtered_jobs(jobs_client):
    stats = jobs_client.get("/jobs/stats").json()
    assert stats["total"] == 3
    assert stats["applied"] == 1
    assert stats["by_status"]["emailed"] == 1 and stats["by_status"]["offer"] == 0
    assert stats["by_company"] == {"Accenture": 2, "Insight Global": 1}
    assert stats["by_remote"] == {"remote": 2, "unmarked": 1, "not_remote": 0}

    accenture = jobs_client.get("/jobs/stats", params={"company": "Accenture"}).json()
    assert accenture["total"] == 2
    assert accenture["by_status"]["interviewing"] == 1


def test_get_job(jobs_client):
    response = jobs_client.get("/jobs/acn-python")
    assert response.status_code == 200
    job = response.json()["job"]
    assert (job["id"], job["title"], job["notes"]) == ("acn-python", "Senior Python Engineer", "Recruiter: Sam")

    # Saved before salary periods were kept: no period yet.
    assert (job["salary_period"], job["salary_period_estimated"]) == (None, False)

    missing = jobs_client.get("/jobs/nope")
    assert missing.status_code == 404
    assert missing.json() == {"error": "Job nope is not in the store"}


def test_get_job_says_what_its_salary_is_per(job_store):
    job_store.update_jobs({"ig-react": {"salary_period": "hour", "salary_period_estimated": True}})
    client = TestClient(api.create_app(api.RunManager(FakeSearch()), store_factory=lambda: job_store))

    job = client.get("/jobs/ig-react").json()["job"]

    assert (job["salary_low"], job["salary_high"]) == (55.0, 65.0)
    assert (job["salary_period"], job["salary_period_estimated"]) == ("hour", True)


def test_patch_job_sets_status_like_the_dashboard(jobs_client, job_store):
    response = jobs_client.patch("/jobs/ig-react", json={"status": "applied", "notes": "  Applied on site  "})

    assert response.status_code == 200
    job = response.json()["job"]
    assert job["status"] == "applied"
    assert job["notes"] == "Applied on site"  # trimmed
    assert job["applied_at"] is not None and job["applied_at"] == job["status_updated_at"]
    assert job_store.get_job("ig-react")["status"] == "applied"  # saved
    assert job_ids(jobs_client.get("/jobs", params={"status": "applied"})) == ["ig-react", "acn-python"]


def test_patch_job_notes_only_and_clearing(jobs_client):
    assert jobs_client.patch("/jobs/acn-python", json={"notes": "Call back Friday"}).json()["job"]["notes"] == (
        "Call back Friday"
    )
    cleared = jobs_client.patch("/jobs/acn-python", json={"notes": None}).json()["job"]
    assert cleared["notes"] == ""
    assert cleared["status"] == "applied"  # untouched


def test_patch_job_work_arrangement(jobs_client, job_store):
    marked = jobs_client.patch("/jobs/ig-react", json={"work_arrangement": "on_site"}).json()["job"]
    assert (marked["work_arrangement"], marked["is_remote"], marked["site_is_remote"]) == ("on_site", False, True)
    assert marked["work_arrangement_set_at"] is not None
    assert "ig-react" not in job_ids(jobs_client.get("/jobs", params={"remote": "remote"}))  # out of "Remote only"
    assert job_store.get_job("ig-react")["is_remote"] is True  # the site's value is kept

    cleared = jobs_client.patch("/jobs/ig-react", json={"work_arrangement": None}).json()["job"]
    assert (cleared["work_arrangement"], cleared["is_remote"]) == (None, True)
    assert jobs_client.patch("/jobs/ig-react", json={"work_arrangement": "moon"}).status_code == 422


@pytest.mark.parametrize(
    "body, message",
    [
        ({}, "Nothing to update: provide status, notes, and/or work_arrangement"),
        ({"status": None}, "Nothing to update: provide status, notes, and/or work_arrangement"),
        ({"status": "bogus"}, "Invalid request: status:"),
        ({"notes": "x" * 5001}, "Invalid request: notes:"),
        ({"title": "hacked"}, "Invalid request: title: Extra inputs are not permitted"),
    ],
)
def test_patch_job_rejects_bad_bodies(jobs_client, job_store, body, message):
    response = jobs_client.patch("/jobs/ig-react", json=body)
    assert response.status_code == 422
    assert response.json()["error"].startswith(message)
    assert job_store.get_job("ig-react")["status"] == "emailed"


def test_patch_unknown_job_is_404(jobs_client, job_store):
    response = jobs_client.patch("/jobs/nope", json={"status": "skipped"})
    assert response.status_code == 404
    assert job_store.get_job("nope") is None  # not created


def test_jobs_report_a_store_that_cant_be_opened_and_retry():
    attempts = []

    def broken_then_fixed():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("No Firebase credentials found.")
        return FakeStore()

    class FakeStore:
        def list_job_documents(self):
            return []

    client = TestClient(api.create_app(api.RunManager(FakeSearch()), store_factory=broken_then_fixed))
    failed = client.get("/jobs")
    assert failed.status_code == 500
    assert failed.json() == {"error": "Could not open the job store: No Firebase credentials found."}
    assert client.get("/jobs").json()["total"] == 0  # fixed without a restart
    client.get("/jobs")
    assert len(attempts) == 2  # then kept


@pytest.mark.parametrize(
    "method, path",
    [("get", "/jobs"), ("get", "/jobs/stats"), ("get", "/jobs/ig-react"), ("patch", "/jobs/ig-react")],
)
def test_jobs_need_the_token_when_configured(with_token, jobs_client, job_store, method, path):
    response = getattr(jobs_client, method)(path, **({"json": {"status": "skipped"}} if method == "patch" else {}))
    assert response.status_code == 401
    assert job_store.get_job("ig-react")["status"] == "emailed"

    ok = getattr(jobs_client, method)(
        path,
        headers={"Authorization": "Bearer s3cret"},
        **({"json": {"status": "skipped"}} if method == "patch" else {}),
    )
    assert ok.status_code == 200


# --- Reassessing saved jobs against your skills ------------------------------------------


REASSESSED = job_search.ReassessSummary(
    total_jobs=3, reassessed=2, changed=1, no_longer_match=1, fetched=2, unavailable=1, skills_source="saved"
)


def test_reassess_rescores_saved_jobs_and_returns_the_summary(job_store):
    calls = []

    def fake_reassess(store, fetch):
        calls.append((store, fetch))
        return REASSESSED

    client = TestClient(api.create_app(
        api.RunManager(FakeSearch()), store_factory=lambda: job_store, reassess=fake_reassess
    ))

    response = client.post("/jobs/reassess")

    assert response.status_code == 200
    assert response.json() == {
        "total_jobs": 3, "reassessed": 2, "changed": 1, "no_longer_match": 1,
        "fetched": 2, "unavailable": 1, "skills_source": "saved",
    }
    assert calls == [(job_store, True)]
    client.post("/jobs/reassess?fetch=false")
    assert calls[-1] == (job_store, False)


def test_reassess_really_rescores_with_the_saved_skills(job_store):
    """End to end through the real job_search.reassess_saved_jobs."""
    from search_skills import SearchSkills

    job_store.save_descriptions({"ig-react": "React and TypeScript.", "acn-python": "Python and AWS."})
    job_store.save_search_skills(SearchSkills(("React", "TypeScript", "Go"), ("React",)))
    client = TestClient(api.create_app(api.RunManager(FakeSearch()), store_factory=lambda: job_store))

    body = client.post("/jobs/reassess?fetch=false").json()

    assert body["reassessed"] == 2 and body["no_longer_match"] == 1
    react = client.get("/jobs/ig-react").json()["job"]
    python = client.get("/jobs/acn-python").json()["job"]
    assert (react["matches_skills"], react["skills_mismatch_reason"]) == (True, None)
    assert python["matches_skills"] is False
    assert python["skills_mismatch_reason"] == "it doesn't mention any of your skills"
    assert python["status"] == "applied"  # your status is left alone
    # Not reassessed yet (no description): null.
    assert client.get("/jobs/acn-java").json()["job"]["matches_skills"] is None


def test_reassess_waits_for_a_running_search(job_store):
    search = FakeSearch(block=True)
    manager = api.RunManager(search)
    client = TestClient(api.create_app(manager, store_factory=lambda: job_store, reassess=lambda s, f: REASSESSED))
    run = client.post("/runs").json()["run"]
    assert search.started.wait(5)

    response = client.post("/jobs/reassess")

    assert response.status_code == 409
    assert "A search is already running" in response.json()["error"]
    assert "reassesses saved jobs when it finishes" in response.json()["error"]
    assert response.json()["run"]["id"] == run["id"]
    search.release.set()
    wait_for(manager, run["id"])
    assert client.post("/jobs/reassess").status_code == 200


def test_a_search_waits_for_a_reassessment(job_store):
    started, release = threading.Event(), threading.Event()

    def slow_reassess(store, fetch):
        started.set()
        assert release.wait(5)
        return REASSESSED

    manager = api.RunManager(FakeSearch())
    client = TestClient(api.create_app(manager, store_factory=lambda: job_store, reassess=slow_reassess))
    worker = threading.Thread(target=lambda: client.post("/jobs/reassess"))
    worker.start()
    assert started.wait(5)

    run = client.post("/runs")
    again = client.post("/jobs/reassess")

    assert run.status_code == 409 and "being reassessed" in run.json()["error"]
    assert again.status_code == 409 and "being reassessed" in again.json()["error"]
    release.set()
    worker.join(5)
    assert client.post("/runs").status_code == 202


# --- Resume ----------------------------------------------------------------------------

import base64  # noqa: E402
import re  # noqa: E402

from resume_ai import AiReadError  # noqa: E402
from resume_parser import parse_resume  # noqa: E402
from tests.resume_files import SAMPLE_RESUME, make_pdf  # noqa: E402


def _fake_ai(text, your_skills):
    """Stands in for resume_ai.read_resume_with_ai: a parse, labelled as AI."""
    parsed = parse_resume(text, your_skills)
    return type(parsed)(**{**parsed.__dict__, "method": "ai", "provider": "anthropic", "model": "fake"})


@pytest.fixture
def resume_client(tmp_path):
    store = FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)
    app = api.create_app(api.RunManager(FakeSearch()), store_factory=lambda: store, ai_reader=_fake_ai)
    return TestClient(app)


def _upload(client, data, filename="jane.pdf"):
    return client.post("/resume", json={"filename": filename, "content_base64": base64.b64encode(data).decode()})


def test_no_resume_yet(resume_client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    body = resume_client.get("/resume").json()
    assert body["resume"] is None
    assert body["ai"]["configured"] is False and "ANTHROPIC_API_KEY" in body["ai"]["problem"]


def test_upload_a_resume_file_then_read_it_with_ai(resume_client):
    response = _upload(resume_client, make_pdf(SAMPLE_RESUME.splitlines()))

    assert response.status_code == 200
    saved = response.json()["resume"]
    assert (saved["filename"], saved["file_type"]) == ("jane.pdf", "pdf")
    assert isinstance(saved["uploaded_at"], str)  # JSON: timestamps as ISO strings
    parsed = saved["analyses"]["parse"]
    # "Present" is today, so the exact total moves with the clock.
    assert parsed["years_basis"] == "positions" and parsed["years_experience"] >= 10
    assert isinstance(parsed["analyzed_at"], str)
    assert {"name", "years", "mentions", "category", "last_used", "aliases"} <= set(parsed["skills"][0])

    analyzed = resume_client.post("/resume/analyze", json={"method": "ai"})
    assert analyzed.status_code == 200
    assert sorted(analyzed.json()["resume"]["analyses"]) == ["ai", "parse"]
    assert sorted(resume_client.get("/resume").json()["resume"]["analyses"]) == ["ai", "parse"]


def test_upload_pasted_text(resume_client):
    saved = resume_client.post("/resume", json={"text": SAMPLE_RESUME}).json()["resume"]
    assert (saved["filename"], saved["file_type"]) == ("Pasted text", "text")


@pytest.mark.parametrize(
    ("body", "status_code", "message"),
    [
        ({"filename": "cv.doc", "content_base64": base64.b64encode(b"\xd0\xcf\x11\xe0rest").decode()}, 422,
         r"\.doc\) files can't be read"),
        ({"content_base64": "not base64!"}, 422, "didn't arrive intact"),
        ({"text": "   "}, 422, "Paste your resume's text first"),
        ({"text": "a", "content_base64": "eA=="}, 422, "either content_base64 \\(a file\\) or text"),
        ({}, 422, "either content_base64"),
        ({"text": "a", "surprise": 1}, 422, "surprise"),
    ],
)
def test_upload_problems(resume_client, body, status_code, message):
    response = resume_client.post("/resume", json=body)
    assert response.status_code == status_code
    assert re.search(message, response.json()["error"])


def test_analyze_problems(tmp_path, monkeypatch):
    store = FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)

    def failing_ai(text, skills):
        raise AiReadError("Anthropic answered 401: invalid x-api-key")

    def slow_ai(text, skills):
        raise AiReadError("Anthropic didn't answer within 120s; try again.", timed_out=True)

    def client_with(reader=None):
        return TestClient(api.create_app(api.RunManager(FakeSearch()), store_factory=lambda: store, ai_reader=reader))

    assert client_with().post("/resume/analyze", json={"method": "parse"}).status_code == 404
    client_with().post("/resume", json={"text": SAMPLE_RESUME})

    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "RESUME_AI_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    not_configured = client_with().post("/resume/analyze", json={"method": "ai"})
    assert not_configured.status_code == 503 and "AI isn't set up" in not_configured.json()["error"]

    failed = client_with(failing_ai).post("/resume/analyze", json={"method": "ai"})
    assert (failed.status_code, failed.json()) == (502, {"error": "Anthropic answered 401: invalid x-api-key"})
    assert client_with(slow_ai).post("/resume/analyze", json={"method": "ai"}).status_code == 504
    assert client_with().post("/resume/analyze", json={"method": "guess"}).status_code == 422

    # The failures left the parsed reading alone.
    assert list(store.load_resume()["analyses"]) == ["parse"]


def test_delete_the_resume(resume_client):
    resume_client.post("/resume", json={"text": SAMPLE_RESUME})
    assert resume_client.delete("/resume").json() == {"resume": None}
    assert resume_client.get("/resume").json()["resume"] is None


@pytest.mark.parametrize(("method", "path"), [("get", "/resume"), ("post", "/resume"), ("post", "/resume/analyze"),
                                              ("delete", "/resume")])
def test_resume_needs_the_token_too(with_token, resume_client, method, path):
    assert getattr(resume_client, method)(path).status_code == 401
