"""Your own skill list (search_skills.py): saving it, and every search using it."""

import json
import re
from pathlib import Path

import pytest

import job_search
import jobs_cli
from job_sites import InsightGlobalSite, Posting
from job_store import FirestoreJobStore
from search_skills import (
    DEFAULT_PROFICIENCY,
    MAX_SKILLS,
    InvalidSkillsError,
    SearchSkills,
    clean_skills,
    skills_from_document,
)

FRONTEND_SKILLS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "skills.ts"
IG = InsightGlobalSite(job_search.INSIGHT_GLOBAL_URL)
MINE = SearchSkills(("Go", "Kotlin", "Kubernetes", "PostgreSQL"), ("Go", "Kotlin"))


@pytest.fixture
def store(tmp_path):
    return FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)


def _posting(title="Software Engineer", description="", job_id="insight-global-1"):
    return Posting(
        job_id=job_id, title=title, url="https://x", company="Insight Global",
        is_remote=True, job_type="Contract", description=description,
    )


# --- The rules -------------------------------------------------------------------------


def test_clean_skills_trims_and_drops_repeats_in_any_case():
    assert clean_skills(["  Python ", "REST   API", "", "python", "Go"], ["PYTHON"]) == SearchSkills(
        ("Python", "REST API", "Go"), ("Python",)
    )


def test_core_skills_take_the_lists_spelling_and_order():
    assert clean_skills(["Python", "Go", "SQL"], ["go", "Python", "Go"]).core_skills == ("Python", "Go")


@pytest.mark.parametrize(
    ("skills", "core", "message"),
    [
        ([], ["Python"], "Add at least one skill"),
        (["  "], [], "Add at least one skill"),
        (["Python", "SQL"], [], "Mark at least one skill as core"),
        (["Python"], ["Go"], 'Core skill "Go" is not in the skill list'),
        (["x" * 61], [], "too long"),
        ([f"Skill {i}" for i in range(MAX_SKILLS + 1)], ["Skill 0"], f"At most {MAX_SKILLS} skills"),
        ([42], [], "Skills must be text"),
    ],
)
def test_clean_skills_rejects_lists_that_cant_be_searched(skills, core, message):
    with pytest.raises(InvalidSkillsError, match=re.escape(message)):
        clean_skills(skills, core)


def test_skills_from_document():
    assert skills_from_document(None) is None
    assert skills_from_document({"skills": ["Go"], "core_skills": ["Go"], "updated_at": "x"}) == SearchSkills(
        ("Go",), ("Go",)
    )
    with pytest.raises(InvalidSkillsError, match="must both be lists"):
        skills_from_document({"skills": "Go"})


def test_the_defaults_are_a_valid_list():
    defaults = job_search.default_search_skills()
    cleaned = clean_skills(defaults.skills, defaults.core_skills)
    assert cleaned.skills == defaults.skills
    # Core skills come back in the list's order; their order doesn't matter.
    assert set(cleaned.core_skills) == set(defaults.core_skills)


def test_the_dashboard_shows_the_same_defaults():
    """frontend/src/lib/skills.ts mirrors RESUME_SKILLS / CORE_LANGUAGE_SKILLS to
    show them before you save a list of your own."""
    if not FRONTEND_SKILLS.exists():
        pytest.skip("frontend/ isn't next to backend/")
    source = FRONTEND_SKILLS.read_text(encoding="utf-8")
    block = re.search(r"const DEFAULT_SKILL_LISTS = \{(.*?)\n\};", source, re.DOTALL)
    assert block, "DEFAULT_SKILL_LISTS not found in skills.ts"

    def array(name):
        found = re.search(rf"{name}: \[(.*?)\]", block.group(1), re.DOTALL)
        return json.loads("[" + re.sub(r",\s*$", "", found.group(1).strip()) + "]")

    assert array("skills") == job_search.RESUME_SKILLS
    # In the list's order there (as the dashboard saves them); order doesn't matter.
    assert sorted(array("core_skills")) == sorted(job_search.CORE_LANGUAGE_SKILLS)


