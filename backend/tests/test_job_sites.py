"""Tests for job_sites.py: resolving careers URLs and reading each site's API."""

from datetime import datetime, timedelta, timezone

import pytest

import job_search
import job_sites
from job_sites import (
    GreenhouseSite,
    InsightGlobalSite,
    LeverSite,
    UnsupportedSiteError,
    WorkdaySite,
    resolve_job_site,
)

ACCENTURE_BOARD = "https://accenture.wd103.myworkdayjobs.com/AccentureCareers"
ACCENTURE_API = "https://accenture.wd103.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers"
US_FACET_ID = "bc33aa3152ec42d4995f4791a106ed09"
CORE_TRACK = job_search.TRACKS[0]
JAVA_TRACK = job_search.TRACKS[1]


def _days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()


class FakeResponse:
    def __init__(self, payload, text=""):
        self.payload = payload
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class NoNetworkSession:
    """Fails the test if anything tries to make a request."""

    def get(self, *args, **kwargs):
        raise AssertionError(f"unexpected GET {args}")

    def post(self, *args, **kwargs):
        raise AssertionError(f"unexpected POST {args}")


# --- Shared helpers ---------------------------------------------------------------


def test_html_to_text_strips_tags_and_entities():
    assert (
        job_sites.html_to_text("Required<br><br>&bull; 5+ years of Python &amp; SQL<br>")
        == "Required \u2022 5+ years of Python & SQL"
    )
    assert job_sites.html_to_text(None) == ""


def test_split_location():
    assert job_sites.split_location("Austin, TX") == ("Austin", "TX")
    assert job_sites.split_location("3 Locations") == ("3 Locations", "")
    assert job_sites.split_location("Chicago, IL, United States") == (
        "Chicago, IL, United States",
        "",
    )
    assert job_sites.split_location("") == ("", "")


# --- Resolving URLs -----------------------------------------------------------------


def test_insight_global_url_resolves_to_its_own_api_without_network():
    site = resolve_job_site(job_search.INSIGHT_GLOBAL_URL, NoNetworkSession())

    assert isinstance(site, InsightGlobalSite)
    assert site.api_url == "https://insightglobal.com/all/jobs"
    assert site.contract_only is True
    assert site.kind == "insight-global"
    assert site.id_prefix == "insight-global-"


def test_accenture_search_url_resolves_to_its_workday_board_without_network():
    site = resolve_job_site(
        job_search.ACCENTURE_SEARCH_URL, NoNetworkSession(), country="United States of America"
    )

    assert isinstance(site, WorkdaySite)
    assert site.name == "Accenture"
    assert site.search_url == job_search.ACCENTURE_SEARCH_URL
    assert site.board_url == ACCENTURE_BOARD
    assert site.api_url == ACCENTURE_API
    assert site.country == "United States of America"
    assert site.contract_only is False  # Accenture hires directly, mostly full time
    assert site.id_prefix == "accenture-"


def test_workday_board_urls_resolve_directly_even_with_a_locale():
    site = resolve_job_site(
        "https://acme.wd5.myworkdayjobs.com/en-US/AcmeCareers/job/x", NoNetworkSession()
    )

    assert isinstance(site, WorkdaySite)
    assert site.name == "Acme"
    assert site.api_url == "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/AcmeCareers"


def test_greenhouse_and_lever_board_urls_resolve_directly():
    greenhouse = resolve_job_site("https://boards.greenhouse.io/acme-corp", NoNetworkSession())
    embedded = resolve_job_site(
        "https://boards.greenhouse.io/embed/job_board?for=acme", NoNetworkSession()
    )
    lever = resolve_job_site("https://jobs.lever.co/acme/", NoNetworkSession())

    assert isinstance(greenhouse, GreenhouseSite)
    assert greenhouse.name == "Acme Corp"
    assert greenhouse.api_url == "https://boards-api.greenhouse.io/v1/boards/acme-corp/jobs"
    assert embedded.board_token == "acme"
    assert isinstance(lever, LeverSite)
    assert lever.api_url == "https://api.lever.co/v0/postings/acme"


def test_unknown_careers_page_is_scanned_for_an_ats_board_link():
    class PageSession(NoNetworkSession):
        def get(self, url, timeout=None):
            assert url == "https://careers.example.com/jobs"
            return FakeResponse(
                None,
                text='<a href="https://example.wd1.myworkdayjobs.com/en-US/External">Jobs</a>',
            )

    site = resolve_job_site("https://careers.example.com/jobs", PageSession())

    assert isinstance(site, WorkdaySite)
    assert site.name == "Example"
    assert site.search_url == "https://careers.example.com/jobs"
    assert site.api_url == "https://example.wd1.myworkdayjobs.com/wday/cxs/example/External"


