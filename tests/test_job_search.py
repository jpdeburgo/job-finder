import pytest

import job_search


def test_build_search_params_targets_remote_active_jobs():
    assert job_search.build_search_params("Python Developer", 2) == {
        "keyword": "Python Developer",
        "page": 2,
        "size": 50,
        "sort": "relevance,desc",
        "filter.includeOnlyRemoteWork": "true",
        "filter.distance": 5,
        "filter.status": "active",
    }


def test_api_and_job_urls_derive_from_the_search_page_url():
    assert job_search.BASE_URL == "https://insightglobal.com/jobs/search/all/all"
    assert job_search.API_URL == "https://insightglobal.com/all/jobs"
    assert (
        job_search.build_job_url("6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba")
        == "https://insightglobal.com/jobs/6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba"
    )


def test_html_to_text_strips_tags_and_entities():
    assert (
        job_search.html_to_text("Required<br><br>&bull; 5+ years of Python &amp; SQL<br>")
        == "Required \u2022 5+ years of Python & SQL"
    )
    assert job_search.html_to_text(None) == ""


def test_java_skill_does_not_match_javascript():
    record = {"jobTitle": "JavaScript Engineer", "description": "Build React apps"}

    assert job_search.score_record(record, ("Java",)) == []


def test_score_record_reads_title_and_description():
    record = {"jobTitle": "Python Engineer", "description": "Build React apps on AWS"}

    assert job_search.score_record(record, ("Python", "React", "AWS", "Java")) == [
        "Python",
        "React",
        "AWS",
    ]


def test_extract_min_years_uses_low_end_of_requirements():
    record = {
        "description": (
            "3-5 years of experience with APIs. At least 7+ years experience overall"
        ),
    }

    assert job_search.extract_min_years(record) == 3


def test_extract_min_years_handles_words_between_years_and_experience():
    # Real Insight Global phrasing: filler words (and an N-M+ range) sit
    # between "years" and "experience" instead of directly adjacent to it.
    record = {
        "description": (
            "8-15+ years software engineering (fullstack, emphasis backend "
            "Python, .NET etc) delivering production-grade solutions. "
            "6-7+ years of hands-on Python backend development experience."
        ),
    }

    assert job_search.extract_min_years(record) == 6


def test_extract_min_years_matches_real_concatenated_requirements_text():
    record = {
        "description": (
            "5+ years of software development experienceStrong backend "
            "development experience with Java"
        ),
    }

    assert job_search.extract_min_years(record) == 5


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
    store.import_legacy_ids(["id-1"])
    monkeypatch.setattr(
        job_search, "run_all_searches", lambda: [_job("id-1"), _job("id-2")]
    )

    job_search.main(store)

    (subject, body, recipient) = gmail[0]
    assert subject == "Insight Global: 1 new job match(es)"
    assert "/jobs/id-2" in body and "/jobs/id-1" not in body
    assert recipient == "me@example.com"
    assert store.load_seen_ids() == {"id-1", "id-2"}
    assert store.get_job("id-2")["status"] == "emailed"
    assert store.get_job("id-2")["gmail_message_id"] == "msg-1"
    assert store.get_job("id-1")["status"] == "seen"  # untouched by re-seeing it


def test_main_saves_unemailed_jobs_when_email_fails_and_retries_next_run(
    store, gmail, monkeypatch
):
    monkeypatch.setattr(job_search, "run_all_searches", lambda: [_job("id-2")])

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
        job_search, "run_all_searches", lambda: [_job("id-2"), _job("id-3")]
    )

    def working_send(service, subject, body, recipient, html=False):
        gmail.append((subject, body, recipient))
        return "msg-ok"

    monkeypatch.setattr(job_search, "send_email", working_send)
    job_search.main(store)

    (subject, body, _) = gmail[-1]
    assert subject == "Insight Global: 2 new job match(es)"
    assert "/jobs/id-2" in body and "/jobs/id-3" in body
    assert store.get_job("id-2")["status"] == "emailed"
    assert store.get_job("id-3")["status"] == "emailed"
    assert store.load_unemailed_ids() == set()


def test_main_with_nothing_new_sends_no_email(store, gmail, monkeypatch):
    store.save_matches([_job("id-2")], new_ids={"id-2"})
    store.mark_emailed(["id-2"], "earlier")
    monkeypatch.setattr(job_search, "run_all_searches", lambda: [_job("id-2")])

    job_search.main(store)

    assert gmail == []
    assert store.get_job("id-2")["gmail_message_id"] == "earlier"


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
    monkeypatch.setattr(job_search, "REQUEST_DELAY_SECONDS", 0)


CORE_TRACK = job_search.TRACKS[0]


def test_search_term_builds_matches_from_api_records(no_delay):
    session = FakeSession(
        [_page([_api_job("a")])],
        {"a": "<p>Python and React on AWS.<br>4+ years of experience.</p>"},
    )

    (match,) = job_search.search_term(session, "Python Developer", CORE_TRACK)

    assert match.job_id == "a"
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

    matches = job_search.search_term(session, "Python Developer", CORE_TRACK)

    assert [m.job_id for m in matches] == ["keep"]
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

    matches = job_search.search_term(session, "Python Developer", CORE_TRACK)

    assert [m.job_id for m in matches] == ["ok"]


def test_search_term_fetches_each_description_once_across_searches(no_delay):
    session = FakeSession([_page([_api_job("a")])], {"a": "Python React"})
    descriptions = {}

    job_search.search_term(session, "Python Developer", CORE_TRACK, descriptions)
    job_search.search_term(session, "React Engineer", CORE_TRACK, descriptions)

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

    matches = job_search.search_term(session, "Python Developer", CORE_TRACK)

    assert [m.job_id for m in matches] == ["a", "b"]
    page_calls = [p["page"] for url, p in session.calls if not url.endswith("/details")]
    assert page_calls == [1, 2]


def test_search_term_stops_on_empty_page(no_delay):
    session = FakeSession([_page([])], {})

    assert job_search.search_term(session, "Python Developer", CORE_TRACK) == []
