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
        matched_skills=["Python", "React"],
        min_years=3,
    )
    body = job_search.build_email_body([job])
    assert '<a href="https://jobs.insightglobal.com' in body
    assert "Python Engineer" in body
    assert "https://jobs.insightglobal.com" in body
