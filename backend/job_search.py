"""Search job sites (Insight Global, Accenture, ...) and email new matches through the Gmail API."""

from __future__ import annotations

import argparse
import dataclasses
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, TypeVar
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from gmail_client import GmailNotConfiguredError, get_gmail_service, send_email
from job_sites import (
    JobSite,
    Posting,
    UnsupportedSiteError,
    contains_phrase,
    log,
    onsite_evidence,
    resolve_job_site,
)
from job_boards import ACCENTURE_SEARCH_URL, INSIGHT_GLOBAL_URL, JOB_SEARCH_URLS
from job_fit import CandidateProfile, FitScore, fit_label, score_fit
from job_store import FirestoreJobStore, get_job_store
from salary import PERIODS, salary_period
from salary import format_salary as format_pay
from search_skills import InvalidSkillsError, SearchSkills, skills_from_document

load_dotenv()

SEARCH_TITLES = [
    "Software Engineer",
    "Senior Software Engineer",
    "Full Stack Developer",
    "Backend Developer",
    "Frontend Developer",
    "React Developer",
]
# The skills a Core match is scored on. These are the defaults: the
# dashboard's Skills page saves your own list to the database, and every
# search uses that instead when there is one (see search_skills.py).
# frontend/src/lib/skills.ts mirrors both lists, to show them before you save.
RESUME_SKILLS = [
    "Python",
    "JavaScript",
    "TypeScript",
    "React",
    "ReactJS",
    "React Native",
    "Node.js",
    "NodeJS",
    "SQL",
    "Java",
    "GraphQL",
    "Full Stack",
    "REST API",
    "Docker",
    "Terraform",
    "Azure",
    "AWS",
    "Firebase",
]
# A Core match needs at least one of these on top of MIN_SKILL_MATCHES, so a
# posting that only mentions cloud tooling or SQL (e.g. a network security
# role listing Azure and AWS) doesn't qualify as your main stack.
CORE_LANGUAGE_SKILLS = [
    "Python",
    "JavaScript",
    "TypeScript",
    "Java",
    "React",
    "ReactJS",
    "React Native",
    "Node.js",
    "NodeJS",
]
# Spellings of one skill; the fit score counts a job mentioning both once.
SKILL_ALIASES = [
    ("React", "ReactJS"),
    ("Node.js", "NodeJS"),
]
# Your professional experience. The fit score compares it with the years a
# job asks for (or its title implies: Senior ~5, Lead/Staff ~7), so set it to
# your own number. MAX_YEARS_EXPERIENCE (below) is the hard cutoff.
YEARS_OF_EXPERIENCE = 5
# Title phrases for the roles you're after. A title with one of these scores
# higher on fit than, say, "Network Engineer" or "Data Scientist" that happens
# to mention your skills. GENERIC_ROLE_TITLES earn partial credit.
TARGET_ROLE_TITLES = [
    "Software Engineer",
    "Software Developer",
    "Software Development Engineer",
    "Full Stack",
    "Full-Stack",
    "Fullstack",
    "Backend",
    "Back-End",
    "Back End",
    "Frontend",
    "Front-End",
    "Front End",
    "Web Developer",
    "Web Engineer",
    "Application Developer",
    "Applications Developer",
    "Mobile Developer",
    "Mobile Engineer",
    "Product Engineer",
    "API Engineer",
    "API Developer",
    "SDE",
    "SWE",
]
GENERIC_ROLE_TITLES = ["Developer", "Programmer"]
EXTRA_SEARCH_TERMS = [
    "Python Developer",
    "React Engineer",
    "Full Stack Engineer",
]
JAVA_SEARCH_TERMS = [
    "Java Developer",
    "Junior Java Developer",
    "Entry Level Java Developer",
    "Associate Java Developer",
    "Java Engineer",
]
IOS_SEARCH_TERMS = [
    "iOS Developer",
    "Junior iOS Developer",
    "Entry Level iOS Developer",
    "Associate iOS Developer",
    "iOS Engineer",
]
DOTNET_SEARCH_TERMS = [
    ".NET Developer",
    "Junior .NET Developer",
    "Entry Level .NET Developer",
    "Associate .NET Developer",
    ".NET Engineer",
]
GROWTH_TRACK_JUNIOR_TITLE_HINTS = [
    "junior",
    "jr.",
    "jr ",
    "entry level",
    "entry-level",
    "associate",
    "i ",
]
# Named platforms/frameworks that show up in titles but aren't on the resume.
# A title calling one of these out means the role's core stack is unfamiliar
# territory, even if the description racks up incidental skill matches
# elsewhere. Cross-checked against the resume (Vue.js, Angular, and Ruby are
# on there, so they're deliberately excluded from this list). Add to this
# list as new mismatches show up.
NON_RESUME_TITLE_TECH = [
    "Android",
    "Drupal",
    "WordPress",
    "Salesforce",
    "SAP",
    "Hybris",
    "ServiceNow",
    "Workday",
    "Magento",
    "Shopify",
    "Sitecore",
    "PeopleSoft",
    "Mainframe",
    "COBOL",
    "ABAP",
    "PHP",
    "Golang",
    "Kotlin",
    "Swift",
    "Scala",
    "Rust",
    "Perl",
    "MATLAB",
    "SAS",
    "Tableau",
    "Power BI",
    "MuleSoft",
    "Guidewire",
    "Pega",
    "Appian",
    "OutSystems",
    "Snowflake",
    "Alteryx",
    "Informatica",
    "IDMC",
    "Enovia",
    "Dynatrace",
    "Palantir",
    "Ignition",
    "Accela",
    "UiPath",
    "Power Platform",
]
# Insight Global tags some offshore listings with a state of Alaska as a
# placeholder even when the title doesn't say INTL/LATAM/India/Nearshore
# (e.g. "Madhapur, Alaska", "Hyderabad, Alaska"). Genuine Alaska postings are
# vanishingly rare in a remote-only feed, so anything tagged Alaska whose
# city isn't actually in Alaska gets treated as international.
ALASKA_CITIES = {
    "anchorage",
    "fairbanks",
    "juneau",
    "wasilla",
    "sitka",
    "ketchikan",
    "kenai",
    "kodiak",
    "palmer",
    "homer",
    "soldotna",
    "bethel",
    "college",
    "eagle river",
    "north pole",
}
# Growth-track stacks that should only ever be evaluated under their own
# growth track's rules (junior-friendly cap, no Sr./Senior/etc.), even when a
# job also racks up enough incidental Core-stack matches to pass that
# track's laxer threshold. Prioritizes the title's named stack over
# secondary skill overlap.
GROWTH_TRACK_TITLE_STACKS = ("Java", "iOS", ".NET")

MIN_SKILL_MATCHES = 2
GROWTH_TRACK_MAX_YEARS_EXPERIENCE = 3
MAX_YEARS_EXPERIENCE = 7
MAX_POSTED_AGE_DAYS = 30
REMOTE_ONLY = True
# With REMOTE_ONLY, also keep jobs whose site doesn't say whether they're
# remote ("unmarked": about half of Accenture's postings). They're saved with
# is_remote None so you can tell them apart; jobs marked hybrid or on-site are
# still dropped. `job_search.py --include-unmarked` turns this on for one run.
INCLUDE_UNMARKED_REMOTE = False
# Cap on result pages per search term. Insight Global returns newest-first, so
# its paging usually stops early, once a page reaches postings older than
# MAX_POSTED_AGE_DAYS. Workday sorts by relevance, so every page is read.
MAX_PAGES_PER_SEARCH = 10
RETRY_ATTEMPTS = 4
CONTRACT_JOB_TYPES = {"contract", "contract to perm", "contract-to-perm"}
# Speed vs. politeness. Sites are searched at the same time, each with up to
# MAX_CONCURRENT_REQUESTS_PER_SITE requests in flight, and no host gets more
# than one new request per MIN_SECONDS_BETWEEN_REQUESTS (so at most 4 per
# second). If a site starts answering 429/403, raise the interval or lower the
# concurrency. 429s and 5xx are retried with backoff either way.
MAX_CONCURRENT_REQUESTS_PER_SITE = 4
MIN_SECONDS_BETWEEN_REQUESTS = 0.25
# Sites that support a country filter (Workday boards such as Accenture's) are
# narrowed to this country. Set to None to search every country.
JOB_COUNTRY = "United States of America"
# Greenhouse and Lever boards have no country filter, so with JOB_COUNTRY set
# to the US, a job whose location names somewhere else (and not the US as
# well) is dropped: "Remote - Canada", "Remote, EMEA", "Bengaluru, India".
# Only whole countries/regions and a few unambiguous cities are listed;
# most city names also exist in the US (London, KY; Dublin, OH; Paris, TX).
US_COUNTRY_NAMES = {"united states of america", "united states", "usa", "us"}
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}
# A location naming any of these (or a US state) counts as US, so "Peru, IN"
# and "New Mexico" stay; short codes only match in capitals.
US_LOCATION_WORDS = [
    "US", "USA", "U.S.", "U.S.A.", "United States", "America", "Americas",
    "North America", "AMER", "NA", "New England",
    *US_STATES, *US_STATES.values(),
]
NON_US_LOCATION_WORDS = [
    # Regions
    "EMEA", "APAC", "APJ", "LATAM", "Europe", "European Union", "EU", "Asia",
    "Africa", "Middle East", "Oceania", "Latin America", "South America",
    "Central America", "Caribbean",
    # Countries
    "Canada", "Mexico", "Brazil", "Argentina", "Colombia", "Chile", "Peru",
    "Costa Rica", "Uruguay", "United Kingdom", "UK", "England", "Scotland",
    "Wales", "Ireland", "Germany", "France", "Netherlands", "Belgium",
    "Luxembourg", "Spain", "Portugal", "Italy", "Switzerland", "Austria",
    "Poland", "Czech Republic", "Czechia", "Romania", "Hungary", "Bulgaria",
    "Serbia", "Croatia", "Greece", "Ukraine", "Lithuania", "Latvia", "Estonia",
    "Sweden", "Norway", "Denmark", "Finland", "Iceland", "Israel", "Turkey",
    "Türkiye", "United Arab Emirates", "UAE", "Saudi Arabia", "Egypt",
    "South Africa", "Nigeria", "Kenya", "India", "Pakistan", "Sri Lanka",
    "Bangladesh", "China", "Hong Kong", "Taiwan", "Japan", "Korea",
    "South Korea", "Singapore", "Malaysia", "Indonesia", "Philippines",
    "Thailand", "Vietnam", "Australia", "New Zealand",
    # Cities with no US namesake that job boards list without a country
    "Toronto", "Montreal", "Montréal", "Bengaluru", "Bangalore", "Hyderabad",
    "Pune", "Chennai", "Gurugram", "Gurgaon", "Noida", "Tel Aviv", "São Paulo",
    "Sao Paulo", "Mexico City", "Ciudad de México",
]

