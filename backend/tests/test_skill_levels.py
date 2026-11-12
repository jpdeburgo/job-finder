"""Inferring how well you know each skill on your resume (skill_levels.py)."""

from datetime import datetime, timezone

import pytest

from resume_parser import parse_resume
from skill_catalog import lookup
from skill_levels import Evidence, StatedLevel, infer_level, stated_level, stated_skill_years
from tests.resume_files import SAMPLE_RESUME

NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)


def levels(text, your_skills=()):
    return {s.name: (s.level, s.level_reason) for s in parse_resume(text, your_skills, now=NOW).skills}


def evidence(**overrides):
    base = dict(years=None, mentions=1, jobs=0, in_title=False, months_since_used=None, has_work_history=True)
    return Evidence(**{**base, **overrides})


# --- What the resume says ------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "skill", "level", "word"),
    [
        ("Expert: Python, Go; Familiar: Rust", "Python", 5, "Expert"),
        ("Expert: Python, Go; Familiar: Rust", "Rust", 2, "Familiar"),
        ("Advanced - React, TypeScript | Intermediate: Java", "TypeScript", 4, "Advanced"),
        ("Advanced - React, TypeScript | Intermediate: Java", "Java", 3, "Intermediate"),
        ("Languages: Python (expert), Go (familiar), Java - beginner", "Go", 2, "familiar"),
        ("Languages: Python (expert), Go (familiar), Java - beginner", "Java", 1, "beginner"),
        ("Strong background in Python and Django, familiar with Docker.", "Django", 4, "Strong"),
        ("Strong background in Python and Django, familiar with Docker.", "Docker", 2, "familiar"),
        ("Proficient in Java and working knowledge of Kubernetes", "Kubernetes", 2, "working knowledge"),
        ("Deep knowledge of Kubernetes", "Kubernetes", 4, "Deep knowledge"),
        ("Basic: SQL. Expert: AWS", "SQL", 2, "Basic"),
    ],
)
def test_the_resume_rating_a_skill(text, skill, level, word):
    assert stated_level(text, lookup(skill)) == StatedLevel(level, word)


@pytest.mark.parametrize(
    ("text", "skill"),
    [
        ("Experienced software engineer building apps in Python and React.", "Python"),
        ("Built a strong CI pipeline with Jenkins", "Jenkins"),
        ("Deep learning models in PyTorch", "PyTorch"),  # a skill, not a rating
        ("Scrum Master; led Agile ceremonies", "Scrum"),
        ("Expert: Python. Also wrote some Go tooling", "Go"),  # the sentence ended
    ],
)
def test_words_that_arent_a_rating(text, skill):
    assert stated_level(text, lookup(skill)) is None


def test_the_highest_rating_wins():
    assert stated_level("Familiar: Go\nGo (expert)", lookup("Go")).level == 5


@pytest.mark.parametrize(
    ("text", "skill", "years"),
    [
        ("5+ years of Python", "Python", 5),
        ("3 yrs experience with React", "React", 3),
        ("Kubernetes (4 years)", "Kubernetes", 4),
        ("Python: 6 yrs; Java - 2 years", "Java", 2),
        ("8+ years of experience building web apps in Python", "Python", None),  # the career, not Python
        ("Python", "Python", None),
    ],
)
def test_years_stated_for_one_skill(text, skill, years):
    assert stated_skill_years(text, lookup(skill)) == years


# --- The rules -----------------------------------------------------------------------


def test_a_stated_level_beats_the_evidence():
    level = infer_level(evidence(years=8.0, jobs=3, mentions=9, stated=StatedLevel(2, "familiar")))
    assert level == (2, 'The resume calls it "familiar"')


@pytest.mark.parametrize(("years", "stars"), [(0.5, 2), (1.0, 3), (2.9, 3), (3.0, 4), (4.9, 4), (5.0, 5), (12.0, 5)])
def test_years_of_use(years, stars):
    assert infer_level(evidence(years=years, jobs=2, mentions=3, months_since_used=0))[0] == stars


def test_expert_needs_more_than_a_passing_mention():
    assert infer_level(evidence(years=6.0, jobs=1, mentions=1, months_since_used=0)) == (
        4, "6 years across 1 job; named only once; still using it"
    )
    assert infer_level(evidence(years=6.0, jobs=1, mentions=3, months_since_used=0))[0] == 5
    assert infer_level(evidence(years=6.0, jobs=2, mentions=1, months_since_used=0))[0] == 5
    assert infer_level(evidence(years=6.0, jobs=1, mentions=1, in_title=True, months_since_used=0))[0] == 5


def test_a_job_title_naming_it_means_at_least_advanced():
    assert infer_level(evidence(years=0.5, jobs=1, in_title=True, months_since_used=0)) == (
        4, "0.5 years across 1 job; a job title names it; still using it"
    )


def test_skills_not_used_for_years_lose_a_star_unless_still_listed():
    assert infer_level(evidence(years=3.5, jobs=1, months_since_used=60)) == (
        3, "3.5 years across 1 job; not used for 5 years"
    )
    assert infer_level(evidence(years=3.5, jobs=1, months_since_used=60, in_skills_section=True)) == (
        4, "3.5 years across 1 job; last used 5 years ago, but still listed in your skills"
    )
    assert infer_level(evidence(years=0.5, jobs=1, months_since_used=100))[0] == 1


def test_stated_years_count_as_years_of_use():
    assert infer_level(evidence(stated_years=6, mentions=3)) == (5, "The resume says 6 years")


def test_only_listed():
    assert infer_level(evidence()) == (2, "Listed, but no job on the resume mentions using it")
    assert infer_level(evidence(has_work_history=False)) == (
        3, "On the resume, but there are no dates to judge it by"
    )


# --- On a whole resume ---------------------------------------------------------------


def test_the_sample_resume():
    found = levels(SAMPLE_RESUME)
    assert found["React"] == (5, "7.9 years across 2 jobs; still using it")
    assert found["TypeScript"] == (4, "5.9 years across 1 job; named only 2 times; still using it")
    assert found["Go"] == (2, "Listed, but no job on the resume mentions using it")
    assert found["Java"] == (2, "1.8 years across 1 job; not used for 8 years")
    # Last used in 2020, but the Skills section still lists it.
    assert found["Node.js"][0] == 3


def test_a_skill_used_through_others():
    found = levels(SAMPLE_RESUME)
    assert found["JavaScript"] == (
        5, "10.5 years across 4 jobs (through TypeScript, React, Node.js, jQuery); still using it"
    )
    assert found["SQL"][0] == 3 and "(through PostgreSQL)" in found["SQL"][1]
    # The years shown are still only the jobs that name it.
    javascript = next(s for s in parse_resume(SAMPLE_RESUME, now=NOW).skills if s.name == "JavaScript")
    assert javascript.years is None


def test_a_stated_level_on_a_whole_resume():
    text = SAMPLE_RESUME.replace("Languages: Python, TypeScript, JavaScript, Go, SQL",
                                 "Expert: Python, TypeScript | Familiar: Go, SQL")
    found = levels(text)
    assert found["Go"] == (2, 'The resume calls it "Familiar"')
    assert found["TypeScript"] == (5, 'The resume calls it "Expert"')


def test_best_known_skills_come_first():
    skills = parse_resume(SAMPLE_RESUME, now=NOW).skills
    assert [s.level for s in skills] == sorted((s.level for s in skills), reverse=True)
