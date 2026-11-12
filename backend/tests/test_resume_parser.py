"""Reading skills and years of experience from a resume's text without AI
(resume_parser.py), and the skill catalog it looks for (skill_catalog.py)."""

from datetime import datetime, timezone

import pytest

import job_search
import resume_parser
from resume_parser import (
    Position,
    build_analysis,
    find_date_ranges,
    heading_kind,
    merged_months,
    month_index,
    parse_resume,
    stated_years,
)
from skill_catalog import SKILL_CATALOG, Vocabulary, lookup
from tests.resume_files import SAMPLE_RESUME

NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)
TODAY = month_index(2026, 11)


def skills_by_name(analysis):
    return {skill.name: skill for skill in analysis.skills}


# --- The catalog ---------------------------------------------------------------------


def test_whole_words_only_like_the_job_search():
    found = Vocabulary().find("JavaScript and MySQL, T-SQL")
    assert "JavaScript" in found and "MySQL" in found
    assert "Java" not in found
    assert found["SQL"] == 1  # T-SQL, not MySQL


def test_spellings_are_found_under_one_name():
    assert Vocabulary().find("ReactJS, React.js, react")["React"] == 3
    assert Vocabulary().find("nodejs and Node.js")["Node.js"] == 2
    assert lookup("golang").name == "Go"
    assert lookup("  K8S ").name == "Kubernetes"
    assert lookup("Basket weaving") is None


@pytest.mark.parametrize(
    ("text", "skill"),
    [
        ("Built REST APIs", "REST API"),
        ("Languages: Python, Go, C, R", "Go"),
        ("Languages: Python, Go, C, R", "C"),
        ("Languages: Python, Go, C, R", "R"),
        ("Skills | Rust | Swift", "Rust"),
        ("Frameworks: Spring, Hibernate", "Spring Boot"),
        ("Tested it with Cypress and Jest", "Cypress"),
    ],
)
def test_ordinary_words_count_where_they_mean_the_skill(text, skill):
    assert skill in Vocabulary().find(text)


@pytest.mark.parametrize(
    ("text", "skill"),
    [
        ("I did the rest of the work", "REST API"),
        ("Led the Go-live for 30 stores", "Go"),
        ("Joined after the Series C round", "C"),
        ("Based in Cypress, TX", "Cypress"),
        ("Moved to Spring, TX", "Spring Boot"),
        ("Active TS/SCI clearance", "TypeScript"),
        ("Wrote Objective-C", "C"),
        ("Go to market strategy", "Go"),
    ],
)
def test_ordinary_words_dont_count_where_they_dont(text, skill):
    assert skill not in Vocabulary().find(text)


def test_your_own_skills_are_looked_for_too():
    vocabulary = Vocabulary.with_your_skills(["Ignition", "NodeJS", " ", "Python"])
    found = vocabulary.find("Ignition SCADA on NodeJS with Python")
    assert found == {"Python": 1, "Node.js": 1, "Ignition": 1}  # NodeJS is the catalog's Node.js
    assert vocabulary.resolve("ignition").name == "Ignition"
    assert vocabulary.resolve("Basket weaving").category == "Other"


def test_catalog_names_are_the_job_searchs_spellings():
    """A default skill the catalog knows comes back under a name that's on
    the default list too, so the dashboard sees it's already yours."""
    defaults = {skill.lower() for skill in job_search.RESUME_SKILLS}
    for skill in job_search.RESUME_SKILLS:
        known = lookup(skill)
        if known:
            assert known.name.lower() in defaults, (skill, known.name)


def test_every_catalog_skill_finds_its_own_name():
    for skill in SKILL_CATALOG:
        text = f"Skills: Python, {skill.name}, SQL"
        assert skill.found_in(text), skill.name


# --- Dates ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("Jan 2020 – Present", (2020, 1), None),
        ("January 2019 - March 2021", (2019, 1), (2021, 3)),
        ("Sept. 2018 — Current", (2018, 9), None),
        ("03/2016 - 11/2018", (2016, 3), (2018, 11)),
        ("3/2016 to 11/2018", (2016, 3), (2018, 11)),
        ("2015-04 – 2017-09", (2015, 4), (2017, 9)),
        ("2014 - 2016", (2014, 1), (2016, 12)),
        ("Summer 2019 – Fall 2019", (2019, 6), (2019, 9)),
        ("May, 2012 through June 2013", (2012, 5), (2013, 6)),
        ("Oct 2022 to date", (2022, 10), None),
    ],
)
def test_date_range_forms(text, start, end):
    [(_match, span)] = find_date_ranges(f"Engineer, Acme    {text}")
    assert span.start == month_index(*start)
    assert span.end == (month_index(*end) if end else None)


def test_a_range_that_ends_before_it_starts_is_kept_as_nonsense():
    [(_match, span)] = find_date_ranges("2020 - 2018")
    assert span is None


