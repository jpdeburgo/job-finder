"""Reassessing saved jobs against your skills (job_search.reassess_saved_jobs)."""

import json

import pytest

import job_search
from job_sites import InsightGlobalSite, Posting
from job_store import FirestoreJobStore, job_document
from search_skills import SearchSkills

CORE = job_search.TRACKS[0].name
JAVA = job_search.TRACKS[1].name
MINE = SearchSkills(("Go", "Kotlin", "Kubernetes", "PostgreSQL"), ("Go", "Kotlin"))

PYTHON_TEXT = "Python, React and TypeScript on AWS. 3+ years of experience."
GO_TEXT = "Go services on Kubernetes with PostgreSQL."


def _doc(job_id, title="Full Stack Developer", track=CORE, **fields):
    return {
        "job_id": job_id, "title": title, "company": "Insight Global", "track": track,
        "url": f"https://insightglobal.com/jobs/{job_id.removeprefix('insight-global-')}",
        "is_remote": True, "status": "emailed", "matched_skills": [], "score": 0, **fields,
    }


@pytest.fixture
def store(tmp_path):
    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)
    store.import_documents({
        "insight-global-py": _doc("insight-global-py", status="applied", notes="Call back Monday"),
        "insight-global-go": _doc("insight-global-go", title="Platform Engineer"),
        "insight-global-closed": _doc("insight-global-closed", fit_score=71),
    })
    store.save_descriptions({"insight-global-py": PYTHON_TEXT, "insight-global-go": GO_TEXT})
    return store


def _tracks(skills=None):
    return job_search.build_tracks(skills)


# --- One job -------------------------------------------------------------------------------


def test_a_saved_job_is_scored_like_the_search_scores_it():
    data = _doc("insight-global-py")
    fields = job_search.assess_saved_job(data, PYTHON_TEXT, _tracks())

    posting = Posting(job_id="insight-global-py", title=data["title"], url=data["url"],
                      company="Insight Global", is_remote=True, job_type="Contract", description=PYTHON_TEXT)
    match = job_search.evaluate_posting(posting, InsightGlobalSite(job_search.INSIGHT_GLOBAL_URL),
                                        job_search.TRACKS[0])
    assert fields["matched_skills"] == match.matched_skills
    assert (fields["fit_score"], fields["fit_breakdown"], fields["fit_reasons"]) == (
        match.fit_score, match.fit_breakdown, match.fit_reasons
    )
    assert fields["score"] == len(match.matched_skills)
    assert (fields["matches_skills"], fields["skills_mismatch_reason"]) == (True, None)


@pytest.mark.parametrize(
    ("title", "text", "reason"),
    [
        ("Software Engineer", "Rust and Elixir.", "it doesn't mention any of your skills"),
        ("Software Engineer", "Go and Elixir.", "it mentions only Go; a match needs 2 of your skills"),
        ("Software Engineer", "Kubernetes and PostgreSQL.",
         "it mentions Kubernetes, PostgreSQL, but none of your core skills"),
        ("Scala Engineer", GO_TEXT, "its title names Scala, which isn't one of your skills"),
    ],
)
def test_why_a_job_no_longer_matches(title, text, reason):
    fields = job_search.assess_saved_job(_doc("j", title=title), text, _tracks(MINE))
    assert (fields["matches_skills"], fields["skills_mismatch_reason"]) == (False, reason)


def test_a_job_is_reassessed_on_its_own_track():
    """A Java growth-track job keeps needing just Java, whatever your list says."""
    data = _doc("j", title="Junior Java Developer", track=JAVA)
    fields = job_search.assess_saved_job(data, "Java and Spring.", _tracks(MINE))
    assert fields["matched_skills"] == ["Java"]
    assert fields["matches_skills"] is True


def test_an_unknown_track_is_treated_as_the_core_track():
    fields = job_search.assess_saved_job(_doc("j", track="Old track name"), GO_TEXT, _tracks(MINE))
    assert fields["matched_skills"] == ["Go", "Kubernetes", "PostgreSQL"]


# --- Every saved job ------------------------------------------------------------------------


