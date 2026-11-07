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
from typing import Any
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


def html_to_text(value: Any) -> str:
    """Flatten an HTML job description to plain text."""
    text = HTML_TAG_PATTERN.sub(" ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


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
        return Posting(
            job_id=f"{self.id_prefix}{requisition_id}",
            title=str(record.get("jobTitle") or "").strip() or "Unknown title",
            url=self.build_job_url(requisition_id),
            company=self.name,
            city=str(address.get("locality") or ""),
            state=str(address.get("administrativeArea") or ""),
            is_remote=bool(record.get("workRemote")),
            job_type=_format_job_type(record.get("jobType")),
            salary_low=float(pay.get("min") or 0),
            salary_high=float(pay.get("max") or 0),
            posted_date=str(record.get("postedDate") or ""),
            detail_key=requisition_id,
        )

    def fetch_details(self, session: requests.Session, posting: Posting) -> Posting:
        response = session.get(
            f"{self.api_url}/{posting.detail_key}/details", timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        description = html_to_text(response.json().get("description"))
        return dataclasses.replace(posting, description=description)


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

    def fetch_details(self, session: requests.Session, posting: Posting) -> Posting:
        response = session.get(
            f"{self.api_url}{posting.detail_key}",
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        info = response.json().get("jobPostingInfo") or {}
        location = str(info.get("location") or "")
        remote = posting.is_remote
        if remote is None:
            remote = classify_remote_type(info.get("remoteType"))
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
            description=html_to_text(info.get("jobDescription")),
            is_remote=remote,
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


class GreenhouseSite(WholeBoardSite):
    """``boards.greenhouse.io/<token>`` via the public Job Board API."""

    kind = "greenhouse"

    def __init__(self, name: str, search_url: str, board_token: str, **options: Any):
        super().__init__(name, search_url, **options)
        self.board_token = board_token
        self.api_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"

    def fetch_all(self, session: requests.Session) -> list[Posting]:
        payload = self._get_json(session, self.api_url, content="true")
        postings = []
        for job in payload.get("jobs") or []:
            location = str((job.get("location") or {}).get("name") or "")
            city, state = split_location(location)
            postings.append(
                Posting(
                    job_id=f"{self.id_prefix}{job.get('id')}",
                    title=str(job.get("title") or "").strip() or "Unknown title",
                    url=str(job.get("absolute_url") or self.search_url),
                    company=self.name,
                    city=city,
                    state=state,
                    # Greenhouse has no remote field; the location is all there is.
                    is_remote=remote_from_text(location),
                    posted_date=str(job.get("first_published") or job.get("updated_at") or ""),
                    # The content field is HTML that has been entity-escaped again.
                    description=html_to_text(html.unescape(str(job.get("content") or ""))),
                )
            )
        return postings


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
