"""Read a resume's skills and years of experience from its text, without AI.

``parse_resume(text)`` returns a ``ResumeAnalysis``:

* **Years of experience**: the date ranges in your work history ("Jan 2019 -
  Present", "03/2016 - 06/2018", "2014 - 2016"), added up with overlaps
  counted once, so two jobs at the same time don't double your years. Only
  the experience section counts when the resume has one (education, projects,
  and the like don't); without one, every range outside education does. A
  range given in years only counts from January of the first to December of
  the last. If there are no dates at all, a "10+ years of experience" in the
  text is used instead.
* **Skills**: every skill in ``skill_catalog.SKILL_CATALOG`` or on your own
  list that the resume mentions, with how often, and **years per skill**: the
  time covered by the jobs whose entries mention it (overlaps counted once).
  A skill only named in a Skills section has no years. Each also gets a
  **level**, 1-5 stars like the Skills page's, with the reason
  (``skill_levels.py``).

``resume_ai.py`` reads the same things with a language model and builds its
``ResumeAnalysis`` with ``build_analysis`` here, so both readings add years up
the same way and look the same on the dashboard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Literal, Mapping

from search_skills import DEFAULT_PROFICIENCY
from skill_catalog import CUSTOM_CATEGORY, CatalogSkill, Vocabulary
from skill_levels import IMPLIED_BY, Evidence, infer_level, stated_level, stated_skill_years

Method = Literal["parse", "ai"]
METHODS: tuple[str, ...] = ("parse", "ai")

# --- Dates ---------------------------------------------------------------------------

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
SEASONS = {"spring": 3, "summer": 6, "fall": 9, "autumn": 9, "winter": 12}
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_SEASON = r"(?:spring|summer|fall|autumn|winter)"
_YEAR = r"(?:19[5-9]\d|20\d\d)"
_DATE = (
    rf"(?:(?:{_MONTH}|{_SEASON}),?\s+{_YEAR}"  # Jan 2020, September, 2019, Summer 2018
    rf"|(?:0?[1-9]|1[0-2])(?:\s*[/.]\s*|-){_YEAR}"  # 01/2020, 1.2020, 01-2020
    rf"|{_YEAR}[/-](?:0[1-9]|1[0-2])(?!\d)"  # 2020-01
    rf"|{_YEAR})"  # 2020
)
_PRESENT = r"(?:present|current(?:ly)?|now|today|ongoing|(?:to\s+)?date)"
_SEPARATOR = r"(?:\s*[-–—‒―−~]+\s*|\s+(?:to|through|thru|until|till)\s+)"
DATE_RANGE = re.compile(
    rf"(?<![\w/.])(?P<start>{_DATE}){_SEPARATOR}(?P<end>{_DATE}|{_PRESENT})(?![\w/])",
    re.IGNORECASE,
)
# "10+ years of experience", "over 8 years' professional experience".
STATED_YEARS = re.compile(
    r"(?<!\d)(\d{1,2})\s*\+?\s*(?:years?|yrs?)['’]?\.?\s+(?:of\s+)?(?:[\w/.+#-]+\s+){0,3}?(?:experience|exp\b)",
    re.IGNORECASE,
)
# Anything more is not a career.
MAX_STATED_YEARS = 50


def month_index(year: int, month: int) -> int:
    """Months since year 0, so ranges are easy to add up."""
    return year * 12 + month - 1


def month_label(index: int) -> str:
    """``2024-03`` for a month index."""
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def parse_month(value: str) -> int | None:
    """A month index for ``YYYY-MM`` (or ``YYYY``, meaning January), else None."""
    match = re.fullmatch(r"\s*(19\d\d|20\d\d)(?:-(0[1-9]|1[0-2]))?\s*", value or "")
    if not match:
        return None
    return month_index(int(match.group(1)), int(match.group(2) or 1))


def _date_parts(text: str) -> tuple[int, int | None]:
    """(year, month) of one date; month None when only the year is given."""
    text = text.strip().lower()
    year = int(re.search(_YEAR, text).group())  # type: ignore[union-attr]
    word = re.match(r"[a-z]+", text)
    if word:
        name = word.group()
        return year, SEASONS.get(name) or MONTHS[name[:3]]
    numbers = [int(n) for n in re.findall(r"\d+", text)]
    if len(numbers) == 2:
        month = numbers[1] if numbers[0] == year else numbers[0]
        return year, month
    return year, None


@dataclass(frozen=True)
class DateRange:
    start: int  # month index, inclusive
    end: int | None  # month index, inclusive; None: still there
    text: str

    def last_month(self, today: int) -> int:
        return today if self.end is None else min(self.end, today)


def find_date_ranges(text: str) -> list[tuple[re.Match[str], DateRange | None]]:
    """Every date range in the text, each with its ``DateRange`` (None when
    it makes no sense: ends before it starts)."""
    found = []
    for match in DATE_RANGE.finditer(text):
        year, month = _date_parts(match.group("start"))
        start = month_index(year, month or 1)
        end_text = match.group("end")
        if re.fullmatch(_PRESENT, end_text.strip(), re.IGNORECASE):
            end = None
        else:
            end_year, end_month = _date_parts(end_text)
            end = month_index(end_year, end_month or 12)
        valid = end is None or end >= start
        found.append((match, DateRange(start, end, match.group().strip()) if valid else None))
    return found


def merged_months(ranges: Iterable[tuple[int, int]]) -> int:
    """Months covered by inclusive (start, end) ranges, overlaps counted once."""
    total = 0
    current: list[int] | None = None
    for start, end in sorted(ranges):
        if current and start <= current[1] + 1:
            current[1] = max(current[1], end)
            continue
        if current:
            total += current[1] - current[0] + 1
        current = [start, end]
    if current:
        total += current[1] - current[0] + 1
    return total


def years_from_months(months: int) -> float:
    return round(months / 12, 1)


def stated_years(text: str) -> int | None:
    """The most years of experience the text claims ("8+ years of experience"), or None."""
    years = [int(n) for n in STATED_YEARS.findall(text) if 0 < int(n) <= MAX_STATED_YEARS]
    return max(years) if years else None


# --- Sections ------------------------------------------------------------------------

SectionKind = Literal["experience", "education", "skills", "other", "top"]
_HEADINGS: tuple[tuple[SectionKind, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(rf"(?:{pattern})", re.IGNORECASE))
    for kind, pattern in (
        ("experience", r"(?:(?:professional|work|relevant|employment|career|industry|technical|"
                       r"engineering|software|selected|additional|other|related)\s+)*"
                       r"(?:experience|employment|work history|employment history|career history|"
                       r"professional history|positions held|work)(?:\s+history)?"),
        ("education", r"education(?:al background)?|academic (?:background|history)|"
                      r"education (?:and|&) (?:training|certifications?)|degrees?"),
        ("skills", r"(?:(?:technical|core|key|relevant|professional|software|it)\s+)?"
                   r"(?:skills|competencies|technologies|tech stack|tools|expertise|proficiencies)"
                   r"(?:\s+(?:and|&)\s+(?:tools|technologies|expertise|abilities|certifications))?|"
                   r"skills summary|technical summary|areas of expertise"),
        ("other", r"(?:(?:personal|side|selected|academic|key|notable|technical|open source|relevant)\s+)?"
                  r"projects?|certifications?(?:\s+(?:and|&)\s+(?:licenses|awards|training))?|licenses|"
                  r"(?:professional\s+)?summary|profile|professional profile|objective|about me|awards?|"
                  r"honors?(?:\s+(?:and|&)\s+awards)?|volunteer(?:ing| experience| work)?|publications?|"
                  r"interests|hobbies|languages|references|leadership|activities|"
                  r"affiliations|memberships|training|courses|coursework"),
    )
)
MAX_HEADING_LENGTH = 40


def heading_kind(line: str) -> SectionKind | None:
    """The kind of section a line starts, if it's a heading ("WORK EXPERIENCE",
    "Technical Skills:", "— Education —"), else None."""
    if len(line.strip()) > MAX_HEADING_LENGTH:
        return None
    words = re.sub(r"[^A-Za-z&/ ]+", " ", line)
    words = re.sub(r"\s+", " ", words.replace("/", " & ")).strip()
    if not words:
        return None
    for kind, pattern in _HEADINGS:
        if pattern.fullmatch(words):
            return kind
    return None


@dataclass(frozen=True)
class Section:
    kind: SectionKind
    heading: str
    lines: tuple[str, ...]  # the section's lines, without its heading
    first_line: int  # index of lines[0] in the whole text


def split_sections(text: str) -> list[Section]:
    """The resume's sections, in order. Lines before the first heading (name,
    contact details, often a summary) are a "top" section."""
    lines = text.splitlines()
    sections: list[Section] = []
    kind: SectionKind = "top"
    heading = ""
    start = 0
    for index, line in enumerate(lines):
        found = heading_kind(line)
        if found is None:
            continue
        sections.append(Section(kind, heading, tuple(lines[start:index]), start))
        kind, heading, start = found, line.strip(), index + 1
    sections.append(Section(kind, heading, tuple(lines[start:]), start))
    return [section for section in sections if section.heading or any(l.strip() for l in section.lines)]


# --- The analysis ---------------------------------------------------------------------


@dataclass(frozen=True)
class Position:
    """One job in your work history."""

    title: str
    company: str
    start: int  # month index
    end: int | None  # month index; None: current
    skills: tuple[str, ...] = ()

    def months(self, today: int) -> int:
        last = today if self.end is None else min(self.end, today)
        return max(0, last - self.start + 1)

    def as_document(self, today: int) -> dict[str, Any]:
        return {
            "title": self.title,
            "company": self.company,
            "start": month_label(self.start),
            "end": month_label(self.end) if self.end is not None else None,
            "months": self.months(today),
            "skills": list(self.skills),
        }


@dataclass(frozen=True)
class DetectedSkill:
    name: str
    category: str
    # Time covered by the positions that mention it, overlaps counted once;
    # None when no position does (only listed under Skills, say).
    years: float | None
    # Times the resume mentions it; 0 when the AI inferred it.
    mentions: int
    # The most recent position that mentions it: "present", "YYYY-MM", or None.
    last_used: str | None
    # Other spellings, so the dashboard can tell it's already on your list
    # as "ReactJS".
    aliases: tuple[str, ...] = ()
    # How well you know it, 1-5 stars, and why (skill_levels.py).
    level: int = DEFAULT_PROFICIENCY
    level_reason: str = ""

    def as_document(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "years": self.years,
            "mentions": self.mentions,
            "last_used": self.last_used,
            "aliases": list(self.aliases),
            "level": self.level,
            "level_reason": self.level_reason,
        }


YearsBasis = Literal["positions", "stated"]


@dataclass(frozen=True)
class ResumeAnalysis:
    method: Method
    # Professional experience in years (one decimal), or None if the resume
    # doesn't say; ``years_basis`` says where it came from.
    years_experience: float | None
    years_basis: YearsBasis | None
    # What the resume itself claims ("10+ years of experience"), if anything.
    stated_years: int | None
    skills: tuple[DetectedSkill, ...]
    positions: tuple[Position, ...]
    notes: tuple[str, ...] = ()
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # The AI that read it (None for parsing).
    provider: str | None = None
    model: str | None = None

    def as_document(self) -> dict[str, Any]:
        today = _today_index(self.analyzed_at.date())
        return {
            "method": self.method,
            "years_experience": self.years_experience,
            "years_basis": self.years_basis,
            "stated_years": self.stated_years,
            "skills": [skill.as_document() for skill in self.skills],
            "positions": [position.as_document(today) for position in self.positions],
            "notes": list(self.notes),
            "analyzed_at": self.analyzed_at,
            "provider": self.provider,
            "model": self.model,
        }


def _today_index(today: date) -> int:
    return month_index(today.year, today.month)


def _skill_years(positions: Iterable[Position], today: int) -> tuple[float | None, str | None]:
    spans = [(p.start, today if p.end is None else min(p.end, today)) for p in positions]
    spans = [(start, end) for start, end in spans if end >= start]
    if not spans:
        return None, None
    last = max(end for _, end in spans)
    ongoing = any(p.end is None or p.end >= today for p in positions)
    return years_from_months(merged_months(spans)), "present" if ongoing else month_label(last)


def _inferred_level(
    skill: CatalogSkill, positions: list[Position], today: int, text: str, mentions: int, skills_section: str
) -> tuple[int, str]:
    """skill_levels.infer_level with this resume's evidence for ``skill``."""
    builds_on = IMPLIED_BY.get(skill.name, ())
    used_in = [p for p in positions if skill.name in p.skills or any(name in p.skills for name in builds_on)]
    years, last_used = _skill_years(used_in, today)
    through = tuple(dict.fromkeys(
        name for p in used_in if skill.name not in p.skills for name in p.skills if name in builds_on
    ))
    return infer_level(Evidence(
        years=years,
        mentions=mentions,
        jobs=len(used_in),
        in_title=any(skill.found_in(p.title) for p in positions),
        months_since_used=None if last_used is None
        else 0 if last_used == "present" else today - (parse_month(last_used) or today),
        has_work_history=bool(positions),
        stated=stated_level(text, skill),
        stated_years=stated_skill_years(text, skill),
        through=through,
        in_skills_section=skill.found_in(skills_section),
    ))