# Careers/job search pages to scan live in job_boards.py (JOB_SEARCH_URLS).
# Most of these pages render their results in the browser, so the jobs come
# from the JSON API behind each page; job_sites.resolve_job_site works out
# which API a URL needs:
# * Insight Global: its own API on the same host (/all/jobs).
# * Accenture: its Workday board (see KNOWN_CAREER_SITES in job_sites.py).
# * Workday (<company>.wdN.myworkdayjobs.com/<site>), Greenhouse
#   (boards.greenhouse.io/<company>), Lever (jobs.lever.co/<company>), and
#   Ashby (jobs.ashbyhq.com/<company>) board URLs work as-is, and so do
#   careers pages that link to one of those.
# * Remote job boards (Himalayas, Remote OK, Jobicy, We Work Remotely) list
#   many companies' jobs; each job keeps its own company.
# To add a company, add its URL to job_boards.py and to JOB_SEARCH_URLS there.

# Per-URL overrides of a site's filters: "remote_only" (defaults to
# REMOTE_ONLY), "include_unmarked_remote" (defaults to INCLUDE_UNMARKED_REMOTE),
# and "contract_only" (on for Insight Global, off elsewhere), e.g.
#   ACCENTURE_SEARCH_URL: {"include_unmarked_remote": True},
SITE_SETTINGS: dict[str, dict[str, bool]] = {}
# After each search, load and re-check saved jobs marked remote that the
# search didn't see again (see recheck_saved_jobs).
RECHECK_SAVED_JOBS = True
REMOTE_CHECK_REPORT = Path(__file__).with_name("remote_check_report.txt")
HEADERS = {"User-Agent": "job-finder/1.0 (+personal job search)"}
YEARS_EXPERIENCE_PATTERN = re.compile(
    r"(\d+)\s*(?:-\s*\d+\s*)?\+?\s*years?\b.{0,60}?(?:experience|exp\b)",
    re.IGNORECASE | re.DOTALL,
)
INTERNATIONAL_TITLE_PATTERN = re.compile(
    r"\b(?:INTL|LATAM|India|Nearshore)\b", re.IGNORECASE
)
SENIOR_TITLE_PATTERN = re.compile(
    r"\b(?:sr\.?|senior|principal|staff|lead)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class SearchTrack:
    name: str
    terms: tuple[str, ...]
    skills: tuple[str, ...]
    minimum_matches: int
    growth_track: bool = False
    # When set, at least one of these must be among the matched skills.
    required_skills: tuple[str, ...] = ()
    # Who the fit score compares jobs against, and which title tech counts as
    # off your resume. None: the defaults at the top of this file.
    profile: CandidateProfile | None = None


def default_search_skills() -> SearchSkills:
    """The skills at the top of this file, used until you save your own."""
    return SearchSkills(tuple(RESUME_SKILLS), tuple(CORE_LANGUAGE_SKILLS))


def build_tracks(skills: SearchSkills | None = None) -> tuple[SearchTrack, ...]:
    """The tracks to search, with the Core track scored on ``skills`` (your
    saved list; the defaults at the top of this file when None)."""
    skills = skills or default_search_skills()
    profile = candidate_profile(skills)
    tracks = (
        SearchTrack(
            "Core matches (your main stack)",
            tuple(SEARCH_TITLES + EXTRA_SEARCH_TERMS),
            skills.skills,
            MIN_SKILL_MATCHES,
            required_skills=skills.core_skills,
        ),
        SearchTrack(
            "Java growth track (entry-level / lower bar)",
            tuple(JAVA_SEARCH_TERMS),
            ("Java",),
            1,
            growth_track=True,
        ),
        SearchTrack(
            "iOS growth track (entry-level / lower bar)",
            tuple(IOS_SEARCH_TERMS),
            ("iOS",),
            1,
            growth_track=True,
        ),
        SearchTrack(
            ".NET growth track (entry-level / lower bar)",
            tuple(DOTNET_SEARCH_TERMS),
            (".NET",),
            1,
            growth_track=True,
        ),
    )
    return tuple(dataclasses.replace(track, profile=profile) for track in tracks)


@dataclass
class JobMatch:
    job_id: str
    title: str
    city: str
    state: str
    # None when the site doesn't say ("unmarked"); see INCLUDE_UNMARKED_REMOTE.
    is_remote: bool | None
    job_type: str
    salary_low: float
    salary_high: float
    url: str
    track: str
    posted_date: str = ""
    # What the salary is per ("hour", "day", "week", "month", "year"; "" when
    # it can't be told), and whether that's only an estimate from the amount
    # (the site and the posting don't say). See salary.py.
    salary_period: str = ""
    salary_period_estimated: bool = False
    matched_skills: list[str] = field(default_factory=list)
    min_years: int | None = None
    company: str = ""
    # How well the job fits you, 0-100 (see job_fit.py). None only for matches
    # built outside evaluate_posting.
    fit_score: int | None = None
    # The points behind fit_score ({"skills": 48, "role": 30, "experience": -8,
    # ...}; they add up to it), and the same in words.
    fit_breakdown: dict[str, int] = field(default_factory=dict)
    fit_reasons: list[str] = field(default_factory=list)
    # The posting's text. Saved apart from the job (job_descriptions), so it
    # can be re-scored when you change your skills (reassess_saved_jobs).
    description: str = field(default="", repr=False)

    @property
    def score(self) -> int:
        """The number of matched skills (the track's threshold uses it)."""
        return len(self.matched_skills)

    @property
    def fit_label(self) -> str:
        return fit_label(self.fit_score)


def _contains_skill(text: str, skill: str) -> bool:
    """Match complete skill names so Java does not match JavaScript."""
    return contains_phrase(text, skill)


def _any_same_skill(wanted: Iterable[str], found: Iterable[str]) -> bool:
    """Whether any skill in ``found`` is one of ``wanted``, in any case."""
    return bool({skill.lower() for skill in wanted} & {skill.lower() for skill in found})


def score_posting(posting: Posting, skills: tuple[str, ...]) -> list[str]:
    haystack = f"{posting.title} {posting.description or ''}"
    return [skill for skill in skills if _contains_skill(haystack, skill)]


def extract_min_years(posting: Posting) -> int | None:
    haystack = posting.description or ""
    years = [int(match) for match in YEARS_EXPERIENCE_PATTERN.findall(haystack)]
    return min(years) if years else None


def looks_junior(posting: Posting) -> bool:
    title = posting.title.lower()
    return any(hint in title for hint in GROWTH_TRACK_JUNIOR_TITLE_HINTS)


def _is_contract_job(job_type: str) -> bool:
    """Return True when the job type is contract or contract-to-perm."""
    return any(t in job_type.lower() for t in CONTRACT_JOB_TYPES)


def _is_international_title(title: str) -> bool:
    """Return True when the title is flagged as an offshore INTL/LATAM role.

    The feed has no country, and these listings carry placeholder US locations
    (e.g. "INTL India" in Dunwoody, GA), so the title is the only signal.
    """
    return INTERNATIONAL_TITLE_PATTERN.search(title) is not None


def unfamiliar_tech(skills: SearchSkills | None = None) -> tuple[str, ...]:
    """``NON_RESUME_TITLE_TECH`` minus anything in ``skills``: add "Kotlin" to
    your skills and Kotlin titles are no longer dropped or marked down."""
    mine = {skill.lower() for skill in (skills or default_search_skills()).skills}
    return tuple(tech for tech in NON_RESUME_TITLE_TECH if tech.lower() not in mine)


def _has_unfamiliar_title_tech(title: str, unfamiliar: tuple[str, ...] | None = None) -> bool:
    """Return True when the title names a stack that isn't on the resume."""
    techs = NON_RESUME_TITLE_TECH if unfamiliar is None else unfamiliar
    return any(_contains_skill(title, tech) for tech in techs)


def _is_senior_title(title: str) -> bool:
    """Return True when the title is flagged Sr./Senior/Principal/Staff/Lead."""
    return SENIOR_TITLE_PATTERN.search(title) is not None


def _is_bogus_alaska_location(state: str, city: str) -> bool:
    """Return True when the state is Alaska but the city isn't actually in Alaska."""
    if state.strip().lower() not in ("alaska", "ak"):
        return False
    return city.strip().lower() not in ALASKA_CITIES


def _is_placeholder_listing(title: str) -> bool:
    """Return True for leftover duplicate/test listings, e.g. "COPY - ..."."""
    return title.strip().upper().startswith("COPY")


def _title_names_growth_stack(title: str) -> bool:
    """Return True when the title names a Java/iOS/.NET growth-track stack."""
    return any(_contains_skill(title, stack) for stack in GROWTH_TRACK_TITLE_STACKS)


def _is_outside_job_country(posting: Posting) -> bool:
    """Return True when the location names a place outside the US and not the US too.

    Only used when JOB_COUNTRY is the US. Workday boards are already narrowed
    by their own country filter; this covers boards that have none.
    """
    if str(JOB_COUNTRY or "").strip().lower() not in US_COUNTRY_NAMES:
        return False
    # Case-sensitive for short codes ("US", "UK", "EU", "NA") so "us" or "na"
    # inside ordinary words or city names can't match; full names either way.
    location = f"{posting.city}, {posting.state}"

    def mentions(words: list[str]) -> bool:
        for word in words:
            flags = 0 if len(word) <= 4 and word.isupper() else re.IGNORECASE
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", location, flags):
                return True
        return False

    return mentions(NON_US_LOCATION_WORDS) and not mentions(US_LOCATION_WORDS)


def candidate_profile(skills: SearchSkills | None = None) -> CandidateProfile:
    """Your profile for the fit score, from the settings at the top of this
    file and ``skills`` (your saved skill list; the defaults when None)."""
    skills = skills or default_search_skills()
    return CandidateProfile(
        skills=skills.skills,
        core_skills=skills.core_skills,
        years_experience=YEARS_OF_EXPERIENCE,
        target_roles=tuple(TARGET_ROLE_TITLES),
        generic_roles=tuple(GENERIC_ROLE_TITLES),
        unfamiliar_tech=unfamiliar_tech(skills),
        skill_aliases=tuple(tuple(group) for group in SKILL_ALIASES),
        proficiency=skills.proficiency,
    )


# The tracks with the default skills. Each run builds its own from the skills
# saved in the dashboard (see search_skills_for_run).
TRACKS = build_tracks()


def saved_search_skills(store: FirestoreJobStore) -> SearchSkills | None:
    """The skills saved in the dashboard, or None if there are none (or they
    can't be used, with a warning)."""
    try:
        return skills_from_document(store.load_search_skills())
    except InvalidSkillsError as error:
        print(f"WARNING: the saved skill list can't be used ({error}); "
              "using the defaults in job_search.py instead.")
        return None


def search_skills_for_run(store: FirestoreJobStore) -> SearchSkills:
    """The skills saved in the dashboard, or the defaults at the top of this
    file if there are none (or they can't be used)."""
    saved = saved_search_skills(store)
    skills = saved or default_search_skills()
    source = "saved in the dashboard" if saved else "defaults in job_search.py"
    core = set(skills.core_skills)
    listed = ", ".join(f"{skill}*" if skill in core else skill for skill in skills.skills)
    print(f"Skills ({source}; * = core): {listed}")
    return skills


def _parse_posted_date(value: Any) -> datetime | None:
    # postedDate looks like "2026-10-29T15:42:48.1Z"; the first 19 characters
    # (YYYY-MM-DDTHH:MM:SS) parse the same on every Python version.
    raw_value = str(value or "").strip()[:19]
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def format_posted_date(value: Any) -> str:
    parsed = _parse_posted_date(value)
    if parsed is None:
        return str(value or "").strip()
    return parsed.date().isoformat()


def _is_stale_posting(value: Any) -> bool:
    """Return True when PostedDate is older than MAX_POSTED_AGE_DAYS."""
    parsed = _parse_posted_date(value)
    if parsed is None:
        return False
    return (datetime.now(timezone.utc) - parsed).days > MAX_POSTED_AGE_DAYS


class HostThrottle:
    """Spaces out request starts to each host by at least ``min_interval`` seconds.

    Shared by every session and thread, so two boards on the same host (e.g.
    two Greenhouse boards) share one budget.
    """

    def __init__(self, min_interval: Callable[[], float]) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._next_start: dict[str, float] = {}

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_start.get(host, 0.0))
            self._next_start[host] = start + self._min_interval()
        if start > now:
            time.sleep(start - now)


