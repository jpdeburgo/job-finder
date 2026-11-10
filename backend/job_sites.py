"""Job sites the search can scan, all behind one small interface.

Every URL in ``job_boards.JOB_SEARCH_URLS`` is turned into a ``JobSite`` by
``resolve_job_site``. A site knows how to page through keyword search results
(``fetch_page``) and how to load one posting's full description
(``fetch_details``), and hands back ``Posting`` objects with the same fields
no matter where they came from. ``job_search`` runs its filters and skill
scoring on those, so it doesn't need to know which site a job came from.

Most careers pages render their listings in the browser (Insight Global and
Accenture both do), so their HTML has no jobs in it. The data comes from a
JSON API behind the page, and usually that API belongs to a hosted applicant
tracking system (ATS) that many companies share. So a site resolves to one of:

* ``InsightGlobalSite``: Insight Global's own job API.
* ``WorkdaySite``: any ``<tenant>.wdN.myworkdayjobs.com`` board (Accenture,
  and many other large employers).
* ``GreenhouseSite``: any ``boards.greenhouse.io/<company>`` board.
* ``LeverSite``: any ``jobs.lever.co/<company>`` board.

A careers page on the company's own domain is matched to its ATS board
through ``KNOWN_CAREER_SITES``. If the page isn't listed there, the resolver
looks for an ATS board link in the page's HTML.
"""

from __future__ import annotations

import dataclasses
import html
import re
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import parse_qs, urljoin, urlparse

import requests

REQUEST_TIMEOUT_SECONDS = 20
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


class UnsupportedSiteError(ValueError):
    """Raised when a URL can't be mapped to any job source we can read."""


@dataclass(frozen=True)
class KnownCareerSite:
    name: str
    board_url: str


# Careers pages on a company's own domain, mapped to the ATS board that
# serves their jobs. These pages load their listings client-side, so the
# board can't always be found by reading the page's HTML. Keyed by hostname;
# add a line here when you add a company whose page the resolver can't work
# out on its own.
KNOWN_CAREER_SITES: dict[str, KnownCareerSite] = {
    # www.accenture.com/us-en/careers/jobsearch gets its results from Accenture's
    # Workday tenant, the same board its "Apply" buttons link to.
    "www.accenture.com": KnownCareerSite(
        "Accenture", "https://accenture.wd103.myworkdayjobs.com/AccentureCareers"
    ),
}


@dataclass(frozen=True)
class Posting:
    """One job listing, in the same shape for every site.

    ``is_remote`` is ``None`` and ``job_type`` is ``""`` when the search results
    don't say. ``fetch_details`` may fill them in.
    """

    job_id: str
    title: str
    url: str
    company: str
    city: str = ""
    state: str = ""
    is_remote: bool | None = None
    job_type: str = ""
    salary_low: float = 0.0
    salary_high: float = 0.0
    # Anything ``job_search._parse_posted_date`` understands: an ISO date or
    # timestamp. Empty when the site doesn't say.
    posted_date: str = ""
    # ``None`` until ``fetch_details`` has loaded it (some sites include it in
    # the search results).
    description: str | None = None
    # Site-specific handle for ``fetch_details`` (e.g. a Workday job path).
    detail_key: str = ""
    # Why the site's data says the job isn't remote, when a field other than
    # its main remote flag says so (e.g. 'workType = "Onsite"').
    remote_note: str = ""


@dataclass(frozen=True)
class SearchPage:
    postings: list[Posting]
    has_more: bool


# --- Shared helpers ---------------------------------------------------------------

_LOG_LOCK = threading.Lock()


def log(message: str) -> None:
    """Print one whole line. Sites are searched on parallel threads, and a
    plain print() writes the text and the newline separately, so two threads'
    lines can run together."""
    with _LOG_LOCK:
        sys.stdout.write(f"{message}\n")
        sys.stdout.flush()


BLOCK_TAG_PATTERN = re.compile(
    r"<\s*(?:br|/p|/li|li|/div|/h[1-6]|/tr|/ul|/ol|p|div|h[1-6]|tr|ul|ol)\b[^>]*>", re.IGNORECASE
)


