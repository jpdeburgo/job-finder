"""The on-site / hybrid check: postings whose own words contradict a "remote" flag."""

from datetime import datetime, timedelta, timezone

import pytest

import job_search
from job_sites import (
    GreenhouseSite,
    InsightGlobalSite,
    JobSite,
    Posting,
    SearchPage,
    WorkdaySite,
    greenhouse_workplace,
    html_to_text,
    onsite_evidence,
    structured_remote,
)
from job_store import FirestoreJobStore

# Every one of these says the job is on-site or hybrid.
ONSITE_POSTINGS = [  # (title, description, location)
    ("Java Developer (On-Site)", "", ""),
    ("Onsite - .NET Developer", "", ""),
    ("Software Engineer - Hybrid", "", ""),
    ("Hybrid Software Engineer", "", ""),
    ("React Developer", "", "Denver, CO (Hybrid)"),
    ("Python Developer", "This role is onsite in Dallas, TX.", ""),
    ("Python Developer", "This position is 100% in-office.", ""),
    ("Python Developer", "The position will be hybrid, based in Atlanta.", ""),
    ("Python Developer", "This is a hybrid position requiring 3 days in office.", ""),
    ("Python Developer", "Must be onsite in Plano 5 days a week.", ""),
    ("Python Developer", "Candidates must be able to work onsite at our Charlotte office.", ""),
    ("Python Developer", "You will be required to report to our Austin office.", ""),
    ("Python Developer", "Schedule: 3 days onsite, 2 days remote.", ""),
    ("Python Developer", "Hybrid schedule - 2-3 days a week in office.", ""),
    ("Python Developer", "Onsite 4 days a week in Irving.", ""),
    ("Python Developer", "Work arrangement: Hybrid", ""),
    ("Python Developer", "Location Type - Onsite", ""),
    ("Python Developer", "Location: On-site (Dallas, TX)", ""),
    ("Python Developer", "This is not a remote position.", ""),
    ("Python Developer", "Not fully remote.", ""),
    ("Python Developer", "Remote work is not available for this role.", ""),
    ("Python Developer", "This role is not eligible for remote work.", ""),
    ("Python Developer", "Remote candidates will not be considered.", ""),
    ("Python Developer", "Remote: No", ""),
    ("Python Developer", "Requires onsite presence at the client site in Reston.", ""),
    ("Python Developer", "We work in a hybrid work model with 3 days in our NYC office.", ""),
    ("Python Developer", "Expected to be in the office Tuesday through Thursday.", ""),
    ("Python Developer", "Required: 4x/week in office", ""),
]

# None of these do: remote jobs, benefits, occasional visits, choices, and tech.
REMOTE_POSTINGS = [
    ("Remote Java Developer", "", ""),
    ("Remote/Onsite Java Developer", "", ""),
    ("Hybrid Cloud Engineer", "", ""),
    ("Hybrid Mobile App Developer (React Native)", "", ""),
    ("Senior Streaming Engineer (Kafka & GCP)-Onshore", "", "Atlanta, GA"),
    ("Python Developer", "This role is fully remote.", "Remote - US"),
    ("Python Developer", "Enjoy our on-site gym, onsite cafeteria and on-site childcare.", ""),
    ("Python Developer", "Occasional onsite visits to the client may be required.", ""),
    ("Python Developer", "This role is remote with occasional travel onsite for meetings.", ""),
    ("Python Developer", "You may need to be onsite once a quarter for planning.", ""),
    ("Python Developer", "Must be willing to travel to the office for onboarding.", ""),
    ("Python Developer", "This position can be remote or hybrid.", ""),
    ("Python Developer", "This role is hybrid or remote depending on location.", ""),
    ("Python Developer", "No onsite work required.", ""),
    ("Python Developer", "This is not an onsite role.", ""),
    ("Python Developer", "Experience with hybrid cloud environments and on-premise systems.", ""),
    ("Python Developer", "Build hybrid apps with Ionic. Design hybrid models for search.", ""),
    ("Python Developer", "We are a remote-first company; in-person events twice a year.", ""),
    ("Python Developer", "Work from anywhere in the US. Onsite interviews are not required.", ""),
    ("Python Developer", "Onsite 2 days a month for team meetings.", ""),
    ("Python Developer", "Must be able to pass a background check. Work on site reliability tooling.", ""),
    ("Python Developer", "You will work in person with stakeholders over video.", ""),
    ("Python Developer", "Not a remote-first company, but this team is distributed and fully remote.", ""),
    ("Python Developer", "Remote (US). Interviews will be held in-person or over Zoom.", ""),
    ("Python Developer", "This role is remote. Our offices in Austin are available if you prefer in-office work.", ""),
]