def test_careers_page_without_a_known_board_is_unsupported():
    class PageSession(NoNetworkSession):
        def get(self, url, timeout=None):
            return FakeResponse(None, text="<html><div id='app'></div></html>")

    with pytest.raises(UnsupportedSiteError, match="KNOWN_CAREER_SITES"):
        resolve_job_site("https://careers.example.com", PageSession())


def test_resolve_sites_skips_urls_that_fail(monkeypatch, capsys):
    class PageSession(NoNetworkSession):
        def get(self, url, timeout=None):
            return FakeResponse(None, text="nothing here")

    sites = job_search.resolve_sites(
        PageSession(), [job_search.INSIGHT_GLOBAL_URL, "https://careers.example.com"]
    )

    assert [site.name for site in sites] == ["Insight Global"]
    assert "skipping https://careers.example.com" in capsys.readouterr().out


# --- Workday (Accenture) ----------------------------------------------------------


def test_workday_posted_date_converts_relative_text():
    today = datetime(2026, 11, 5, tzinfo=timezone.utc)

    assert job_sites.workday_posted_date("Posted Today", today) == "2026-11-05"
    assert job_sites.workday_posted_date("Posted Yesterday", today) == "2026-11-04"
    assert job_sites.workday_posted_date("Posted 3 Days Ago", today) == "2026-11-02"
    # "30+" is a bucket for anything older, so it has to count as stale.
    assert job_sites.workday_posted_date("Posted 30+ Days Ago", today) == "2026-10-05"
    assert job_search._is_stale_posting(job_sites.workday_posted_date("Posted 30+ Days Ago"))
    assert job_sites.workday_posted_date(None, today) == ""


def test_classify_remote_type():
    assert job_sites.classify_remote_type("Remote") is True
    assert job_sites.classify_remote_type("Fully Remote") is True
    assert job_sites.classify_remote_type("Hybrid Remote") is False
    assert job_sites.classify_remote_type("On-site") is False
    assert job_sites.classify_remote_type("") is None
    assert job_sites.classify_remote_type(None) is None


def test_find_facet_value_searches_nested_groups():
    facets = [
        {"facetParameter": "jobFamilyGroup", "values": [{"descriptor": "Tech", "id": "t"}]},
        {
            "facetParameter": "locationMainGroup",
            "values": [
                {
                    "facetParameter": "locationCountry",
                    "descriptor": "Country",
                    "values": [
                        {"descriptor": "India", "id": "in"},
                        {"descriptor": "United States of America", "id": US_FACET_ID},
                    ],
                }
            ],
        },
    ]

    assert job_sites._find_facet_value(facets, "country", "United States of America") == (
        "locationCountry",
        US_FACET_ID,
    )
    assert job_sites._find_facet_value(facets, "country", "Narnia") is None
    assert job_sites._find_facet_value(None, "country", "India") is None


def _workday_item(requisition, **overrides):
    item = {
        "title": "Python Developer",
        "externalPath": f"/job/Atlanta/Python-Developer_{requisition}",
        "locationsText": "Atlanta, GA",
        "postedOn": "Posted 2 Days Ago",
        "bulletFields": [requisition],
    }
    item.update(overrides)
    return item


COUNTRY_FACETS = [
    {
        "facetParameter": "locationCountry",
        "values": [{"descriptor": "United States of America", "id": US_FACET_ID, "count": 9}],
    }
]


class FakeWorkday:
    """Serves a Workday board's /jobs search and job-detail endpoints."""

    def __init__(self, items, details, page_size=20, facets=COUNTRY_FACETS):
        self.items = items
        self.details = details
        self.page_size = page_size
        self.facets = facets
        self.posts = []
        self.gets = []

    def post(self, url, json=None, headers=None, timeout=None):
        assert url == f"{ACCENTURE_API}/jobs"
        self.posts.append(json)
        offset, limit = json["offset"], json["limit"]
        page = [i for i in self.items if json["searchText"].lower() in i["title"].lower()]
        # Like the real API: the true total only comes back on the first page.
        return FakeResponse(
            {
                "total": len(page) if offset == 0 else 0,
                "jobPostings": page[offset : offset + limit],
                "facets": self.facets,
            }
        )

    def get(self, url, headers=None, timeout=None):
        self.gets.append(url)
        path = url.removeprefix(ACCENTURE_API)
        return FakeResponse({"jobPostingInfo": self.details[path]})

    def searches(self):
        return [body for body in self.posts if body["searchText"]]