def test_reassessing_after_changing_your_skills(store, capsys):
    store.save_search_skills(MINE)

    summary = job_search.reassess_saved_jobs(store, fetch_missing=False)

    py, go = store.get_job("insight-global-py"), store.get_job("insight-global-go")
    assert (py["matches_skills"], py["skills_mismatch_reason"]) == (False, "it doesn't mention any of your skills")
    assert py["matched_skills"] == [] and py["score"] == 0
    # Flagged, never deleted, and your status and notes are left alone.
    assert (py["status"], py["notes"]) == ("applied", "Call back Monday")
    assert go["matched_skills"] == ["Go", "Kubernetes", "PostgreSQL"] and go["matches_skills"] is True
    assert go["fit_reasons"][0] == "Skills: Go, Kubernetes, PostgreSQL (1 core)"
    # No description saved: left as it was.
    assert store.get_job("insight-global-closed")["fit_score"] == 71
    assert "matches_skills" not in store.get_job("insight-global-closed")

    assert summary == job_search.ReassessSummary(
        total_jobs=3, reassessed=2, changed=2, no_longer_match=1, fetched=0, unavailable=1, skills_source="saved",
    )
    out = capsys.readouterr().out
    assert "Reassessed 2 saved job(s) against your skills: 2 changed, 1 no longer match; 1 left as they were" in out


def test_going_back_to_the_default_skills_matches_them_again(store, tmp_path):
    store.save_search_skills(MINE)
    job_search.reassess_saved_jobs(store, fetch_missing=False)
    # Reset to defaults: the dashboard deletes settings/search_skills.
    data = json.loads((tmp_path / "db.json").read_text())
    del data["settings"]
    (tmp_path / "db.json").write_text(json.dumps(data))

    summary = job_search.reassess_saved_jobs(store, fetch_missing=False)

    assert summary.skills_source == "default"
    assert store.get_job("insight-global-py")["matches_skills"] is True
    assert store.get_job("insight-global-py")["matched_skills"] == [
        "Python", "TypeScript", "React", "Full Stack", "AWS"
    ]
    assert store.get_job("insight-global-go")["matches_skills"] is False
    assert summary.no_longer_match == 1


def test_only_jobs_that_changed_are_written(store, monkeypatch):
    job_search.reassess_saved_jobs(store, fetch_missing=False)
    written = []
    monkeypatch.setattr(store, "update_jobs", lambda changes: written.append(changes))

    summary = job_search.reassess_saved_jobs(store, fetch_missing=False)

    assert written == [{}]
    assert summary.changed == 0 and summary.reassessed == 2


def test_missing_descriptions_are_loaded_once_and_kept(store, monkeypatch):
    calls = []

    def fake_fetch(jobs, selectors=None):
        calls.append([doc_id for doc_id, _ in jobs])
        return {"insight-global-closed": "Python and React apps."}, 0

    monkeypatch.setattr(job_search, "fetch_missing_descriptions", fake_fetch)

    summary = job_search.reassess_saved_jobs(store)
    again = job_search.reassess_saved_jobs(store)

    assert calls == [["insight-global-closed"]]  # the second time, nothing is missing
    assert (summary.fetched, summary.unavailable, summary.reassessed) == (1, 0, 3)
    assert (again.fetched, again.reassessed) == (0, 3)
    assert store.load_descriptions()["insight-global-closed"] == "Python and React apps."
    assert store.get_job("insight-global-closed")["matched_skills"] == ["Python", "React", "Full Stack"]


def test_a_search_saves_descriptions_apart_from_the_jobs(tmp_path):
    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)
    match = job_search.JobMatch(
        job_id="j1", title="T", city="", state="", is_remote=True, job_type="Contract",
        salary_low=0, salary_high=0, url="https://x", track=CORE, matched_skills=["Python"],
        description="Python all day.",
    )

    store.save_matches([match], new_ids={"j1"})

    data = json.loads((tmp_path / "db.json").read_text())
    assert "description" not in data["jobs"]["j1"] and "description" not in job_document(match)
    assert data["jobs"]["j1"]["matches_skills"] is True
    assert data["job_descriptions"]["j1"]["text"] == "Python all day."
    assert store.load_descriptions() == {"j1": "Python all day."}