@pytest.mark.parametrize("title, description, location", ONSITE_POSTINGS)
def test_on_site_and_hybrid_postings_are_caught(title, description, location):
    assert onsite_evidence(title, description, location) is not None


@pytest.mark.parametrize("title, description, location", REMOTE_POSTINGS)
def test_remote_postings_are_left_alone(title, description, location):
    assert onsite_evidence(title, description, location) is None


# Insight Global recruiters' phrasing, as HTML (lines matter: "Onsite" alone
# on a line is a label).
IG_ONSITE = [
    "100% onsite in Plano, TX.",
    "This role is fully in-office.",
    "Onsite in Atlanta, GA - must be local.",
    "Hybrid at our Dallas office.",
    "ONSITE - Plano, TX",
    "Location: Irving, TX (Onsite)",
    "Irving, TX (Hybrid)",
    "Java Developer (onsite 3 days a week)",
    "This consultant will sit onsite in Plano 5 days a week.",
    "Candidates must be local to Atlanta and onsite Tuesday-Thursday.",
    "Must be willing to come into the office daily.",
    "Onsite 3x a week in Charlotte.",
    "Schedule: Onsite M-F",
    "Remote status: Hybrid",
    "NO REMOTE.",
    "Contract: 12 months. No remote!",
    "<p>Job Details</p><ul><li>Onsite</li><li>12 month contract</li></ul>",
    "<p>Required Skills</p><p>Java, Spring</p><p>Hybrid - Dallas, TX</p>",
    "<li>100% Onsite</li>",
    "<br>Hybrid (3 days in office)<br>",
    "<li>Work type: Onsite</li>",
    "Position is onsite in Plano.",
    "Great team. Role is hybrid (3 days).",
    "Location: Dallas, TX - Onsite",
    "<p>Plano, TX | Hybrid</p>",
    "Remote Eligible: No",
    "Work Location: Irving, TX / On-site",
]
IG_REMOTE = [
    "Onsite: No",
    "Hybrid: No - fully remote",
    "Onsite - N/A",
    "Provide onsite support at client locations as needed.",
    "<li>Onsite support for hardware installs</li>",
    "<li>Experience with Hybrid Mobile frameworks (Ionic)</li>",
    "<li>Remote</li><li>Hybrid option available for local candidates</li>",
    "<li>Onsite/Remote flexible</li>",
    "Onsite interviews in Atlanta.",
    "Must be onsite in Atlanta once a quarter for planning.",
    "Hybrid in nature, our teams span the globe. This role is fully remote.",
    "<li>Remote (occasional onsite)</li>",
    "Work with our onsite teams in Dallas.",
    "You must be able to work with onsite engineers to debug issues.",
    "100% remote - no onsite required.",
    "Remote: Yes",
    "(remote, onsite optional)",
    "(Remote or Onsite)",
    "Location: Dallas, TX - Remote",
    "Position is remote.",
    "Remote Eligible: Yes",
    "<li>Skills: AWS, Azure, hybrid</li>",
    "Experience with cloud (public, private, hybrid)",
    "Plano, TX | Remote",
]


@pytest.mark.parametrize("html", IG_ONSITE)
def test_recruiter_phrasing_for_on_site_is_caught(html):
    assert onsite_evidence("Java Developer", html_to_text(html, keep_lines=True)) is not None


@pytest.mark.parametrize("html", IG_REMOTE)
def test_recruiter_phrasing_that_isnt_on_site_is_left_alone(html):
    assert onsite_evidence("Java Developer", html_to_text(html, keep_lines=True)) is None


def test_html_to_text_can_keep_lines():
    html = "<p>Day to day</p><ul><li>Build  APIs</li><li>Onsite</li></ul>Pay&amp;benefits<br>Apply"
    assert html_to_text(html, keep_lines=True) == "Day to day\nBuild APIs\nOnsite\nPay&benefits\nApply"
    assert html_to_text(html) == "Day to day Build APIs Onsite Pay&benefits Apply"