def _accenture(**options):
    options.setdefault("country", "United States of America")
    return WorkdaySite("Accenture", job_search.ACCENTURE_SEARCH_URL, ACCENTURE_BOARD, **options)


def _detail(description="Python and React on AWS. 3+ years of experience.", **overrides):
    info = {
        "jobDescription": f"<p>{description}</p>",
        "startDate": _days_ago(2),
        "timeType": "Full time",
        "remoteType": "Remote",
    }
    info.update(overrides)
    return info


@pytest.fixture
def no_delay(monkeypatch):
    monkeypatch.setattr(job_search, "MIN_SECONDS_BETWEEN_REQUESTS", 0)


def test_workday_fetch_page_sends_search_and_country_filter():
    session = FakeWorkday([_workday_item("R001")], {})
    site = _accenture()

    page = site.fetch_page(session, "Python Developer", 1)
    site.fetch_page(session, "React", 1)

    probe, first, second = session.posts
    assert probe["searchText"] == "" and probe["appliedFacets"] == {}
    assert first == {
        "appliedFacets": {"locationCountry": [US_FACET_ID]},
        "limit": 20,
        "offset": 0,
        "searchText": "Python Developer",
    }
    assert second["appliedFacets"] == {"locationCountry": [US_FACET_ID]}  # looked up once
    (posting,) = page.postings
    assert posting.job_id == "accenture-R001"
    assert posting.company == "Accenture"
    assert posting.url == f"{ACCENTURE_BOARD}/job/Atlanta/Python-Developer_R001"
    assert (posting.city, posting.state) == ("Atlanta", "GA")
    assert posting.posted_date == _days_ago(2)
    assert posting.is_remote is None  # not in the search results
    assert posting.description is None
    assert page.has_more is False


def test_workday_without_the_country_facet_searches_everywhere(capsys):
    session = FakeWorkday([_workday_item("R001")], {}, facets=[])
    site = _accenture()

    site.fetch_page(session, "Python", 1)

    assert session.posts[-1]["appliedFacets"] == {}
    assert "no 'United States of America' country filter" in capsys.readouterr().out


def test_workday_pages_by_offset_using_the_first_page_total():
    items = [_workday_item(f"R{n:03}") for n in range(45)]
    session = FakeWorkday(items, {})
    site = _accenture(country=None)

    pages = [site.fetch_page(session, "Python", n) for n in (1, 2, 3)]

    assert [len(p.postings) for p in pages] == [20, 20, 5]
    assert [p.has_more for p in pages] == [True, True, False]
    assert [body["offset"] for body in session.posts] == [0, 20, 40]


def test_workday_skips_search_results_without_a_job_link():
    # Accenture's board has returned a result with no externalPath, which
    # leaves no details page to read. Skip it, but still count it for paging.
    items = [_workday_item(f"R{n:03}") for n in range(20)]
    del items[5]["externalPath"]
    items.append(_workday_item("R020"))
    session = FakeWorkday(items, {})
    site = _accenture(country=None)

    first = site.fetch_page(session, "Python", 1)

    assert len(first.postings) == 19
    assert "accenture-R005" not in [p.job_id for p in first.postings]
    assert first.has_more is True
    assert [p.job_id for p in site.fetch_page(session, "Python", 2).postings] == ["accenture-R020"]


def test_workday_fetch_details_fills_description_remote_and_exact_date():
    path = "/job/Atlanta/Python-Developer_R001"
    session = FakeWorkday(
        [_workday_item("R001")],
        {path: _detail(externalUrl=f"{ACCENTURE_BOARD}/job/R001-public")},
    )
    site = _accenture(country=None)
    (posting,) = site.fetch_page(session, "Python", 1).postings

    detailed = site.fetch_details(session, posting)

    assert session.gets == [f"{ACCENTURE_API}{path}"]
    assert detailed.description == "Python and React on AWS. 3+ years of experience."
    assert detailed.is_remote is True
    assert detailed.job_type == "Full time"
    assert detailed.posted_date == _days_ago(2)
    assert detailed.url == f"{ACCENTURE_BOARD}/job/R001-public"


