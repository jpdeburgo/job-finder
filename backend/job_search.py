"""Search job sites (Insight Global, Accenture, ...) and email new matches through the Gmail API."""

from __future__ import annotations

import argparse
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar
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
    resolve_job_site,
)
from job_boards import ACCENTURE_SEARCH_URL, INSIGHT_GLOBAL_URL, JOB_SEARCH_URLS
from job_fit import CandidateProfile, FitScore, fit_label, score_fit
from job_store import FirestoreJobStore, get_job_store

load_dotenv()

SEARCH_TITLES = [
    "Software Engineer",
    "Senior Software Engineer",
    "Full Stack Developer",
    "Backend Developer",
    "Frontend Developer",
    "React Developer",
]
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
#   (boards.greenhouse.io/<company>), and Lever (jobs.lever.co/<company>)
#   board URLs work as-is, and so do careers pages that link to one of those.
# To add a company, add its URL to job_boards.py and to JOB_SEARCH_URLS there.

# Per-URL overrides of a site's filters: "remote_only" (defaults to
# REMOTE_ONLY), "include_unmarked_remote" (defaults to INCLUDE_UNMARKED_REMOTE),
# and "contract_only" (on for Insight Global, off elsewhere), e.g.
#   ACCENTURE_SEARCH_URL: {"include_unmarked_remote": True},
SITE_SETTINGS: dict[str, dict[str, bool]] = {}
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


TRACKS = (
    SearchTrack(
        "Core matches (your main stack)",
        tuple(SEARCH_TITLES + EXTRA_SEARCH_TERMS),
        tuple(RESUME_SKILLS),
        MIN_SKILL_MATCHES,
        required_skills=tuple(CORE_LANGUAGE_SKILLS),
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


def _has_unfamiliar_title_tech(title: str) -> bool:
    """Return True when the title names a stack that isn't on the resume."""
    return any(_contains_skill(title, tech) for tech in NON_RESUME_TITLE_TECH)


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


def candidate_profile() -> CandidateProfile:
    """Your profile for the fit score, from the settings at the top of this file."""
    return CandidateProfile(
        skills=tuple(RESUME_SKILLS),
        core_skills=tuple(CORE_LANGUAGE_SKILLS),
        years_experience=YEARS_OF_EXPERIENCE,
        target_roles=tuple(TARGET_ROLE_TITLES),
        generic_roles=tuple(GENERIC_ROLE_TITLES),
        unfamiliar_tech=tuple(NON_RESUME_TITLE_TECH),
        skill_aliases=tuple(tuple(group) for group in SKILL_ALIASES),
    )


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
    if _has_unfamiliar_title_tech(title):
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
    if track.required_skills and not set(track.required_skills) & set(matched_skills):
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

    fit: FitScore = score_fit(posting, candidate_profile(), min_years)
    return JobMatch(
        job_id=posting.job_id,
        title=posting.title,
        city=posting.city,
        state=posting.state,
        is_remote=posting.is_remote,
        job_type=posting.job_type or "Unknown",
        salary_low=posting.salary_low,
        salary_high=posting.salary_high,
        url=posting.url,
        track=track.name,
        posted_date=format_posted_date(posting.posted_date),
        matched_skills=matched_skills,
        min_years=min_years,
        company=posting.company,
        fit_score=fit.score,
        fit_breakdown=dict(fit.breakdown),
        fit_reasons=list(fit.reasons),
    )


@dataclass
class SiteSearchResult:
    matches: list[JobMatch]
    searches: int
    failed_terms: list[str]


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
    for (_, term), _, error in listed:
        if error is not None:
            # Retries are already exhausted; skip this term rather than lose
            # every other term's matches (and the email).
            log(f"  {site.name}: search {term!r} FAILED, skipping: "
                  f"{type(error).__name__}: {error}")
            failed_terms.append(term)

    to_fetch: dict[str, Posting] = {}
    for (track, _), postings, _ in listed:
        for posting in postings or []:
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
            descriptions[job_id] = detailed
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
    return SiteSearchResult(list(best.values()), len(searches), failed_terms)


def search_term(
    session: requests.Session,
    site: JobSite,
    term: str,
    track: SearchTrack,
    descriptions: dict[str, Posting] | None = None,
) -> list[JobMatch]:
    """Search one site for one term (``search_site`` for a single search)."""
    return search_site(session, site, [(track, term)], descriptions).matches


def _search_site_in_own_session(site: JobSite) -> SiteSearchResult:
    started = time.monotonic()
    searches = [(track, term) for track in TRACKS for term in track.terms]
    log(f"Searching {site.name} ({site.kind}) for {len(searches)} term(s) ...")
    with build_session() as session:
        result = search_site(session, site, searches)
    unmarked = sum(1 for match in result.matches if match.is_remote is None)
    log(f"{site.name}: {len(result.matches)} qualifying match(es)"
        f"{f' ({unmarked} not marked remote or on-site)' if unmarked else ''} "
        f"in {time.monotonic() - started:.0f}s.")
    return result


def run_all_searches(
    site_selectors: list[str] | None = None, include_unmarked: bool = False
) -> list[JobMatch]:
    """Search every site (or those ``site_selectors`` pick) at the same time."""
    with build_session() as session:
        sites = resolve_sites(
            session, selectors=site_selectors, include_unmarked=include_unmarked
        )
    if not sites:
        raise RuntimeError("None of JOB_SEARCH_URLS could be resolved to a job site.")

    all_matches: dict[str, JobMatch] = {}
    failed_searches: list[str] = []
    total_searches = 0
    with ThreadPoolExecutor(max_workers=len(sites)) as pool:
        futures = [(site, pool.submit(_search_site_in_own_session, site)) for site in sites]
        for site, future in futures:
            result = future.result()
            total_searches += result.searches
            failed_searches.extend(f"{site.name}: {term}" for term in result.failed_terms)
            for job in result.matches:
                existing = all_matches.get(job.job_id)
                if existing is None or job.score > existing.score:
                    all_matches[job.job_id] = job

    if failed_searches and len(failed_searches) == total_searches:
        raise RuntimeError("Every search failed; the job sites may be unreachable.")
    if failed_searches:
        print(f"WARNING: {len(failed_searches)} search(es) failed: {failed_searches}")

    track_order = {track.name: index for index, track in enumerate(TRACKS)}

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
    if not job.salary_low and not job.salary_high:
        return "Not listed"
    if not job.salary_low:
        return f"Up to ${job.salary_high:,.0f}"
    if not job.salary_high:
        return f"From ${job.salary_low:,.0f}"
    return f"${job.salary_low:,.0f} - ${job.salary_high:,.0f}"


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
    all_matches = run_all_searches(site_selectors, include_unmarked)

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
        "kind (workday, greenhouse, lever, insight-global), or any careers page / "
        "job board URL, even one not in JOB_SEARCH_URLS. Repeat for several.",
    )
    parser.add_argument(
        "--include-unmarked",
        action="store_true",
        help="also keep jobs whose site doesn't say whether they're remote (saved "
        "with is_remote null; filter them in the dashboard). Jobs marked hybrid or "
        "on-site are still dropped.",
    )
    parser.add_argument(
        "--list-sites",
        action="store_true",
        help="show the configured sites and how each one is read, then exit",
    )
    return parser


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
    store = FirestoreJobStore.local() if args.local else None
    try:
        main(store, site_selectors=args.sites, include_unmarked=args.include_unmarked)
    except SiteSelectionError as error:
        print(f"job_search.py: error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(cli())
