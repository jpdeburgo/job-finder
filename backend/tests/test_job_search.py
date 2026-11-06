import pytest

import job_search
from job_sites import InsightGlobalSite, Posting

IG = InsightGlobalSite(job_search.INSIGHT_GLOBAL_URL)


def _posting(title="Python Engineer", description="", **overrides):
    fields = dict(
        job_id="p1",
        title=title,
        url="https://example.com/p1",
        company="Example",
        description=description,
    )
    fields.update(overrides)
    return Posting(**fields)


def test_build_search_params_targets_remote_active_jobs():
    assert IG.build_search_params("Python Developer", 2) == {
        "keyword": "Python Developer",
        "page": 2,
        "size": 50,
        "sort": "postedDate,desc",
        "filter.jobType": "Contract",
        "filter.includeOnlyRemoteWork": "true",
        "filter.distance": 5,
        "filter.status": "active",
    }


def test_api_and_job_urls_derive_from_the_search_page_url():
    assert job_search.INSIGHT_GLOBAL_URL == "https://insightglobal.com/jobs/search/all/all"
    assert IG.api_url == "https://insightglobal.com/all/jobs"
    assert (
        IG.build_job_url("6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba")
        == "https://insightglobal.com/jobs/6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba"
    )


def test_job_search_urls_lists_insight_global_and_accenture():
    assert job_search.JOB_SEARCH_URLS == [
        "https://insightglobal.com/jobs/search/all/all",
        "https://www.accenture.com/us-en/careers/jobsearch",
    ]
    assert job_search.ACCENTURE_SEARCH_URL in job_search.JOB_SEARCH_URLS


def test_java_skill_does_not_match_javascript():
    posting = _posting("JavaScript Engineer", "Build React apps")

    assert job_search.score_posting(posting, ("Java",)) == []


def test_score_posting_reads_title_and_description():
    posting = _posting("Python Engineer", "Build React apps on AWS")

    assert job_search.score_posting(posting, ("Python", "React", "AWS", "Java")) == [
        "Python",
        "React",
        "AWS",
    ]


def test_extract_min_years_uses_low_end_of_requirements():
    posting = _posting(
        description="3-5 years of experience with APIs. At least 7+ years experience overall"
    )

    assert job_search.extract_min_years(posting) == 3


def test_extract_min_years_handles_words_between_years_and_experience():
    # Real Insight Global phrasing: filler words (and an N-M+ range) sit
    # between "years" and "experience" instead of directly adjacent to it.
    posting = _posting(
        description=(
            "8-15+ years software engineering (fullstack, emphasis backend "
            "Python, .NET etc) delivering production-grade solutions. "
            "6-7+ years of hands-on Python backend development experience."
        ),
    )

    assert job_search.extract_min_years(posting) == 6


def test_extract_min_years_matches_real_concatenated_requirements_text():
    posting = _posting(
        description=(
            "5+ years of software development experienceStrong backend "
            "development experience with Java"
        ),
    )

    assert job_search.extract_min_years(posting) == 5


def test_format_posted_date_converts_api_timestamp():
    assert job_search.format_posted_date("2026-10-29T15:42:48.1Z") == "2026-10-29"


def test_format_posted_date_preserves_iso_date():
    assert job_search.format_posted_date("2026-08-15") == "2026-08-15"


def test_format_posted_date_passes_through_unparseable_values():
    assert job_search.format_posted_date("sometime") == "sometime"
    assert job_search.format_posted_date(None) == ""


def _job(job_id, **overrides):
    fields = dict(
        job_id=job_id,
        title="Python Engineer",
        city="Austin",
        state="TX",
        is_remote=True,
        job_type="Contract",
        salary_low=100000,
        salary_high=120000,
        url=f"https://insightglobal.com/jobs/{job_id}",
        track="Core matches (your main stack)",
        posted_date="2026-08-15",
        matched_skills=["Python", "React"],
        min_years=3,
    )
    fields.update(overrides)
    return job_search.JobMatch(**fields)


@pytest.fixture
def store(tmp_path):
    from job_store import FirestoreJobStore

    return FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)