def html_to_text(value: Any, keep_lines: bool = False) -> str:
    """Flatten an HTML job description to plain text.

    With ``keep_lines``, paragraphs, list items, and line breaks stay on
    their own lines, so a line that just says "Onsite" or "Hybrid - Plano, TX"
    can be told apart from "onsite" in the middle of a sentence.
    """
    source = str(value or "")
    if not keep_lines:
        return re.sub(r"\s+", " ", html.unescape(HTML_TAG_PATTERN.sub(" ", source))).strip()
    text = html.unescape(HTML_TAG_PATTERN.sub(" ", BLOCK_TAG_PATTERN.sub("\n", source)))
    lines = (re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def contains_phrase(text: str, phrase: str) -> bool:
    """Match whole words/phrases so that Java does not match JavaScript."""
    pattern = rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def split_location(text: str) -> tuple[str, str]:
    """Split "Austin, TX" into ("Austin", "TX"). Anything else stays in the city."""
    parts = [part.strip() for part in str(text or "").split(",")]
    if len(parts) == 2 and all(parts):
        return parts[0], parts[1]
    return str(text or "").strip(), ""


def _mentions_remote(*values: Any) -> bool:
    return any(contains_phrase(str(value or ""), "remote") for value in values)


NOT_REMOTE_WORDS = ("hybrid", "on-site", "onsite", "on site", "in-office", "in office")


def remote_from_text(text: Any) -> bool | None:
    """Read remote status from free text such as a location ("Remote - US",
    "Denver, CO (Hybrid)"): True, False, or None when it doesn't say."""
    value = str(text or "")
    if any(contains_phrase(value, word) for word in NOT_REMOTE_WORDS):
        return False
    return True if contains_phrase(value, "remote") else None


# --- Postings that say they're on-site or hybrid -----------------------------------
#
# Sites' remote flags are often wrong: Insight Global marks jobs "remote" whose
# posting says "Onsite in Dallas", and a Greenhouse location of "Remote - US"
# can sit above "This role is hybrid, 3 days a week in our NYC office". So the
# title, location, and description are read for an explicit statement. Only
# clear ones count: benefits ("on-site gym"), occasional visits ("travel
# onsite quarterly"), choices ("remote or hybrid"), and tech ("Hybrid Cloud")
# don't.

_ONSITE = r"(?:on[- ]?site|onsite|in[- ]office|in[- ]person)"
_ONSITE_OR_HYBRID = rf"(?:{_ONSITE}|hybrid)"
_OFFICE_PLACE = (
    r"(?:in the office|into the office|in office|"
    r"(?:to|into|at|in)\s+(?:the|our|an?)\s+(?:\w+\s+)?"
    r"(?:office|offices|headquarters|hq|facility|campus|site|location))"
)
_WEEKLY = r"(?:\s*(?:a|per|each|every|/|x)\s*(?:week|wk))?"
_NOT_MONTHLY = r"(?!\s*(?:a|per|each|every|/)\s*(?:month|quarter|year))"
# Words after "onsite" that make it describe something else ("onsite teams").
# A label answered in the negative: "Onsite: No", "Hybrid - N/A".
_NOT_NEGATED = r"(?!\s*(?:no|none|n/?a|not|never|optional)\b)"
_NOT_ABOUT_YOU = (
    r"(?!\s+(?:teams?|staff|colleagues|employees|personnel|support|customers?|clients?|"
    r"partners?|engineers?|technicians?|resources?|counterparts|stakeholders|users|events?|"
    r"meetings?|visits?|interviews?|training|gym|cafeteria|amenities|parking|childcare|"
    r"health|clinic|services?|equipment|hardware|installations?|deployments?)\b)"
)
ONSITE_DESCRIPTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # "100% onsite", "fully in-office"
        rf"\b(?:100\s*%|fully|entirely|completely|strictly)\s+{_ONSITE}\b{_NOT_ABOUT_YOU}",
        # "Onsite in Atlanta", "hybrid at our Dallas office", "in-office in NYC"
        rf"\b{_ONSITE_OR_HYBRID}\s+(?:in|at)\s+(?:our\s+|the\s+)?(?-i:[A-Z])",
        # "Onsite - Plano, TX", "ONSITE: Dallas" (but not "Onsite - Remote")
        rf"\b{_ONSITE}\s*[-–:]{_NOT_NEGATED}\s*(?!remote)(?-i:[A-Z])",
        # "(Hybrid)", "(onsite 3 days)", "(100% Onsite)"
        rf"\(\s*(?:100\s*%\s*|fully\s+)?{_ONSITE_OR_HYBRID}\b(?![^)]*(?:remote|\bno\b|\bnot\b|optional))"
        r"[^)]{0,40}\)",
        # "must be onsite", "will sit onsite in Plano", "must be local to Atlanta and onsite",
        # "expected to report to our Austin office" (but not "work with onsite teams")
        r"\b(?:must|will|would|shall|required to|expected to|needs? to|have to|has to|"
        r"will need to|will be required to|will be expected to|requires you to)\s+"
        r"(?:\w+ly\s+)?(?:be able to\s+)?(?:be|sit|work|report|come|commute|go)\s+"
        rf"(?:[\w,]+\s+){{0,4}}?(?:{_ONSITE}|on site|{_OFFICE_PLACE})\b{_NOT_ABOUT_YOU}",
        # "onsite 3x a week"
        rf"\b{_ONSITE}\s*[(:\-–]?\s*\d\s*x{_WEEKLY}{_NOT_MONTHLY}",
        # "Schedule: Onsite", "Work environment - Hybrid", "Remote status: Onsite"
        r"\b(?:schedule|setting|environment|arrangement|remote status|work status)\s*[:\-–]\s*"
        rf"(?:100%\s+|fully\s+)?{_ONSITE_OR_HYBRID}\b",
        # "This role is onsite", "The position will be 100% in-office", "Position is hybrid"
        r"(?:\b(?:this|the)\s+|^|(?<=[.:;!\n]\s))(?:role|position|job|opportunity|contract|assignment|engagement)\s+"
        r"(?:is|will be|is going to be)\s+(?:an?\s+)?(?:100%\s+|fully\s+|primarily\s+|strictly\s+)?"
        rf"{_ONSITE_OR_HYBRID}\b",
        # "a hybrid position", "onsite role", "requires onsite presence", "hybrid schedule"
        rf"\b{_ONSITE_OR_HYBRID}\s+(?:role|position|job|opportunity|contract|assignment|"
        r"schedule|requirement|presence|work\s+(?:model|schedule|arrangement|environment))\b",
        # "must be onsite", "required to work in the office", "expected to report to our Austin office"
        r"\b(?:must|required to|requirement to|expected to|needs? to|will need to|"
        r"will be required to|will be expected to|requires you to)\s+(?:\w+\s+){0,4}?"
        rf"(?:{_ONSITE}|on site|{_OFFICE_PLACE})\b",
        # "3 days onsite", "2-3 days a week in office", "4x/week in the office"
        rf"\b\d\s*(?:(?:-|to|or)\s*\d\s*)?(?:days?|x){_WEEKLY}\s*(?:{_ONSITE}|on site|{_OFFICE_PLACE})\b",
        # "onsite 3 days a week", "in office: 2 days" (but not "onsite 2 days a month")
        rf"\b(?:{_ONSITE}|in the office|in office)\s*[(:\-–]?\s*\d\s*(?:(?:-|to|or)\s*\d\s*)?"
        rf"days?{_WEEKLY}\b{_NOT_MONTHLY}",
        # "Work arrangement: Hybrid", "Location type - Onsite", "Location: On-site (Dallas)"
        r"\b(?:work(?:place)?|location|job|employment|position)\s*"
        r"(?:type|model|arrangement|setting|style|location)?\s*[:\-–]\s*(?:100%\s+|fully\s+)?"
        rf"{_ONSITE_OR_HYBRID}\b",
    )
)
# Statements that the job is not remote; read as-is, with no softening.
NOT_REMOTE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bnot\s+(?:an?\s+)?(?:fully\s+|100%\s+)?remote\b(?!\s*-?\s*first)",
        r"\bno\s+remote\s+(?:work|option|options|opportunity|candidates|applicants)\b",
        r"\bnon[- ]remote\b",
        r"\bremote\s+(?:work\s+)?(?:is\s+)?not\s+(?:available|an option|possible|offered|permitted|allowed|supported)\b",
        r"\bnot\s+(?:eligible|open|available)\s+(?:for|to)\s+(?:fully\s+)?remote\b",
        r"\bremote\s+(?:candidates|applicants|workers)\s+(?:will\s+not|won't|cannot|can't)\s+be\s+considered\b",
        # "Remote: No" (a label, so a colon; "remote - no onsite" is the opposite)
        r"\bremote\s*(?:work|option|eligible|eligibility|possible|available|allowed|opportunity)?\s*\??\s*:\s*no\b",
        # "No remote." / "NO REMOTE!" on its own
        r"\bno\s+remote\b(?=\s*(?:[.!,;)]|$))",
    )
)
# A line that is nothing but a work-arrangement label: "Onsite",
# "ONSITE - Plano, TX", "Hybrid (3 days in office)", "100% Onsite in Atlanta".
# A short line ending in one: "Location: Dallas, TX - Onsite", "Plano, TX | Hybrid".
ONSITE_LINE_END = re.compile(
    rf"[-–|/:]\s*(?:100\s*%\s*|fully\s+)?{_ONSITE_OR_HYBRID}\s*[.!]?\s*$",
    re.IGNORECASE,
)
# ...when the line is a location or a label, not a list of skills.
_LOCATION_LIKE = re.compile(
    r"(?i:\b(?:location|work|site|setting|schedule|type|arrangement)\b)|,\s*[A-Z]{2}\b"
)
ONSITE_LABEL_LINE = re.compile(
    rf"^[\W_]*(?:work\s*(?:type|model|arrangement|location|setting)\s*[:\-–]\s*)?"
    rf"(?:100\s*%\s*|fully\s+)?{_ONSITE_OR_HYBRID}\s*"
    rf"(?:$|[-–:(,|/]{_NOT_NEGATED}\s*(?!remote)|\s+(?:in|at)\s+(?-i:[A-Z])|\s+\d)",
    re.IGNORECASE,
)
# Words near a match that make it something other than a requirement.
_SOFTENING_BEFORE = re.compile(
    r"\b(?:no|not|never|without|occasional(?:ly)?|periodic(?:ally)?|sometimes|rare(?:ly)?|"
    r"optional(?:ly)?|may|might|could|limited|minimal|infrequent(?:ly)?|if needed|as needed|"
    r"when needed|if required|as required|quarterly|monthly|annual(?:ly)?|once a|travel|"
    r"visits?|interviews?|onboarding|training|orientation|meetings?|events?|offsites?|"
    r"first (?:day|week)|remote\s*(?:or|/|and/or))\b",
    re.IGNORECASE,
)
_SOFTENING_AFTER = re.compile(
    r"^\W{0,3}(?:[^.;!?]{0,40}?\b(?:optional|as needed|if needed|when needed|occasionally|"
    r"for (?:onboarding|training|orientation|meetings|interviews|events)|"
    r"(?:once|twice|\d+\s*(?:times|days?|x))\s*(?:a|per|each|every|/)\s*(?:month|quarter|year))\b|"
    r"\s*(?:or|/|and/or)\s*(?:fully\s+|100%\s+)?remote\b)",
    re.IGNORECASE,
)
# "Hybrid" followed by one of these is tech, not a work arrangement.
HYBRID_TECH_WORDS = {
    "cloud", "clouds", "multicloud", "multi-cloud", "app", "apps", "mobile", "application",
    "applications", "it", "infrastructure", "integration", "integrations", "environment",
    "environments", "network", "networks", "networking", "system", "systems", "model", "models",
    "architecture", "architectures", "solution", "solutions", "search", "storage", "data",
    "database", "databases", "framework", "frameworks", "approach", "methodology", "agile",
    "development", "ai", "ml", "deployment", "deployments",
}
_TITLE_ONSITE = re.compile(rf"(?<![A-Za-z]){_ONSITE}(?![A-Za-z])", re.IGNORECASE)
_HYBRID_WORD = re.compile(r"(?<![A-Za-z])hybrid(?![A-Za-z])(?:[\s/-]+([A-Za-z-]+))?", re.IGNORECASE)


