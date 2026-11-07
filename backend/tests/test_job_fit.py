"""Tests for the fit score (job_fit.py) and how the search uses it."""

import pytest

import job_fit
import job_search
from job_fit import CandidateProfile, fit_label, implied_years, score_fit
from job_sites import InsightGlobalSite, Posting

PROFILE = CandidateProfile(
    skills=("Python", "JavaScript", "TypeScript", "React", "ReactJS", "Node.js", "NodeJS",
            "SQL", "AWS", "Docker", "Full Stack"),
    core_skills=("Python", "JavaScript", "TypeScript", "React", "ReactJS", "Node.js", "NodeJS"),
    years_experience=5,
    target_roles=("Software Engineer", "Full Stack", "Backend", "Frontend"),
    generic_roles=("Developer",),
    unfamiliar_tech=("Kotlin", "Scala", "Swift", "Salesforce", "PHP"),
    skill_aliases=(("React", "ReactJS"), ("Node.js", "NodeJS")),
)


def _posting(title="Software Engineer", description="", is_remote=True, company="Example"):
    return Posting(
        job_id="p1", title=title, url="https://example.com/p1", company=company,
        is_remote=is_remote, description=description,
    )


def _fit(title="Software Engineer", description="", min_years=None, **kwargs):
    return score_fit(_posting(title, description, **kwargs), PROFILE, min_years)


# --- The parts -------------------------------------------------------------------------


def test_a_strong_match_scores_full_marks():
    fit = _fit("Full Stack React Engineer", "Python, TypeScript, Node.js, AWS and SQL", 3)

    assert fit.score == 100
    assert fit.breakdown == {"skills": 55, "role": 45, "experience": 0, "remote": 0, "stack": 0}
    assert fit.label == "Strong"


def test_breakdown_always_adds_up_to_the_score():
    cases = [
        ("Senior Backend Developer", "Python SQL Kotlin Scala", 7, None),
        ("Network Engineer", "Python AWS Docker", 3, True),
        ("Principal Software Engineer", "React", None, False),
        ("Data Analyst", "", None, True),
    ]
    for title, description, years, remote in cases:
        fit = _fit(title, description, years, is_remote=remote)
        assert sum(fit.breakdown.values()) == fit.score, (title, fit)
        assert 0 <= fit.score <= 100


def test_core_languages_count_double_supporting_skills():
    core = _fit("Analyst", "Python and TypeScript")  # 2 core = weight 2
    tooling = _fit("Analyst", "SQL and AWS")  # 2 supporting = weight 1

    assert core.breakdown["skills"] == round(55 * 2 / 4)
    assert tooling.breakdown["skills"] == round(55 * 1 / 4)


def test_spellings_of_one_skill_count_once():
    both = _fit("Analyst", "React and ReactJS, Node.js and NodeJS")
    once = _fit("Analyst", "React and Node.js")

    assert both.breakdown["skills"] == once.breakdown["skills"]
    assert "Skills: React, Node.js (2 core)" in both.reasons


def test_target_titles_beat_titles_that_only_mention_your_skills():
    # The case the old skill count got wrong: a Network Engineer posting that
    # mentions plenty of your tooling vs. a real software role.
    network = _fit("Network Engineer", "Python, AWS, Docker, SQL")
    software = _fit("Software Engineer", "Python, AWS, Docker, SQL")

    assert network.breakdown["role"] == 0
    assert software.breakdown["role"] == 30
    assert software.score > network.score
    assert fit_label(network.score) == "Weak"


def test_role_points():
    assert _fit("Backend Engineer").breakdown["role"] == 30
    assert _fit("Integration Developer").breakdown["role"] == 15  # generic
    assert _fit("React Developer").breakdown["role"] == 30  # generic + core skill in title
    assert _fit("Full Stack Engineer (React/Node.js)").breakdown["role"] == 45  # capped
    assert _fit("Data Scientist").breakdown["role"] == 0