def test_evidence_quotes_the_posting():
    assert onsite_evidence("Java Developer (On-Site)") == 'title says "On-Site"'
    assert onsite_evidence("Dev", "Great team. This role is onsite in Dallas, TX. Apply now.") == (
        'description: "This role is onsite in Dallas, TX"'  # just the sentence that says so
    )
    assert onsite_evidence("Dev", "", "Denver, CO (Hybrid)") == 'location says "Denver, CO (Hybrid)"'


# --- Structured fields ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"workRemote": True, "workType": "Onsite"}, (False, 'workType = "Onsite"')),
        ({"isHybrid": True}, (False, "isHybrid = true")),
        ({"job": {"locationType": "HYBRID"}}, (False, 'job.locationType = "HYBRID"')),
        ({"remoteEligible": False}, (False, "remoteEligible = false")),
        ({"workType": "Non-Remote"}, (False, 'workType = "Non-Remote"')),
        ({"workplaceType": "Remote"}, (True, 'workplaceType = "Remote"')),
        ({"workArrangements": ["Remote", "Hybrid"]}, (True, "workArrangements = ['Remote', 'Hybrid']")),
        # Insight Global-style variations the old reader missed
        ({"remoteWork": "No"}, (False, 'remoteWork = "No"')),
        ({"telework": "N"}, (False, 'telework = "N"')),
        ({"workLocation": {"type": "ONSITE"}}, (False, 'workLocation.type = "ONSITE"')),
        ({"tags": ["Contract", "Onsite"]}, (False, "tags = ['Contract', 'Onsite']")),
        ({"badges": [{"label": "Hybrid"}]}, (False, 'badges.label = "Hybrid"')),
        ({"setting": "100% On-Site"}, (False, 'setting = "100% On-Site"')),
        ({"category": "Hybrid Cloud"}, (None, "")),  # not just an arrangement
        ({"skills": ["Java", "Remote Sensing"]}, (None, "")),
        ({"count": 1, "active": True}, (None, "")),  # true/1 outside a named field is just data
        ({"workRemote": True}, (None, "")),  # skipped: the search flag itself
        ({"isOnsite": False}, (None, "")),
        ({"jobType": "Contract", "workAddress": {"locality": "Austin"}}, (None, "")),
        ({"description": "This role is onsite. " * 10}, (None, "")),  # text is for onsite_evidence
    ],
)
def test_structured_remote_reads_work_arrangement_fields(payload, expected):
    assert structured_remote(payload, skip=("workRemote",)) == expected


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeIG:
    """Insight Global's search and details endpoints."""

    def __init__(self, record, details):
        self.record, self.details = record, details

    def get(self, url, params=None, timeout=None, headers=None):
        if url.endswith("/details"):
            return FakeResponse(self.details)
        return FakeResponse({"jobs": [self.record], "pageMetadata": {"totalPages": 1}})


IG_RECORD = {
    "requisitionId": "abc", "jobTitle": "Java Developer", "workRemote": True, "jobType": "Contract",
    "workAddress": {"locality": "Plano", "administrativeArea": "TX"},
}


def test_insight_global_details_fields_override_work_remote():
    site = InsightGlobalSite(job_search.INSIGHT_GLOBAL_URL)
    session = FakeIG(IG_RECORD, {"description": "<p>Java</p>", "workSetting": "Onsite"})

    (listed,) = site.fetch_page(session, "Java", 1).postings
    detailed = site.fetch_details(session, listed)

    assert listed.is_remote is True
    assert (detailed.is_remote, detailed.remote_note) == (False, 'workSetting = "Onsite"')


def test_insight_global_search_record_fields_override_work_remote():
    site = InsightGlobalSite(job_search.INSIGHT_GLOBAL_URL)
    session = FakeIG({**IG_RECORD, "isHybrid": True}, {"description": ""})

    (listed,) = site.fetch_page(session, "Java", 1).postings

    assert (listed.is_remote, listed.remote_note) == (False, "isHybrid = true")