# Reads the setting at request time, so tests (or you) can change it.
HOST_THROTTLE = HostThrottle(lambda: MIN_SECONDS_BETWEEN_REQUESTS)


class ThrottledAdapter(HTTPAdapter):
    def send(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        HOST_THROTTLE.wait(urlparse(request.url).hostname or "")
        return super().send(request, *args, **kwargs)


def build_session() -> requests.Session:
    """Return a throttled session that retries dropped connections and 5xx/429s."""
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=RETRY_ATTEMPTS,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        # Workday's search is a POST, but it only reads, so retrying it is safe.
        allowed_methods=("GET", "POST"),
    )
    adapter = ThrottledAdapter(
        max_retries=retry, pool_maxsize=max(10, MAX_CONCURRENT_REQUESTS_PER_SITE)
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _is_stale_page(postings: list[Posting]) -> bool:
    """Return True when a newest-first page has reached stale postings.

    Postings without a date are ignored; the oldest dated posting on the
    page decides, because everything on later pages is older still.
    """
    dated = [p for p in postings if _parse_posted_date(p.posted_date)]
    return bool(dated) and _is_stale_posting(dated[-1].posted_date)


# --- Choosing sites -----------------------------------------------------------------


class SiteSelectionError(ValueError):
    """A `--site` value that matches none of the sites."""


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _site_matches(site: JobSite, url: str, selector: str) -> bool:
    """`--site` matches a site's name ("accenture", "Insight Global"), its board
    kind ("workday"), or any part of its configured URL ("insightglobal")."""
    wanted = _normalize(selector)
    return bool(wanted) and (
        wanted in (_normalize(site.name), _normalize(site.kind))
        or wanted in _normalize(urlparse(url).netloc + urlparse(url).path)
    )


def resolve_sites(
    session: requests.Session,
    urls: list[str] | None = None,
    selectors: list[str] | None = None,
    include_unmarked: bool = False,
) -> list[JobSite]:
    """Resolve ``JOB_SEARCH_URLS`` to sites, keeping only those ``selectors`` pick.

    A selector that is itself a URL is searched even if it isn't in the
    list, which is handy for trying out a new board. URLs that can't be
    resolved are skipped with a warning. Raises ``SiteSelectionError`` when
    a selector matches nothing. ``include_unmarked`` (``--include-unmarked``)
    keeps unmarked-remote jobs on every site, whatever the settings say.
    """
    urls = list(JOB_SEARCH_URLS if urls is None else urls)
    selectors = list(selectors or [])
    extra_urls = [s for s in selectors if re.match(r"https?://", s)]
    selectors = [s for s in selectors if s not in extra_urls]
    if extra_urls and not selectors:
        urls = extra_urls  # only URLs were given: search exactly those
    elif extra_urls:
        urls += [u for u in extra_urls if u not in urls]

    resolved: list[tuple[str, JobSite]] = []
    for url in urls:
        try:
            site = resolve_job_site(url, session, remote_only=REMOTE_ONLY, country=JOB_COUNTRY)
        except (UnsupportedSiteError, requests.RequestException) as error:
            print(f"WARNING: skipping {url}: {type(error).__name__}: {error}")
            continue
        site.include_unmarked_remote = INCLUDE_UNMARKED_REMOTE
        for setting, value in SITE_SETTINGS.get(url, {}).items():
            if setting not in ("remote_only", "contract_only", "include_unmarked_remote"):
                raise ValueError(f"Unknown SITE_SETTINGS option {setting!r} for {url}")
            setattr(site, setting, value)
        if include_unmarked:
            site.include_unmarked_remote = True
        resolved.append((url, site))

    if not selectors:
        return [site for _, site in resolved]
    unmatched = [
        s for s in selectors if not any(_site_matches(site, url, s) for url, site in resolved)
    ]
    if unmatched:
        available = ", ".join(f"{site.name} ({site.kind})" for _, site in resolved)
        raise SiteSelectionError(
            f"--site {', '.join(unmatched)} matched nothing. Available: {available}. "
            "You can also pass a careers page or job board URL."
        )
    return [
        site
        for url, site in resolved
        if url in extra_urls or any(_site_matches(site, url, s) for s in selectors)
    ]


# --- Searching ----------------------------------------------------------------------

T = TypeVar("T")


def _run_parallel(
    calls: list[tuple[Any, Callable[[], T]]], workers: int
) -> list[tuple[Any, T | None, Exception | None]]:
    """Run ``(key, fn)`` calls on a thread pool; returns ``(key, result, error)``
    for each call, in the order given. RequestExceptions are returned as the
    error instead of raised."""
    if not calls:
        return []
    outcomes: dict[int, tuple[Any, T | None, Exception | None]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(calls)))) as pool:
        futures = {pool.submit(fn): index for index, (_, fn) in enumerate(calls)}
        for future in as_completed(futures):
            index = futures[future]
            key = calls[index][0]
            try:
                outcomes[index] = (key, future.result(), None)
            except requests.RequestException as error:
                outcomes[index] = (key, None, error)
    return [outcomes[index] for index in range(len(calls))]