@pytest.fixture
def gmail(monkeypatch):
    """Stub Gmail; returns the list of sent (subject, body, recipient) tuples."""
    sent = []

    def fake_send(service, subject, body, recipient, html=False):
        sent.append((subject, body, recipient))
        return f"msg-{len(sent)}"

    monkeypatch.setattr(job_search, "get_gmail_service", lambda: "service")
    monkeypatch.setattr(job_search, "send_email", fake_send)
    monkeypatch.setenv("IG_EMAIL_TO", "me@example.com")
    return sent


def test_main_emails_only_unseen_jobs_and_persists_state(store, gmail, monkeypatch):
    store.save_matches([_job("id-1")], new_ids={"id-1"})  # found and emailed by an earlier run
    store.mark_emailed(["id-1"], "earlier")
    store.set_status("id-1", "applied")
    monkeypatch.setattr(
        job_search, "run_all_searches", lambda *_: [_job("id-1"), _job("id-2")]
    )

    job_search.main(store)

    (subject, body, recipient) = gmail[0]
    assert subject == "Job search: 1 new job match(es)"
    assert "/jobs/id-2" in body and "/jobs/id-1" not in body
    assert recipient == "me@example.com"
    assert store.load_seen_ids() == {"id-1", "id-2"}
    assert store.get_job("id-2")["status"] == "emailed"
    assert store.get_job("id-2")["gmail_message_id"] == "msg-1"
    assert store.get_job("id-1")["status"] == "applied"  # untouched by re-seeing it


def test_main_saves_unemailed_jobs_when_email_fails_and_retries_next_run(
    store, gmail, monkeypatch
):
    monkeypatch.setattr(job_search, "run_all_searches", lambda *_: [_job("id-2")])

    def failing_send(*args, **kwargs):
        raise RuntimeError("gmail down")

    monkeypatch.setattr(job_search, "send_email", failing_send)
    with pytest.raises(RuntimeError, match="gmail down"):
        job_search.main(store)

    # Saved anyway, flagged so it isn't lost.
    assert store.get_job("id-2")["status"] == "unemailed"
    assert store.load_unemailed_ids() == {"id-2"}

    # Next run: Gmail works again, job 2 still matches alongside a new job 3.
    monkeypatch.setattr(
        job_search, "run_all_searches", lambda *_: [_job("id-2"), _job("id-3")]
    )

    def working_send(service, subject, body, recipient, html=False):
        gmail.append((subject, body, recipient))
        return "msg-ok"

    monkeypatch.setattr(job_search, "send_email", working_send)
    job_search.main(store)

    (subject, body, _) = gmail[-1]
    assert subject == "Job search: 2 new job match(es)"
    assert "/jobs/id-2" in body and "/jobs/id-3" in body
    assert store.get_job("id-2")["status"] == "emailed"
    assert store.get_job("id-3")["status"] == "emailed"
    assert store.load_unemailed_ids() == set()


def test_main_with_nothing_new_sends_no_email(store, gmail, monkeypatch):
    store.save_matches([_job("id-2")], new_ids={"id-2"})
    store.mark_emailed(["id-2"], "earlier")
    monkeypatch.setattr(job_search, "run_all_searches", lambda *_: [_job("id-2")])

    job_search.main(store)

    assert gmail == []
    assert store.get_job("id-2")["gmail_message_id"] == "earlier"


def _gmail_not_set_up():
    raise job_search.GmailNotConfiguredError(
        "Gmail OAuth client secret not found at credentials.json. See README.md for Gmail API setup."
    )


def test_main_without_gmail_set_up_prints_an_error_and_keeps_jobs(
    store, gmail, monkeypatch, capsys
):
    monkeypatch.delenv("IG_REQUIRE_EMAIL", raising=False)
    monkeypatch.setattr(job_search, "get_gmail_service", _gmail_not_set_up)
    monkeypatch.setattr(job_search, "run_all_searches", lambda *_: [_job("id-1"), _job("id-2")])

    job_search.main(store)  # no exception

    out = capsys.readouterr().out
    assert "Email is not set up, so no email was sent: Gmail OAuth client secret not found" in out
    assert "2 job(s) stay 'unemailed'" in out
    assert "Traceback" not in out
    assert store.load_unemailed_ids() == {"id-1", "id-2"}
    (run,) = [doc.to_dict() for doc in store._runs.stream()]
    assert run["email_sent"] is False
    assert run["error"].startswith("Email not set up: Gmail OAuth client secret not found")

    # Once Gmail is set up, the next run emails everything that piled up.
    monkeypatch.setattr(job_search, "get_gmail_service", lambda: "service")
    job_search.main(store)

    (subject, body, _) = gmail[-1]
    assert subject == "Job search: 2 new job match(es)"
    assert store.load_unemailed_ids() == set()