def test_check_remote_explains_an_insight_global_job(monkeypatch, capsys):
    details = {
        "jobTitle": "Java Developer", "workRemote": True, "jobType": "Contract",
        "description": "<p>Build APIs</p><p>Onsite - Plano, TX</p><p>Great benefits</p>",
    }

    class Session(FakeIG):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(job_search, "build_session", lambda: Session(IG_RECORD, details))

    assert job_search.cli(["--check-remote", "https://insightglobal.com/jobs/abc"]) == 0

    out = capsys.readouterr().out
    assert "Insight Global: Java Developer" in out
    assert 'VERDICT: NOT REMOTE. Its description: "Onsite - Plano, TX".' in out
    assert "  search result.workRemote: True" in out and "  details.jobType: Contract" in out
    assert "  | Onsite - Plano, TX" in out
    assert "Great benefits" not in out  # only lines about where you'd work


def test_check_remote_takes_a_saved_job_id(monkeypatch, capsys, tmp_path):
    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)
    store.import_documents({"insight-global-abc": {
        "job_id": "insight-global-abc", "title": "Java Developer",
        "url": "https://insightglobal.com/jobs/abc", "is_remote": True,
    }})
    seen = []

    class Session(FakeIG):
        def get(self, url, **kwargs):
            seen.append(url)
            return super().get(url, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(job_search, "build_session", lambda: Session(IG_RECORD, {"description": "Java"}))

    assert job_search.check_remote(["insight-global-abc"], store) == 0

    # The details, then the job's own entry in the search results (by its saved title).
    assert seen == ["https://insightglobal.com/all/jobs/abc/details", "https://insightglobal.com/all/jobs"]
    assert "VERDICT: remote. No on-site or hybrid wording found." in capsys.readouterr().out


def test_check_remote_reports_what_it_cant_check(capsys, tmp_path):
    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)

    assert job_search.check_remote(["no-such-job"], store) == 1
    assert "neither a job URL nor a saved job ID" in capsys.readouterr().out


def test_saved_jobs_are_corrected_when_the_sites_own_fields_say_on_site(tmp_path):
    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)
    store.import_documents({"insight-global-abc": {"job_id": "insight-global-abc",
                                                   "title": "Java Developer", "is_remote": True}})
    site = FakeSite([])
    posting = _remote_posting("insight-global-abc", "Java Developer")
    posting = Posting(**{**posting.__dict__, "is_remote": False, "remote_note": 'workSetting = "Onsite"'})
    site.postings = [posting]
    site.remote_only = True

    result = job_search.search_site(None, site, [(job_search.TRACKS[0], "Java Developer")])
    job_search.correct_saved_remote_flags(store, result.onsite)

    saved = store.get_job("insight-global-abc")
    assert (saved["is_remote"], saved["not_remote_reason"]) == (False, 'the site\'s workSetting = "Onsite"')



def test_greenhouse_workplace_type_field_beats_the_location():
    def field(name, value):
        return [{"id": 1, "name": name, "value": value, "value_type": "single_select"}]

    assert greenhouse_workplace(field("Workplace Type", "Hybrid")) is False
    assert greenhouse_workplace(field("Location Type", "On-site")) is False
    assert greenhouse_workplace(field("Workplace Type", "Remote")) is True
    assert greenhouse_workplace(field("Remote", "No")) is False
    assert greenhouse_workplace(field("Remote Eligible", "Yes")) is True
    assert greenhouse_workplace(field("Department Budget", "Hybrid")) is None  # not a workplace field
    assert greenhouse_workplace(None) is None


def test_greenhouse_board_reads_the_workplace_field(monkeypatch):
    site = GreenhouseSite("Acme", "https://boards.greenhouse.io/acme", "acme")
    job = {
        "id": 1, "title": "Software Engineer", "location": {"name": "Remote - US"},
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "content": "Python",
        "metadata": [{"name": "Workplace Type", "value": "Hybrid"}],
    }
    monkeypatch.setattr(site, "_get_json", lambda *a, **k: {"jobs": [job]})

    (posting,) = site.fetch_all(None)

    assert posting.is_remote is False


class FakeWorkday:
    def __init__(self, details):
        self.details = details

    def get(self, url, headers=None, timeout=None):
        class Response:
            def raise_for_status(self):
                pass

            def json(inner):
                return {"jobPostingInfo": self.details}

        return Response()