def list_postings(session: requests.Session, site: JobSite, term: str) -> list[Posting]:
    """Walk a term's result pages and return every posting listed."""
    postings: list[Posting] = []
    for page in range(1, MAX_PAGES_PER_SEARCH + 1):
        result = site.fetch_page(session, term, page)
        postings.extend(result.postings)
        if not result.postings or not result.has_more:
            break
        if site.newest_first and _is_stale_page(result.postings):
            break
    return postings


def _passes_listing_filters(
    posting: Posting, site: JobSite, track: SearchTrack, *, details_loaded: bool
) -> bool:
    """Apply every check that doesn't need the description.

    Runs before the description is fetched, and again afterwards, because
    some sites only give the remote flag, job type, and exact date in the
    details. Before that, a value the site didn't give counts as a pass;
    afterwards, a missing job type counts as a fail, and so does a missing
    remote flag unless the site keeps unmarked-remote jobs.
    """
    title = posting.title
    if site.remote_only and not posting.is_remote:
        if posting.is_remote is False:
            return False  # marked hybrid / on-site
        if details_loaded and not site.include_unmarked_remote:
            return False  # the site never said
    if _is_international_title(title):
        return False
    if _is_bogus_alaska_location(posting.state, posting.city):
        return False
    if _is_outside_job_country(posting):
        return False
    if _is_placeholder_listing(title):
        return False
    if _has_unfamiliar_title_tech(title, track.profile.unfamiliar_tech if track.profile else None):
        return False
    if _title_names_growth_stack(title) and not track.growth_track:
        return False
    if _is_stale_posting(posting.posted_date):
        return False
    if track.growth_track and _is_senior_title(title):
        return False
    if site.contract_only and (posting.job_type or details_loaded):
        if not _is_contract_job(posting.job_type):
            return False
    return True


def evaluate_posting(posting: Posting, site: JobSite, track: SearchTrack) -> JobMatch | None:
    """Return a match if a posting (with its description loaded) qualifies for a track."""
    if not _passes_listing_filters(posting, site, track, details_loaded=True):
        return None
    matched_skills = score_posting(posting, track.skills)
    if len(matched_skills) < track.minimum_matches:
        return None
    if track.required_skills and not _any_same_skill(track.required_skills, matched_skills):
        return None

    min_years = extract_min_years(posting)
    if min_years is not None and min_years > MAX_YEARS_EXPERIENCE:
        return None
    if (
        track.growth_track
        and min_years is not None
        and min_years > GROWTH_TRACK_MAX_YEARS_EXPERIENCE
        and not looks_junior(posting)
    ):
        return None

    fit: FitScore = score_fit(posting, track.profile or candidate_profile(), min_years)
    period, period_estimated = salary_period(
        posting.salary_period, posting.description, posting.salary_low, posting.salary_high
    )
    return JobMatch(
        job_id=posting.job_id,
        title=posting.title,
        city=posting.city,
        state=posting.state,
        is_remote=posting.is_remote,
        job_type=posting.job_type or "Unknown",
        salary_low=posting.salary_low,
        salary_high=posting.salary_high,
        salary_period=period,
        salary_period_estimated=period_estimated,
        url=posting.url,
        track=track.name,
        posted_date=format_posted_date(posting.posted_date),
        matched_skills=matched_skills,
        min_years=min_years,
        company=posting.company,
        fit_score=fit.score,
        fit_breakdown=dict(fit.breakdown),
        fit_reasons=list(fit.reasons),
        description=posting.description or "",
    )


@dataclass
class SiteSearchResult:
    matches: list[JobMatch]
    searches: int
    failed_terms: list[str]
    # Jobs the site didn't mark on-site whose posting says they are:
    # job ID -> why (see check_work_arrangement).
    onsite: dict[str, str] = field(default_factory=dict)
    # Every job whose remote status this search checked.
    checked: set[str] = field(default_factory=set)


def _describe_evidence(why: str) -> str:
    """A phrase for logs and the dashboard: 'its title says "On-Site"',
    'its description: "..."', 'the site's workSetting = "Onsite"'."""
    if why.startswith(("its ", "the site")):
        return why  # already described
    if why.startswith(("title ", "description", "location ")):
        return f"its {why}"
    return f"the site's {why}" if "=" in why else why


def check_work_arrangement(posting: Posting) -> tuple[Posting, str | None, bool]:
    """Mark a posting not remote when its title, location, or description says
    it's on-site or hybrid, whatever the site's own remote flag says.

    Returns ``(posting, why, overridden)``: the posting (updated if needed);
    why it isn't remote, or None if it is (or may be); and whether that
    contradicts the site's main remote flag (worth logging).
    """
    if posting.is_remote is False:
        if posting.remote_note:
            return posting, posting.remote_note, True
        return posting, "the site marks it hybrid or on-site", False
    evidence = onsite_evidence(
        posting.title, posting.description, ", ".join(p for p in (posting.city, posting.state) if p)
    )
    if evidence is None:
        return posting, None, False
    return dataclasses.replace(posting, is_remote=False, remote_note=evidence), evidence, True


def search_site(
    session: requests.Session,
    site: JobSite,
    searches: list[tuple[SearchTrack, str]],
    descriptions: dict[str, Posting] | None = None,
) -> SiteSearchResult:
    """Search one site for every ``(track, term)`` pair, in three steps:

    1. List every term's postings, several terms at a time.
    2. Fetch the details (description) of every distinct posting that passes
       the cheap title/date/remote checks for at least one track, several at a
       time. A job listed under ten terms is fetched once.
    3. Score each (track, posting) pair. A job that qualifies more than once
       keeps its highest-scoring match.
    """
    descriptions = {} if descriptions is None else descriptions
    workers = MAX_CONCURRENT_REQUESTS_PER_SITE

    listed = _run_parallel(
        [((track, term), lambda term=term: list_postings(session, site, term))
         for track, term in searches],
        workers,
    )
    failed_terms = []
    errors = [error for _, _, error in listed if error is not None]
    if len(listed) > 1 and len(errors) == len(listed) and len({str(e) for e in errors}) == 1:
        # One failure behind every term (a board that couldn't be
        # downloaded, say): one line, not one per term.
        log(f"  {site.name}: couldn't be searched, skipping it: "
            f"{type(errors[0]).__name__}: {errors[0]}")
        failed_terms = [term for (_, term), _, _ in listed]
    else:
        for (_, term), _, error in listed:
            if error is not None:
                # Retries are already exhausted; skip this term rather than lose
                # every other term's matches (and the email).
                log(f"  {site.name}: search {term!r} FAILED, skipping: "
                    f"{type(error).__name__}: {error}")
                failed_terms.append(term)

    to_fetch: dict[str, Posting] = {}
    onsite: dict[str, str] = {}
    for (track, _), postings, _ in listed:
        for posting in postings or []:
            if posting.is_remote is False and posting.job_id not in onsite:
                # Dropped before its details load, but a saved copy may still
                # say remote (correct_saved_remote_flags fixes it from this).
                onsite[posting.job_id] = posting.remote_note or "the site marks it hybrid or on-site"
                if posting.remote_note:
                    log(f"  {site.name}: {posting.title!r} ({posting.job_id}) isn't remote: "
                        f"{_describe_evidence(posting.remote_note)}.")
            if posting.job_id in descriptions or posting.job_id in to_fetch:
                continue
            if _passes_listing_filters(posting, site, track, details_loaded=False):
                to_fetch[posting.job_id] = posting

    listed_count = len({p.job_id for _, postings, _ in listed for p in postings or []})
    log(f"  {site.name}: {listed_count} distinct listing(s); "
          f"loading {len(to_fetch)} job description(s) ...")
    details = _run_parallel(
        [(job_id, lambda posting=posting: site.fetch_details(session, posting)
          if posting.description is None else posting)
         for job_id, posting in to_fetch.items()],
        workers,
    )
    failed_details = 0
    for job_id, detailed, error in details:
        if error is None:
            checked, why, overridden = check_work_arrangement(detailed)
            descriptions[job_id] = checked
            if why:
                # Saved jobs are corrected from this (correct_saved_remote_flags).
                onsite[job_id] = why
            if overridden:
                # What the search results said, before the details were read.
                flag = {True: "marked remote", None: "not marked either way", False: "listed"}[
                    to_fetch.get(job_id, detailed).is_remote
                ]
                log(f"  {site.name}: {detailed.title!r} ({job_id}) is {flag}, but "
                    f"{_describe_evidence(why)}; treating it as not remote.")
        else:
            failed_details += 1
    if failed_details:
        log(f"  WARNING: {site.name}: {failed_details} job description(s) "
              "couldn't be loaded; those jobs were skipped.")

    best: dict[str, JobMatch] = {}
    for (track, _), postings, _ in listed:
        for posting in postings or []:
            detailed = descriptions.get(posting.job_id)
            if detailed is None:
                continue
            match = evaluate_posting(detailed, site, track)
            existing = best.get(posting.job_id)
            if match and (existing is None or match.score > existing.score):
                best[posting.job_id] = match

    # A last check on the jobs that would be kept as remote. On most sites it
    # costs nothing; Insight Global reads each one's job page for On-Site.
    if site.remote_only:
        verified = _run_parallel(
            [(job_id, lambda posting=descriptions[job_id]: site.verify_remote(session, posting))
             for job_id, match in best.items() if match.is_remote is not False],
            workers,
        )
        for job_id, why, _ in verified:
            if why:
                match = best.pop(job_id)
                onsite[job_id] = why
                log(f"  {site.name}: {match.title!r} ({job_id}) is marked remote, but "
                    f"{_describe_evidence(why)}; treating it as not remote.")
    return SiteSearchResult(
        list(best.values()), len(searches), failed_terms, onsite, set(descriptions) | set(onsite)
    )