def test_experience_gap_takes_a_growing_share():
    def score(years):
        return _fit("Software Engineer", "Python React TypeScript Node.js", years).score

    base = score(5)
    assert base == 85
    # Each part is rounded on its own so they add up exactly; that can put the
    # total a point off the unrounded product.
    assert abs(score(6) - 85 * 0.9) <= 1
    assert abs(score(7) - 85 * 0.75) <= 1
    assert abs(score(8) - 85 * 0.6) <= 1
    assert abs(score(12) - 85 * 0.45) <= 1
    assert base > score(6) > score(7) > score(8) > score(12)
    # Fewer years than you have is no penalty.
    assert score(1) == base


def test_title_level_counts_when_it_asks_for_more_than_the_description():
    # "3+ years of X" understates a Principal role.
    fit = _fit("Principal Software Engineer", "Python React TypeScript Node.js", 3)

    assert fit.breakdown["experience"] < 0
    assert "Asks for 3+ yrs; title suggests ~9 yrs; you have 5 (4 short)" in fit.reasons
    # With nothing stated, the title alone decides; with neither, no change.
    assert _fit("Senior Software Engineer").breakdown["experience"] == 0  # ~5 = you
    assert _fit("Staff Software Engineer").breakdown["experience"] < 0
    assert "Experience: not stated" in _fit("Software Engineer").reasons


@pytest.mark.parametrize(
    "title, years",
    [
        ("Sr. Software Engineer", 5),
        ("Senior Backend Developer", 5),
        ("Lead Engineer", 7),
        ("Staff Software Engineer", 7),
        ("Principal Engineer", 9),
        ("Junior Java Developer", 0),
        ("Entry-Level Developer", 0),
        ("Software Engineer", None),
        ("Sriracha Engineer", None),  # "Sr" only as a word
    ],
)
def test_implied_years(title, years):
    assert implied_years(title) == years


def test_remote_status_adjustment():
    remote = _fit(description="Python React", is_remote=True)
    unmarked = _fit(description="Python React", is_remote=None)
    onsite = _fit(description="Python React", is_remote=False)

    assert remote.breakdown["remote"] == 0
    assert remote.score > unmarked.score > onsite.score
    assert "Remote not stated" in unmarked.reasons


def test_unfamiliar_tech_in_the_description_costs_a_little():
    clean = _fit(description="Python React TypeScript")
    one = _fit(description="Python React TypeScript and Kotlin")
    many = _fit(description="Python React TypeScript Kotlin Scala PHP Swift")

    assert clean.score > one.score > many.score
    assert many.breakdown["stack"] == round(-(clean.score * 0.15))  # capped at 15%
    assert "Also asks for tech not on your resume: Kotlin" in one.reasons


def test_unfamiliar_tech_ignores_ordinary_words_and_the_company_name():
    # "swift" in lower case is English, not the language; every Salesforce
    # posting names Salesforce.
    assert _fit(description="Python, swift delivery").breakdown["stack"] == 0
    assert _fit(description="Python at Salesforce", company="Salesforce").breakdown["stack"] == 0


def test_fit_labels():
    assert [fit_label(s) for s in (100, 75, 74, 60, 59, 40, 39, 0)] == [
        "Strong", "Strong", "Good", "Good", "Fair", "Fair", "Weak", "Weak",
    ]
    assert fit_label(None) == ""


# --- In the search -----------------------------------------------------------------------


IG = InsightGlobalSite(job_search.INSIGHT_GLOBAL_URL)
CORE = job_search.TRACKS[0]


def test_candidate_profile_comes_from_the_settings(monkeypatch):
    monkeypatch.setattr(job_search, "YEARS_OF_EXPERIENCE", 9)
    profile = job_search.candidate_profile()

    assert profile.years_experience == 9
    assert profile.skills == tuple(job_search.RESUME_SKILLS)
    assert profile.core_skills == tuple(job_search.CORE_LANGUAGE_SKILLS)
    assert ("React", "ReactJS") in profile.skill_aliases
    assert "Software Engineer" in profile.target_roles