def test_workday_details_remote_type_beats_a_remote_location_in_the_listing():
    # The search results said "Remote" (from locationsText), but the job's own
    # remoteType says Hybrid: the job isn't remote.
    site = WorkdaySite("Acme", "https://acme.wd5.myworkdayjobs.com/Careers",
                       "https://acme.wd5.myworkdayjobs.com/Careers")
    listed = Posting(job_id="acme-1", title="Developer", url="https://x", company="Acme",
                     city="Remote", is_remote=True, detail_key="/job/x_1")

    detailed = site.fetch_details(FakeWorkday({"jobDescription": "Python", "remoteType": "Hybrid"}), listed)
    assert detailed.is_remote is False

    unset = site.fetch_details(FakeWorkday({"jobDescription": "Python"}), listed)
    assert unset.is_remote is True  # no remoteType: the listing's answer stands


# --- In the search ---------------------------------------------------------------------------


RECENT = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
DESCRIPTION = "Python, React, TypeScript and Node.js. 3+ years of experience."


class FakeSite(JobSite):
    """A site whose every posting is flagged remote, like Insight Global's workRemote."""

    name = "Insight Global"
    kind = "insight-global"

    def __init__(self, postings):
        self.postings = postings

    def fetch_page(self, session, term, page):
        return SearchPage([p for p in self.postings if term.lower() in p.title.lower()], has_more=False)


def _remote_posting(job_id, title, description=DESCRIPTION):
    return Posting(job_id=job_id, title=title, url=f"https://x/{job_id}", company="Insight Global",
                   is_remote=True, job_type="Contract", posted_date=RECENT, description=description)


def test_search_drops_remote_flagged_jobs_that_say_on_site(capsys):
    site = FakeSite([
        _remote_posting("ig-ok", "Python Developer"),
        _remote_posting("ig-title", "Python Developer (On-Site)"),
        _remote_posting("ig-desc", "Python Developer", DESCRIPTION + " Must be onsite in Plano 5 days a week."),
    ])

    result = job_search.search_site(None, site, [(job_search.TRACKS[0], "Python Developer")])

    assert [m.job_id for m in result.matches] == ["ig-ok"]
    assert result.onsite == {
        "ig-title": 'title says "On-Site"',
        "ig-desc": 'description: "Must be onsite in Plano 5 days a week"',
    }
    out = capsys.readouterr().out
    assert "'Python Developer (On-Site)' (ig-title) is marked remote, but its title says" in out


def test_with_remote_only_off_the_job_is_kept_as_not_remote():
    site = FakeSite([_remote_posting("ig-title", "Python Developer (On-Site)")])
    site.remote_only = False

    (match,) = job_search.search_site(None, site, [(job_search.TRACKS[0], "Python Developer")]).matches

    assert match.is_remote is False


# --- Jobs already saved --------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)

    def doc(title, **fields):
        return {"job_id": title, "title": title, "is_remote": True, "status": "applied", **fields}

    store.import_documents({
        "ig-onsite-title": doc("Java Developer - Onsite"),
        "ig-onsite-desc": doc("Python Developer"),  # only the description says so
        "ig-fine": doc("Python Developer"),
        "ig-hybrid-location": doc("React Developer", city="Denver", state="CO (Hybrid)"),
        "acn-already": doc("Dev (On-Site)", is_remote=False),
    })
    return store


def test_saved_jobs_are_corrected_from_their_title_and_this_runs_descriptions(store, capsys):
    found = {"ig-onsite-desc": 'description: "This role is onsite"'}

    assert job_search.correct_saved_remote_flags(store, found) == 3

    assert store.get_job("ig-onsite-title")["is_remote"] is False
    assert store.get_job("ig-onsite-title")["not_remote_reason"] == 'its title says "Onsite"'
    assert store.get_job("ig-onsite-desc")["not_remote_reason"] == 'its description: "This role is onsite"'
    assert store.get_job("ig-hybrid-location")["is_remote"] is False
    assert store.get_job("ig-fine")["is_remote"] is True
    assert "not_remote_reason" not in store.get_job("acn-already")  # already not remote
    # Your status is left alone.
    assert store.get_job("ig-onsite-title")["status"] == "applied"
    assert "Marked 3 saved job(s) not remote" in capsys.readouterr().out


