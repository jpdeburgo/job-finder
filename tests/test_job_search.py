import json

import job_search


def test_extract_job_records_skips_invalid_embedded_json():
    html = (
        'before {"JobID":12,"Title":"Python Engineer"} middle '
        '{"JobID":not-json} after'
    )

    assert job_search.extract_job_records(html) == [
        {"JobID": 12, "Title": "Python Engineer"}
    ]


def test_java_skill_does_not_match_javascript():
    record = {"Title": "JavaScript Engineer", "Description": "Build React apps"}

    assert job_search.score_record(record, ("Java",)) == []


def test_extract_min_years_uses_low_end_of_requirements():
    record = {
        "Requirements": "3-5 years of experience with APIs",
        "Description": "At least 7+ years experience overall",
    }

    assert job_search.extract_min_years(record) == 3


def test_format_posted_date_converts_dotnet_timestamp():
    assert job_search.format_posted_date("/Date(1787105014000)/") == "2026-08-19"


def test_format_posted_date_preserves_iso_date():
    assert job_search.format_posted_date("2026-08-15") == "2026-08-15"


def test_local_state_round_trip(tmp_path, monkeypatch):
    state_file = tmp_path / "seen_jobs.json"
    monkeypatch.setattr(job_search, "STATE_FILE", state_file)
    monkeypatch.delenv("IG_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("IG_GITHUB_REPO", raising=False)

    job_search.save_seen_ids({7, 3})

    assert json.loads(state_file.read_text()) == [3, 7]
    assert job_search.load_seen_ids() == {3, 7}


def test_partial_github_configuration_is_rejected(monkeypatch):
    monkeypatch.setenv("IG_GITHUB_TOKEN", "token")
    monkeypatch.delenv("IG_GITHUB_REPO", raising=False)

    try:
        job_search.load_seen_ids()
    except RuntimeError as error:
        assert "must be set together" in str(error)
    else:
        raise AssertionError("Expected incomplete GitHub configuration to fail")


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
    recent_ms = int((now - timedelta(days=10)).timestamp() * 1000)
    stale_ms = int((now - timedelta(days=90)).timestamp() * 1000)

    assert job_search._is_stale_posting(f"/Date({recent_ms})/") is False
    assert job_search._is_stale_posting(f"/Date({stale_ms})/") is True
    assert job_search._is_stale_posting("") is False


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


def test_is_us_country_requires_full_name_or_usa():
    assert job_search._is_us_country("United States") is True
    assert job_search._is_us_country("USA") is True
    assert job_search._is_us_country("US") is False
    assert job_search._is_us_country(None) is False


def test_is_contract_job_matches_contract_types():
    assert job_search._is_contract_job("Contract") is True
    assert job_search._is_contract_job("Contract To Perm") is True
    assert job_search._is_contract_job("contract-to-perm") is True
    assert job_search._is_contract_job("Full Time") is False
    assert job_search._is_contract_job("Permanent") is False


def test_build_email_body_uses_hyperlink():
    job = job_search.JobMatch(
        job_id=1,
        title="Python Engineer",
        city="Austin",
        state="TX",
        is_remote=True,
        job_type="Contract",
        salary_low=100000,
        salary_high=120000,
        industry="Tech",
        url="https://jobs.insightglobal.com/jobs/find_a_job/tx/austin/python-engineer/job-1/",
        track="Core matches (your main stack)",
        posted_date="2026-08-15",
        req_id="AUS-1234",
        matched_skills=["Python", "React"],
        min_years=3,
    )
    body = job_search.build_email_body([job])
    expected_url = "https://jobs.insightglobal.com/jobs/find_a_job/tx/austin/python-engineer/job-1/"
    assert f'href="{expected_url}"' in body
    assert "Python Engineer" in body
    assert "Job ID: 1" in body
    assert "Req: AUS-1234" in body