# --- The store -------------------------------------------------------------------------


def test_store_saves_and_loads_the_list(store, tmp_path):
    assert store.load_search_skills() is None

    store.save_search_skills(MINE)

    saved = store.load_search_skills()
    assert skills_from_document(saved) == MINE
    data = json.loads((tmp_path / "local_firestore.json").read_text())
    assert set(data["settings"]["search_skills"]) == {"skills", "core_skills", "proficiency", "updated_at"}
    assert data["settings"]["search_skills"]["proficiency"] == {skill: 3 for skill in MINE.skills}
    assert data["settings"]["search_skills"]["skills"] == list(MINE.skills)


def test_reads_a_list_saved_by_the_dashboard(tmp_path):
    """The dashboard writes settings/search_skills to the same file
    (LocalJsonJobStore.saveSearchSkills in ../frontend)."""
    path = tmp_path / "local_firestore.json"
    path.write_text(json.dumps({
        "jobs": {},
        "settings": {"search_skills": {
            "core_skills": ["Go"], "skills": ["Go", "SQL"], "updated_at": "2026-11-08T22:00:00.000+00:00",
        }},
    }))
    store = FirestoreJobStore.local(path, verbose=False)

    assert skills_from_document(store.load_search_skills()) == SearchSkills(("Go", "SQL"), ("Go",))


def test_settings_collection_name_comes_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRESTORE_SETTINGS_COLLECTION", "ig_settings")
    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)
    store.save_search_skills(MINE)
    assert list(json.loads((tmp_path / "db.json").read_text())) == ["ig_settings"]


# --- The search ------------------------------------------------------------------------


def test_build_tracks_scores_the_core_track_on_your_skills():
    core, *growth = job_search.build_tracks(MINE)

    assert core.skills == MINE.skills
    assert core.required_skills == MINE.core_skills
    assert core.profile.skills == MINE.skills and core.profile.core_skills == MINE.core_skills
    # The growth tracks are about their own stack, whatever your list says.
    assert [t.skills for t in growth] == [t.skills for t in job_search.TRACKS[1:]]
    assert all(t.profile is core.profile for t in growth)


def test_default_tracks_are_unchanged():
    core = job_search.build_tracks()[0]
    assert core.skills == tuple(job_search.RESUME_SKILLS)
    assert core.required_skills == tuple(job_search.CORE_LANGUAGE_SKILLS)


def test_a_job_matches_on_your_skills_instead_of_the_defaults():
    posting = _posting("Platform Engineer", "Go and PostgreSQL services on Kubernetes.")
    core = job_search.build_tracks(MINE)[0]

    assert job_search.evaluate_posting(posting, IG, job_search.TRACKS[0]) is None  # no default skills
    match = job_search.evaluate_posting(posting, IG, core)

    assert match.matched_skills == ["Go", "Kubernetes", "PostgreSQL"]
    # The fit score counts your core skills too: Go 1 + two others 0.5 each.
    assert match.fit_reasons[0] == "Skills: Go, Kubernetes, PostgreSQL (1 core)"
    assert match.fit_breakdown["skills"] == round(55 * 2 / 4)


def test_a_match_still_needs_one_of_your_core_skills():
    posting = _posting("Software Engineer", "Kubernetes and PostgreSQL.")
    assert job_search.evaluate_posting(posting, IG, job_search.build_tracks(MINE)[0]) is None