def build_analysis(
    method: Method,
    text: str,
    positions: list[Position],
    skill_names: Iterable[str],
    vocabulary: Vocabulary,
    *,
    notes: Iterable[str] = (),
    now: datetime | None = None,
    provider: str | None = None,
    model: str | None = None,
    categories: Mapping[str, str] | None = None,
    levels: Mapping[str, tuple[int, str]] | None = None,
) -> ResumeAnalysis:
    """Put a reading of a resume together: total years from ``positions``
    (or what the text states, if there are none), and each skill's years from
    the positions that list it. ``skill_names`` are every skill found, in any
    spelling; positions' skills are included automatically. Names are mapped
    onto the catalog ("ReactJS" -> "React") and repeats merged. ``categories``
    (by lowercase name) categorize skills that aren't in the catalog.
    ``levels`` (by lowercase name: stars and why) are the AI's; every other
    skill's level is inferred by skill_levels.infer_level."""
    now = now or datetime.now(timezone.utc)
    today = _today_index(now.date())
    notes = list(notes)

    # One entry per skill, in the order first named.
    resolved: dict[str, CatalogSkill] = {}
    for name in [*skill_names, *(s for p in positions for s in p.skills)]:
        if not name or not name.strip():
            continue
        skill = vocabulary.resolve(name)
        resolved.setdefault(skill.name.lower(), skill)
    positions = [
        Position(p.title, p.company, p.start, p.end,
                 tuple(dict.fromkeys(vocabulary.resolve(s).name for s in p.skills if s.strip())))
        for p in positions
    ]

    skills_section = "\n".join(
        line for section in split_sections(text) if section.kind == "skills" for line in section.lines
    )
    skills = []
    for skill in resolved.values():
        used_in = [p for p in positions if skill.name in p.skills]
        years, last_used = _skill_years(used_in, today)
        mentions = skill.count(text)
        given = (levels or {}).get(skill.name.lower())
        if given is None:
            given = _inferred_level(skill, positions, today, text, mentions, skills_section)
        skills.append(DetectedSkill(
            name=skill.name,
            category=(categories or {}).get(skill.name.lower(), skill.category)
            if skill.category == CUSTOM_CATEGORY else skill.category,
            years=years,
            mentions=mentions,
            last_used=last_used,
            aliases=tuple(s for s in skill.spellings if s != skill.name),
            level=given[0],
            level_reason=given[1],
        ))
    # Best known first, then most experience, then most mentioned; ties keep their order.
    skills.sort(key=lambda s: (-s.level, -(s.years or 0), -s.mentions))

    spans = [(p.start, today if p.end is None else min(p.end, today)) for p in positions]
    months = merged_months((start, end) for start, end in spans if end >= start)
    stated = stated_years(text)
    if months:
        years: float | None = years_from_months(months)
        basis: YearsBasis | None = "positions"
        if stated is not None and abs(stated - years) >= 2:
            notes.append(f"The resume mentions {stated} years of experience; the dates in its work "
                         f"history add up to {years:g}.")
    elif stated is not None:
        years, basis = float(stated), "stated"
        notes.append("No dates found in the work history, so the years are the ones the resume states.")
    else:
        years, basis = None, None
        notes.append("No dates found in the work history, so years of experience couldn't be worked out.")

    positions.sort(key=lambda p: (p.end is not None, -(p.end or 0), -p.start))
    return ResumeAnalysis(
        method=method,
        years_experience=years,
        years_basis=basis,
        stated_years=stated,
        skills=tuple(skills),
        positions=tuple(positions),
        notes=tuple(dict.fromkeys(notes)),
        analyzed_at=now,
        provider=provider,
        model=model,
    )