def test_main_reassesses_saved_jobs_without_loading_postings(store, monkeypatch):
    store.save_search_skills(MINE)
    monkeypatch.setattr(job_search, "run_all_searches", lambda *a, **k: [])
    monkeypatch.setattr(job_search, "fetch_missing_descriptions", pytest.fail)

    job_search.main(store)

    assert store.get_job("insight-global-py")["matches_skills"] is False


def test_reassess_command(store, monkeypatch, capsys):
    monkeypatch.setattr(job_search, "get_job_store", lambda *a, **k: store)
    monkeypatch.setattr(job_search, "fetch_missing_descriptions", lambda jobs, selectors=None: ({}, len(jobs)))

    assert job_search.cli(["--reassess"]) == 0

    assert "1 left as they were (couldn't load the posting: closed?)" in capsys.readouterr().out


# --- Loading descriptions from the sites -------------------------------------------------------


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class DetailsSession:
    """Insight Global's details endpoint, for a few jobs."""

    def __init__(self, details):
        self.details, self.gets = details, []

    def get(self, url, params=None, timeout=None, headers=None):
        self.gets.append(url)
        job = url.split("/all/jobs/")[1].split("/")[0]
        if job not in self.details:
            raise job_search.requests.HTTPError("404 Not Found")
        return FakeResponse(self.details[job])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_descriptions_come_from_each_jobs_site(monkeypatch):
    session = DetailsSession({
        "a": {"description": "<p>Python</p><p>React</p>"},
        "empty": {"description": ""},
        "odd": ["not", "a dict"],  # an unexpected answer: skipped, not fatal
    })
    monkeypatch.setattr(job_search, "build_session", lambda: session)
    jobs = [(f"insight-global-{j}", _doc(f"insight-global-{j}")) for j in ("a", "empty", "closed", "odd")]
    jobs.append(("somewhere-else-1", _doc("somewhere-else-1")))  # not a configured site

    texts, unavailable = job_search.fetch_missing_descriptions(jobs)

    assert texts == {"insight-global-a": "Python\nReact"}
    assert unavailable == 4
    # One details request per job (no search for its remote flags).
    assert sorted(session.gets) == sorted(
        f"https://insightglobal.com/all/jobs/{j}/details" for j in ("a", "empty", "closed", "odd")
    )


def test_recheck_keeps_the_descriptions_it_loads(tmp_path, monkeypatch):
    session = DetailsSession({"r": {"jobTitle": "Python Developer", "description": "<p>Python, fully remote.</p>"}})
    session.get = _with_search(session.get)
    monkeypatch.setattr(job_search, "build_session", lambda: session)
    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)
    store.import_documents({"insight-global-r": _doc("insight-global-r", title="Python Developer")})

    job_search.recheck_saved_jobs(store)

    assert store.load_descriptions() == {"insight-global-r": "Python, fully remote."}


def _with_search(get):
    def wrapped(url, params=None, timeout=None, headers=None):
        if url.endswith("/all/jobs"):
            return FakeResponse({"jobs": [], "pageMetadata": {"totalPages": 1}})
        return get(url, params, timeout, headers)

    return wrapped


def test_changing_only_your_proficiency_rescores_the_fit(store):
    job_search.reassess_saved_jobs(store, fetch_missing=False)
    before = store.get_job("insight-global-py")
    rated = SearchSkills(
        job_search.default_search_skills().skills,
        job_search.default_search_skills().core_skills,
        (("Python", 1), ("React", 1), ("TypeScript", 1)),
    )
    store.save_search_skills(rated)

    summary = job_search.reassess_saved_jobs(store, fetch_missing=False)

    after = store.get_job("insight-global-py")
    assert after["fit_score"] < before["fit_score"]
    assert after["fit_reasons"][0].startswith("Skills: Python 1★, TypeScript 1★, React 1★")
    # Which jobs match doesn't depend on proficiency.
    assert after["matched_skills"] == before["matched_skills"] and after["matches_skills"] is True
    assert summary.changed == 1  # the Go job mentions none of those skills: unchanged