def _hybrid_means_tech(text: str) -> bool:
    """True when every "hybrid" in ``text`` is followed by a tech word ("Hybrid Cloud")."""
    words = [(match.group(1) or "").lower() for match in _HYBRID_WORD.finditer(text)]
    return bool(words) and all(word in HYBRID_TECH_WORDS for word in words)


def _sentence_around(text: str, start: int, end: int) -> tuple[str, str]:
    """Up to 60 characters before and after a match, cut at sentence ends."""
    before = re.split(r"[.!?;\n•]", text[max(0, start - 60):start])[-1]
    after = re.split(r"[.!?;\n•]", text[end:end + 60])[0]
    return before, after


def _snippet(text: str, start: int, end: int) -> str:
    before, after = _sentence_around(text, start, end)
    return re.sub(r"\s+", " ", f"{before[-25:]}{text[start:end]}{after[:25]}").strip()


def onsite_evidence(title: str, description: str | None = "", location: str = "") -> str | None:
    """Return why a posting reads as on-site or hybrid, or None if it doesn't say so.

    The result is a short quote for logs and the job's ``not_remote_reason``,
    e.g. 'title says "On-Site"' or 'description: "must be onsite in Dallas"'.
    """
    title = str(title or "")
    # A title naming both ("Remote/Onsite", "Remote or Hybrid") is a choice.
    if not contains_phrase(title, "remote"):
        onsite = _TITLE_ONSITE.search(title)
        if onsite:
            return f'title says "{onsite.group(0)}"'
        if _HYBRID_WORD.search(title) and not _hybrid_means_tech(title):
            return 'title says "Hybrid"'
    if remote_from_text(location) is False and not _hybrid_means_tech(location):
        return f'location says "{location.strip()}"'

    text = str(description or "")
    for line in text.split("\n"):
        if (
            len(line) <= 80
            and (
                ONSITE_LABEL_LINE.search(line)
                or (ONSITE_LINE_END.search(line) and _LOCATION_LIKE.search(line))
            )
            and not contains_phrase(line, "remote")
            and not _hybrid_means_tech(line)
            and not _SOFTENING_BEFORE.search(line)
        ):
            return f'description: "{line.strip()}"'
    for pattern in NOT_REMOTE_PATTERNS:
        match = pattern.search(text)
        if match:
            return f'description: "{_snippet(text, match.start(), match.end())}"'
    for pattern in ONSITE_DESCRIPTION_PATTERNS:
        for match in pattern.finditer(text):
            matched = match.group(0)
            before, after = _sentence_around(text, match.start(), match.end())
            if "hybrid" in matched.lower():
                following = text[match.start():match.end() + 30]
                if _hybrid_means_tech(following):
                    continue
            if _SOFTENING_BEFORE.search(f"{before} {matched}") or _SOFTENING_AFTER.search(after):
                continue
            # "work in person with stakeholders" is about meeting people, not where you work.
            if re.search(r"in[- ]person$", matched, re.IGNORECASE) and re.match(r"\s+with\b", after):
                continue
            return f'description: "{_snippet(text, match.start(), match.end())}"'
    return None


# Field names that carry a work arrangement in a site's JSON: Insight Global's
# workRemote, "workType", "isHybrid", "locationType", "workplaceType", ...
WORKPLACE_FIELD = re.compile(
    r"remote|on_?site|hybrid|in_?office|in_?person|telecommut|telework|wfh|workplace|"
    r"work_?(?:type|setting|arrangement|model|location|style|mode|environment|schedule)|"
    r"location\W*_?type|job_?setting",
    re.IGNORECASE,
)


