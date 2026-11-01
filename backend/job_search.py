"""Search Insight Global jobs and email new matches through the Gmail API."""

from __future__ import annotations

import html
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from gmail_client import get_gmail_service, send_email
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
# Safety cap only: results are sorted newest-first and paging stops on its own
# once a page reaches postings older than MAX_POSTED_AGE_DAYS.
MAX_PAGES_PER_SEARCH = 10
RETRY_ATTEMPTS = 4
PAGE_SIZE = 50  # the API silently caps page size at 50
CONTRACT_JOB_TYPES = {"contract", "contract to perm", "contract-to-perm"}
REQUEST_DELAY_SECONDS = 1.5

# The search page is an Angular app that renders its results client-side, so
# there is no job data in its HTML. The page loads jobs from a JSON API on the
# same host (``/all/jobs`` for search, ``/all/jobs/<id>/details`` for the
# description); we call that API directly and link to the public job page.
BASE_URL = "https://insightglobal.com/jobs/search/all/all"
API_URL = urljoin(BASE_URL, "/all/jobs")
JOB_PAGE_URL = urljoin(BASE_URL, "/jobs/")
HEADERS = {"User-Agent": "job-finder/1.0 (+personal job search)"}
YEARS_EXPERIENCE_PATTERN = re.compile(
    r"(\d+)\s*(?:-\s*\d+\s*)?\+?\s*years?\b.{0,60}?(?:experience|exp\b)",
    re.IGNORECASE | re.DOTALL,
)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
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
    is_remote: bool
    job_type: str
    salary_low: float
    salary_high: float
    url: str
    track: str
    posted_date: str = ""
    matched_skills: list[str] = field(default_factory=list)
    min_years: int | None = None

    @property
    def score(self) -> int:
        return len(self.matched_skills)


def build_search_params(term: str, page: int) -> dict[str, Any]:
    return {
        "keyword": term,
        "page": page,
        "size": PAGE_SIZE,
        "sort": "postedDate,desc",
        # Matches Contract, Contract To Perm and "Contract, perm possible", and
        # drops Perm. Only one value works: the API 500s on a list of types.
        "filter.jobType": "Contract",
        "filter.includeOnlyRemoteWork": "true" if REMOTE_ONLY else "false",
        "filter.distance": 5,
        "filter.status": "active",
    }


def build_job_url(job_id: str) -> str:
    return f"{JOB_PAGE_URL}{job_id}"