def test_accenture_shaped_results_get_their_location_and_remote_status_from_details(no_delay):
    # Accenture's real search results carry only these four fields: no
    # location and no remoteType. Both are only on the details page.
    def bare(requisition, title="Python Developer"):
        return {
            "title": title,
            "externalPath": f"/job/Atlanta/Python-Developer_{requisition}",
            "postedOn": "Posted 2 Days Ago",
            "bulletFields": [requisition],
        }

    details = {
        "/job/Atlanta/Python-Developer_R001": _detail(
            remoteType="Remote", location="Atlanta, GA", additionalLocations=["Austin, TX"]
        ),
        "/job/Atlanta/Python-Developer_R002": _detail(remoteType="Hybrid", location="Chicago, IL"),
        "/job/Atlanta/Python-Developer_R003": _detail(remoteType=None, location="Boston, MA"),
    }
    session = FakeWorkday([bare("R001"), bare("R002"), bare("R003")], details)
    site = _accenture()
    listed = site.fetch_page(session, "Python Developer", 1).postings
    assert [(p.city, p.state, p.is_remote) for p in listed] == [("", "", None)] * 3

    matches = job_search.search_term(session, site, "Python Developer", CORE_TRACK)

    # Hybrid and unmarked jobs are dropped; every posting needed its details.
    assert [(m.job_id, m.city, m.state) for m in matches] == [("accenture-R001", "Atlanta", "GA")]
    assert len(session.gets) == 3


def test_workday_location_from_the_listing_wins_over_details():
    path = "/job/Atlanta/Python-Developer_R001"
    session = FakeWorkday([_workday_item("R001")], {path: _detail(location="Somewhere Else")})
    site = _accenture(country=None)
    (posting,) = site.fetch_page(session, "Python", 1).postings

    assert (site.fetch_details(session, posting).city, posting.state) == ("Atlanta", "GA")


def test_search_term_matches_accenture_jobs_end_to_end(no_delay):
    items = [
        _workday_item("R001"),  # remote per its details -> match
        _workday_item("R002"),  # hybrid per its details -> dropped after details
        _workday_item("R003", postedOn="Posted 30+ Days Ago"),  # stale -> no details
        _workday_item("R004", title="Python Developer - Salesforce"),  # title tech
        _workday_item("R005", remoteType="On-site"),  # on-site in the listing
        _workday_item("R006", locationsText="Remote, US"),  # remote in the listing
    ]
    details = {
        f"/job/Atlanta/Python-Developer_{req}": _detail(**extra)
        for req, extra in [
            ("R001", {}),
            ("R002", {"remoteType": "Hybrid"}),
            ("R006", {"remoteType": ""}),
        ]
    }
    session = FakeWorkday(items, details)

    matches = job_search.search_term(session, _accenture(), "Python Developer", CORE_TRACK)

    assert [m.job_id for m in matches] == ["accenture-R001", "accenture-R006"]
    match = matches[0]
    assert match.company == "Accenture"
    assert match.job_type == "Full time"  # not dropped: Accenture isn't contract-only
    assert match.is_remote is True
    assert match.matched_skills == ["Python", "React", "AWS"]
    assert match.min_years == 3
    assert match.posted_date == _days_ago(2)
    fetched = sorted(url.rsplit("_", 1)[-1] for url in session.gets)
    assert fetched == ["R001", "R002", "R006"]


def test_search_term_drops_workday_jobs_whose_remote_status_is_never_given(no_delay):
    path = "/job/Atlanta/Python-Developer_R001"
    session = FakeWorkday([_workday_item("R001")], {path: _detail(remoteType=None)})

    assert job_search.search_term(session, _accenture(), "Python", CORE_TRACK) == []


def test_search_term_keeps_them_when_the_site_is_not_remote_only(no_delay):
    path = "/job/Atlanta/Python-Developer_R001"
    session = FakeWorkday([_workday_item("R001")], {path: _detail(remoteType=None)})
    site = _accenture(remote_only=False)

    (match,) = job_search.search_term(session, site, "Python", CORE_TRACK)

    assert match.is_remote is None  # saved as unmarked, not as "not remote"


def test_include_unmarked_keeps_jobs_the_site_never_marked(no_delay):
    details = {
        f"/job/Atlanta/Python-Developer_{req}": _detail(remoteType=remote_type)
        for req, remote_type in [
            ("R001", "Remote"), ("R002", None), ("R003", "Hybrid"), ("R004", "On-Site"),
        ]
    }
    items = [_workday_item(req) for req in ("R001", "R002", "R003", "R004")]

    def run(include_unmarked):
        site = _accenture()
        site.include_unmarked_remote = include_unmarked
        matches = job_search.search_term(FakeWorkday(items, details), site, "Python", CORE_TRACK)
        return {m.job_id: m.is_remote for m in matches}

    assert run(False) == {"accenture-R001": True}
    # Unmarked comes in as None; hybrid and on-site stay out.
    assert run(True) == {"accenture-R001": True, "accenture-R002": None}