def search_term(
    session: requests.Session,
    site: JobSite,
    term: str,
    track: SearchTrack,
    descriptions: dict[str, Posting] | None = None,
) -> list[JobMatch]:
    """Search one site for one term (``search_site`` for a single search)."""
    return search_site(session, site, [(track, term)], descriptions).matches


def _search_site_in_own_session(
    site: JobSite, tracks: tuple[SearchTrack, ...] = TRACKS
) -> SiteSearchResult:
    started = time.monotonic()
    searches = [(track, term) for track in tracks for term in track.terms]
    log(f"Searching {site.name} ({site.kind}) for {len(searches)} term(s) ...")
    with build_session() as session:
        result = search_site(session, site, searches)
    unmarked = sum(1 for match in result.matches if match.is_remote is None)
    log(f"{site.name}: {len(result.matches)} qualifying match(es)"
        f"{f' ({unmarked} not marked remote or on-site)' if unmarked else ''} "
        f"in {time.monotonic() - started:.0f}s.")
    return result


def run_all_searches(
    site_selectors: list[str] | None = None,
    include_unmarked: bool = False,
    onsite: dict[str, str] | None = None,
    checked: set[str] | None = None,
    tracks: tuple[SearchTrack, ...] | None = None,
) -> list[JobMatch]:
    """Search every site (or those ``site_selectors`` pick) at the same time.

    ``onsite``, if given, is filled with the jobs whose posting says on-site or
    hybrid although the site didn't mark them so (job ID -> why). ``tracks``
    defaults to ``TRACKS`` (the default skills); ``main`` passes the tracks
    for the skills saved in the dashboard.
    """
    tracks = tracks or TRACKS
    with build_session() as session:
        sites = resolve_sites(
            session, selectors=site_selectors, include_unmarked=include_unmarked
        )
    if not sites:
        raise RuntimeError("None of JOB_SEARCH_URLS could be resolved to a job site.")

    all_matches: dict[str, JobMatch] = {}
    failed_searches: list[str] = []
    # Sites where every search failed, listed by name instead of term by term.
    failed_sites: list[str] = []
    total_searches = 0
    with ThreadPoolExecutor(max_workers=len(sites)) as pool:
        futures = [
            (site, pool.submit(_search_site_in_own_session, site, tracks)) for site in sites
        ]
        for site, future in futures:
            result = future.result()
            total_searches += result.searches
            failed_searches.extend(f"{site.name}: {term}" for term in result.failed_terms)
            if result.failed_terms and len(result.failed_terms) == result.searches:
                failed_sites.append(site.name)
            if onsite is not None:
                onsite.update(result.onsite)
            if checked is not None:
                checked.update(result.checked)
            for job in result.matches:
                existing = all_matches.get(job.job_id)
                if existing is None or job.score > existing.score:
                    all_matches[job.job_id] = job

    if failed_searches and len(failed_searches) == total_searches:
        raise RuntimeError("Every search failed; the job sites may be unreachable.")
    if failed_searches:
        shown = [f"{name} (every search)" for name in failed_sites] + [
            search for search in failed_searches if search.split(": ", 1)[0] not in failed_sites
        ]
        print(f"WARNING: {len(failed_searches)} search(es) failed: {shown}")

    track_order = {track.name: index for index, track in enumerate(tracks)}

    def sort_key(job: JobMatch) -> tuple[int, int, str]:
        order = track_order[job.track]
        # Best fit first within each track, then newest first.
        fit = -(job.fit_score if job.fit_score is not None else -1)
        # Negate the date string so that later dates sort first
        # (ISO-format dates compare lexicographically).
        inverted_date = (
            "".join(chr(0xFF - ord(c)) for c in job.posted_date)
            if job.posted_date
            else "\xff"  # push undated jobs to the end
        )
        return order, fit, inverted_date

    return sorted(all_matches.values(), key=sort_key)


def format_salary(job: JobMatch) -> str:
    """"$60 - $65/hr", "From $140,000/yr", "From $64/hr (est.)", ... (salary.py)."""
    return format_pay(job.salary_low, job.salary_high, job.salary_period, job.salary_period_estimated)


REMOTE_LABELS = {
    True: "Remote",
    None: "<strong>Remote not stated: check the posting</strong>",
    False: "Not remote",
}


def build_email_body(jobs: list[JobMatch]) -> str:
    """Return an HTML email body with clickable job-title hyperlinks."""
    import html as html_module

    companies = ", ".join(sorted({job.company for job in jobs if job.company}))
    lines = [
        "<html><body>",
        f"<p><strong>{len(jobs)} new job match(es)"
        f"{f' from {html_module.escape(companies)}' if companies else ''} — "
        f"{datetime.now():%Y-%m-%d %H:%M}</strong></p>",
    ]
    current_track: str | None = None
    for job in jobs:
        if job.track != current_track:
            current_track = job.track
            lines.append(f"<h3>{html_module.escape(current_track)}</h3>")
        years = (
            f"est. {job.min_years}+ yrs required"
            if job.min_years is not None
            else "years required: not stated"
        )
        skill_text = (
            f"{job.score} skill match{'es' if job.score != 1 else ''}: "
            f"{', '.join(job.matched_skills)}"
        )
        posted = (
            f" &nbsp;|&nbsp; Posted: {html_module.escape(job.posted_date)}"
            if job.posted_date
            else ""
        )
        company = f"{html_module.escape(job.company)} &nbsp;|&nbsp; " if job.company else ""
        fit = (
            f"<strong>Fit {job.fit_score}/100 ({job.fit_label})</strong> &nbsp;|&nbsp; "
            if job.fit_score is not None
            else ""
        )
        remote = REMOTE_LABELS[job.is_remote]
        location = ", ".join(part for part in (job.city, job.state) if part)
        lines.append(
            f'<p><a href="{html_module.escape(job.url)}">'
            f"{html_module.escape(job.title)}</a> "
            f"({html_module.escape(skill_text)})<br>"
            f"{fit}"
            f"{company}"
            f"{html_module.escape(location or 'Location not listed')}"
            f" &nbsp;|&nbsp; {remote}"
            f" &nbsp;|&nbsp; {html_module.escape(job.job_type)}"
            f" &nbsp;|&nbsp; {html_module.escape(format_salary(job))}"
            f" &nbsp;|&nbsp; {html_module.escape(years)}"
            f"{posted}"
            f" &nbsp;|&nbsp; Job ID: {html_module.escape(job.job_id)}</p>"
        )
    lines.append("</body></html>")
    return "\n".join(lines)


class EmailNotConfiguredError(RuntimeError):
    """The digest has nowhere to go: IG_EMAIL_TO isn't set."""


def _email_required() -> bool:
    """IG_REQUIRE_EMAIL=true (set on Render) makes missing email setup fatal."""
    return os.environ.get("IG_REQUIRE_EMAIL", "").strip().lower() in ("1", "true", "yes")


def _email_setup() -> tuple[Any, str]:
    """Return ``(gmail service, recipient)``.

    Raises ``EmailNotConfiguredError`` / ``GmailNotConfiguredError`` when
    email simply hasn't been set up. Anything else (an expired token, a
    network error) is a real failure and propagates as is.
    """
    recipient = os.environ.get("IG_EMAIL_TO", "").strip()
    if not recipient:
        raise EmailNotConfiguredError(
            "IG_EMAIL_TO is not set. Add it to backend/.env (see .env.example)."
        )
    return get_gmail_service(), recipient