# --- Parsing -------------------------------------------------------------------------

# A header line (title, company, location) is short, isn't a bullet point or
# a sentence, and isn't a "Tech: ..." line.
MAX_HEADER_LINE = 90
# Dates on a longer line are in a paragraph, not a job's header.
MAX_DATE_LINE = 200
_BULLET = re.compile(r"^\s*(?:[-*•·▪●◦‣–]|\d+[.)])\s+")
_HEADER_JUNK = re.compile(r"^[\s|,–—\-•·:()]+|[\s|,–—\-•·:()]+$")


def _is_header_line(line: str) -> bool:
    stripped = line.strip()
    return (
        bool(stripped)
        and len(stripped) <= MAX_HEADER_LINE
        and not _BULLET.match(line)
        and not stripped.endswith(".")
        and ":" not in stripped
    )


def _header_text(lines: list[str]) -> str:
    """ "Senior Engineer · Acme Corp · Austin, TX" from a job's header lines."""
    parts = [_HEADER_JUNK.sub("", re.sub(r"\s{2,}|\t", " · ", line)) for line in lines]
    parts = [re.sub(r"\s*[|•·]\s*", " · ", part) for part in parts if part]
    return re.sub(r"(?: · )+", " · ", " · ".join(parts)).strip(" ·")


