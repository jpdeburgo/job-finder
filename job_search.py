"""Search Insight Global jobs and email new matches through the Gmail API."""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv

from gmail_client import get_gmail_service, send_email

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

MIN_SKILL_MATCHES = 2
GROWTH_TRACK_MAX_YEARS_EXPERIENCE = 3
MAX_YEARS_EXPERIENCE = 7
REMOTE_ONLY = True
MAX_PAGES_PER_SEARCH = 3
CONTRACT_JOB_TYPES = {"contract", "contract to perm", "contract-to-perm"}
REQUEST_DELAY_SECONDS = 1.5

BASE_URL = "https://jobs.insightglobal.com/find_a_job"
HEADERS = {"User-Agent": "job-finder/1.0 (+personal job search)"}
JOB_JSON_MARKER = '{"JobID":'
STATE_FILE = Path(__file__).with_name("seen_jobs.json")
YEARS_EXPERIENCE_PATTERN = re.compile(
    r"(\d+)\s*\+?\s*(?:-\s*\d+\s*)?years?\s*(?:of\s*)?"
    r"(?:experience|exp\b)",
    re.IGNORECASE,
)
DOTNET_DATE_PATTERN = re.compile(r"^/Date\((-?\d+)(?:[+-]\d{4})?\)/$")
INTERNATIONAL_TITLE_PATTERN = re.compile(r"\b(?:INTL|LATAM)\b", re.IGNORECASE)
US_COUNTRY_HINTS = ("united states", "usa")


@dataclass(frozen=True)
class SearchTrack:
    name: str
    terms: tuple[str, ...]
    skills: tuple[str, ...]
    minimum_matches: int
    growth_track: bool = False