def test_remote_from_text():
    assert job_sites.remote_from_text("Remote - US") is True
    assert job_sites.remote_from_text("New York; Remote") is True
    assert job_sites.remote_from_text("Hybrid Remote") is False
    assert job_sites.remote_from_text("Denver, CO (On-site)") is False
    assert job_sites.remote_from_text("Denver, CO") is None
    assert job_sites.remote_from_text("") is None


def test_lever_workplace_type_wins_and_unspecified_falls_back_to_the_location():
    def posting(workplace_type, location):
        payload = [{"id": "1", "text": "Full Stack Engineer", "workplaceType": workplace_type,
                    "categories": {"location": location}}]
        site = LeverSite("Acme", "https://jobs.lever.co/acme", "acme")
        return site.fetch_page(FakeBoard(payload), "Full Stack Engineer", 1).postings[0]

    assert posting("remote", "Austin, TX").is_remote is True
    assert posting("hybrid", "Remote").is_remote is False
    assert posting("onsite", "Austin, TX").is_remote is False
    assert posting("unspecified", "Remote - US").is_remote is True
    assert posting("unspecified", "Austin, TX").is_remote is None
    assert posting(None, "Austin, TX").is_remote is None


def test_workday_growth_track_still_rejects_senior_titles(no_delay):
    items = [
        _workday_item("R001", title="Java Developer"),
        _workday_item("R002", title="Senior Java Developer"),
    ]
    details = {
        f"/job/Atlanta/Python-Developer_{req}": _detail("Java services. 2+ years of experience.")
        for req in ("R001", "R002")
    }
    session = FakeWorkday(items, details)

    matches = job_search.search_term(session, _accenture(), "Java Developer", JAVA_TRACK)

    assert [m.job_id for m in matches] == ["accenture-R001"]


# --- Greenhouse and Lever -----------------------------------------------------------


class FakeBoard:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return FakeResponse(self.payload)


def test_greenhouse_downloads_the_board_once_and_matches_terms_locally():
    payload = {
        "jobs": [
            {
                "id": 123,
                "title": "Backend Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                "location": {"name": "Remote - US"},
                "first_published": "2026-11-01T09:00:00-04:00",
                "content": "&lt;p&gt;Python Developer work on AWS&lt;/p&gt;",
            },
            {
                "id": 456,
                "title": "Office Manager",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/456",
                "location": {"name": "Denver, CO"},
                "updated_at": "2026-11-02T09:00:00-04:00",
                "content": "",
            },
        ]
    }
    session = FakeBoard(payload)
    site = GreenhouseSite("Acme", "https://boards.greenhouse.io/acme", "acme")

    first = site.fetch_page(session, "Python Developer", 1)
    site.fetch_page(session, "React", 1)

    assert session.calls == [
        ("https://boards-api.greenhouse.io/v1/boards/acme/jobs", {"content": "true"})
    ]
    (posting,) = first.postings
    assert posting.job_id == "acme-123"
    assert posting.description == "Python Developer work on AWS"
    assert posting.is_remote is True
    assert posting.posted_date.startswith("2026-11-01")
    assert first.has_more is False
    assert site.fetch_page(session, "Python Developer", 2).postings == []


def test_lever_postings_are_normalized():
    payload = [
        {
            "id": "abc-1",
            "text": "Full Stack Engineer",
            "hostedUrl": "https://jobs.lever.co/acme/abc-1",
            "createdAt": 1793000000000,
            "workplaceType": "remote",
            "categories": {"location": "Austin, TX", "commitment": "Contract"},
            "salaryRange": {"min": 100000, "max": 140000, "currency": "USD", "interval": "per-year-salary"},
            "descriptionPlain": "Build things.",
            "lists": [{"text": "Requirements", "content": "<li>React and Node.js</li>"}],
            "additionalPlain": "Benefits.",
        }
    ]
    site = LeverSite("Acme", "https://jobs.lever.co/acme", "acme")

    (posting,) = site.fetch_page(FakeBoard(payload), "Full Stack Engineer", 1).postings

    assert posting.job_id == "acme-abc-1"
    assert (posting.city, posting.state) == ("Austin", "TX")
    assert posting.is_remote is True
    assert posting.job_type == "Contract"
    assert (posting.salary_low, posting.salary_high) == (100000, 140000)
    assert posting.salary_period == "year"
    assert posting.description == "Build things. Requirements React and Node.js Benefits."
    assert posting.posted_date.startswith("2026-10-26")