def _work_history(sections: list[Section]) -> tuple[list[Section], str | None]:
    """The sections whose dates count, and a note about how they were chosen."""
    experience = [s for s in sections if s.kind == "experience"]
    if experience:
        return experience, None
    counted = [s for s in sections if s.kind not in ("education", "skills", "other")]
    return counted, (
        "No work experience heading found, so every date range outside education, "
        "skills, and projects was counted."
    )


def _date_lines(lines: list[str]) -> list[tuple[int, re.Match[str], DateRange | None]]:
    """(line index, match, range) for the job dates in a section: ranges on
    header lines, not in bullet points ("migrated it 2019-2020") or paragraphs."""
    found = []
    for index, line in enumerate(lines):
        if _BULLET.match(line) or len(line.strip()) > MAX_DATE_LINE:
            continue
        found += [(index, match, span) for match, span in find_date_ranges(line)]
    return found


def parse_positions(text: str, vocabulary: Vocabulary, today: int) -> tuple[list[Position], list[str]]:
    """The jobs in the resume's work history, each with the skills its entry mentions."""
    sections, note = _work_history(split_sections(text))
    notes = [note] if note else []
    positions: list[Position] = []
    skipped: list[str] = []
    for section in sections:
        lines = list(section.lines)
        found = _date_lines(lines)
        # An entry starts at its date line, or at the (up to two) title and
        # company lines just above it, and runs until the next entry starts.
        starts: list[int] = []
        floor = 0
        for index, _match, _span in found:
            start = index
            while start > floor and index - start < 2 and _is_header_line(lines[start - 1]):
                start -= 1
            starts.append(start)
            floor = index + 1
        for number, (index, match, span) in enumerate(found):
            if span is None or span.start > today:
                skipped.append(match.group().strip())
                continue
            following = starts[number + 1] if number + 1 < len(found) else len(lines)
            entry = lines[starts[number]:max(following, index + 1)]
            date_line = lines[index]
            title = _header_text(lines[starts[number]:index] + [date_line[:match.start()], date_line[match.end():]])
            if not title and index + 1 < len(lines) and _is_header_line(lines[index + 1]) \
                    and not find_date_ranges(lines[index + 1]):
                # The dates come first, the title on the next line.
                title = _header_text([lines[index + 1]])
            positions.append(Position(
                title=title[:200],
                company="",
                start=span.start,
                # A range ending this month or later ("2022 - 2026") is current.
                end=span.end if span.end is not None and span.end < today else None,
                skills=tuple(vocabulary.find("\n".join(entry))),
            ))
    if skipped:
        notes.append(f"Skipped dates that don't make sense: {', '.join(dict.fromkeys(skipped))}.")
    return positions, notes


def parse_resume(
    text: str,
    your_skills: Iterable[str] = (),
    now: datetime | None = None,
) -> ResumeAnalysis:
    """Read a resume's skills and years of experience from its text (see the
    module docstring). ``your_skills`` (your skill list) are looked for too,
    on top of the catalog."""
    now = now or datetime.now(timezone.utc)
    vocabulary = Vocabulary.with_your_skills(your_skills)
    positions, notes = parse_positions(text, vocabulary, _today_index(now.date()))
    return build_analysis("parse", text, positions, vocabulary.find(text), vocabulary, notes=notes, now=now)