@dataclass
class RunSummary:
    """What one run did; returned by ``main()`` (the API reports it to the dashboard)."""

    total_matches: int
    new_matches: int
    # Jobs in this run's digest: the new ones plus any an earlier run failed to email.
    emailed_matches: int
    email_sent: bool
    gmail_message_id: str | None = None
    # Set when the digest was skipped because Gmail / IG_EMAIL_TO isn't set up.
    email_skipped_reason: str | None = None


def correct_saved_remote_flags(store: FirestoreJobStore, found: dict[str, str]) -> int:
    """Mark saved jobs not remote when their posting says on-site or hybrid.

    ``found`` is what this run's search read in the descriptions of jobs it
    saw again. Every saved job's title and location are checked too, so jobs
    saved before this check existed are fixed even if they're no longer listed.
    Returns how many jobs were changed.
    """
    fixes: dict[str, str] = {}
    for doc_id, data in store.list_job_documents():
        if data.get("is_remote") is False or data.get("work_arrangement"):
            continue  # already not remote, or you've said how it's worked
        location = ", ".join(str(data.get(key) or "") for key in ("city", "state") if data.get(key))
        reason = found.get(doc_id) or onsite_evidence(str(data.get("title") or ""), "", location)
        if reason:
            # A phrase that reads after "Listed as remote, but ..." in the dashboard.
            fixes[doc_id] = _describe_evidence(reason)
    store.mark_not_remote(fixes)
    if fixes:
        print(f"Marked {len(fixes)} saved job(s) not remote because the posting says on-site "
              "or hybrid (see each job's not_remote_reason).")
    return len(fixes)


def main(
    store: FirestoreJobStore | None = None,
    site_selectors: list[str] | None = None,
    include_unmarked: bool = False,
) -> RunSummary:
    """Search, save every match, and email the new ones.

    Shared by the command line (``python job_search.py``, which the cron job
    runs) and the HTTP API (``api.py``, which the dashboard calls).
    """
    store = store or get_job_store()
    print(f"Job state: {store.description}")
    seen_ids = store.load_seen_ids()
    unemailed_ids = store.load_unemailed_ids()
    onsite: dict[str, str] = {}
    checked: set[str] = set()
    tracks = build_tracks(search_skills_for_run(store))
    all_matches = run_all_searches(site_selectors, include_unmarked, onsite, checked, tracks=tracks)

    brand_new = [job for job in all_matches if job.job_id not in seen_ids]
    # Re-send anything a previous run saved but failed to email.
    to_email = [
        job for job in all_matches
        if job.job_id not in seen_ids or job.job_id in unemailed_ids
    ]

    print(f"\nTotal qualifying matches this run: {len(all_matches)}")
    print(f"New (never seen before): {len(brand_new)}")
    if len(to_email) > len(brand_new):
        print(f"Retrying from an earlier failed email: {len(to_email) - len(brand_new)}")

    # Save first so nothing is lost if Gmail fails; new jobs start as
    # "unemailed" and flip to "emailed" below once the digest is accepted.
    store.save_matches(all_matches, new_ids={job.job_id for job in brand_new})
    print(f"Saved {len(all_matches)} match(es).")
    correct_saved_remote_flags(store, onsite)
    if RECHECK_SAVED_JOBS:
        recheck_saved_jobs(store, skip=checked | set(onsite), selectors=site_selectors)
    # Re-score the saved jobs this run didn't match, in case your skills
    # changed. Only descriptions already saved are used (no site requests).
    reassess_saved_jobs(store, fetch_missing=False)

    message_id: str | None = None
    if to_email:
        try:
            service, recipient = _email_setup()
            message_id = send_email(
                service,
                f"Job search: {len(to_email)} new job match(es)",
                build_email_body(to_email),
                recipient,
                html=True,
            )
        except (EmailNotConfiguredError, GmailNotConfiguredError) as error:
            store.log_run(
                total_matches=len(all_matches),
                new_job_ids=sorted(job.job_id for job in to_email),
                email_sent=False,
                error=f"Email not set up: {error}",
            )
            if _email_required():
                raise
            print(f"\nEmail is not set up, so no email was sent: {error}")
            print(
                f"{len(to_email)} job(s) stay 'unemailed' and will be emailed on the "
                "first run after Gmail is set up (see README.md, Gmail API setup)."
            )
            return RunSummary(
                total_matches=len(all_matches),
                new_matches=len(brand_new),
                emailed_matches=0,
                email_sent=False,
                email_skipped_reason=str(error),
            )
        except Exception as error:
            store.log_run(
                total_matches=len(all_matches),
                new_job_ids=sorted(job.job_id for job in to_email),
                email_sent=False,
                error=f"{type(error).__name__}: {error}",
            )
            print(f"Email failed; {len(to_email)} job(s) left as 'unemailed' for next run.")
            raise
        store.mark_emailed([job.job_id for job in to_email], message_id)
        print(f"Email sent ({message_id}).")
    else:
        print("Nothing new to email.")

    store.log_run(
        total_matches=len(all_matches),
        new_job_ids=sorted(job.job_id for job in to_email),
        email_sent=message_id is not None,
        gmail_message_id=message_id,
    )
    return RunSummary(
        total_matches=len(all_matches),
        new_matches=len(brand_new),
        emailed_matches=len(to_email) if message_id is not None else 0,
        email_sent=message_id is not None,
        gmail_message_id=message_id,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job_search.py",
        description="Search the job sites in JOB_SEARCH_URLS, save matches, and email new ones.",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="use local_firestore.json (or IG_LOCAL_DB_PATH) instead of Firebase, "
        "even if Firebase is configured",
    )
    parser.add_argument(
        "--site",
        action="append",
        metavar="NAME_OR_URL",
        dest="sites",
        help="search only this site: a name (accenture, 'insight global'), a board "
        "kind (workday, greenhouse, lever, ashby, insight-global, himalayas, remoteok, "
        "jobicy, weworkremotely), or any careers page / job board URL, even one not in "
        "JOB_SEARCH_URLS. Repeat for several.",
    )
    parser.add_argument(
        "--include-unmarked",
        action="store_true",
        help="also keep jobs whose site doesn't say whether they're remote (saved "
        "with is_remote null; filter them in the dashboard). Jobs marked hybrid or "
        "on-site are still dropped.",
    )
    parser.add_argument(
        "--check-remote",
        action="append",
        metavar="URL_OR_JOB_ID",
        help="explain how the search reads one job's remote status: the site's own "
        "fields, the verdict, and the description lines that decided it. Takes a "
        "posting URL or a saved job ID (from the dashboard); repeat for several.",
    )
    parser.add_argument(
        "--recheck-saved",
        action="store_true",
        help="without searching or emailing, re-check every saved job marked remote "
        "against its posting, mark the on-site/hybrid ones not remote, and write "
        "each job's verdict to remote_check_report.txt (with --site, only those sites)",
    )
    parser.add_argument(
        "--reassess",
        action="store_true",
        help="without searching or emailing, re-score every saved job against your "
        "current skills (the dashboard's Skills page): matched skills, fit score, and "
        "whether it still matches. Descriptions not saved yet are loaded from the job sites once.",
    )
    parser.add_argument(
        "--list-sites",
        action="store_true",
        help="show the configured sites and how each one is read, then exit",
    )
    return parser


# Lines of a description worth showing when checking a job's remote status.
ARRANGEMENT_WORDS = re.compile(
    r"on[- ]?site|onsite|hybrid|in[- ]office|in the office|in[- ]person|remote|local to|"
    r"days? (?:a|per) week|commut|relocat",
    re.IGNORECASE,
)


def _site_for(target: str, session: requests.Session, store: FirestoreJobStore | None):
    """Work out (site, url, native ID) for a job URL or a saved job ID."""
    native_id = ""
    url = target
    if not re.match(r"https?://", target):
        saved = (store or get_job_store(verbose=False)).get_job(target)
        if saved is None:
            raise SiteSelectionError(f"{target!r} is neither a job URL nor a saved job ID.")
        url = str(saved.get("url") or "")
        for site in resolve_sites(session):
            if target.startswith(site.id_prefix):
                return site, url, target[len(site.id_prefix):]
        raise SiteSelectionError(f"No configured site makes job IDs like {target!r}.")
    parsed = urlparse(url)
    host, path = (parsed.hostname or "").lower(), parsed.path + "/"
    for site in resolve_sites(session):
        board = urlparse(str(getattr(site, "board_url", "") or ""))
        token = str(getattr(site, "board_token", "") or "")
        if site.kind == "insight-global" and host.endswith("insightglobal.com"):
            return site, url, native_id
        if board.hostname == host and f"{board.path}/" in path:  # a Workday board
            return site, url, native_id
        if token and host.endswith("greenhouse.io") and f"/{token}/" in path:
            return site, url, native_id
    # Not a configured site: resolve it on its own (any Workday/Greenhouse board).
    return resolve_job_site(url, session, remote_only=REMOTE_ONLY, country=JOB_COUNTRY), url, native_id