def test_adding_unfamiliar_tech_to_your_skills_stops_dropping_it():
    """Kotlin is in NON_RESUME_TITLE_TECH: titles naming it are dropped, and
    descriptions naming it cost fit points, until it's one of your skills."""
    posting = _posting("Kotlin Developer", "Kotlin and Go microservices on Kubernetes.")

    assert "Kotlin" not in job_search.unfamiliar_tech(MINE)
    assert "Kotlin" in job_search.unfamiliar_tech()
    defaults_plus_go = SearchSkills(job_search.default_search_skills().skills + ("Go",), ("Go",))
    assert job_search.evaluate_posting(posting, IG, job_search.build_tracks(defaults_plus_go)[0]) is None

    match = job_search.evaluate_posting(posting, IG, job_search.build_tracks(MINE)[0])
    assert match is not None
    assert match.fit_breakdown["stack"] == 0


def test_main_searches_with_the_skills_saved_in_the_dashboard(store, monkeypatch, capsys):
    store.save_search_skills(MINE)
    seen = {}

    def fake_search(*args, tracks=None, **kwargs):
        seen["tracks"] = tracks
        return []

    monkeypatch.setattr(job_search, "run_all_searches", fake_search)

    job_search.main(store)

    assert seen["tracks"][0].skills == MINE.skills
    assert seen["tracks"][0].required_skills == MINE.core_skills
    assert "Skills (saved in the dashboard; * = core): Go*, Kotlin*, Kubernetes, PostgreSQL" in capsys.readouterr().out


def test_main_uses_the_defaults_without_a_saved_list(store, monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(
        job_search, "run_all_searches", lambda *a, tracks=None, **k: seen.setdefault("tracks", tracks) and []
    )

    job_search.main(store)

    assert seen["tracks"][0].skills == tuple(job_search.RESUME_SKILLS)
    assert "Skills (defaults in job_search.py; * = core): Python*, JavaScript*" in capsys.readouterr().out


def test_main_falls_back_to_the_defaults_when_the_saved_list_is_broken(tmp_path, monkeypatch, capsys):
    path = tmp_path / "local_firestore.json"
    path.write_text(json.dumps({"settings": {"search_skills": {"skills": ["SQL"], "core_skills": []}}}))
    store = FirestoreJobStore.local(path, verbose=False)
    seen = {}
    monkeypatch.setattr(
        job_search, "run_all_searches", lambda *a, tracks=None, **k: seen.setdefault("tracks", tracks) and []
    )

    job_search.main(store)

    assert seen["tracks"][0].skills == tuple(job_search.RESUME_SKILLS)
    out = capsys.readouterr().out
    assert "WARNING: the saved skill list can't be used (Mark at least one skill as core" in out


def test_run_all_searches_hands_the_tracks_to_every_site(monkeypatch):
    tracks = job_search.build_tracks(MINE)
    given = []

    class Result:
        matches, searches, failed_terms, onsite, checked = [], 1, [], {}, set()

    def fake_site_search(site, site_tracks):
        given.append(site_tracks)
        return Result()

    monkeypatch.setattr(job_search, "_search_site_in_own_session", fake_site_search)

    job_search.run_all_searches(tracks=tracks)

    assert given == [tracks, tracks]  # Insight Global and Accenture (conftest)


# --- Moving to Firebase ------------------------------------------------------------------


def test_migrate_copies_your_skill_list(tmp_path, capsys):
    source = FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)
    source.save_search_skills(MINE)
    target = FirestoreJobStore.local(tmp_path / "target.json", verbose=False)

    assert jobs_cli.main(["migrate", str(tmp_path / "local_firestore.json")], target) == 0

    assert skills_from_document(target.load_search_skills()) == MINE
    assert "Imported your skill list (4 skills)." in capsys.readouterr().out


def test_migrate_keeps_a_list_already_saved_in_the_target(tmp_path, capsys):
    source = FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)
    source.save_search_skills(MINE)
    target = FirestoreJobStore.local(tmp_path / "target.json", verbose=False)
    theirs = SearchSkills(("Rust",), ("Rust",))
    target.save_search_skills(theirs)

    assert jobs_cli.main(["migrate", str(tmp_path / "local_firestore.json")], target) == 0

    assert skills_from_document(target.load_search_skills()) == theirs
    assert "Kept the skill list already saved there" in capsys.readouterr().out