def test_main_corrects_saved_jobs_after_saving_the_run(store, monkeypatch):
    def fake_search(selectors, include_unmarked, onsite, checked=None):
        onsite["ig-onsite-desc"] = 'description: "must be onsite"'
        return []

    monkeypatch.setattr(job_search, "run_all_searches", fake_search)

    job_search.main(store)

    assert store.get_job("ig-onsite-desc")["is_remote"] is False
    assert store.get_job("ig-onsite-title")["is_remote"] is False
    assert store.get_job("ig-fine")["is_remote"] is True


# --- Re-checking saved jobs the search didn't see -------------------------------------------------


class SavedJobsSession:
    """Insight Global's search and details endpoints for a few saved jobs."""

    DETAILS = {
        "onsite": {"jobTitle": "Java Developer", "description": "<p>Java</p><p>Onsite - Plano, TX</p>"},
        "badge": {"jobTitle": "React Developer", "description": "React", "workSetting": "On-site"},
        "fine": {"jobTitle": "Python Developer", "description": "<p>Fully remote.</p>"},
        # Like the Reston job: nothing in the description or details; only the
        # search entry's flag says it isn't remote.
        "flag": {"jobTitle": "Secret - Full Stack Software Engineer", "description": "<p>Build things.</p>"},
    }
    WORK_REMOTE = {"flag": "false"}

    def __init__(self):
        self.gets = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.gets.append(url)
        if url.endswith("/all/jobs"):  # the search: the job's own entry, found by title
            assert params["filter.includeOnlyRemoteWork"] == "false"
            jobs = [
                {"requisitionId": job, "jobTitle": details["jobTitle"], "jobType": "Contract",
                 "workRemote": self.WORK_REMOTE.get(job, True)}
                for job, details in self.DETAILS.items() if details["jobTitle"] == params["keyword"]
            ]
            return FakeResponse({"jobs": jobs, "pageMetadata": {"totalPages": 1}})
        job = url.split("/all/jobs/")[1].split("/")[0]
        if job not in self.DETAILS:
            raise job_search.requests.HTTPError("404 Not Found")
        return FakeResponse(self.DETAILS[job])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def saved(tmp_path, monkeypatch):
    session = SavedJobsSession()
    monkeypatch.setattr(job_search, "build_session", lambda: session)
    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)

    def doc(job, **fields):
        title = SavedJobsSession.DETAILS.get(job, {}).get("jobTitle", f"Job {job}")
        return {"job_id": f"insight-global-{job}", "title": title, "is_remote": True, "status": "emailed",
                "url": f"https://insightglobal.com/jobs/{job}", **fields}

    store.import_documents(
        {f"insight-global-{j}": doc(j) for j in ("onsite", "badge", "fine", "flag", "closed", "seen")}
    )
    store.import_documents({"insight-global-known": doc("known", is_remote=False)})
    return store, session


def test_saved_jobs_the_search_missed_are_rechecked(saved, capsys):
    store, session = saved

    changed = job_search.recheck_saved_jobs(store, skip={"insight-global-seen"})

    assert changed == 3
    flag = store.get_job("insight-global-flag")
    assert (flag["is_remote"], flag["not_remote_reason"]) == (False, "the site marks it hybrid or on-site")
    onsite, badge = store.get_job("insight-global-onsite"), store.get_job("insight-global-badge")
    assert (onsite["is_remote"], onsite["not_remote_reason"]) == (False, 'its description: "Onsite - Plano, TX"')
    assert (badge["is_remote"], badge["not_remote_reason"]) == (False, 'the site\'s workSetting = "On-site"')
    assert store.get_job("insight-global-fine")["is_remote"] is True
    assert store.get_job("insight-global-closed")["is_remote"] is True  # couldn't load: unchanged
    # Already not remote, or checked by this run's search: not loaded again.
    assert not any("/known/" in url or "/seen/" in url for url in session.gets)
    out = capsys.readouterr().out
    assert "Re-checked 5 saved job(s): 3 marked not remote, 1 couldn't be loaded" in out