# --- Both sites in one run ----------------------------------------------------------


class BothSitesSession:
    """Serves Insight Global's API and Accenture's Workday board together."""

    def __init__(self):
        self.workday = FakeWorkday(
            [_workday_item("R001")], {"/job/Atlanta/Python-Developer_R001": _detail()}
        )

    def get(self, url, params=None, headers=None, timeout=None):
        if url.startswith(ACCENTURE_API):
            return self.workday.get(url, headers=headers, timeout=timeout)
        if url.endswith("/details"):
            return FakeResponse({"description": "Python and React. 2+ years of experience."})
        assert url == "https://insightglobal.com/all/jobs"
        jobs = []
        if params["keyword"] == "Python Developer":
            jobs = [
                {
                    "requisitionId": "ig-1",
                    "jobTitle": "Python Developer",
                    "workAddress": {"administrativeArea": "TX", "locality": "Austin"},
                    "postedDate": f"{_days_ago(1)}T00:00:00.1Z",
                    "workRemote": True,
                    "jobType": "Contract",
                    "payRate": {"min": 70.0, "max": 90.0},
                }
            ]
        return FakeResponse({"jobs": jobs, "pageMetadata": {"totalPages": 1}})

    def post(self, url, json=None, headers=None, timeout=None):
        return self.workday.post(url, json=json, headers=headers, timeout=timeout)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_main_saves_insight_global_and_accenture_jobs(tmp_path, monkeypatch, no_delay):
    from job_store import FirestoreJobStore

    store = FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)
    monkeypatch.setattr(job_search, "build_session", BothSitesSession)
    sent = []
    monkeypatch.setattr(job_search, "get_gmail_service", lambda: "service")
    monkeypatch.setattr(
        job_search, "send_email", lambda service, subject, body, to, html=False: sent.append(body)
    )
    monkeypatch.setenv("IG_EMAIL_TO", "me@example.com")

    job_search.main(store)

    saved = {job["job_id"]: job for job in store.list_jobs()}
    assert set(saved) == {"insight-global-ig-1", "accenture-R001"}
    assert saved["insight-global-ig-1"]["company"] == "Insight Global"
    assert saved["insight-global-ig-1"]["url"] == "https://insightglobal.com/jobs/ig-1"
    assert saved["accenture-R001"]["company"] == "Accenture"
    assert saved["accenture-R001"]["url"].startswith(ACCENTURE_BOARD)
    (body,) = sent
    assert "from Accenture, Insight Global" in body
    assert "Accenture &nbsp;|&nbsp; Atlanta, GA" in body


def test_site_settings_override_a_sites_filters(monkeypatch):
    monkeypatch.setattr(
        job_search, "SITE_SETTINGS", {job_search.ACCENTURE_SEARCH_URL: {"remote_only": False}}
    )

    ig, accenture = job_search.resolve_sites(NoNetworkSession())

    assert ig.remote_only is True
    assert accenture.remote_only is False


def test_include_unmarked_flag_and_setting(monkeypatch):
    assert [s.include_unmarked_remote for s in job_search.resolve_sites(NoNetworkSession())] == [
        False, False,
    ]
    monkeypatch.setattr(
        job_search,
        "SITE_SETTINGS",
        {job_search.ACCENTURE_SEARCH_URL: {"include_unmarked_remote": True}},
    )
    ig, accenture = job_search.resolve_sites(NoNetworkSession())
    assert (ig.include_unmarked_remote, accenture.include_unmarked_remote) == (False, True)

    # The command-line flag turns it on everywhere.
    sites = job_search.resolve_sites(NoNetworkSession(), include_unmarked=True)
    assert [s.include_unmarked_remote for s in sites] == [True, True]


def test_site_settings_reject_unknown_options(monkeypatch):
    monkeypatch.setattr(
        job_search, "SITE_SETTINGS", {job_search.INSIGHT_GLOBAL_URL: {"remote": False}}
    )

    with pytest.raises(ValueError, match="Unknown SITE_SETTINGS option 'remote'"):
        job_search.resolve_sites(NoNetworkSession())