def _fill_from_search(site: JobSite, posting: Posting, saved: dict[str, Any] | None) -> Posting:
    """Fill in what a lookup couldn't find (its title, the site's remote flag)
    from the saved job."""
    changes: dict[str, Any] = {}
    if saved and saved.get("title") and posting.title.startswith("("):
        changes["title"] = str(saved["title"])
    if posting.is_remote is None:
        if saved and isinstance(saved.get("is_remote"), bool):
            changes["is_remote"] = saved["is_remote"]

    return dataclasses.replace(posting, **changes) if changes else posting


def _short_fields(payload: Any, prefix: str = "") -> list[str]:
    """Every short, non-description field in a site's JSON, as "key: value"."""
    lines = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            name = f"{prefix}{key}"
            if isinstance(value, dict):
                lines += _short_fields(value, f"{name}.")
            elif isinstance(value, list) and all(isinstance(v, dict) for v in value) and value:
                for index, item in enumerate(value[:5]):
                    lines += _short_fields(item, f"{name}[{index}].")
            elif value not in (None, "", []) and len(str(value)) <= 80:
                lines.append(f"{name}: {value}")
    return lines


def _verified(site: JobSite, session: requests.Session, posting: Posting) -> Posting:
    """``posting``, marked not remote if the site's last check (verify_remote:
    Insight Global's job page) says it isn't."""
    if not site.remote_only or posting.is_remote is False:
        return posting
    why = site.verify_remote(session, posting)
    return dataclasses.replace(posting, is_remote=False, remote_note=why) if why else posting


def _page_lines(site: JobSite, session: requests.Session, posting: Posting) -> list[str]:
    """For --check-remote: what the job's page says (Insight Global only)."""
    check = getattr(site, "check_job_page", None)
    if check is None or not getattr(site, "reads_job_pages", False):
        return []
    try:
        page = check(session, posting)
    except requests.RequestException as error:
        return [f"Couldn't load the job page: {type(error).__name__}: {error}"]
    if not page.lines:
        return [f"The job page ({page.url}) doesn't include the job in its HTML (the browser "
                "fills it in), so only the site's data above was checked."]
    mentions = [line for line in page.lines if ARRANGEMENT_WORDS.search(line)]
    lines = [f"Job page ({page.url}), lines about where you'd work:" if mentions
             else f"The job page ({page.url}) doesn't mention on-site, hybrid, office, or remote."]
    return lines + [f"  | {line[:200]}" for line in mentions[:15]]


def explain_posting(site: JobSite, posting: Posting, payload: Any) -> tuple[Posting, list[str]]:
    """The remote verdict for one job, and why, as printable lines."""
    checked, why, _ = check_work_arrangement(posting)
    lines = [f"{site.name}: {posting.title}", f"Posting: {posting.url}"]
    flag = {True: "remote", False: "not remote", None: "not stated"}[posting.is_remote]
    lines.append(f"Site's own data says: {flag}"
                 + (f" ({posting.remote_note})" if posting.remote_note else ""))
    if checked.is_remote is False:
        reason = _describe_evidence(why or "")
        lines.append(f"VERDICT: NOT REMOTE. {reason[:1].upper()}{reason[1:]}.")
    elif checked.is_remote is None:
        lines.append("VERDICT: remote status not stated (kept only with --include-unmarked).")
    else:
        lines.append("VERDICT: remote. No on-site or hybrid wording found.")
    fields = [line for line in _short_fields(payload)
              if not re.search(r"description|content|jobDescription", line.split(":")[0], re.I)]
    lines.append("Fields in the site's data:" if fields else "No short fields in the site's data.")
    lines += [f"  {line}" for line in fields[:60]]
    mentions = [line for line in (checked.description or "").split("\n") if ARRANGEMENT_WORDS.search(line)]
    lines.append("Description lines about where you'd work:" if mentions
                 else "The description doesn't mention on-site, hybrid, office, or remote.")
    lines += [f"  | {line[:200]}" for line in mentions[:15]]
    return checked, lines


def check_remote(targets: list[str], store: FirestoreJobStore | None = None) -> int:
    """Explain how the search reads one job's remote status (--check-remote)."""
    status = 0
    with build_session() as session:
        for target in targets:
            print(f"\n=== {target}")
            try:
                site, url, native_id = _site_for(target, session, store)
                saved = None
                if not re.match(r"https?://", target):
                    saved = (store or get_job_store(verbose=False)).get_job(target)
                posting, payload = site.lookup(
                    session, url, native_id, title=str((saved or {}).get("title") or "")
                )
                posting = _fill_from_search(site, posting, saved)
            except (SiteSelectionError, UnsupportedSiteError, requests.RequestException) as error:
                print(f"Couldn't check it: {type(error).__name__}: {error}")
                status = 1
                continue
            posting = _verified(site, session, posting)
            for line in explain_posting(site, posting, payload)[1]:
                print(line)
            for line in _page_lines(site, session, posting):
                print(line)
    print("\nIf a job says on-site but the verdict is remote, send this output so the check "
          "can learn its wording.")
    return status


def recheck_saved_jobs(
    store: FirestoreJobStore,
    skip: set[str] | None = None,
    selectors: list[str] | None = None,
    report: Path | None = None,
) -> int:
    """Re-check saved jobs marked remote that this run's search didn't check.

    A job saved before the on-site checks existed (or before they learned a
    wording) is only corrected when the search sees it again, and a search
    doesn't see every saved job again: postings close, and each term only
    reads its newest pages. So each such job's posting is loaded on its own
    and checked; jobs that turn out on-site or hybrid are marked not remote.
    With ``report``, every re-checked job's verdict and the lines behind it
    are written there. Returns how many jobs were changed.
    """
    skip = skip or set()
    with build_session() as session:
        sites = resolve_sites(session, selectors=selectors)
        targets = []
        for doc_id, data in store.list_job_documents():
            if data.get("is_remote") is False or doc_id in skip or not data.get("url"):
                continue
            if data.get("work_arrangement"):
                continue  # you've said how it's worked
            site = next((s for s in sites if doc_id.startswith(s.id_prefix)), None)
            # Sites that can't load one job (the remote job boards, Lever)
            # only see their jobs again in a search.
            if site is not None and site.supports_lookup:
                targets.append((doc_id, data, site))
        if not targets:
            return 0
        print(f"Re-checking {len(targets)} saved remote job(s) this search didn't check ...")

        def load(doc_id: str, data: dict[str, Any], site: JobSite) -> Any:
            try:
                posting, payload = site.lookup(
                    session, str(data["url"]), doc_id[len(site.id_prefix):], title=str(data.get("title") or "")
                )
            except UnsupportedSiteError as error:
                return error
            return _verified(site, session, _fill_from_search(site, posting, data)), payload

        results = _run_parallel(
            [((doc_id, data, site), lambda d=doc_id, v=data, s=site: load(d, v, s))
             for doc_id, data, site in targets],
            MAX_CONCURRENT_REQUESTS_PER_SITE,
        )
    fixes: dict[str, str] = {}
    texts: dict[str, str] = {}
    unavailable = 0
    sections: list[str] = []
    for (doc_id, data, site), result, error in results:
        if error is not None or isinstance(result, Exception) or result is None:
            unavailable += 1
            sections.append(f"=== {doc_id}\n{data.get('title')}: couldn't load the posting "
                            f"(it may be closed): {error or result}")
            continue
        posting, payload = result
        if posting.description:
            texts[doc_id] = posting.description  # for reassessing it against your skills
        checked, lines = explain_posting(site, posting, payload)
        if checked.is_remote is False:
            fixes[doc_id] = _describe_evidence(checked.remote_note or "the site marks it hybrid or on-site")
            print(f"  {site.name}: {data.get('title')!r} ({doc_id}) isn't remote: {fixes[doc_id]}.")
        sections.append(f"=== {doc_id}\n" + "\n".join(lines))
    store.mark_not_remote(fixes)
    store.save_descriptions(texts)
    print(f"Re-checked {len(targets)} saved job(s): {len(fixes)} marked not remote"
          + (f", {unavailable} couldn't be loaded (closed postings?)" if unavailable else "") + ".")
    if report is not None:
        report.write_text("\n\n".join(sections) + "\n")
        print(f"Every re-checked job's verdict, fields, and description lines: {report}")
    return len(fixes)


# --- Reassessing saved jobs against your skills -------------------------------------

# The fields a reassessment rewrites; everything else about a job (status,
# notes, remote status, ...) is left alone.
REASSESSED_FIELDS = (
    "matched_skills", "score", "fit_score", "fit_breakdown", "fit_reasons",
    "matches_skills", "skills_mismatch_reason",
)


@dataclass
class ReassessSummary:
    """What ``reassess_saved_jobs`` did; the API returns it to the dashboard."""

    # Every saved job, and how many of them were re-scored.
    total_jobs: int
    reassessed: int
    # Re-scored jobs whose skills, fit score, or match changed (only these are written).
    changed: int
    # Re-scored jobs that wouldn't match your skills now (flagged, never deleted).
    no_longer_match: int
    # Descriptions loaded from the job sites this time (saved for next time).
    fetched: int
    # Jobs left as they were because their description couldn't be loaded
    # (closed postings, or a site that's no longer in JOB_SEARCH_URLS).
    unavailable: int
    # "saved": your list from the dashboard; "default": the lists in this file.
    skills_source: str


