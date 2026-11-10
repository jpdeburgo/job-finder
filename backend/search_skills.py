"""The skills the search looks for, and your own list of them.

The defaults are ``RESUME_SKILLS`` and ``CORE_LANGUAGE_SKILLS`` at the top of
``job_search.py``. The dashboard's **Skills** page (``../frontend``) saves your
own list to the database, in the ``settings`` collection::

    settings/search_skills
        skills        every skill to look for, e.g. ["Python", "React", "SQL", ...]
        core_skills   the ones that are your main stack (a subset of skills)
        proficiency   how well you know each one, 1-5 stars: {"Python": 5, "SQL": 2, ...}
        updated_at

Every search (the cron job, the dashboard's Run search button, the command
line) reads it when it starts and uses it instead of the defaults, for the
Core track's matching and for the fit score. Deleting the document (the
dashboard's **Reset to defaults**) goes back to the defaults.

The rules here are mirrored by ``frontend/src/lib/skills.ts``; keep them in sync.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

SEARCH_SKILLS_DOCUMENT = "search_skills"
MAX_SKILLS = 100
MAX_SKILL_LENGTH = 60

# Proficiency: how well you know a skill, in stars. A skill you haven't rated
# (and every skill in a list saved before ratings existed) counts as
# DEFAULT_PROFICIENCY, which leaves its fit score as it was. job_fit.py turns
# stars into weight (PROFICIENCY_FACTORS).
MIN_PROFICIENCY = 1
MAX_PROFICIENCY = 5
DEFAULT_PROFICIENCY = 3
PROFICIENCY_LABELS = {1: "Beginner", 2: "Familiar", 3: "Proficient", 4: "Advanced", 5: "Expert"}


class InvalidSkillsError(ValueError):
    """A skill list that can't be searched with."""


@dataclass(frozen=True)
class SearchSkills:
    """Skills a Core match is scored on, the core ones among them, and how
    well you know each.

    A Core match needs ``MIN_SKILL_MATCHES`` of ``skills``, at least one of
    them from ``core_skills``. The fit score counts a core skill 1 and any
    other 0.5, times its proficiency's factor (job_fit.PROFICIENCY_FACTORS).
    Proficiency doesn't change which jobs match, only how well they fit.
    """

    skills: tuple[str, ...]
    core_skills: tuple[str, ...]
    # (skill, stars) for every skill, in the list's order. Given fewer (or
    # none), the rest are filled in with DEFAULT_PROFICIENCY.
    proficiency: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        given = dict(self.proficiency)
        object.__setattr__(
            self,
            "proficiency",
            tuple((skill, given.get(skill, DEFAULT_PROFICIENCY)) for skill in self.skills),
        )

    def level(self, skill: str) -> int:
        """Stars for ``skill`` (DEFAULT_PROFICIENCY if it isn't listed)."""
        return dict(self.proficiency).get(skill, DEFAULT_PROFICIENCY)

    def as_document(self) -> dict[str, Any]:
        return {
            "skills": list(self.skills),
            "core_skills": list(self.core_skills),
            "proficiency": dict(self.proficiency),
        }


def _clean_name(value: Any) -> str:
    if not isinstance(value, str):
        raise InvalidSkillsError(f"Skills must be text, not {value!r}")
    return re.sub(r"\s+", " ", value).strip()


def _clean_level(name: str, value: Any) -> int:
    # bool is an int in Python; True stars make no sense.
    whole = isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if isinstance(value, bool) or not whole:
        raise InvalidSkillsError(f'Proficiency for "{name}" must be a whole number of stars, not {value!r}')
    if not MIN_PROFICIENCY <= value <= MAX_PROFICIENCY:
        raise InvalidSkillsError(
            f'Proficiency for "{name}" must be {MIN_PROFICIENCY} to {MAX_PROFICIENCY} stars, not {int(value)}'
        )
    return int(value)


def clean_skills(
    skills: Iterable[Any],
    core_skills: Iterable[Any],
    proficiency: dict[str, Any] | None = None,
) -> SearchSkills:
    """Validate a skill list, as the dashboard saves it.

    Names are trimmed and spaces collapsed; blanks and repeats (any case, the
    first spelling wins) are dropped, since matching ignores case. Core skills
    and ratings take the spelling used in ``skills``; a skill without a rating
    gets DEFAULT_PROFICIENCY. Raises ``InvalidSkillsError`` when there are no
    skills, no core skill, too many, a name is too long, a core skill or a
    rating's skill isn't in the list, or a rating isn't 1-5 stars.
    """
    names: list[str] = []
    for value in skills:
        name = _clean_name(value)
        if not name or name.lower() in (n.lower() for n in names):
            continue
        if len(name) > MAX_SKILL_LENGTH:
            raise InvalidSkillsError(
                f'"{name[:20]}..." is too long: skills can be at most {MAX_SKILL_LENGTH} characters'
            )
        names.append(name)
    if not names:
        raise InvalidSkillsError("Add at least one skill")
    if len(names) > MAX_SKILLS:
        raise InvalidSkillsError(f"At most {MAX_SKILLS} skills")

    spelling = {name.lower(): name for name in names}
    core: list[str] = []
    for value in core_skills:
        name = _clean_name(value)
        if not name:
            continue
        if name.lower() not in spelling:
            raise InvalidSkillsError(f'Core skill "{name}" is not in the skill list')
        if spelling[name.lower()] not in core:
            core.append(spelling[name.lower()])
    if not core:
        raise InvalidSkillsError(
            "Mark at least one skill as core: a Core match needs one of them"
        )

    levels: dict[str, int] = {}
    for key, value in (proficiency or {}).items():
        name = _clean_name(key)
        if name.lower() not in spelling:
            raise InvalidSkillsError(f'Proficiency is given for "{name}", which is not in the skill list')
        levels[spelling[name.lower()]] = _clean_level(name, value)
    # Keep core skills in the list's order, so the saved document reads naturally.
    return SearchSkills(
        tuple(names),
        tuple(name for name in names if name in core),
        tuple((name, levels.get(name, DEFAULT_PROFICIENCY)) for name in names),
    )


def skills_from_document(data: dict[str, Any] | None) -> SearchSkills | None:
    """The saved skills in a ``settings/search_skills`` document, or None
    when there is no document. Raises ``InvalidSkillsError`` for one that
    can't be used (e.g. edited by hand in the Firebase console)."""
    if data is None:
        return None
    skills, core = data.get("skills"), data.get("core_skills")
    if not isinstance(skills, list) or not isinstance(core, list):
        raise InvalidSkillsError("skills and core_skills must both be lists")
    proficiency = data.get("proficiency")
    if proficiency is not None and not isinstance(proficiency, dict):
        raise InvalidSkillsError("proficiency must map skills to stars")
    return clean_skills(skills, core, proficiency)
