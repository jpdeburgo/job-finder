"""How well a job fits you: a 0-100 "fit score" for every match.

The search's filters decide whether a job is worth showing at all. The fit
score ranks the jobs that got through, so the best ones are easy to find in
the email and the dashboard. ``score`` (the number of matched skills) is
still saved, but a raw count can't tell a "Network Engineer" that mentions
four tools from a "Full Stack Developer" built on your main languages. The
fit score looks at what the job *is*, not just what it mentions.

It has two parts, which add up to the score:

1. **Relevance** (0-100 points): how close the job is to what you do.

   * ``skills`` (up to 55): your resume skills the posting mentions. A core
     language (Python, React, ...) counts 1, a supporting skill (SQL, AWS,
     Docker, ...) counts 0.5, and spellings of one skill (React / ReactJS)
     count once. Full marks at ``SKILL_POINTS_FULL_AT`` (4).
   * ``role`` (up to 45): whether the title is a role you target. A
     software-engineering title ("Software Engineer", "Full Stack", "Backend",
     ...) earns 30 and a generic one ("Developer") 15. A core skill in the
     title ("React Developer") adds 15.

2. **Adjustments** (0 or negative): things that make a relevant job a
   worse fit. Each takes a share of what's left, so it costs more on a
   strong match than on a weak one.

   * ``experience``: the years the job asks for, or what its title implies
     (Senior ~5, Lead/Staff ~7, Principal ~9) if that's more, compared with
     ``years_experience`` in your profile. Not stated either way: no change.
   * ``remote``: remote jobs keep everything; jobs that don't say lose 15%,
     and hybrid/on-site jobs (only kept when remote-only is off) 40%.
   * ``stack``: the description names tech that isn't on your resume
     (``NON_RESUME_TITLE_TECH``): 5% per name, up to 15%.

``fit_breakdown`` stores each part in points, so they add up to the score,
e.g. ``{"skills": 48, "role": 30, "experience": -8, "remote": 0, "stack": -4}``
is 66. ``fit_reasons`` says the same thing in words.

Everything is a pure function of a ``Posting`` and a ``CandidateProfile``;
``job_search.candidate_profile()`` builds the profile from the settings at
the top of ``job_search.py``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from job_sites import Posting, contains_phrase

MAX_SCORE = 100
SKILL_POINTS = 55
ROLE_POINTS = 45
# Skill weight (core = 1, supporting = 0.5) that earns every skill point.
SKILL_POINTS_FULL_AT = 4.0
CORE_SKILL_WEIGHT = 1.0
SUPPORTING_SKILL_WEIGHT = 0.5
TARGET_ROLE_POINTS = 30
GENERIC_ROLE_POINTS = 15
TITLE_SKILL_POINTS = 15

# Share of the score kept when a job asks for this many more years than you
# have. Two years over is a stretch worth applying for; four is a long shot.
EXPERIENCE_GAP_FACTORS = {0: 1.0, 1: 0.9, 2: 0.75, 3: 0.6}
EXPERIENCE_GAP_FACTOR_MAX = 0.45  # 4+ years over
# What a title implies when the description doesn't state years. Checked in
# order; the first match wins.
TITLE_IMPLIED_YEARS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"\b(?:principal|distinguished|director)\b", re.IGNORECASE), 9),
    (re.compile(r"\b(?:staff|lead|architect)\b", re.IGNORECASE), 7),
    (re.compile(r"\b(?:sr\.?|senior)(?![A-Za-z])", re.IGNORECASE), 5),
    (re.compile(r"\b(?:jr\.?|junior|entry[- ]level|intern|graduate|new grad)(?![A-Za-z])",
                re.IGNORECASE), 0),
)
REMOTE_FACTORS = {True: 1.0, None: 0.85, False: 0.6}
STACK_PENALTY_PER_TECH = 0.05
STACK_PENALTY_MAX = 0.15

# Score bands, for the email and the dashboard (frontend/src/lib/jobs.ts
# mirrors these).
FIT_LABELS = ((75, "Strong"), (60, "Good"), (40, "Fair"), (0, "Weak"))


@dataclass(frozen=True)
class CandidateProfile:
    """What the fit score compares a job against."""

    # Every skill on your resume, and the subset that is your main stack.
    skills: tuple[str, ...]
    core_skills: tuple[str, ...]
    years_experience: int
    # Title phrases for the roles you're after ("software engineer",
    # "full stack", ...) and weaker, generic ones ("developer").
    target_roles: tuple[str, ...]
    generic_roles: tuple[str, ...] = ()
    # Tech that isn't on your resume; naming it in the description costs a little.
    unfamiliar_tech: tuple[str, ...] = ()
    # Spellings of one skill, e.g. ("React", "ReactJS"): a job mentioning
    # both gets credit once.
    skill_aliases: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class FitScore:
    score: int
    # Points per part; they add up to ``score``.
    breakdown: dict[str, int] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return fit_label(self.score)


def fit_label(score: float | None) -> str:
    """"Strong", "Good", "Fair", or "Weak" ("" when there is no score)."""
    if score is None:
        return ""
    return next(label for floor, label in FIT_LABELS if score >= floor)


def _canonical_skills(skills: list[str], profile: CandidateProfile) -> list[str]:
    """Collapse spellings of one skill (React / ReactJS) into the first one listed."""
    canonical: list[str] = []
    for skill in skills:
        group = next((g for g in profile.skill_aliases if skill in g), (skill,))
        name = next((alias for alias in group if alias in skills), skill)
        if name not in canonical:
            canonical.append(name)
    return canonical


def _skill_part(posting: Posting, profile: CandidateProfile) -> tuple[float, list[str]]:
    text = f"{posting.title} {posting.description or ''}"
    found = _canonical_skills(
        [skill for skill in profile.skills if contains_phrase(text, skill)], profile
    )
    core = set(profile.core_skills)
    weight = sum(
        CORE_SKILL_WEIGHT if skill in core else SUPPORTING_SKILL_WEIGHT for skill in found
    )
    points = SKILL_POINTS * min(1.0, weight / SKILL_POINTS_FULL_AT)
    if found:
        core_found = [s for s in found if s in core]
        other = [s for s in found if s not in core]
        detail = ", ".join(core_found + other)
        reason = f"Skills: {detail} ({len(core_found)} core)"
    else:
        reason = "Skills: none of your resume skills are mentioned"
    return points, [reason]


def _role_part(title: str, profile: CandidateProfile) -> tuple[float, list[str]]:
    reasons = []
    role = next((r for r in profile.target_roles if contains_phrase(title, r)), None)
    generic = next((r for r in profile.generic_roles if contains_phrase(title, r)), None)
    if role:
        points = TARGET_ROLE_POINTS
        reasons.append(f'Title is a target role ("{role}")')
    elif generic:
        points = GENERIC_ROLE_POINTS
        reasons.append(f'Title is a generic role ("{generic}")')
    else:
        points = 0
        reasons.append("Title isn't one of your target roles")
    title_skills = _canonical_skills(
        [skill for skill in profile.core_skills if contains_phrase(title, skill)], profile
    )
    if title_skills:
        points += TITLE_SKILL_POINTS
        reasons.append(f"Title names your stack ({', '.join(title_skills)})")
    return min(points, ROLE_POINTS), reasons


def implied_years(title: str) -> int | None:
    """Years of experience a title implies ("Senior" ~5), or None."""
    return next((years for pattern, years in TITLE_IMPLIED_YEARS if pattern.search(title)), None)


def _experience_factor(
    title: str, min_years: int | None, profile: CandidateProfile
) -> tuple[float, str]:
    # The stated years are the lowest number in the description ("3+ years
    # of Angular"), which understates a Principal role, so the title's level
    # counts too: whichever asks for more.
    from_title = implied_years(title)
    parts = []
    if min_years is not None:
        parts.append(f"Asks for {min_years}+ yrs")
    if from_title is not None and (min_years is None or from_title > min_years):
        parts.append(f"title suggests ~{from_title} yrs")
    if not parts:
        return 1.0, "Experience: not stated"
    required = max(years for years in (min_years, from_title) if years is not None)
    source = "; ".join(parts)
    source = source[0].upper() + source[1:]
    gap = required - profile.years_experience
    if gap <= 0:
        return 1.0, f"{source}; you have {profile.years_experience}"
    factor = EXPERIENCE_GAP_FACTORS.get(gap, EXPERIENCE_GAP_FACTOR_MAX)
    return factor, f"{source}; you have {profile.years_experience} ({gap} short)"


def _remote_factor(is_remote: bool | None) -> tuple[float, str]:
    reason = {True: "Remote", None: "Remote not stated", False: "Not remote"}[is_remote]
    return REMOTE_FACTORS[is_remote], reason


def _stack_factor(posting: Posting, profile: CandidateProfile) -> tuple[float, str | None]:
    # Case-sensitive, because these are product names and several are also
    # ordinary words ("swift", "rust", "ignition"). The company's own name
    # doesn't count: every Salesforce posting says "Salesforce".
    text = f"{posting.title} {posting.description or ''}"
    company = posting.company.lower()
    unfamiliar = [
        tech
        for tech in profile.unfamiliar_tech
        if tech.lower() not in company
        and re.search(rf"(?<![A-Za-z0-9]){re.escape(tech)}(?![A-Za-z0-9])", text)
    ]
    if not unfamiliar:
        return 1.0, None
    penalty = min(STACK_PENALTY_MAX, STACK_PENALTY_PER_TECH * len(unfamiliar))
    return 1.0 - penalty, f"Also asks for tech not on your resume: {', '.join(unfamiliar)}"


def score_fit(
    posting: Posting, profile: CandidateProfile, min_years: int | None = None
) -> FitScore:
    """Score how well ``posting`` (with its description loaded) fits ``profile``.

    ``min_years`` is the experience the posting asks for
    (``job_search.extract_min_years``); None when it doesn't say.
    """
    skill_points, reasons = _skill_part(posting, profile)
    role_points, role_reasons = _role_part(posting.title, profile)
    reasons += role_reasons
    relevance = skill_points + role_points

    # Apply the adjustments one after another, recording what each one cost.
    breakdown = {"skills": skill_points, "role": role_points}
    current = relevance
    adjustments = (
        ("experience", _experience_factor(posting.title, min_years, profile)),
        ("remote", _remote_factor(posting.is_remote)),
        ("stack", _stack_factor(posting, profile)),
    )
    for name, (factor, reason) in adjustments:
        adjusted = current * factor
        breakdown[name] = adjusted - current
        current = adjusted
        if reason:
            reasons.append(reason)

    # Round each part, then add them up, so the breakdown always sums to the score.
    # (Half up, not Python's round-half-to-even, so 8.5 is always 9.)
    rounded = {name: math.floor(points + 0.5) for name, points in breakdown.items()}
    score = max(0, min(MAX_SCORE, sum(rounded.values())))
    return FitScore(score=score, breakdown=rounded, reasons=tuple(reasons))