def test_merged_months_counts_overlaps_once():
    assert merged_months([]) == 0
    assert merged_months([(0, 11)]) == 12
    assert merged_months([(0, 11), (6, 17)]) == 18  # overlap
    assert merged_months([(0, 11), (12, 23)]) == 24  # back to back
    assert merged_months([(12, 23), (0, 5)]) == 18  # a gap, any order
    assert merged_months([(0, 23), (3, 5)]) == 24  # one inside another


def test_stated_years():
    assert stated_years("Engineer with 8+ years of experience") == 8
    assert stated_years("over 10 years' professional software development experience; 3 years of React experience") == 10
    assert stated_years("5 yrs exp") == 5
    assert stated_years("Managed 12 engineers for 3 years") is None
    assert stated_years("Experience: 99 years of experience") is None


# --- Sections ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ("PROFESSIONAL EXPERIENCE", "experience"),
        ("Work History", "experience"),
        ("— Experience —", "experience"),
        ("Education", "education"),
        ("Technical Skills:", "skills"),
        ("Skills/Tools", "skills"),
        ("Projects", "other"),
        ("Certifications", "other"),
        ("SUMMARY", "other"),
        ("Languages: Python, Java", None),
        ("Pearson Education", None),
        ("Senior Software Engineer at a company with a long name", None),
    ],
)
def test_headings(line, kind):
    assert heading_kind(line) == kind


# --- Reading a resume ----------------------------------------------------------------


def test_total_years_count_overlaps_once_and_only_work_history():
    analysis = parse_resume(SAMPLE_RESUME, now=NOW)
    # June 2016 to November 2026 without a gap; the freelance years overlap
    # Beta, and education (2012-2016) and the Rust project don't count.
    assert analysis.years_experience == 10.5
    assert analysis.years_basis == "positions"
    assert analysis.method == "parse"
    assert [p.title for p in analysis.positions] == [
        "Senior Software Engineer · Acme Corp · Austin, TX",
        "Freelance Web Developer",
        "Software Engineer · Beta LLC, Remote",
        "Junior Developer, Gamma Inc.",
    ]


def test_dates_in_a_bullet_point_arent_a_job():
    analysis = parse_resume(SAMPLE_RESUME, now=NOW)
    assert not any(p.start == month_index(2019, 1) and p.end == month_index(2020, 12) and "Acme" in p.title
                   for p in analysis.positions)
    assert len(analysis.positions) == 4


def test_years_per_skill_come_from_the_jobs_that_mention_it():
    skills = skills_by_name(parse_resume(SAMPLE_RESUME, now=NOW))
    # Acme (Jan 2021 - now, 71 months), Beta (Mar 2018 - Dec 2020, 34 months).
    assert skills["AWS"].years == 8.8
    assert skills["AWS"].last_used == "present"
    # React: Acme plus the freelance work (2019-2020), which overlaps Beta but not Acme.
    assert skills["React"].years == round((71 + 24) / 12, 1)
    assert skills["Java"].years == 1.8
    assert skills["Java"].last_used == "2018-02"
    # Only in the skills list: found, but no years.
    assert skills["Go"].years is None and skills["Go"].last_used is None
    assert skills["Go"].mentions == 1
    # Most experience first.
    assert list(skills)[:2] == ["AWS", "React"]


def test_skills_outside_work_history_are_still_found():
    skills = skills_by_name(parse_resume(SAMPLE_RESUME, now=NOW))
    assert "Rust" in skills and skills["Rust"].years is None  # the project
    assert "Cypress" not in skills  # the address


def test_a_mismatch_with_the_stated_years_is_noted():
    analysis = parse_resume(SAMPLE_RESUME, now=NOW)
    assert analysis.stated_years == 8
    assert analysis.notes == (
        "The resume mentions 8 years of experience; the dates in its work history add up to 10.5.",
    )


def test_without_headings_every_range_outside_education_counts():
    text = """Sam Smith

Python Developer, Initech
2019 - 2021
- Django and PostgreSQL
Data Analyst, Initrode
2017 - 2018
- SQL and Tableau
Education
BS Math 2013 - 2017"""
    analysis = parse_resume(text, now=NOW)
    assert analysis.years_experience == 5.0  # 2017-2018 and 2019-2021: 24 + 36 months
    assert [p.title for p in analysis.positions] == ["Python Developer, Initech", "Data Analyst, Initrode"]
    skills = skills_by_name(analysis)
    assert skills["Django"].years == 3.0 and skills["Tableau"].years == 2.0
    assert analysis.notes[0].startswith("No work experience heading found")


def test_title_and_company_on_their_own_lines():
    text = "EXPERIENCE\nStaff Engineer\nUmbrella Corp\nFeb 2015 - Jan 2016\n- Kotlin\nEngineer\nVandelay\n2014 - 2014"
    positions = parse_resume(text, now=NOW).positions
    assert [p.title for p in positions] == ["Staff Engineer · Umbrella Corp", "Engineer · Vandelay"]
    assert [p.skills for p in positions] == [("Kotlin",), ()]