# A value that is nothing but a work arrangement, under any field name: a
# badge or tag like "Onsite", "HYBRID", "100% On-Site", "Remote".
ARRANGEMENT_VALUE = re.compile(
    r"^\s*(?:100\s*%\s*|fully\s+|only\s+)?"
    r"(on[- ]?site|onsite|hybrid|in[- ]office|in[- ]person|office[- ]based|"
    r"remote|telecommute|work from home|wfh)(?:\s+only)?\s*$",
    re.IGNORECASE,
)
IDENTIFIER_FIELD = re.compile(r"(?:^|_)id$|Id$|ID$|url$|Url$|URL$|link$|slug$|path$|Path$|title$|Title$", re.ASCII)
_REMOTE_WORDS = ("remote", "telecommut", "telework", "wfh", "work from home", "workfromhome")
_ONSITE_KEY_WORDS = ("hybrid", "onsite", "on_site", "inoffice", "in_office", "inperson")


def flag_value(value: Any) -> bool | None:
    """A yes/no flag as sites send it: True, "true", "Yes", "Y", 1 (None if it isn't one)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("yes", "true", "y", "1"):
            return True
        if lowered in ("no", "false", "n", "0"):
            return False
    return None


def structured_remote(payload: Any, skip: Iterable[str] = ()) -> tuple[bool | None, str]:
    """Read remote status from a site's JSON, outside its descriptions.

    Looks at fields named for the work arrangement (workType, isHybrid,
    remoteWork, workLocation.type, ...) and at any field whose whole value is
    one ("Onsite", ["Contract", "Hybrid"]). Returns ``(status, why)``: False
    with the field when any says on-site or hybrid (that wins), else True when
    one says remote, else ``(None, "")``. Long text is left to ``onsite_evidence``.
    """
    skipped = {name.lower() for name in skip}
    found_remote = ""

    def judge(path: str, name: str, item: Any) -> bool | None:
        lowered = name.lower()
        named = bool(WORKPLACE_FIELD.search(path))
        flag = flag_value(item)
        # A yes/no value only means something in a field named for it
        # ("isHybrid": true, "remoteWork": "No"); elsewhere true/1 is just data.
        if flag is not None and (named or not isinstance(item, str)):
            if not named:
                return None
            if any(word in lowered for word in _ONSITE_KEY_WORDS):
                return False if flag else None
            if any(word in lowered for word in _REMOTE_WORDS):
                return flag
            return None
        texts = [t for t in (item if isinstance(item, list) else [item]) if isinstance(t, (str, int, float))]
        text = " ".join(str(t) for t in texts)
        if not text or len(text) > 60:
            return None
        if not named:
            # Any field: only a value that is an arrangement and nothing else,
            # and not an identifier or a title (titles are read on their own).
            if IDENTIFIER_FIELD.search(name):
                return None
            words = [ARRANGEMENT_VALUE.match(str(t)) for t in texts]
            found = [m.group(1).lower() for m in words if m]
            if not found:
                return None
            return True if any(w.startswith(_REMOTE_WORDS) for w in found) else False
        if re.search(r"\b(?:non|not|no)[- ]?remote\b", text, re.IGNORECASE):
            return False  # "Non-Remote", "Not remote"
        if contains_phrase(text, "remote"):
            return True  # "Remote", or a choice like ["Remote", "Hybrid"]
        return remote_from_text(text)

    def visit(value: Any, depth: int, parent: str) -> str | None:
        nonlocal found_remote
        if depth > 4:
            return None
        items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
        for key, item in items:
            name = str(key)
            if name.lower() in skipped:
                continue
            path = f"{parent}.{name}" if parent else name
            if isinstance(item, dict) or (isinstance(item, list) and any(isinstance(i, dict) for i in item)):
                deeper = visit(item, depth + 1, path if isinstance(value, dict) else parent)
                if deeper:
                    return deeper
                continue
            label = path if isinstance(value, dict) else parent
            verdict = judge(label, name if isinstance(value, dict) else parent.rsplit(".", 1)[-1], item)
            shown = item if not isinstance(item, str) else f'"{item}"'
            if isinstance(item, bool):
                shown = str(item).lower()
            if verdict is False:
                return f"{label} = {shown}"
            if verdict is True:
                found_remote = found_remote or f"{label} = {shown}"
        return None

    onsite = visit(payload, 0, "")
    if onsite:
        return False, onsite
    return (True, found_remote) if found_remote else (None, "")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _company_name(label: str) -> str:
    """Turn a tenant/board slug like "acme-corp" into "Acme Corp"."""
    return " ".join(word.capitalize() for word in re.split(r"[-_]+", label) if word)


class JobSite:
    """Base class: one company's (or agency's) job listings."""

    name: str = ""
    search_url: str = ""
    # Which kind of board this is ("workday", "greenhouse", ...); `--site`
    # accepts it to pick every board of one kind.
    kind: str = ""
    # True when search results come back newest-first, so paging can stop
    # as soon as a page reaches stale postings.
    newest_first = False
    # Drop jobs that aren't marked remote / contract. Set per site because
    # they depend on who is posting: staffing agencies post contracts, and
    # companies hiring directly mostly post full-time roles.
    remote_only = True
    contract_only = False
    # With remote_only, also keep jobs whose remote status the site doesn't
    # give ("unmarked"; saved with is_remote None). Jobs marked hybrid or
    # on-site are dropped either way.
    include_unmarked_remote = False

    @property
    def id_prefix(self) -> str:
        """Prefix for job IDs ("accenture-", "insight-global-"), so two sites
        can't produce the same ID."""
        return f"{_slug(self.name)}-"

    def fetch_page(self, session: requests.Session, term: str, page: int) -> SearchPage:
        raise NotImplementedError

    def fetch_details(self, session: requests.Session, posting: Posting) -> Posting:
        """Return the posting with its description (and any extra fields) filled in."""
        return posting

    def lookup(
        self, session: requests.Session, url: str, native_id: str = "", title: str = ""
    ) -> tuple[Posting, dict[str, Any]]:
        """Load one job by its posting URL (or the site's own ID), with details.

        ``title``, if known, helps sites whose details leave out fields that
        only their search results have (Insight Global). Returns the posting
        and the raw JSON behind it, for ``--check-remote`` and re-checks.
        """
        raise UnsupportedSiteError(f"Can't look up single {self.kind or self.name} jobs yet.")

    def fetch_description(
        self, session: requests.Session, url: str, native_id: str = "", title: str = ""
    ) -> str:
        """Just the description of one saved job, for re-scoring it against your
        skills. Raises ``UnsupportedSiteError`` or ``requests.RequestException``
        when it can't be loaded (say, the posting has closed)."""
        return self.lookup(session, url, native_id, title)[0].description or ""

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r}, {self.search_url!r})"