TRACKS = (
    SearchTrack(
        "Core matches (your main stack)",
        tuple(SEARCH_TITLES + EXTRA_SEARCH_TERMS),
        tuple(RESUME_SKILLS),
        MIN_SKILL_MATCHES,
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
    job_id: int
    title: str
    city: str
    state: str
    is_remote: bool
    job_type: str
    salary_low: float
    salary_high: float
    industry: str
    url: str
    track: str
    posted_date: str = ""
    req_id: str = ""
    matched_skills: list[str] = field(default_factory=list)
    min_years: int | None = None

    @property
    def score(self) -> int:
        return len(self.matched_skills)


def build_search_url(term: str, page: int) -> str:
    page_segment = "" if page == 1 else f"{page}/"
    query = (
        f"?remote={'true' if REMOTE_ONLY else 'false'}"
        f"&miles=False&srch={quote_plus(term)}"
    )
    return f"{BASE_URL}/{page_segment}{query}"


def extract_job_records(html: str) -> list[dict[str, Any]]:
    """Extract embedded job JSON objects from a search results page."""
    records: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    for match in re.finditer(re.escape(JOB_JSON_MARKER), html):
        try:
            record, _ = decoder.raw_decode(html, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def slugify_job_url(record: dict[str, Any]) -> str:
    state = re.sub(r"[^a-z0-9]+", "-", str(record.get("State") or "").lower())
    city = re.sub(r"[^a-z0-9]+", "-", str(record.get("City") or "").lower())
    title = re.sub(
        r"[^a-z0-9]+", "-", str(record.get("Title") or "").lower()
    ).strip("-")
    job_id = record.get("JobID")
    if state and city and title and job_id:
        return (
            "https://jobs.insightglobal.com/jobs/find_a_job/"
            f"{state.strip('-')}/{city.strip('-')}/{title}/job-{job_id}/"
        )
    return f"{BASE_URL}/?srch={job_id}"


def _contains_skill(text: str, skill: str) -> bool:
    """Match complete skill names so Java does not match JavaScript."""
    pattern = rf"(?<![A-Za-z0-9]){re.escape(skill)}(?![A-Za-z0-9])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def score_record(record: dict[str, Any], skills: tuple[str, ...]) -> list[str]:
    haystack = " ".join(
        str(record.get(key) or "")
        for key in ("Title", "Description", "Requirements", "Skills")
    )
    return [skill for skill in skills if _contains_skill(haystack, skill)]


def extract_min_years(record: dict[str, Any]) -> int | None:
    haystack = " ".join(
        str(record.get(key) or "") for key in ("Requirements", "Description")
    )
    years = [int(match) for match in YEARS_EXPERIENCE_PATTERN.findall(haystack)]
    return min(years) if years else None


def looks_junior(record: dict[str, Any]) -> bool:
    title = str(record.get("Title") or "").lower()
    return any(hint in title for hint in GROWTH_TRACK_JUNIOR_TITLE_HINTS)


def _format_job_type(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "Unknown"
    return str(value or "Unknown")


def _is_contract_job(job_type: str) -> bool:
    """Return True when the job type is contract or contract-to-perm."""
    return any(t in job_type.lower() for t in CONTRACT_JOB_TYPES)


def _is_international_title(title: str) -> bool:
    """Return True when the title is flagged as an offshore INTL/LATAM role."""
    return INTERNATIONAL_TITLE_PATTERN.search(title) is not None


def _is_us_country(country: Any) -> bool:
    value = str(country or "").strip().lower()
    return any(hint in value for hint in US_COUNTRY_HINTS)


def format_posted_date(value: Any) -> str:
    raw_value = str(value or "").strip()
    match = DOTNET_DATE_PATTERN.fullmatch(raw_value)
    if not match:
        return raw_value

    milliseconds = int(match.group(1))
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).date().isoformat()


def search_term(
    session: requests.Session, term: str, track: SearchTrack
) -> list[JobMatch]:
    matches: dict[int, JobMatch] = {}
    for page in range(1, MAX_PAGES_PER_SEARCH + 1):
        response = session.get(build_search_url(term, page), timeout=20)
        response.raise_for_status()
        records = extract_job_records(response.text)
        if not records:
            break

        for record in records:
            job_id = record.get("JobID")
            if not isinstance(job_id, int) or job_id in matches:
                continue
            if REMOTE_ONLY and not record.get("IsRemoteJob"):
                continue

            title = str(record.get("Title") or "Unknown title")
            if _is_international_title(title) and not _is_us_country(
                record.get("Country")
            ):
                continue

            job_type = _format_job_type(record.get("JobType"))
            if not _is_contract_job(job_type):
                continue

            matched_skills = score_record(record, track.skills)
            if len(matched_skills) < track.minimum_matches:
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

            matches[job_id] = JobMatch(
                job_id=job_id,
                title=title,
                city=str(record.get("City") or ""),
                state=str(record.get("State") or ""),
                is_remote=bool(record.get("IsRemoteJob")),
                job_type=job_type,
                salary_low=float(record.get("SalaryLow") or 0),
                salary_high=float(record.get("SalaryHigh") or 0),
                industry=str(record.get("Industry") or ""),
                url=slugify_job_url(record),
                track=track.name,
                posted_date=format_posted_date(record.get("PostedDate")),
                req_id=str(record.get("ReferenceID") or ""),
                matched_skills=matched_skills,
                min_years=min_years,
            )
        time.sleep(REQUEST_DELAY_SECONDS)
    return list(matches.values())


def run_all_searches() -> list[JobMatch]:
    all_matches: dict[int, JobMatch] = {}
    with requests.Session() as session:
        session.headers.update(HEADERS)
        for track in TRACKS:
            for term in track.terms:
                print(f"Searching [{track.name}]: {term!r} ...")
                for job in search_term(session, term, track):
                    existing = all_matches.get(job.job_id)
                    if existing is None or job.score > existing.score:
                        all_matches[job.job_id] = job
                time.sleep(REQUEST_DELAY_SECONDS)

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


def _github_state_config() -> tuple[str, str, str] | None:
    token = os.environ.get("IG_GITHUB_TOKEN")
    repo = os.environ.get("IG_GITHUB_REPO")
    if bool(token) != bool(repo):
        raise RuntimeError(
            "IG_GITHUB_TOKEN and IG_GITHUB_REPO must be set together"
        )
    if not token or not repo:
        return None
    return token, repo, os.environ.get("IG_GIT_BRANCH", "main")


def _github_state_request(method: str, **kwargs: Any) -> requests.Response:
    config = _github_state_config()
    if config is None:
        raise RuntimeError("GitHub state storage is not configured")
    token, repo, _ = config
    url = f"https://api.github.com/repos/{repo}/contents/{STATE_FILE.name}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    return requests.request(method, url, headers=headers, timeout=20, **kwargs)


def load_seen_ids() -> set[int]:
    config = _github_state_config()
    if config is not None:
        _, _, branch = config
        response = _github_state_request("GET", params={"ref": branch})
        if response.status_code == 404:
            return set()
        response.raise_for_status()
        content = base64.b64decode(response.json()["content"]).decode("utf-8")
    elif STATE_FILE.exists():
        content = STATE_FILE.read_text(encoding="utf-8")
    else:
        return set()

    data = json.loads(content)
    if not isinstance(data, list) or not all(isinstance(item, int) for item in data):
        raise ValueError(f"{STATE_FILE.name} must contain a JSON array of job IDs")
    return set(data)


def save_seen_ids(ids: set[int]) -> None:
    content = json.dumps(sorted(ids), indent=2) + "\n"
    config = _github_state_config()
    if config is not None:
        _, _, branch = config
        current = _github_state_request("GET", params={"ref": branch})
        if current.status_code not in (200, 404):
            current.raise_for_status()
        payload: dict[str, Any] = {
            "message": f"Update seen jobs - {datetime.now():%Y-%m-%d %H:%M}",
            "content": base64.b64encode(content.encode()).decode("ascii"),
            "branch": branch,
        }
        if current.status_code == 200:
            payload["sha"] = current.json()["sha"]
        response = _github_state_request("PUT", json=payload)
        response.raise_for_status()
        print(f"Updated {STATE_FILE.name} on GitHub.")
        return

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=STATE_FILE.parent, delete=False
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    temporary_path.replace(STATE_FILE)


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
        req = (
            f" &nbsp;|&nbsp; Req: {html_module.escape(job.req_id)}"
            if job.req_id
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
            f" &nbsp;|&nbsp; Job ID: {job.job_id}"
            f"{req}</p>"
        )
    lines.append("</body></html>")
    return "\n".join(lines)


def main() -> None:
    seen_ids = load_seen_ids()
    all_matches = run_all_searches()
    new_matches = [job for job in all_matches if job.job_id not in seen_ids]

    print(f"\nTotal qualifying matches this run: {len(all_matches)}")
    print(f"New (not previously emailed): {len(new_matches)}")

    if new_matches:
        message_id = send_email(
            get_gmail_service(),
            f"Insight Global: {len(new_matches)} new job match(es)",
            build_email_body(new_matches),
            os.environ["IG_EMAIL_TO"],
            html=True,
        )
        print(f"Email sent ({message_id}).")
    else:
        print("Nothing new to email.")

    save_seen_ids(seen_ids | {job.job_id for job in all_matches})


if __name__ == "__main__":
    main()