def skills_mismatch(posting: Posting, track: SearchTrack, matched: list[str]) -> str | None:
    """Why a saved job wouldn't be a match on ``track`` any more, or None if
    it still is. Only the checks your skills affect; the rest (remote, age,
    location, ...) were settled when the search found it. Reads after "No
    longer matches your skills: ..."."""
    unfamiliar = track.profile.unfamiliar_tech if track.profile else NON_RESUME_TITLE_TECH
    named = [tech for tech in unfamiliar if _contains_skill(posting.title, tech)]
    if named:
        return f"its title names {named[0]}, which isn't one of your skills"
    if len(matched) < track.minimum_matches:
        if not matched:
            return "it doesn't mention any of your skills"
        return (f"it mentions only {', '.join(matched)}; a match needs "
                f"{track.minimum_matches} of your skills")
    if track.required_skills and not _any_same_skill(track.required_skills, matched):
        return f"it mentions {', '.join(matched)}, but none of your core skills"
    return None


def saved_salary_period(data: dict[str, Any], description: str | None) -> dict[str, Any]:
    """The ``salary_period`` fields a saved job should have, or {} if it has
    them already. A period the site or posting stated is kept; an estimate
    (or a job saved before periods were kept) is worked out again from the
    description and amounts. The site's own field isn't saved, so a search
    that finds the job again is what brings that back."""
    if data.get("salary_period") in PERIODS and data.get("salary_period_estimated") is False:
        return {}

    def amount(value: Any) -> float:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

    period, estimated = salary_period(
        "", description, amount(data.get("salary_low")), amount(data.get("salary_high"))
    )
    fields = {"salary_period": period, "salary_period_estimated": estimated}
    return fields if any(data.get(key) != value for key, value in fields.items()) else {}


def assess_saved_job(
    data: dict[str, Any], description: str, tracks: tuple[SearchTrack, ...]
) -> dict[str, Any]:
    """Re-score one saved job (its stored fields plus its description) on the
    track it was found on: its matched skills, fit score, and whether it
    still matches. Returns the ``REASSESSED_FIELDS``."""
    track = next((t for t in tracks if t.name == data.get("track")), tracks[0])
    posting = Posting(
        job_id=str(data.get("job_id") or ""),
        title=str(data.get("title") or ""),
        url=str(data.get("url") or ""),
        company=str(data.get("company") or ""),
        # What the search decided (the fit score's remote part); your own
        # work_arrangement doesn't change the score, like in the search.
        is_remote=data.get("is_remote") if isinstance(data.get("is_remote"), bool) else None,
        description=description,
    )
    matched = score_posting(posting, track.skills)
    fit = score_fit(posting, track.profile or candidate_profile(), extract_min_years(posting))
    reason = skills_mismatch(posting, track, matched)
    return {
        "matched_skills": matched,
        "score": len(matched),
        "fit_score": fit.score,
        "fit_breakdown": dict(fit.breakdown),
        "fit_reasons": list(fit.reasons),
        "matches_skills": reason is None,
        "skills_mismatch_reason": reason,
    }


def fetch_missing_descriptions(
    jobs: list[tuple[str, dict[str, Any]]], selectors: list[str] | None = None
) -> tuple[dict[str, str], int]:
    """Load the descriptions of saved jobs from their sites. Returns
    ``(texts by job ID, how many couldn't be loaded)``."""
    if not jobs:
        return {}, 0
    with build_session() as session:
        sites = resolve_sites(session, selectors=selectors)
        targets = []
        unavailable = 0
        for doc_id, data in jobs:
            site = next((s for s in sites if doc_id.startswith(s.id_prefix)), None)
            if site is None or not data.get("url"):
                unavailable += 1
                continue
            targets.append((doc_id, data, site))
        print(f"Loading {len(targets)} saved job description(s) from the job sites (once; "
              "they're kept for next time) ...")

        def load(doc_id: str, data: dict[str, Any], site: JobSite) -> str:
            try:
                return site.fetch_description(
                    session, str(data["url"]), doc_id[len(site.id_prefix):], str(data.get("title") or "")
                )
            except requests.RequestException:
                raise  # counted by _run_parallel
            except Exception as error:  # noqa: BLE001 - one odd posting mustn't stop the rest
                log(f"  {site.name}: couldn't read {doc_id}'s description: {type(error).__name__}: {error}")
                return ""

        # Sites are loaded side by side; HOST_THROTTLE still spaces out the
        # requests to each host.
        results = _run_parallel(
            [(doc_id, lambda d=doc_id, v=data, s=site: load(d, v, s)) for doc_id, data, site in targets],
            MAX_CONCURRENT_REQUESTS_PER_SITE * max(1, len({id(s) for _, _, s in targets})),
        )
    texts = {doc_id: text for doc_id, text, error in results if error is None and text and text.strip()}
    return texts, unavailable + len(targets) - len(texts)


def reassess_saved_jobs(
    store: FirestoreJobStore,
    fetch_missing: bool = True,
    selectors: list[str] | None = None,
) -> ReassessSummary:
    """Re-score every saved job against your current skills.

    Each job's matched skills and fit score are worked out again from its
    saved description, on the track it was found on. Jobs that wouldn't match
    now are flagged (``matches_skills`` false, with ``skills_mismatch_reason``),
    never deleted; their status and notes are left alone. Jobs saved before
    descriptions were kept have theirs loaded from the job site first
    (``fetch_missing``; once, they're saved for next time). Only jobs whose
    fields change are written.
    """
    saved = saved_search_skills(store)
    tracks = build_tracks(saved)
    jobs = store.list_job_documents()
    texts = store.load_descriptions()

    fetched: dict[str, str] = {}
    missing = [(doc_id, data) for doc_id, data in jobs if doc_id not in texts]
    unavailable = len(missing)
    if missing and fetch_missing:
        fetched, unavailable = fetch_missing_descriptions(missing, selectors)
        store.save_descriptions(fetched)
        texts.update(fetched)

    changes: dict[str, dict[str, Any]] = {}
    # Salary periods for jobs saved without one (they aren't skill changes,
    # so they're written but not counted as changed).
    pay_fixes: dict[str, dict[str, Any]] = {}
    reassessed = no_longer_match = 0
    for doc_id, data in jobs:
        pay = saved_salary_period(data, texts.get(doc_id))
        if pay:
            pay_fixes[doc_id] = pay
        if doc_id not in texts:
            continue
        fields = assess_saved_job(data, texts[doc_id], tracks)
        reassessed += 1
        no_longer_match += not fields["matches_skills"]
        if any(data.get(key) != value for key, value in fields.items()):
            changes[doc_id] = fields
    store.update_jobs({
        doc_id: {**pay_fixes.get(doc_id, {}), **changes.get(doc_id, {})}
        for doc_id in {*changes, *pay_fixes}
    })

    summary = ReassessSummary(
        total_jobs=len(jobs),
        reassessed=reassessed,
        changed=len(changes),
        no_longer_match=no_longer_match,
        fetched=len(fetched),
        unavailable=unavailable,
        skills_source="saved" if saved else "default",
    )
    if not unavailable:
        left_out = ""
    elif fetch_missing:
        left_out = f"; {unavailable} left as they were (couldn't load the posting: closed?)"
    else:
        left_out = (f"; {unavailable} left as they were (no saved description yet: "
                    "`job_search.py --reassess` or the dashboard's Refresh loads them)")
    print(f"Reassessed {reassessed} saved job(s) against your skills: {len(changes)} changed, "
          f"{no_longer_match} no longer match{left_out}.")
    return summary


def list_sites() -> None:
    with build_session() as session:
        sites = resolve_sites(session)
    for site in sites:
        board = getattr(site, "board_url", None) or getattr(site, "api_url", "")
        print(f"{site.name:<16} {site.kind:<15} {site.search_url}")
        if board and board != site.search_url:
            print(f"{'':<16} {'':<15} -> {board}")


def cli(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_sites:
        list_sites()
        return 0
    if args.check_remote:
        store = FirestoreJobStore.local() if args.local else None
        return check_remote(args.check_remote, store)
    if args.reassess:
        store = FirestoreJobStore.local() if args.local else get_job_store()
        reassess_saved_jobs(store)
        return 0
    if args.recheck_saved:
        store = FirestoreJobStore.local() if args.local else get_job_store()
        try:
            recheck_saved_jobs(store, selectors=args.sites, report=REMOTE_CHECK_REPORT)
        except SiteSelectionError as error:
            print(f"job_search.py: error: {error}", file=sys.stderr)
            return 2
        return 0
    store = FirestoreJobStore.local() if args.local else None
    try:
        main(store, site_selectors=args.sites, include_unmarked=args.include_unmarked)
    except SiteSelectionError as error:
        print(f"job_search.py: error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(cli())