def test_main_without_a_recipient_prints_an_error(store, gmail, monkeypatch, capsys):
    monkeypatch.delenv("IG_REQUIRE_EMAIL", raising=False)
    monkeypatch.delenv("IG_EMAIL_TO")
    monkeypatch.setattr(
        job_search, "get_gmail_service", lambda: pytest.fail("shouldn't sign in to Gmail")
    )
    monkeypatch.setattr(job_search, "run_all_searches", lambda *_: [_job("id-1")])

    job_search.main(store)

    assert "no email was sent: IG_EMAIL_TO is not set" in capsys.readouterr().out
    assert store.load_unemailed_ids() == {"id-1"}
    assert gmail == []


def test_main_fails_when_email_is_required_but_not_set_up(store, gmail, monkeypatch):
    monkeypatch.setenv("IG_REQUIRE_EMAIL", "true")  # as on Render
    monkeypatch.setattr(job_search, "get_gmail_service", _gmail_not_set_up)
    monkeypatch.setattr(job_search, "run_all_searches", lambda *_: [_job("id-1")])

    with pytest.raises(job_search.GmailNotConfiguredError):
        job_search.main(store)
    assert store.load_unemailed_ids() == {"id-1"}


def test_main_still_raises_when_gmail_is_set_up_but_fails(store, gmail, monkeypatch, capsys):
    monkeypatch.delenv("IG_REQUIRE_EMAIL", raising=False)

    def expired_token():
        raise RuntimeError("token has been expired or revoked")

    monkeypatch.setattr(job_search, "get_gmail_service", expired_token)
    monkeypatch.setattr(job_search, "run_all_searches", lambda *_: [_job("id-1")])

    with pytest.raises(RuntimeError, match="expired or revoked"):
        job_search.main(store)
    assert "Email failed; 1 job(s) left as 'unemailed'" in capsys.readouterr().out


def test_growth_tracks_mirror_java_for_ios_and_dotnet():
    growth_tracks = {track.name: track for track in job_search.TRACKS if track.growth_track}

    assert "iOS growth track (entry-level / lower bar)" in growth_tracks
    assert ".NET growth track (entry-level / lower bar)" in growth_tracks
    for track in growth_tracks.values():
        assert track.minimum_matches == 1


def test_is_international_title_matches_india():
    assert job_search._is_international_title(
        "Front-End Developer (India) - React, Typescript, Next.JS, AWS"
    ) is True
    assert job_search._is_international_title("Indianapolis Backend Developer") is False