# --- Insight Global ---------------------------------------------------------------


def _format_job_type(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "Unknown"
    return str(value or "Unknown")


class InsightGlobalSite(JobSite):
    """insightglobal.com, read through the JSON API its Angular search page uses.

    The API lives on the same host as the search page: ``/all/jobs`` for
    search and ``/all/jobs/<id>/details`` for a description. Job pages are
    ``/jobs/<id>``.
    """

    kind = "insight-global"
    newest_first = True  # requested with sort=postedDate,desc
    PAGE_SIZE = 50  # the API silently caps page size at 50

    def __init__(self, search_url: str, *, remote_only: bool = True, contract_only: bool = True):
        self.name = "Insight Global"
        self.search_url = search_url
        self.remote_only = remote_only
        self.contract_only = contract_only
        self.api_url = urljoin(search_url, "/all/jobs")
        self.job_page_url = urljoin(search_url, "/jobs/")

    def build_search_params(self, term: str, page: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "keyword": term,
            "page": page,
            "size": self.PAGE_SIZE,
            "sort": "postedDate,desc",
        }
        if self.contract_only:
            # Matches Contract, Contract To Perm and "Contract, perm possible",
            # and drops Perm. Only one value works: the API 500s on a list.
            params["filter.jobType"] = "Contract"
        params.update(
            {
                "filter.includeOnlyRemoteWork": "true" if self.remote_only else "false",
                "filter.distance": 5,
                "filter.status": "active",
            }
        )
        return params

    def build_job_url(self, job_id: str) -> str:
        return f"{self.job_page_url}{job_id}"

    def fetch_page(self, session: requests.Session, term: str, page: int) -> SearchPage:
        response = session.get(
            self.api_url,
            params=self.build_search_params(term, page),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        postings = [
            posting
            for posting in (self._posting(record) for record in payload.get("jobs") or [])
            if posting is not None
        ]
        total_pages = (payload.get("pageMetadata") or {}).get("totalPages") or 1
        return SearchPage(postings, has_more=page < total_pages)

    def _posting(self, record: dict[str, Any]) -> Posting | None:
        requisition_id = record.get("requisitionId")
        if not isinstance(requisition_id, str):
            return None
        address = record.get("workAddress") or {}
        pay = record.get("payRate") or {}
        # workRemote is the search's flag, but any other work-arrangement
        # field saying on-site or hybrid wins.
        flag = record.get("workRemote")
        is_remote = flag_value(flag)
        if is_remote is None and isinstance(flag, str):
            is_remote = remote_from_text(flag)  # "Remote", "Onsite", ...
        status, why = structured_remote(record, skip=("workRemote",))
        if status is False:
            is_remote = False
        return Posting(
            job_id=f"{self.id_prefix}{requisition_id}",
            title=str(record.get("jobTitle") or "").strip() or "Unknown title",
            url=self.build_job_url(requisition_id),
            company=self.name,
            city=str(address.get("locality") or ""),
            state=str(address.get("administrativeArea") or ""),
            is_remote=is_remote,
            remote_note=why if status is False else "",
            job_type=_format_job_type(record.get("jobType")),
            salary_low=float(pay.get("min") or 0),
            salary_high=float(pay.get("max") or 0),
            posted_date=str(record.get("postedDate") or ""),
            detail_key=requisition_id,
        )

    def details_payload(self, session: requests.Session, requisition_id: str) -> dict[str, Any]:
        response = session.get(
            f"{self.api_url}/{requisition_id}/details", timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return response.json()

    def apply_details(self, posting: Posting, payload: dict[str, Any]) -> Posting:
        description = html_to_text(payload.get("description"), keep_lines=True)
        # The details can carry work-arrangement fields the search didn't.
        status, why = structured_remote(payload, skip=("description",))
        if status is False:
            return dataclasses.replace(
                posting, description=description, is_remote=False, remote_note=why
            )
        if posting.is_remote is None and status is True:
            return dataclasses.replace(posting, description=description, is_remote=True)
        return dataclasses.replace(posting, description=description)

    def fetch_details(self, session: requests.Session, posting: Posting) -> Posting:
        return self.apply_details(posting, self.details_payload(session, posting.detail_key))

    def fetch_description(
        self, session: requests.Session, url: str, native_id: str = "", title: str = ""
    ) -> str:
        # The details alone have the description: one request, where lookup()
        # also searches for the job's remote flags.
        requisition_id = native_id or urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        return html_to_text(
            self.details_payload(session, requisition_id).get("description"), keep_lines=True
        )

    def find_search_record(
        self, session: requests.Session, requisition_id: str, title: str
    ) -> dict[str, Any] | None:
        """The job's own entry in the search results, found by its title.

        That's where workRemote and the other arrangement fields are (the
        details leave them out). Searched without the remote and job-type
        filters, so an on-site job is found too.
        """
        if not title:
            return None
        for page in (1, 2, 3):
            params = self.build_search_params(title, page)
            params["filter.includeOnlyRemoteWork"] = "false"
            params.pop("filter.jobType", None)
            response = session.get(self.api_url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            for record in payload.get("jobs") or []:
                if record.get("requisitionId") == requisition_id:
                    return record
            if page >= ((payload.get("pageMetadata") or {}).get("totalPages") or 1):
                break
        return None

    def lookup(
        self, session: requests.Session, url: str, native_id: str = "", title: str = ""
    ) -> tuple[Posting, dict[str, Any]]:
        requisition_id = native_id or urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        details = self.details_payload(session, requisition_id)
        title = title or str(details.get("jobTitle") or details.get("title") or "").strip()
        try:
            record = self.find_search_record(session, requisition_id, title)
        except requests.RequestException:
            record = None
        posting = self._posting(record) if record else None
        if posting is None:
            posting = Posting(
                job_id=f"{self.id_prefix}{requisition_id}",
                title=title or "(title not in the details)",
                url=self.build_job_url(requisition_id),
                company=self.name,
                # Without its search entry, the site's remote flag is unknown.
                is_remote=None,
                detail_key=requisition_id,
            )
        payload = {"search result": record or "(not found in Insight Global's search)", "details": details}
        return self.apply_details(posting, details), payload


# --- Workday ----------------------------------------------------------------------

WORKDAY_URL_PATTERN = re.compile(
    r"https?://(?P<tenant>[a-z0-9-]+)\.(?P<instance>wd\d+)\.myworkdayjobs\.com"
    r"/(?:(?P<locale>[a-z]{2}-[A-Z]{2})/)?(?P<site>(?!wday\b)[A-Za-z0-9_-]+)"
)
# "Posted Today", "Posted Yesterday", "Posted 3 Days Ago", "Posted 30+ Days Ago".
WORKDAY_POSTED_DAYS_PATTERN = re.compile(r"(\d+)(\+?)\s*days?\s+ago", re.IGNORECASE)


def workday_posted_date(posted_on: Any, today: datetime | None = None) -> str:
    """Convert Workday's relative ``postedOn`` text to an ISO date.

    "30+ Days Ago" comes out as 31 days back: Workday stops counting at 30,
    so a posting in that bucket is at least a month old.
    """
    text = str(posted_on or "").lower()
    today = today or datetime.now(timezone.utc)
    if "today" in text:
        days = 0
    elif "yesterday" in text:
        days = 1
    else:
        match = WORKDAY_POSTED_DAYS_PATTERN.search(text)
        if not match:
            return ""
        days = int(match.group(1)) + (1 if match.group(2) else 0)
    return (today - timedelta(days=days)).date().isoformat()


def classify_remote_type(value: Any) -> bool | None:
    """Map Workday's free-text ``remoteType`` to True/False (None if unset)."""
    text = str(value or "").strip().lower()
    if not text:
        return None
    # Hybrid, on-site, in-office, etc. all mean you have to come in.
    return "remote" in text and "hybrid" not in text


def _find_facet_value(facets: Any, parameter_hint: str, descriptor: str) -> tuple[str, str] | None:
    """Search Workday's (possibly nested) facet list for ``descriptor``.

    Returns ``(facetParameter, value id)`` for the first facet whose parameter
    name contains ``parameter_hint`` and that has a value labelled
    ``descriptor``, e.g. ("locationCountry", "bc33aa...") for the US.
    """
    for facet in facets if isinstance(facets, list) else []:
        if not isinstance(facet, dict):
            continue
        parameter = str(facet.get("facetParameter") or "")
        values = facet.get("values") or []
        if parameter_hint.lower() in parameter.lower():
            for value in values:
                if (
                    isinstance(value, dict)
                    and str(value.get("descriptor") or "").strip().lower()
                    == descriptor.strip().lower()
                    and value.get("id")
                ):
                    return parameter, str(value["id"])
        # Some tenants group facets, e.g. locationMainGroup -> locationCountry.
        nested = _find_facet_value(values, parameter_hint, descriptor)
        if nested:
            return nested
    return None


class WorkdaySite(JobSite):
    """A Workday careers board, read through the JSON API its own search page uses.

    Board pages look like ``https://<tenant>.wdN.myworkdayjobs.com/<site>``.
    Search is ``POST /wday/cxs/<tenant>/<site>/jobs`` and a posting's details
    are ``GET /wday/cxs/<tenant>/<site><externalPath>``.
    """

    kind = "workday"
    PAGE_SIZE = 20  # Workday rejects larger pages with a 400

    def __init__(
        self,
        name: str,
        search_url: str,
        board_url: str,
        *,
        remote_only: bool = True,
        contract_only: bool = False,
        country: str | None = None,
    ):
        match = WORKDAY_URL_PATTERN.match(board_url)
        if not match:
            raise UnsupportedSiteError(f"Not a Workday board URL: {board_url}")
        tenant, instance, site = match.group("tenant", "instance", "site")
        host = f"https://{tenant}.{instance}.myworkdayjobs.com"
        self.name = name
        self.search_url = search_url
        self.board_url = f"{host}/{site}"
        self.api_url = f"{host}/wday/cxs/{tenant}/{site}"
        self.remote_only = remote_only
        self.contract_only = contract_only
        self.country = country
        self._country_facets: dict[str, list[str]] | None = None
        self._country_lock = threading.Lock()  # terms are searched in parallel
        self._totals: dict[str, int] = {}

    def _post(self, session: requests.Session, body: dict[str, Any]) -> dict[str, Any]:
        response = session.post(
            f"{self.api_url}/jobs",
            json=body,
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def applied_facets(self, session: requests.Session) -> dict[str, list[str]]:
        """Return the country filter for ``self.country``; looked up once per board."""
        if not self.country:
            return {}
        with self._country_lock:
            return self._lookup_country_facets(session)

    def _lookup_country_facets(self, session: requests.Session) -> dict[str, list[str]]:
        if self._country_facets is None:
            probe = self._post(
                session, {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
            )
            found = _find_facet_value(probe.get("facets"), "country", self.country)
            if found is None:
                log(
                    f"  WARNING: {self.name} has no {self.country!r} country filter; "
                    "searching every country."
                )
                self._country_facets = {}
            else:
                self._country_facets = {found[0]: [found[1]]}
        return self._country_facets

    def fetch_page(self, session: requests.Session, term: str, page: int) -> SearchPage:
        offset = (page - 1) * self.PAGE_SIZE
        payload = self._post(
            session,
            {
                "appliedFacets": self.applied_facets(session),
                "limit": self.PAGE_SIZE,
                "offset": offset,
                "searchText": term,
            },
        )
        # Workday only reports the real total on the first page; later pages
        # can say 0, so remember it per search term.
        if payload.get("total"):
            self._totals[term] = int(payload["total"])
        items = payload.get("jobPostings") or []
        postings = [
            posting
            for posting in (self._posting(item) for item in items)
            if posting is not None
        ]
        has_more = len(items) == self.PAGE_SIZE and offset + len(items) < self._totals.get(term, 0)
        return SearchPage(postings, has_more=has_more)

    def _posting(self, item: dict[str, Any]) -> Posting | None:
        external_path = str(item.get("externalPath") or "")
        if not external_path:
            return None
        # ".../job/Atlanta/Python-Developer_R00212345" -> "R00212345"
        requisition = external_path.rstrip("/").rsplit("/", 1)[-1].rsplit("_", 1)[-1]
        location = str(item.get("locationsText") or "")
        city, state = split_location(location)
        remote = classify_remote_type(item.get("remoteType"))
        if remote is None and _mentions_remote(location):
            remote = True
        return Posting(
            job_id=f"{self.id_prefix}{requisition}",
            title=str(item.get("title") or "").strip() or "Unknown title",
            url=f"{self.board_url}{external_path}",
            company=self.name,
            city=city,
            state=state,
            is_remote=remote,
            job_type=str(item.get("timeType") or ""),
            posted_date=workday_posted_date(item.get("postedOn")),
            detail_key=external_path,
        )

    def details_payload(self, session: requests.Session, external_path: str) -> dict[str, Any]:
        response = session.get(
            f"{self.api_url}{external_path}",
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def lookup(
        self, session: requests.Session, url: str, native_id: str = "", title: str = ""
    ) -> tuple[Posting, dict[str, Any]]:
        # .../<site>/job/Austin/Software-Engineer_R123 (maybe with /en-US/ first)
        site_segment = "/" + self.board_url.rsplit("/", 1)[-1]
        path = urlparse(url).path
        if site_segment not in path:
            raise UnsupportedSiteError(f"{url} isn't a job on {self.board_url}")
        external_path = path.split(site_segment, 1)[1]
        payload = self.details_payload(session, external_path)
        info = payload.get("jobPostingInfo") or {}
        requisition = external_path.rstrip("/").rsplit("/", 1)[-1].rsplit("_", 1)[-1]
        posting = Posting(
            job_id=f"{self.id_prefix}{requisition}",
            title=str(info.get("title") or "").strip() or "Unknown title",
            url=url,
            company=self.name,
            detail_key=external_path,
        )
        return self.apply_details(posting, payload), payload

    def fetch_details(self, session: requests.Session, posting: Posting) -> Posting:
        return self.apply_details(posting, self.details_payload(session, posting.detail_key))

    def apply_details(self, posting: Posting, payload: dict[str, Any]) -> Posting:
        info = payload.get("jobPostingInfo") or {}
        location = str(info.get("location") or "")
        # The details page's remoteType is the board's own answer, so it wins
        # over a guess from the search results' location text ("Remote"): a
        # job listed at "Remote" can still be remoteType "Hybrid".
        remote = classify_remote_type(info.get("remoteType"))
        note = posting.remote_note
        if remote is False:
            note = f'remoteType = "{info.get("remoteType")}"'
        else:
            status, why = structured_remote(info, skip=("jobDescription", "remoteType"))
            if status is False:
                remote, note = False, why
        if remote is None:
            remote = posting.is_remote
        if remote is None and _mentions_remote(location, *(info.get("additionalLocations") or [])):
            remote = True
        # Some boards (Accenture's) leave the location out of search results,
        # so the details page is the only place to get it.
        city, state = (
            (posting.city, posting.state)
            if posting.city or posting.state
            else split_location(location)
        )
        return dataclasses.replace(
            posting,
            description=html_to_text(info.get("jobDescription"), keep_lines=True),
            is_remote=remote,
            remote_note=note if remote is False else "",
            city=city,
            state=state,
            job_type=str(info.get("timeType") or posting.job_type),
            # startDate is the exact posting date (YYYY-MM-DD); postedOn was relative.
            posted_date=str(info.get("startDate") or posting.posted_date),
            url=str(info.get("externalUrl") or posting.url),
        )


# --- Whole-board sites (Greenhouse, Lever) ---------------------------------------


class WholeBoardSite(JobSite):
    """A board whose API returns every posting at once, descriptions included.

    These APIs have no keyword search, so each search term is matched against
    the title and description locally. The board is downloaded once per run.
    """

    def __init__(self, name: str, search_url: str, *, remote_only: bool = True,
                 contract_only: bool = False):
        self.name = name
        self.search_url = search_url
        self.remote_only = remote_only
        self.contract_only = contract_only
        self._postings: list[Posting] | None = None
        self._postings_lock = threading.Lock()  # terms are searched in parallel

    def fetch_all(self, session: requests.Session) -> list[Posting]:
        raise NotImplementedError

    def fetch_page(self, session: requests.Session, term: str, page: int) -> SearchPage:
        if page > 1:
            return SearchPage([], has_more=False)
        with self._postings_lock:
            if self._postings is None:
                self._postings = self.fetch_all(session)
        matching = [
            posting
            for posting in self._postings
            if contains_phrase(f"{posting.title} {posting.description or ''}", term)
        ]
        return SearchPage(matching, has_more=False)

    def _get_json(self, session: requests.Session, url: str, **params: Any) -> Any:
        response = session.get(url, params=params or None, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()


# Greenhouse custom fields that some companies use for the work arrangement,
# e.g. {"name": "Workplace Type", "value": "Hybrid"}.
GREENHOUSE_WORKPLACE_FIELD = re.compile(
    r"workplace|work\s*(?:type|model|arrangement|location|setting|style)|location\s*type|remote",
    re.IGNORECASE,
)


def greenhouse_workplace(metadata: Any) -> bool | None:
    """Remote status from a Greenhouse job's custom fields, or None if none say."""
    return greenhouse_workplace_field(metadata)[0]


def greenhouse_workplace_field(metadata: Any) -> tuple[bool | None, str]:
    """``(status, 'Workplace Type = "Hybrid"')`` from a Greenhouse job's custom fields."""
    for item in metadata if isinstance(metadata, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not GREENHOUSE_WORKPLACE_FIELD.search(name):
            continue
        value = item.get("value")
        text = " ".join(map(str, value)) if isinstance(value, list) else str(value or "")
        field = f'{name} = "{text}"'
        if "remote" in name.lower() and text.strip().lower() in ("yes", "true"):
            return True, field
        if "remote" in name.lower() and text.strip().lower() in ("no", "false"):
            return False, field
        found = remote_from_text(text)
        if found is not None:
            return found, field
    return None, ""


class GreenhouseSite(WholeBoardSite):
    """``boards.greenhouse.io/<token>`` via the public Job Board API."""

    kind = "greenhouse"

    def __init__(self, name: str, search_url: str, board_token: str, **options: Any):
        super().__init__(name, search_url, **options)
        self.board_token = board_token
        self.api_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"

    def fetch_all(self, session: requests.Session) -> list[Posting]:
        payload = self._get_json(session, self.api_url, content="true")
        return [self._posting(job) for job in payload.get("jobs") or []]

    def lookup(
        self, session: requests.Session, url: str, native_id: str = "", title: str = ""
    ) -> tuple[Posting, dict[str, Any]]:
        # boards.greenhouse.io/<token>/jobs/<id>, or a careers page with ?gh_jid=<id>
        parsed = urlparse(url)
        job_id = native_id or (parse_qs(parsed.query).get("gh_jid") or [""])[0]
        if not job_id:
            match = re.search(r"/jobs/(\d+)", parsed.path)
            job_id = match.group(1) if match else ""
        if not job_id:
            raise UnsupportedSiteError(f"Couldn't find a Greenhouse job ID in {url}")
        payload = self._get_json(session, f"{self.api_url}/{job_id}")
        return self._posting(payload), payload

    def _posting(self, job: dict[str, Any]) -> Posting:
        location = str((job.get("location") or {}).get("name") or "")
        city, state = split_location(location)
        # Greenhouse has no standard remote field: a company's own
        # "Workplace Type" field if it has one, else the location.
        remote, field = greenhouse_workplace_field(job.get("metadata"))
        note = field if remote is False else ""
        if remote is None:
            remote = remote_from_text(location)
        return Posting(
            job_id=f"{self.id_prefix}{job.get('id')}",
            title=str(job.get("title") or "").strip() or "Unknown title",
            url=str(job.get("absolute_url") or self.search_url),
            company=self.name,
            city=city,
            state=state,
            is_remote=remote,
            remote_note=note,
            posted_date=str(job.get("first_published") or job.get("updated_at") or ""),
            # The content field is HTML that has been entity-escaped again.
            description=html_to_text(html.unescape(str(job.get("content") or "")), keep_lines=True),
        )


# Lever's workplaceType; "unspecified" (or missing) falls back to the location.
LEVER_WORKPLACE_TYPES = {"remote": True, "hybrid": False, "onsite": False}


class LeverSite(WholeBoardSite):
    """``jobs.lever.co/<company>`` via the public Postings API."""

    kind = "lever"

    def __init__(self, name: str, search_url: str, company: str, *, eu: bool = False,
                 **options: Any):
        super().__init__(name, search_url, **options)
        self.company_slug = company
        host = "api.eu.lever.co" if eu else "api.lever.co"
        self.api_url = f"https://{host}/v0/postings/{company}"

    def fetch_all(self, session: requests.Session) -> list[Posting]:
        postings = []
        for job in self._get_json(session, self.api_url, mode="json") or []:
            categories = job.get("categories") or {}
            location = str(categories.get("location") or "")
            city, state = split_location(location)
            salary = job.get("salaryRange") or {}
            created_ms = job.get("createdAt")
            posted = (
                datetime.fromtimestamp(created_ms / 1000, timezone.utc).isoformat()
                if isinstance(created_ms, (int, float))
                else ""
            )
            sections = [str(job.get("descriptionPlain") or "")]
            for item in job.get("lists") or []:
                sections.append(str(item.get("text") or ""))
                sections.append(html_to_text(item.get("content")))
            sections.append(str(job.get("additionalPlain") or ""))
            postings.append(
                Posting(
                    job_id=f"{self.id_prefix}{job.get('id')}",
                    title=str(job.get("text") or "").strip() or "Unknown title",
                    url=str(job.get("hostedUrl") or self.search_url),
                    company=self.name,
                    city=city,
                    state=state,
                    is_remote=LEVER_WORKPLACE_TYPES.get(
                        str(job.get("workplaceType") or "").lower(), remote_from_text(location)
                    ),
                    job_type=str(categories.get("commitment") or ""),
                    salary_low=float(salary.get("min") or 0),
                    salary_high=float(salary.get("max") or 0),
                    posted_date=posted,
                    description=re.sub(r"\s+", " ", " ".join(sections)).strip(),
                )
            )
        return postings


# --- Resolving a careers URL to a site ------------------------------------------

GREENHOUSE_HOSTS = (
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "boards.eu.greenhouse.io",
    "job-boards.eu.greenhouse.io",
)
LEVER_HOSTS = {"jobs.lever.co": False, "jobs.eu.lever.co": True}  # host -> EU API
# ATS board links to look for in a careers page's HTML.
BOARD_LINK_PATTERNS = (
    WORKDAY_URL_PATTERN,
    re.compile(
        r"https?://(?:job-)?boards(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?"
        r"[A-Za-z0-9_-]+"
    ),
    re.compile(r"https?://jobs(?:\.eu)?\.lever\.co/[A-Za-z0-9_.-]+"),
)
# Path segments that are part of an ATS's own URL scheme, not a board name.
NON_BOARD_SEGMENTS = {"embed", "v1", "boards", "job_board", "js"}


def _board_site(name: str | None, search_url: str, board_url: str,
                options: dict[str, Any]) -> JobSite | None:
    """Build a site for an ATS board URL, or return None if it isn't one."""
    parsed = urlparse(board_url)
    host = (parsed.hostname or "").lower()
    segments = [segment for segment in parsed.path.split("/") if segment]

    workday = WORKDAY_URL_PATTERN.match(board_url)
    if workday:
        return WorkdaySite(
            name or _company_name(workday.group("tenant")), search_url, board_url, **options
        )

    ats_options = {key: value for key, value in options.items() if key != "country"}
    if host in GREENHOUSE_HOSTS or host == "boards-api.greenhouse.io":
        token = (parse_qs(parsed.query).get("for") or [None])[0]
        if token is None:
            token = next((s for s in segments if s not in NON_BOARD_SEGMENTS), None)
        if token:
            return GreenhouseSite(name or _company_name(token), search_url, token, **ats_options)

    if host in LEVER_HOSTS and segments:
        return LeverSite(
            name or _company_name(segments[0]), search_url, segments[0],
            eu=LEVER_HOSTS[host], **ats_options,
        )
    return None


def discover_board_url(page_html: str) -> str | None:
    """Return the first ATS board link found in a careers page's HTML."""
    for pattern in BOARD_LINK_PATTERNS:
        match = pattern.search(page_html)
        if match:
            return html.unescape(match.group(0))
    return None


def resolve_job_site(
    url: str,
    session: requests.Session,
    *,
    remote_only: bool = True,
    country: str | None = None,
) -> JobSite:
    """Work out how to read the jobs behind a careers/search page URL.

    1. Insight Global's search page uses its own API.
    2. Pages listed in ``KNOWN_CAREER_SITES`` use the ATS board they map to.
    3. ATS board URLs (Workday, Greenhouse, Lever) are used directly.
    4. Otherwise the page is downloaded and checked for an ATS board link.

    ``country`` narrows boards that support a country filter (Workday).
    Raises ``UnsupportedSiteError`` if nothing works.
    """
    host = (urlparse(url).hostname or "").lower()
    options: dict[str, Any] = {"remote_only": remote_only, "country": country}

    if host == "insightglobal.com" or host.endswith(".insightglobal.com"):
        return InsightGlobalSite(url, remote_only=remote_only)

    known = KNOWN_CAREER_SITES.get(host)
    if known:
        site = _board_site(known.name, url, known.board_url, options)
        if site is None:
            raise UnsupportedSiteError(
                f"KNOWN_CAREER_SITES[{host!r}] points at an unsupported board: {known.board_url}"
            )
        return site

    site = _board_site(None, url, url, options)
    if site:
        return site

    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    board_url = discover_board_url(response.text)
    if board_url:
        name = _company_name(
            next(
                (label for label in host.split(".") if label not in {"www", "careers", "jobs"}),
                host,
            )
        )
        site = _board_site(name, url, board_url, options)
        if site:
            return site
    raise UnsupportedSiteError(
        f"Couldn't find job listings behind {url}. The page doesn't link to a "
        "Workday, Greenhouse, or Lever board; if you know which board it uses, add "
        "it to KNOWN_CAREER_SITES in job_sites.py."
    )