def test_the_title_can_follow_the_dates():
    text = "EXPERIENCE\nJan 2020 - Dec 2020\nBackend Engineer, Hooli\n- Go services\n"
    [position] = parse_resume(text, now=NOW).positions
    assert position.title == "Backend Engineer, Hooli"


def test_a_docx_table_row_with_the_dates_beside_the_title():
    text = "EXPERIENCE\nSenior Engineer, Acme | Jan 2020 – Present\n- Python and AWS"
    [position] = parse_resume(text, now=NOW).positions
    assert position.title == "Senior Engineer, Acme"
    assert position.end is None and set(position.skills) == {"Python", "AWS"}


def test_a_range_ending_in_the_future_is_current_and_nonsense_is_skipped():
    text = "EXPERIENCE\nEngineer, A    2022 - 2026\nEngineer, B    2020 - 2018\nEngineer, C    2027 - Present"
    analysis = parse_resume(text, now=NOW)
    [position] = analysis.positions
    assert position.end is None  # runs to December 2026: still there
    assert analysis.years_experience == round((TODAY - month_index(2022, 1) + 1) / 12, 1)
    assert "Skipped dates that don't make sense: 2020 - 2018, 2027 - Present." in analysis.notes


def test_without_dates_the_stated_years_are_used():
    analysis = parse_resume("Engineer with 6 years of experience in Java and Spring Boot.", now=NOW)
    assert analysis.years_experience == 6.0
    assert analysis.years_basis == "stated"
    assert analysis.positions == ()


def test_without_dates_or_stated_years_the_years_are_unknown():
    analysis = parse_resume("Python, SQL", now=NOW)
    assert analysis.years_experience is None and analysis.years_basis is None
    assert "couldn't be worked out" in analysis.notes[-1]
    assert [s.name for s in analysis.skills] == ["Python", "SQL"]


def test_your_skills_are_found_and_keep_your_spelling():
    analysis = parse_resume("EXPERIENCE\nControls Engineer  2020 - 2021\n- Ignition HMI screens", ["Ignition"], now=NOW)
    skill = skills_by_name(analysis)["Ignition"]
    assert (skill.years, skill.category) == (2.0, "Other")


def test_the_document_the_dashboard_reads():
    document = parse_resume(SAMPLE_RESUME, now=NOW).as_document()
    assert document["method"] == "parse" and document["analyzed_at"] == NOW
    assert document["positions"][0] == {
        "title": "Senior Software Engineer · Acme Corp · Austin, TX",
        "company": "",
        "start": "2021-01",
        "end": None,
        "months": 71,
        "skills": ["Python", "TypeScript", "React", "Django", "REST API", "AWS", "Kubernetes", "Terraform"],
    }
    react = next(skill for skill in document["skills"] if skill["name"] == "React")
    assert react == {
        "name": "React", "category": "Frontend", "years": 7.9, "mentions": 4,
        "last_used": "present", "aliases": ["ReactJS", "React.js"],
        "level": 5, "level_reason": "7.9 years across 2 jobs; still using it",
    }


def test_build_analysis_merges_spellings_and_positions_skills():
    positions = [Position("Dev", "X", month_index(2020, 1), month_index(2020, 12), ("ReactJS", "nodejs"))]
    analysis = build_analysis(
        "ai", "React dev", positions, ["React.js", "Kubernetes"], Vocabulary(), now=NOW,
        categories={"kubernetes": "Cloud"},
    )
    skills = skills_by_name(analysis)
    assert list(skills) == ["React", "Node.js", "Kubernetes"]
    assert analysis.positions[0].skills == ("React", "Node.js")
    assert skills["React"].years == 1.0 and skills["React"].mentions == 1
    assert skills["Kubernetes"].mentions == 0  # named, but not in the text: inferred
    assert skills["Kubernetes"].category == "DevOps"  # the catalog's category wins over the AI's


def test_ai_categories_apply_to_skills_outside_the_catalog():
    analysis = build_analysis("ai", "", [], ["Unreal Engine"], Vocabulary(), now=NOW,
                              categories={"unreal engine": "Tools"})
    assert analysis.skills[0].category == "Tools"


def test_month_labels_round_trip():
    assert resume_parser.month_label(month_index(2024, 3)) == "2024-03"
    assert resume_parser.parse_month("2024-03") == month_index(2024, 3)
    assert resume_parser.parse_month("2024") == month_index(2024, 1)
    assert resume_parser.parse_month("March 2024") is None


def test_backstage_is_found_without_being_on_your_list():
    found = Vocabulary().find("Built the developer portal on Backstage.io; wrote backstage plugins")
    assert found["Backstage"] == 2