def test_is_stale_posting_uses_max_posted_age_days():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.1Z")
    stale = (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.1Z")

    assert job_search._is_stale_posting(recent) is False
    assert job_search._is_stale_posting(stale) is True
    assert job_search._is_stale_posting("") is False


def test_is_international_title_matches_nearshore():
    assert job_search._is_international_title("Nearshore Java/React Developer") is True


def test_is_bogus_alaska_location_flags_non_alaska_cities():
    assert job_search._is_bogus_alaska_location("Alaska", "Madhapur") is True
    assert job_search._is_bogus_alaska_location("Alaska", "Hyderabad") is True
    assert job_search._is_bogus_alaska_location("AK", "Hyderabad") is True
    assert job_search._is_bogus_alaska_location("Alaska", "Anchorage") is False
    assert job_search._is_bogus_alaska_location("AK", "Anchorage") is False
    assert job_search._is_bogus_alaska_location("Arizona", "Phoenix") is False


def test_is_placeholder_listing_flags_copy_prefix():
    assert job_search._is_placeholder_listing(
        "COPY - Enterprise Applications Accela Developer"
    ) is True
    assert job_search._is_placeholder_listing("Java Developer") is False


def test_title_names_growth_stack():
    assert job_search._title_names_growth_stack(
        "Senior Full Stack Developer (.NET/React/SQL)"
    ) is True
    assert job_search._title_names_growth_stack("Java Developer") is True
    assert job_search._title_names_growth_stack("Full Stack Developer") is False


def test_is_senior_title_matches_overqualified_prefixes():
    assert job_search._is_senior_title("Senior Application Security Engineer (Java)") is True
    assert job_search._is_senior_title("Sr. Backend Engineer") is True
    assert job_search._is_senior_title("Remote Senior Java Developer") is True
    assert job_search._is_senior_title("Principal Software Engineers - Agentic AI") is True
    assert job_search._is_senior_title("Staff Engineer (.NET)") is True
    assert job_search._is_senior_title("Lead iOS Developer") is True
    assert job_search._is_senior_title("Java Developer") is False
    assert job_search._is_senior_title("Junior Java Developer") is False


def test_has_unfamiliar_title_tech_flags_non_resume_stack():
    assert job_search._has_unfamiliar_title_tech("Drupal Senior Frontend Engineer") is True
    assert job_search._has_unfamiliar_title_tech("Android Developer") is True
    assert job_search._has_unfamiliar_title_tech("Senior Software Engineer (React)") is False
    assert job_search._has_unfamiliar_title_tech(".NET Developer") is False


def test_has_unfamiliar_title_tech_allows_skills_on_resume():
    assert job_search._has_unfamiliar_title_tech("Vue.js Developer") is False
    assert job_search._has_unfamiliar_title_tech("Angular Developer") is False
    assert job_search._has_unfamiliar_title_tech("Ruby on Rails Developer") is False


def test_is_international_title_matches_intl_and_latam():
    assert job_search._is_international_title("Java Developer - INTL India") is True
    assert job_search._is_international_title("Senior Java Developer- LATAM") is True
    assert job_search._is_international_title("Java Developer") is False


def test_is_contract_job_matches_contract_types():
    assert job_search._is_contract_job("Contract") is True
    assert job_search._is_contract_job("Contract To Perm") is True
    assert job_search._is_contract_job("Contract, perm possible") is True
    assert job_search._is_contract_job("contract-to-perm") is True
    assert job_search._is_contract_job("Full Time") is False
    assert job_search._is_contract_job("Permanent") is False
    assert job_search._is_contract_job("Perm") is False


def test_build_email_body_uses_hyperlink():
    job = _job(
        "6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba",
        url="https://insightglobal.com/jobs/6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba",
    )
    body = job_search.build_email_body([job])
    expected_url = "https://insightglobal.com/jobs/6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba"
    assert f'href="{expected_url}"' in body
    assert "Python Engineer" in body
    assert "Job ID: 6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba" in body


def test_build_email_body_flags_jobs_whose_remote_status_is_unknown():
    body = job_search.build_email_body(
        [_job("a", is_remote=True), _job("b", is_remote=None), _job("c", is_remote=False)]
    )
    lines = {job_id: line for job_id in "abc" for line in body.splitlines() if f"Job ID: {job_id}<" in line}

    assert "&nbsp;|&nbsp; Remote &nbsp;|&nbsp;" in lines["a"]
    assert "Remote not stated: check the posting" in lines["b"]
    assert "Not remote" in lines["c"]


# --- search_term against the JSON API -------------------------------------------------


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    """Serves search pages and job details like insightglobal.com/all/jobs."""

    def __init__(self, pages, descriptions):
        self.pages = pages
        self.descriptions = descriptions
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if url.endswith("/details"):
            job_id = url.rsplit("/", 2)[-2]
            return FakeResponse({"description": self.descriptions[job_id]})
        return FakeResponse(self.pages[params["page"] - 1])

    def detail_calls(self):
        return [url for url, _ in self.calls if url.endswith("/details")]


def _api_job(job_id, **overrides):
    record = {
        "requisitionId": job_id,
        "jobTitle": "Python Developer ",
        "workAddress": {"administrativeArea": "TX", "locality": "Austin"},
        "postedDate": "2099-01-01T00:00:00.1Z",
        "workRemote": True,
        "jobType": "Contract",
        "payRate": {"min": 70.0, "max": 90.0, "currency": "USD", "type": "Hourly"},
        "jobStatus": "active",
    }
    record.update(overrides)
    return record


def _page(jobs, number=1, total_pages=1):
    return {
        "jobs": jobs,
        "pageMetadata": {"size": 50, "number": number, "totalPages": total_pages},
    }


@pytest.fixture
def no_delay(monkeypatch):
    monkeypatch.setattr(job_search, "MIN_SECONDS_BETWEEN_REQUESTS", 0)


CORE_TRACK = job_search.TRACKS[0]


def test_search_term_builds_matches_from_api_records(no_delay):
    session = FakeSession(
        [_page([_api_job("a")])],
        {"a": "<p>Python and React on AWS.<br>4+ years of experience.</p>"},
    )

    (match,) = job_search.search_term(session, IG, "Python Developer", CORE_TRACK)

    assert match.job_id == "insight-global-a"
    assert match.title == "Python Developer"
    assert (match.city, match.state) == ("Austin", "TX")
    assert match.url == "https://insightglobal.com/jobs/a"
    assert match.matched_skills == ["Python", "React", "AWS"]
    assert match.min_years == 4
    assert (match.salary_low, match.salary_high) == (70.0, 90.0)
    assert match.job_type == "Contract"
    assert match.posted_date == "2099-01-01"
    assert match.track == CORE_TRACK.name
    assert session.calls[0][0] == "https://insightglobal.com/all/jobs"


def test_search_term_skips_jobs_failing_list_level_filters_without_fetching_details(
    no_delay,
):
    jobs = [
        _api_job("onsite", workRemote=False),
        _api_job("perm", jobType="Perm"),
        _api_job("intl", jobTitle="Python Developer - INTL India"),
        _api_job("latam", jobTitle="Python Developer - LATAM"),
        _api_job("android", jobTitle="Android Developer"),
        _api_job("stale", postedDate="2020-01-01T00:00:00.1Z"),
        _api_job("copy", jobTitle="COPY - Python Developer"),
        _api_job("keep"),
    ]
    session = FakeSession([_page(jobs)], {"keep": "Python and React"})

    matches = job_search.search_term(session, IG, "Python Developer", CORE_TRACK)

    assert [m.job_id for m in matches] == ["insight-global-keep"]
    assert session.detail_calls() == [
        "https://insightglobal.com/all/jobs/keep/details"
    ]


def test_search_term_applies_description_based_filters(no_delay):
    jobs = [_api_job("few-skills"), _api_job("too-senior"), _api_job("ok")]
    session = FakeSession(
        [_page(jobs)],
        {
            "few-skills": "Only Python here",
            "too-senior": "Python React 10+ years of experience",
            "ok": "Python React 3+ years of experience",
        },
    )

    matches = job_search.search_term(session, IG, "Python Developer", CORE_TRACK)

    assert [m.job_id for m in matches] == ["insight-global-ok"]


def test_search_term_fetches_each_description_once_across_searches(no_delay):
    session = FakeSession([_page([_api_job("a")])], {"a": "Python React"})
    descriptions = {}

    job_search.search_term(session, IG, "Python Developer", CORE_TRACK, descriptions)
    job_search.search_term(session, IG, "React Engineer", CORE_TRACK, descriptions)

    assert len(session.detail_calls()) == 1


def test_search_term_walks_pages_until_the_last_one(no_delay, monkeypatch):
    monkeypatch.setattr(job_search, "MAX_PAGES_PER_SEARCH", 5)
    session = FakeSession(
        [
            _page([_api_job("a")], number=1, total_pages=2),
            _page([_api_job("b")], number=2, total_pages=2),
        ],
        {"a": "Python React", "b": "Python React"},
    )

    matches = job_search.search_term(session, IG, "Python Developer", CORE_TRACK)

    assert [m.job_id for m in matches] == ["insight-global-a", "insight-global-b"]
    page_calls = [p["page"] for url, p in session.calls if not url.endswith("/details")]
    assert page_calls == [1, 2]


def test_search_term_stops_on_empty_page(no_delay):
    session = FakeSession([_page([])], {})

    assert job_search.search_term(session, IG, "Python Developer", CORE_TRACK) == []


def test_search_term_stops_paging_once_a_page_reaches_stale_postings(
    no_delay, monkeypatch
):
    monkeypatch.setattr(job_search, "MAX_PAGES_PER_SEARCH", 5)
    fresh = _api_job("fresh")
    old = _api_job("old", postedDate="2020-01-01T00:00:00.1Z")
    session = FakeSession(
        [
            _page([fresh], number=1, total_pages=9),
            _page([fresh, old], number=2, total_pages=9),
            _page([_api_job("never-fetched")], number=3, total_pages=9),
        ],
        {"fresh": "Python React"},
    )

    matches = job_search.search_term(session, IG, "Python Developer", CORE_TRACK)

    assert [m.job_id for m in matches] == ["insight-global-fresh"]
    page_calls = [p["page"] for url, p in session.calls if not url.endswith("/details")]
    assert page_calls == [1, 2]


def test_is_stale_page_ignores_undated_records():
    stale = _posting(posted_date="2020-01-01T00:00:00.1Z")
    fresh = _posting(posted_date="2099-01-01T00:00:00.1Z")
    undated = _posting()

    assert job_search._is_stale_page([fresh, stale, undated]) is True
    assert job_search._is_stale_page([stale, fresh]) is False
    assert job_search._is_stale_page([undated]) is False
    assert job_search._is_stale_page([]) is False


def test_build_session_retries_connection_errors_and_server_errors():
    session = job_search.build_session()
    retry = session.get_adapter("https://insightglobal.com").max_retries

    assert retry.total == job_search.RETRY_ATTEMPTS
    assert 503 in retry.status_forcelist
    assert session.headers["User-Agent"] == job_search.HEADERS["User-Agent"]


def _fake_list_postings(fail_terms=(), fail_all=False):
    def fake(session, site, term):
        if fail_all or term in fail_terms:
            raise job_search.requests.ConnectionError("dropped")
        if site.name == "Insight Global" and term == "Python Developer":
            return [
                job_search.Posting(
                    job_id="insight-global-kept",
                    title="Python Developer",
                    url="https://insightglobal.com/jobs/kept",
                    company="Insight Global",
                    is_remote=True,
                    job_type="Contract",
                    description="Python and React",
                )
            ]
        return []

    return fake


def test_run_all_searches_skips_a_failing_term_but_keeps_the_rest(monkeypatch, capsys):
    monkeypatch.setattr(job_search, "list_postings", _fake_list_postings({"Software Engineer"}))

    jobs = job_search.run_all_searches()

    assert [j.job_id for j in jobs] == ["insight-global-kept"]
    out = capsys.readouterr().out
    assert "Insight Global: search 'Software Engineer' FAILED" in out
    assert "Accenture: search 'Software Engineer' FAILED" in out
    assert "2 search(es) failed" in out


def test_run_all_searches_raises_when_every_term_fails(monkeypatch):
    monkeypatch.setattr(job_search, "list_postings", _fake_list_postings(fail_all=True))

    with pytest.raises(RuntimeError, match="Every search failed"):
        job_search.run_all_searches()


def test_run_all_searches_only_searches_selected_sites(monkeypatch, capsys):
    searched = []

    def fake(session, site, term):
        searched.append(site.name)
        return []

    monkeypatch.setattr(job_search, "list_postings", fake)

    job_search.run_all_searches(["accenture"])

    assert set(searched) == {"Accenture"}
    assert len(searched) == sum(len(track.terms) for track in job_search.TRACKS)


def test_core_track_requires_a_core_language_not_just_cloud_skills(no_delay):
    jobs = [
        _api_job("cloud-only", jobTitle="Network Security Engineer"),
        _api_job("has-python", jobTitle="Platform Engineer"),
    ]
    session = FakeSession(
        [_page(jobs)],
        {
            "cloud-only": "Network security on Azure and AWS with SQL",
            "has-python": "Python scripting on AWS",
        },
    )

    matches = job_search.search_term(session, IG, "Python Developer", CORE_TRACK)

    assert [m.job_id for m in matches] == ["insight-global-has-python"]


def test_growth_tracks_do_not_require_a_core_language():
    for track in job_search.TRACKS:
        if track.growth_track:
            assert track.required_skills == ()


def test_core_language_skills_are_all_resume_skills():
    assert set(job_search.CORE_LANGUAGE_SKILLS) <= set(job_search.RESUME_SKILLS)