def html_to_text(value: Any) -> str:
    """Flatten the HTML description the details API returns to plain text."""
    text = HTML_TAG_PATTERN.sub(" ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _contains_skill(text: str, skill: str) -> bool:
    """Match complete skill names so Java does not match JavaScript."""
    pattern = rf"(?<![A-Za-z0-9]){re.escape(skill)}(?![A-Za-z0-9])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def score_record(record: dict[str, Any], skills: tuple[str, ...]) -> list[str]:
    haystack = " ".join(
        str(record.get(key) or "") for key in ("jobTitle", "description")
    )
    return [skill for skill in skills if _contains_skill(haystack, skill)]


def extract_min_years(record: dict[str, Any]) -> int | None:
    haystack = str(record.get("description") or "")
    years = [int(match) for match in YEARS_EXPERIENCE_PATTERN.findall(haystack)]
    return min(years) if years else None


def looks_junior(record: dict[str, Any]) -> bool:
    title = str(record.get("jobTitle") or "").lower()
    return any(hint in title for hint in GROWTH_TRACK_JUNIOR_TITLE_HINTS)


def _format_job_type(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "Unknown"
    return str(value or "Unknown")


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


def build_session() -> requests.Session:
    """Return a session that retries dropped connections and 5xx/429 responses."""
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=RETRY_ATTEMPTS,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _is_stale_page(records: list[dict[str, Any]]) -> bool:
    """Return True when a newest-first page has reached stale postings.

    Records without a postedDate are ignored; the oldest dated record on the
    page decides, because everything on later pages is older still.
    """
    dated = [r for r in records if _parse_posted_date(r.get("postedDate"))]
    return bool(dated) and _is_stale_posting(dated[-1]["postedDate"])


def fetch_job_page(session: requests.Session, term: str, page: int) -> dict[str, Any]:
    response = session.get(API_URL, params=build_search_params(term, page), timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_description(
    session: requests.Session, job_id: str, cache: dict[str, str]
) -> str:
    """Return a job's plain-text description, fetching each job at most once."""
    if job_id not in cache:
        response = session.get(f"{API_URL}/{job_id}/details", timeout=20)
        response.raise_for_status()
        cache[job_id] = html_to_text(response.json().get("description"))
        time.sleep(REQUEST_DELAY_SECONDS)
    return cache[job_id]


def search_term(
    session: requests.Session,
    term: str,
    track: SearchTrack,
    descriptions: dict[str, str] | None = None,
) -> list[JobMatch]:
    descriptions = {} if descriptions is None else descriptions
    matches: dict[str, JobMatch] = {}
    for page in range(1, MAX_PAGES_PER_SEARCH + 1):
        payload = fetch_job_page(session, term, page)
        records = payload.get("jobs") or []
        if not records:
            break

        for record in records:
            job_id = record.get("requisitionId")
            if not isinstance(job_id, str) or job_id in matches:
                continue
            if REMOTE_ONLY and not record.get("workRemote"):
                continue

            title = str(record.get("jobTitle") or "").strip() or "Unknown title"
            address = record.get("workAddress") or {}
            state = str(address.get("administrativeArea") or "")
            city = str(address.get("locality") or "")
            if _is_international_title(title):
                continue
            if _is_bogus_alaska_location(state, city):
                continue
            if _is_placeholder_listing(title):
                continue
            if _has_unfamiliar_title_tech(title):
                continue
            if _title_names_growth_stack(title) and not track.growth_track:
                continue
            if _is_stale_posting(record.get("postedDate")):
                continue
            if track.growth_track and _is_senior_title(title):
                continue

            job_type = _format_job_type(record.get("jobType"))
            if not _is_contract_job(job_type):
                continue

            # The search results carry no description, so scoring waits until
            # every cheap check above has passed.
            record = {
                **record,
                "description": fetch_description(session, job_id, descriptions),
            }
            matched_skills = score_record(record, track.skills)
            if len(matched_skills) < track.minimum_matches:
                continue
            if track.required_skills and not set(track.required_skills) & set(
                matched_skills
            ):
                continue

            min_years = extract_min_years(record)
            if min_years is not None and min_years > MAX_YEARS_EXPERIENCE:
                continue

            if (
                track.growth_track
                and min_years is not None
                and min_years > GROWTH_TRACK_MAX_YEARS_EXPERIENCE
                and not looks_junior(record)
            ):
                continue

            pay = record.get("payRate") or {}
            matches[job_id] = JobMatch(
                job_id=job_id,
                title=title,
                city=city,
                state=state,
                is_remote=bool(record.get("workRemote")),
                job_type=job_type,
                salary_low=float(pay.get("min") or 0),
                salary_high=float(pay.get("max") or 0),
                url=build_job_url(job_id),
                track=track.name,
                posted_date=format_posted_date(record.get("postedDate")),
                matched_skills=matched_skills,
                min_years=min_years,
            )

        total_pages = (payload.get("pageMetadata") or {}).get("totalPages") or 1
        if page >= total_pages or _is_stale_page(records):
            break
        time.sleep(REQUEST_DELAY_SECONDS)
    return list(matches.values())


def run_all_searches() -> list[JobMatch]:
    all_matches: dict[str, JobMatch] = {}
    descriptions: dict[str, str] = {}
    failed_terms: list[str] = []
    total_terms = sum(len(track.terms) for track in TRACKS)
    with build_session() as session:
        for track in TRACKS:
            for term in track.terms:
                print(f"Searching [{track.name}]: {term!r} ...")
                try:
                    found = search_term(session, term, track, descriptions)
                except requests.RequestException as error:
                    # Retries are already exhausted; skip this term rather
                    # than lose every other term's matches (and the email).
                    print(f"  FAILED, skipping: {type(error).__name__}: {error}")
                    failed_terms.append(term)
                    continue
                for job in found:
                    existing = all_matches.get(job.job_id)
                    if existing is None or job.score > existing.score:
                        all_matches[job.job_id] = job
                time.sleep(REQUEST_DELAY_SECONDS)

    if len(failed_terms) == total_terms:
        raise RuntimeError("Every search failed; Insight Global may be unreachable.")
    if failed_terms:
        print(f"WARNING: {len(failed_terms)} search(es) failed: {failed_terms}")

    track_order = {track.name: index for index, track in enumerate(TRACKS)}

    def sort_key(job: JobMatch) -> tuple[int, str]:
        order = track_order[job.track]
        # Negate the date string so that later dates sort first within each
        # track (ISO-format dates compare lexicographically).
        inverted_date = (
            "".join(chr(0xFF - ord(c)) for c in job.posted_date)
            if job.posted_date
            else "\xff"  # push undated jobs to the end
        )
        return order, inverted_date

    return sorted(all_matches.values(), key=sort_key)


def format_salary(job: JobMatch) -> str:
    if not job.salary_low and not job.salary_high:
        return "Not listed"
    if not job.salary_low:
        return f"Up to ${job.salary_high:,.0f}"
    if not job.salary_high:
        return f"From ${job.salary_low:,.0f}"
    return f"${job.salary_low:,.0f} - ${job.salary_high:,.0f}"


def build_email_body(jobs: list[JobMatch]) -> str:
    """Return an HTML email body with clickable job-title hyperlinks."""
    import html as html_module

    lines = [
        "<html><body>",
        f"<p><strong>{len(jobs)} new Insight Global job match(es) — "
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
        lines.append(
            f'<p><a href="{html_module.escape(job.url)}">'
            f"{html_module.escape(job.title)}</a> "
            f"({html_module.escape(skill_text)})<br>"
            f"{html_module.escape(job.city)}, {html_module.escape(job.state)}"
            f" &nbsp;|&nbsp; {html_module.escape(job.job_type)}"
            f" &nbsp;|&nbsp; {html_module.escape(format_salary(job))}"
            f" &nbsp;|&nbsp; {html_module.escape(years)}"
            f"{posted}"
            f" &nbsp;|&nbsp; Job ID: {html_module.escape(job.job_id)}</p>"
        )
    lines.append("</body></html>")
    return "\n".join(lines)


def main(store: FirestoreJobStore | None = None) -> None:
    store = store or get_job_store()
    print(f"Job state: {store.description}")
    seen_ids = store.load_seen_ids()
    unemailed_ids = store.load_unemailed_ids()
    all_matches = run_all_searches()

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
            message_id = send_email(
                get_gmail_service(),
                f"Insight Global: {len(to_email)} new job match(es)",
                build_email_body(to_email),
                os.environ["IG_EMAIL_TO"],
                html=True,
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


if __name__ == "__main__":
    main()