def test_evaluate_posting_attaches_the_fit_score():
    posting = Posting(
        job_id="insight-global-1", title="Full Stack Developer", url="https://x", company="Insight Global",
        is_remote=True, job_type="Contract",
        description="Python, React, TypeScript and Node.js on AWS. 3+ years of experience.",
    )

    match = job_search.evaluate_posting(posting, IG, CORE)

    assert match.fit_score == score_fit(posting, job_search.candidate_profile(), 3).score
    assert match.fit_score >= 75 and match.fit_label == "Strong"
    assert sum(match.fit_breakdown.values()) == match.fit_score
    assert match.fit_reasons[0].startswith("Skills: Python")
    # The skill count is still there.
    assert match.score == len(match.matched_skills)


def _match(job_id, fit, track=CORE.name, posted="2026-10-01"):
    return job_search.JobMatch(
        job_id=job_id, title="T", city="", state="", is_remote=True, job_type="Contract",
        salary_low=0, salary_high=0, url="https://x", track=track, posted_date=posted,
        matched_skills=["Python", "React"], fit_score=fit,
    )


def test_results_are_ordered_by_track_then_best_fit_then_newest(monkeypatch):
    java = job_search.TRACKS[1].name
    matches = [
        _match("weak-new", 30, posted="2026-10-09"),
        _match("java-strong", 95, track=java),
        _match("strong-old", 90, posted="2026-10-01"),
        _match("strong-new", 90, posted="2026-10-05"),
        _match("unscored", None),
    ]

    class Result:
        def __init__(self, found):
            self.matches, self.searches, self.failed_terms = found, 1, []

    monkeypatch.setattr(job_search, "_search_site_in_own_session", lambda site: Result(
        matches if site.name == "Insight Global" else []
    ))

    ordered = [job.job_id for job in job_search.run_all_searches()]

    assert ordered == ["strong-new", "strong-old", "weak-new", "unscored", "java-strong"]


def test_email_shows_the_fit_score():
    body = job_search.build_email_body([_match("1", 82)])

    assert "Fit 82/100 (Strong)" in body


# --- Locations outside JOB_COUNTRY ---------------------------------------------------------


def _located(city, state=""):
    return Posting(job_id="x", title="Software Engineer", url="https://x", company="Gitlab",
                   city=city, state=state, is_remote=True)


@pytest.mark.parametrize(
    "city, state",
    [
        ("Remote - Canada", ""),
        ("Remote", "EMEA"),
        ("Bengaluru", "India"),
        ("London", "United Kingdom"),
        ("Remote - UK", ""),
        ("Toronto", "ON"),
        ("Remote, LATAM", ""),
        ("Berlin", "Germany"),
    ],
)
def test_locations_outside_the_us_are_dropped(city, state):
    assert job_search._is_outside_job_country(_located(city, state)) is True
    assert not job_search._passes_listing_filters(
        _located(city, state), IG, CORE, details_loaded=True
    )


@pytest.mark.parametrize(
    "city, state",
    [
        ("Remote", ""),
        ("Austin", "TX"),
        ("Remote - US", ""),
        ("Remote, Americas", ""),
        ("Remote - US; Remote - Canada", ""),  # the US is one of the options
        ("Santa Fe", "New Mexico"),
        ("Peru", "IN"),
        ("Toronto", "OH"),
        ("Indianapolis", "Indiana"),  # not "India"
        ("United States", ""),
        ("US, CA, Santa Clara", ""),  # Workday style
        ("2 Locations", ""),
        ("", ""),
    ],
)
def test_us_and_unknown_locations_are_kept(city, state):
    assert job_search._is_outside_job_country(_located(city, state)) is False


def test_location_check_is_off_when_job_country_is_not_the_us(monkeypatch):
    monkeypatch.setattr(job_search, "JOB_COUNTRY", None)

    assert job_search._is_outside_job_country(_located("Remote - Canada")) is False