# --- Proficiency (1-5 stars) ---------------------------------------------------------------


def test_unrated_skills_get_the_default_proficiency():
    skills = SearchSkills(("Go", "SQL"), ("Go",), (("Go", 5),))
    assert skills.proficiency == (("Go", 5), ("SQL", DEFAULT_PROFICIENCY))
    assert skills.level("SQL") == 3 and skills.level("Unlisted") == 3
    # So lists saved before ratings existed read exactly as before.
    assert SearchSkills(("Go",), ("Go",)) == clean_skills(["Go"], ["Go"])


def test_clean_skills_reads_ratings_in_any_case():
    cleaned = clean_skills(["Python", "SQL", "Go"], ["Python"], {"python": 5, "SQL": 1.0})
    assert cleaned.proficiency == (("Python", 5), ("SQL", 1), ("Go", 3))
    assert cleaned.as_document()["proficiency"] == {"Python": 5, "SQL": 1, "Go": 3}


@pytest.mark.parametrize(
    ("proficiency", "message"),
    [
        ({"Rust": 4}, 'Proficiency is given for "Rust", which is not in the skill list'),
        ({"Go": 0}, 'Proficiency for "Go" must be 1 to 5 stars, not 0'),
        ({"Go": 6}, 'Proficiency for "Go" must be 1 to 5 stars, not 6'),
        ({"Go": 2.5}, "must be a whole number of stars"),
        ({"Go": "5"}, "must be a whole number of stars"),
        ({"Go": True}, "must be a whole number of stars"),
        ({"Go": float("inf")}, "must be a whole number of stars"),
    ],
)
def test_clean_skills_rejects_ratings_that_arent_1_to_5_stars(proficiency, message):
    with pytest.raises(InvalidSkillsError, match=re.escape(message)):
        clean_skills(["Go"], ["Go"], proficiency)


def test_ratings_round_trip_through_the_store(store):
    rated = clean_skills(["Go", "SQL"], ["Go"], {"Go": 5, "SQL": 2})
    store.save_search_skills(rated)
    assert skills_from_document(store.load_search_skills()) == rated


def test_a_saved_document_without_ratings_still_reads():
    assert skills_from_document({"skills": ["Go"], "core_skills": ["Go"]}).proficiency == (("Go", 3),)
    with pytest.raises(InvalidSkillsError, match="proficiency must map skills to stars"):
        skills_from_document({"skills": ["Go"], "core_skills": ["Go"], "proficiency": [5]})


def test_the_fit_score_uses_your_ratings_but_matching_doesnt():
    text = "Go, Kubernetes and PostgreSQL."
    posting = _posting("Platform Engineer", text)
    expert = SearchSkills(MINE.skills, MINE.core_skills, (("Go", 5), ("Kubernetes", 5), ("PostgreSQL", 5)))
    beginner = SearchSkills(MINE.skills, MINE.core_skills, (("Go", 1), ("Kubernetes", 1), ("PostgreSQL", 1)))

    matches = {
        name: job_search.evaluate_posting(posting, IG, job_search.build_tracks(skills)[0])
        for name, skills in (("expert", expert), ("default", MINE), ("beginner", beginner))
    }

    # Same match either way: proficiency only changes how well it fits.
    assert {tuple(m.matched_skills) for m in matches.values()} == {("Go", "Kubernetes", "PostgreSQL")}
    assert matches["expert"].fit_score > matches["default"].fit_score > matches["beginner"].fit_score
    assert matches["expert"].fit_reasons[0] == "Skills: Go 5★, Kubernetes 5★, PostgreSQL 5★ (1 core)"
    assert matches["default"].fit_reasons[0] == "Skills: Go, Kubernetes, PostgreSQL (1 core)"