def test_recheck_saved_command_writes_a_report(saved, monkeypatch, tmp_path, capsys):
    store, _ = saved
    report = tmp_path / "report.txt"
    monkeypatch.setattr(job_search, "REMOTE_CHECK_REPORT", report)
    monkeypatch.setattr(job_search, "get_job_store", lambda *a, **k: store)

    assert job_search.cli(["--recheck-saved"]) == 0

    text = report.read_text()
    assert "=== insight-global-fine" in text and "VERDICT: remote." in text
    assert "  | Fully remote." in text
    assert 'VERDICT: NOT REMOTE. Its description: "Onsite - Plano, TX".' in text
    assert "couldn't load the posting" in text


def test_main_rechecks_saved_jobs_after_a_search(saved, monkeypatch):
    store, session = saved
    monkeypatch.setattr(job_search, "RECHECK_SAVED_JOBS", True)

    def fake_search(selectors, include_unmarked, onsite, checked):
        checked.add("insight-global-seen")
        return []

    monkeypatch.setattr(job_search, "run_all_searches", fake_search)

    job_search.main(store)

    assert store.get_job("insight-global-onsite")["is_remote"] is False
    assert not any("/seen/" in url for url in session.gets)


def test_a_string_work_remote_flag_is_read_as_a_flag():
    site = InsightGlobalSite(job_search.INSIGHT_GLOBAL_URL)
    for value, expected in (("false", False), ("No", False), ("true", True), (True, True),
                            ("Onsite", False), ("Remote", True), (None, None)):
        session = FakeIG({**IG_RECORD, "workRemote": value}, {"description": ""})
        (posting,) = site.fetch_page(session, "Java", 1).postings
        assert posting.is_remote is expected, value


# --- Your say on how a job is worked ------------------------------------------------------------


def test_your_work_arrangement_wins_when_jobs_are_read(tmp_path):
    from job_queries import JobFilters, filter_jobs, normalize_job

    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)
    store.import_documents({"ig-1": {"job_id": "ig-1", "title": "Dev", "is_remote": True}})

    store.update_job("ig-1", work_arrangement="hybrid")
    job = normalize_job("ig-1", store.get_job("ig-1"))

    assert (job["is_remote"], job["work_arrangement"], job["site_is_remote"]) == (False, "hybrid", True)
    assert filter_jobs([job], JobFilters(remote=("remote",))) == []
    assert filter_jobs([job], JobFilters(remote=("not_remote",))) == [job]
    with pytest.raises(ValueError, match="Unknown work arrangement 'moon'"):
        store.update_job("ig-1", work_arrangement="moon")


def test_searches_never_undo_your_work_arrangement(tmp_path, monkeypatch):
    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)
    match = job_search.JobMatch(
        job_id="insight-global-abc", title="Secret - Full Stack Software Engineer", city="Reston",
        state="VA", is_remote=True, job_type="Contract To Perm", salary_low=71, salary_high=0,
        url="https://insightglobal.com/jobs/abc", track=job_search.TRACKS[0].name,
    )
    store.save_matches([match], new_ids={match.job_id})
    store.update_job(match.job_id, work_arrangement="on_site")

    # The next run finds it again, flagged remote by the site, and re-saves it...
    monkeypatch.setattr(job_search, "run_all_searches", lambda *args: [match])
    job_search.main(store)
    # ...and a re-check says remote too.
    assert job_search.recheck_saved_jobs(store) == 0

    from job_queries import normalize_job
    job = normalize_job(match.job_id, store.get_job(match.job_id))
    assert (job["work_arrangement"], job["is_remote"]) == ("on_site", False)


def test_jobs_cli_marks_work_arrangements(tmp_path, capsys):
    import jobs_cli

    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)
    store.import_documents({"ig-1": {"job_id": "ig-1", "title": "Secret - Full Stack", "is_remote": True}})

    assert jobs_cli.main(["onsite", "ig-1"], store=store) == 0
    assert store.get_job("ig-1")["work_arrangement"] == "on_site"
    assert "Job ig-1 -> On-site: Secret - Full Stack" in capsys.readouterr().out
    assert jobs_cli.main(["hybrid", "ig-1"], store=store) == 0
    assert store.get_job("ig-1")["work_arrangement"] == "hybrid"
    assert jobs_cli.main(["arrangement", "ig-1", "site"], store=store) == 0
    assert store.get_job("ig-1")["work_arrangement"] is None
    assert jobs_cli.main(["onsite", "nope"], store=store) == 1
