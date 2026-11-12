"""How well you know each skill on your resume, in the Skills page's 1-5
stars (search_skills.PROFICIENCY_LABELS: Beginner, Familiar, Proficient,
Advanced, Expert).

Parsing a resume (resume_parser.py) infers a level from, in order:

1. **What the resume says.** "Expert: Python, Go", "familiar with Docker",
   "Python (advanced)": your own assessment wins. "5+ years of Python" or
   "React (4 years)" count as years of use, below.
2. **Years of use**, from the jobs that mention the skill or something built
   on it (``IMPLIED_BY``: React and TypeScript are JavaScript, Django is
   Python, PostgreSQL is SQL), or the years the resume states for it, if
   more: under 1 year Familiar, 1-3 Proficient, 3-5 Advanced, 5+ Expert.
   Expert also needs the skill to be more than a passing mention: named 3+
   times, in 2+ jobs, or in a job title.
3. **A job title naming it** ("Senior Python Developer"): at least Advanced.
4. **Not used for 4+ years**: one star less, unless the resume still lists it
   among your skills.
5. **Only listed** (a Skills section, no job mentions it): Familiar. With no
   dates on the resume at all there's nothing to go on, so it's left at the
   default, Proficient.

Reading with AI (resume_ai.py) asks the model for a level and a reason per
skill instead, since it can also weigh what the bullets say ("led the
migration" vs. "some exposure to"); these rules fill in any it leaves out.
Each level comes with a short reason, shown on the dashboard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from search_skills import DEFAULT_PROFICIENCY, MAX_PROFICIENCY, MIN_PROFICIENCY, PROFICIENCY_LABELS
from skill_catalog import CatalogSkill

# Words a resume uses to rate a skill, and the stars they mean.
LEVEL_WORDS = {
    "expert": 5, "expertise": 5,
    "highly proficient": 4, "very proficient": 4, "advanced": 4, "strong": 4, "extensive": 4,
    # Not "deep" alone: "Deep learning models in PyTorch" is a skill, not a rating.
    "deep knowledge": 4, "deep expertise": 4, "deep experience": 4,
    "proficient": 3, "experienced": 3, "skilled": 3, "intermediate": 3, "competent": 3, "solid": 3,
    "working proficiency": 3,
    "familiar": 2, "working knowledge": 2, "exposure": 2, "basic": 2, "some experience": 2,
    "beginner": 1, "novice": 1, "learning": 1, "currently learning": 1, "introductory": 1,
}
_LABEL = "|".join(sorted((re.escape(word) for word in LEVEL_WORDS), key=len, reverse=True))
# A rating that covers the skills after it on the line: at the start of the
# line or of a part of it, and followed by a colon or "in"/"with" (up to two
# words later: "strong background in"). So "Expert: Python" and "familiar
# with Go" rate skills, but "Experienced software engineer ..." doesn't.
LINE_LEVEL = re.compile(
    rf"(?:^|(?<=[.;|•:,(])|\band\s)\s*(?P<label>{_LABEL})"
    rf"(?:(?:\s+[A-Za-z-]+){{0,2}}?\s+(?:in|with|at|using|of)\b|\s*[:–—-])",
    re.IGNORECASE,
)
# A rating right after the skill: "Python (expert)", "Go - familiar".
AFTER_LEVEL = re.compile(rf"^\s*(?:[(\[]|[:–—-])\s*(?P<label>{_LABEL})\b", re.IGNORECASE)
# Parts of a line a rating doesn't reach past.
_BREAK = re.compile(r"[.;|•]")
# Years for one skill: "5+ years of Python", "3 yrs experience with React",
# "Python (5 years)", "Go: 2+ yrs".
YEARS_BEFORE = re.compile(
    r"(?<!\d)(\d{1,2})\s*\+?\s*(?:years?|yrs?)['’]?\.?\s+(?:of\s+)?"
    r"(?:(?:professional|hands-on|commercial|production)\s+)?"
    r"(?:(?:experience|exp)\s+(?:with|in|using)\s+)?$",
    re.IGNORECASE,
)
YEARS_AFTER = re.compile(r"^\s*[(:–—-]\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)
MAX_SKILL_YEARS = 50

# Skills that are used through others: working in React or TypeScript is
# working in JavaScript. A skill's level counts the jobs that use these too.
IMPLIED_BY: dict[str, tuple[str, ...]] = {
    "JavaScript": ("TypeScript", "React", "React Native", "Node.js", "Next.js", "Vue.js", "Angular",
                   "AngularJS", "Svelte", "Express", "NestJS", "jQuery"),
    "Python": ("Django", "Flask", "FastAPI", "Pandas", "NumPy", "PyTorch", "TensorFlow", "scikit-learn", "pytest"),
    "Java": ("Spring Boot", "Hibernate", "JUnit"),
    "C#": (".NET Core", "ASP.NET", "Entity Framework", "Blazor"),
    "Ruby": ("Ruby on Rails",),
    "PHP": ("Laravel",),
    "Dart": ("Flutter",),
    "SQL": ("PostgreSQL", "MySQL", "SQL Server", "SQLite", "Oracle"),
    "AWS": ("AWS Lambda", "DynamoDB"),
    "Docker": ("Kubernetes",),
    "Git": ("GitHub", "GitLab", "Bitbucket"),
}

# Years of use -> stars: under 1, 1-3, 3-5, 5+.
YEARS_LEVELS = ((5.0, 5), (3.0, 4), (1.0, 3), (0.0, 2))
# Expert needs the skill to be more than a passing mention.
EXPERT_MIN_MENTIONS = 3
EXPERT_MIN_JOBS = 2
TITLE_LEVEL = 4
# Not used for this long: one star less.
STALE_MONTHS = 48
LISTED_ONLY_LEVEL = 2


@dataclass(frozen=True)
class StatedLevel:
    level: int
    word: str  # as the resume puts it: "Expert", "familiar"


def stated_level(text: str, skill: CatalogSkill) -> StatedLevel | None:
    """The level the resume gives the skill itself, if any (the highest, if
    it gives several)."""
    found: list[StatedLevel] = []
    for line in text.splitlines():
        labels = list(LINE_LEVEL.finditer(line))
        for match in skill.pattern.finditer(line):
            after = AFTER_LEVEL.match(line[match.end():])
            if after:
                found.append(StatedLevel(LEVEL_WORDS[after.group("label").lower()], after.group("label")))
                continue
            # The nearest rating before it on the line, with no break between.
            before = [label for label in labels if label.end() <= match.start()
                      and not _BREAK.search(line[label.end():match.start()])]
            if before:
                word = before[-1].group("label")
                found.append(StatedLevel(LEVEL_WORDS[word.lower()], word))
    return max(found, key=lambda stated: stated.level) if found else None


def stated_skill_years(text: str, skill: CatalogSkill) -> int | None:
    """Years the resume gives for the skill itself ("5+ years of Python"), if any."""
    years = []
    for match in skill.pattern.finditer(text):
        before = YEARS_BEFORE.search(text[max(0, match.start() - 80):match.start()])
        after = YEARS_AFTER.match(text[match.end():match.end() + 30])
        years += [int(m.group(1)) for m in (before, after) if m]
    years = [y for y in years if 0 < y <= MAX_SKILL_YEARS]
    return max(years) if years else None


@dataclass(frozen=True)
class Evidence:
    """What the resume shows about one skill."""

    years: float | None  # from the jobs that mention it
    mentions: int
    jobs: int  # jobs that mention it
    in_title: bool  # a job title names it
    months_since_used: int | None  # 0: still using it; None: no job mentions it
    has_work_history: bool  # the resume has dated jobs at all
    stated: StatedLevel | None = None
    stated_years: int | None = None
    # Skills built on it that those jobs used (React, for JavaScript).
    through: tuple[str, ...] = ()
    # Named in the resume's Skills section: you still claim it.
    in_skills_section: bool = False


def _stars(level: int) -> int:
    return max(MIN_PROFICIENCY, min(MAX_PROFICIENCY, level))


def _years_text(years: float) -> str:
    return f"{years:g} year{'' if years == 1 else 's'}"


def infer_level(evidence: Evidence) -> tuple[int, str]:
    """Stars for a skill, and why (see the module docstring)."""
    if evidence.stated:
        return evidence.stated.level, f'The resume calls it "{evidence.stated.word}"'

    years = max(evidence.years or 0, evidence.stated_years or 0) or None
    if years is None:
        if evidence.has_work_history:
            return LISTED_ONLY_LEVEL, "Listed, but no job on the resume mentions using it"
        return DEFAULT_PROFICIENCY, "On the resume, but there are no dates to judge it by"

    level = next(stars for floor, stars in YEARS_LEVELS if years >= floor)
    if evidence.stated_years and evidence.stated_years >= (evidence.years or 0):
        reasons = [f"the resume says {_years_text(evidence.stated_years)}"]
    else:
        through = f" (through {', '.join(evidence.through)})" if evidence.through else ""
        reasons = [f"{_years_text(years)} across {evidence.jobs} job{'' if evidence.jobs == 1 else 's'}{through}"]

    emphasized = (evidence.mentions >= EXPERT_MIN_MENTIONS or evidence.jobs >= EXPERT_MIN_JOBS
                  or evidence.in_title)
    if level == MAX_PROFICIENCY and not emphasized:
        level -= 1
        reasons.append("named only once" if evidence.mentions == 1 else f"named only {evidence.mentions} times")
    if evidence.in_title and level < TITLE_LEVEL:
        level = TITLE_LEVEL
        reasons.append("a job title names it")
    elif evidence.in_title:
        reasons.append("a job title names it")
    if evidence.months_since_used is not None and evidence.months_since_used >= STALE_MONTHS:
        if evidence.in_skills_section:
            reasons.append(f"last used {evidence.months_since_used // 12} years ago, but still listed in your skills")
        else:
            level -= 1
            reasons.append(f"not used for {evidence.months_since_used // 12} years")
    elif evidence.months_since_used == 0:
        reasons.append("still using it")
    text = "; ".join(reasons)
    return _stars(level), text[0].upper() + text[1:]


def label(level: int) -> str:
    return PROFICIENCY_LABELS[level]
