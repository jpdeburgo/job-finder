"""Tests for the Ashby reader and the remote-only job boards in job_sites.py
(Himalayas, Remote OK, Jobicy, We Work Remotely). The payloads follow each
API's documented shape; no test touches the network."""

from datetime import datetime, timedelta, timezone

import pytest
import requests

import job_search
import job_sites
from job_sites import (
    AshbySite,
    HimalayasSite,
    JobicySite,
    RemoteOkSite,
    UnsupportedSiteError,
    WeWorkRemotelySite,
    format_employment_type,
    resolve_job_site,
    timestamp_to_iso,
)

CORE_TRACK = job_search.TRACKS[0]
US = job_search.JOB_COUNTRY


def _recent(days=2):
    return datetime.now(timezone.utc) - timedelta(days=days)


class FakeResponse:
    def __init__(self, payload=None, content=b"", status=200):
        self.payload = payload
        self.content = content
        self.text = content.decode() if isinstance(content, bytes) else str(content)
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")

    def json(self):
        return self.payload


class FakeSession:
    """Answers GETs from a list of responses (the last one repeats), recording each call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None, **kwargs):
        self.calls.append((url, params))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

    def post(self, *args, **kwargs):
        raise AssertionError(f"unexpected POST {args}")


class NoNetworkSession(FakeSession):
    def get(self, *args, **kwargs):
        raise AssertionError(f"unexpected GET {args}")


# --- Resolving URLs -----------------------------------------------------------------


@pytest.mark.parametrize(
    "url, kind, board",
    [
        ("https://jobs.ashbyhq.com/posthog", AshbySite, "posthog"),
        ("https://jobs.ashbyhq.com/posthog/", AshbySite, "posthog"),
        ("https://api.ashbyhq.com/posting-api/job-board/linear?includeCompensation=true",
         AshbySite, "linear"),
    ],
)
def test_ashby_board_urls_resolve_without_network(url, kind, board):
    site = resolve_job_site(url, NoNetworkSession(), country=US)

    assert isinstance(site, kind)
    assert site.board == board
    assert site.api_url == f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    assert site.id_prefix == f"{board}-"


def test_a_careers_page_linking_to_ashby_resolves_to_that_board():
    page = '<iframe src="https://jobs.ashbyhq.com/acme/embed?version=2"></iframe>'
    site = resolve_job_site("https://acme.com/careers", FakeSession(FakeResponse(content=page.encode())))

    assert isinstance(site, AshbySite)
    assert (site.name, site.board) == ("Acme", "acme")


@pytest.mark.parametrize(
    "url, kind",
    [
        ("https://himalayas.app/jobs/api/search", HimalayasSite),
        ("https://himalayas.app/jobs/api", HimalayasSite),
        ("https://remoteok.com/api", RemoteOkSite),
        ("https://remoteok.io/api", RemoteOkSite),
        ("https://jobicy.com/api/v2/remote-jobs", JobicySite),
        ("https://weworkremotely.com/remote-jobs.rss", WeWorkRemotelySite),
    ],
)
def test_remote_board_urls_resolve_without_network(url, kind):
    site = resolve_job_site(url, NoNetworkSession(), country=US)

    assert isinstance(site, kind)
    assert site.search_url == url
    assert site.remote_only is True


def test_himalayas_keeps_the_urls_filters_and_adds_the_country_and_sort():
    plain = HimalayasSite("https://himalayas.app/jobs/api/search", country=US)
    part_time = HimalayasSite(
        "https://himalayas.app/jobs/api/search?employment_type=Part%20Time&country=CA&q=x&page=3",
        country=US,
    )
    anywhere = HimalayasSite("https://himalayas.app/jobs/api/search", country=None)

    assert plain.params == {"sort": "recent", "country": "US"}
    # Search terms and pages come from the search, not the URL; a country
    # in the URL wins over JOB_COUNTRY.
    assert part_time.params == {"employment_type": "Part Time", "country": "CA", "sort": "recent"}
    assert anywhere.params == {"sort": "recent"}
    assert (plain.name, part_time.name) == ("Himalayas", "Himalayas (Part Time)")
    # Both save jobs under one prefix, so a job found by both is saved once.
    assert plain.id_prefix == part_time.id_prefix == "himalayas-"


def test_jobicy_defaults_to_100_us_jobs_unless_the_url_says_otherwise():
    assert JobicySite("https://jobicy.com/api/v2/remote-jobs", country=US).params == {
        "count": "100", "geo": "usa",
    }
    assert JobicySite("https://jobicy.com/api/v2/remote-jobs?count=20&geo=canada", country=US).params == {
        "count": "20", "geo": "canada",
    }


def test_we_work_remotely_category_pages_read_their_feed():
    page = WeWorkRemotelySite("https://weworkremotely.com/categories/remote-back-end-programming-jobs")
    feed = WeWorkRemotelySite("https://weworkremotely.com/categories/remote-programming-jobs.rss")
    home = WeWorkRemotelySite("https://weworkremotely.com/")

    assert page.feed_url == "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss"
    assert page.name == "We Work Remotely (Back End Programming)"
    assert feed.name == "We Work Remotely (Programming)"
    assert (home.feed_url, home.name) == ("https://weworkremotely.com/remote-jobs.rss", "We Work Remotely")
    assert page.id_prefix == feed.id_prefix == home.id_prefix == "we-work-remotely-"


# --- Shared helpers -----------------------------------------------------------------


def test_timestamp_to_iso_reads_every_date_format_the_boards_use():
    assert timestamp_to_iso(1793000000) == "2026-10-26T07:33:20+00:00"  # Unix seconds
    assert timestamp_to_iso(1793000000000) == "2026-10-26T07:33:20+00:00"  # milliseconds
    assert timestamp_to_iso("1793000000") == "2026-10-26T07:33:20+00:00"
    assert timestamp_to_iso("2026-11-01 10:00:00") == "2026-11-01T10:00:00"  # Jobicy
    assert timestamp_to_iso("2026-11-01T10:00:00.000Z") == "2026-11-01T10:00:00.000Z"
    assert timestamp_to_iso("Tue, 10 Nov 2026 14:02:11 +0000") == "2026-11-10T14:02:11+00:00"
    assert timestamp_to_iso("soon") == ""
    assert timestamp_to_iso(None) == ""
    assert timestamp_to_iso(True) == ""


def test_format_employment_type():
    assert format_employment_type("FullTime") == "Full-time"
    assert format_employment_type("PartTime") == "Part-time"
    assert format_employment_type("Part Time") == "Part-time"
    assert format_employment_type(["full-time", "part-time"]) == "Full-time, Part-time"
    assert format_employment_type("Contractor") == "Contract"
    assert format_employment_type("Intern") == "Internship"
    assert format_employment_type(None) == ""


# --- Ashby --------------------------------------------------------------------------


def _ashby_job(job_id="11111111-aaaa", **overrides):
    job = {
        "id": job_id,
        "title": "Senior Product Engineer",
        "location": "Remote (US)",
        "secondaryLocations": [],
        "department": "Engineering",
        "isListed": True,
        "isRemote": True,
        "workplaceType": "Remote",
        "descriptionHtml": "<p>Build with TypeScript and React.</p><p>Python a plus.</p>",
        "descriptionPlain": "Build with TypeScript and React. Python a plus.",
        "publishedAt": _recent().isoformat(),
        "employmentType": "FullTime",
        "address": {"postalAddress": {"addressCountry": "United States"}},
        "jobUrl": f"https://jobs.ashbyhq.com/acme/{job_id}",
        "applyUrl": f"https://jobs.ashbyhq.com/acme/{job_id}/application",
        "compensation": {
            "summaryComponents": [
                {"compensationType": "EquityPercentage", "minValue": 0.1, "maxValue": 0.2},
                {"compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "USD",
                 "minValue": 150000, "maxValue": 190000},
            ]
        },
    }
    job.update(overrides)
    return job


def test_ashby_reads_the_board_once_with_compensation_and_normalizes_jobs():
    session = FakeSession(FakeResponse({"apiVersion": "1", "jobs": [
        _ashby_job(),
        _ashby_job("2222", title="Hidden", isListed=False),
    ]}))
    site = AshbySite("Acme", "https://jobs.ashbyhq.com/acme", "acme")

    first = site.fetch_page(session, "Product Engineer", 1)
    site.fetch_page(session, "React", 1)

    assert session.calls == [
        ("https://api.ashbyhq.com/posting-api/job-board/acme", {"includeCompensation": "true"})
    ]
    (posting,) = first.postings  # unlisted jobs are left out
    assert posting.job_id == "acme-11111111-aaaa"
    assert posting.company == "Acme"
    assert posting.url == "https://jobs.ashbyhq.com/acme/11111111-aaaa"
    assert posting.is_remote is True
    assert posting.job_type == "Full-time"
    assert (posting.salary_low, posting.salary_high) == (150000, 190000)
    assert posting.description == "Build with TypeScript and React.\nPython a plus."
    assert (posting.city, posting.state) == ("Remote (US)", "United States")


def test_ashby_workplace_type_wins_over_is_remote_and_says_why():
    site = AshbySite("Acme", "https://jobs.ashbyhq.com/acme", "acme")
    jobs = [
        _ashby_job("a", workplaceType="Hybrid", isRemote=True),
        _ashby_job("b", workplaceType="OnSite", isRemote=False),
        _ashby_job("c", workplaceType=None, isRemote=False),
        _ashby_job("d", workplaceType=None, isRemote=None, location="Remote - US"),
    ]

    postings = site.fetch_all(FakeSession(FakeResponse({"jobs": jobs})))

    assert [p.is_remote for p in postings] == [False, False, False, True]
    assert postings[0].remote_note == 'workplaceType = "Hybrid"'
    assert postings[1].remote_note == 'workplaceType = "OnSite"'


def test_ashby_part_time_jobs_and_non_dollar_salaries():
    site = AshbySite("Acme", "https://jobs.ashbyhq.com/acme", "acme")
    job = _ashby_job(employmentType="PartTime", compensation={"summaryComponents": [
        {"compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "EUR",
         "minValue": 60000, "maxValue": 80000},
    ]})

    (posting,) = site.fetch_all(FakeSession(FakeResponse({"jobs": [job]})))

    assert posting.job_type == "Part-time"
    # Shown as "Not listed" rather than as dollars.
    assert (posting.salary_low, posting.salary_high) == (0, 0)


def test_ashby_locations_name_every_country_for_the_us_filter():
    site = AshbySite("Acme", "https://jobs.ashbyhq.com/acme", "acme")
    canada = _ashby_job("ca", location="Remote", address={"postalAddress": {"addressCountry": "Canada"}})
    both = _ashby_job("both", location="Remote - Canada",
                      secondaryLocations=[{"location": "Remote - US"}], address={})

    canada_posting, both_posting = site.fetch_all(FakeSession(FakeResponse({"jobs": [canada, both]})))

    assert job_search._is_outside_job_country(canada_posting)
    assert both_posting.city == "Remote - Canada; Remote - US"
    assert not job_search._is_outside_job_country(both_posting)


def test_ashby_job_id_falls_back_to_the_job_url():
    site = AshbySite("Acme", "https://jobs.ashbyhq.com/acme", "acme")
    job = _ashby_job(id=None, jobUrl="https://jobs.ashbyhq.com/acme/3333-bbbb")

    (posting,) = site.fetch_all(FakeSession(FakeResponse({"jobs": [job]})))

    assert posting.job_id == "acme-3333-bbbb"


def test_ashby_looks_up_one_job_by_its_url():
    site = AshbySite("Acme", "https://jobs.ashbyhq.com/acme", "acme")
    session = FakeSession(FakeResponse({"jobs": [_ashby_job("x1"), _ashby_job("x2", title="Other")]}))

    posting, payload = site.lookup(session, "https://jobs.ashbyhq.com/acme/x2/application")

    assert posting.job_id == "acme-x2"
    assert payload["title"] == "Other"
    assert site.supports_lookup
    with pytest.raises(UnsupportedSiteError, match="no longer listed"):
        site.lookup(session, "https://jobs.ashbyhq.com/acme/gone")


# --- Himalayas ----------------------------------------------------------------------


def _himalayas_job(slug="senior-python-engineer", company="Globex", **overrides):
    job = {
        "title": "Senior Python Engineer",
        "excerpt": "Python and React.",
        "companyName": company,
        "companySlug": company.lower(),
        "employmentType": "Full Time",
        "minSalary": 120000,
        "maxSalary": 160000,
        "currency": "USD",
        "seniority": ["Senior"],
        "locationRestrictions": ["United States"],
        "timezoneRestrictions": [-5, -8],
        "categories": ["Software-Engineer"],
        "description": "<p>We use Python, React, and AWS.</p>",
        "pubDate": int(_recent().timestamp()),
        "applicationLink": f"https://himalayas.app/companies/{company.lower()}/jobs/{slug}",
        "guid": f"https://himalayas.app/companies/{company.lower()}/jobs/{slug}",
    }
    job.update(overrides)
    return job


def test_himalayas_searches_each_term_on_its_server():
    session = FakeSession(FakeResponse({"offset": 0, "limit": 20, "totalCount": 1,
                                        "jobs": [_himalayas_job()]}))
    site = HimalayasSite("https://himalayas.app/jobs/api/search", country=US)

    page = site.fetch_page(session, "Python Developer", 1)

    assert session.calls == [("https://himalayas.app/jobs/api/search", {
        "sort": "recent", "country": "US", "q": "Python Developer", "page": 1,
    })]
    (posting,) = page.postings
    assert page.has_more is False
    # The hiring company, not the job board, and the link back to Himalayas.
    assert posting.company == "Globex"
    assert posting.url == "https://himalayas.app/companies/globex/jobs/senior-python-engineer"
    assert posting.job_id == "himalayas-globex-senior-python-engineer"
    assert posting.is_remote is True
    assert posting.job_type == "Full-time"
    assert posting.city == "United States"
    assert (posting.salary_low, posting.salary_high) == (120000, 160000)
    assert posting.description == "We use Python, React, and AWS."
    assert job_search._parse_posted_date(posting.posted_date) is not None
    assert site.newest_first


def test_himalayas_pages_until_the_total_is_reached():
    site = HimalayasSite("https://himalayas.app/jobs/api/search", country=US)
    full = [_himalayas_job(f"job-{n}") for n in range(20)]

    first = site.fetch_page(FakeSession(FakeResponse({"offset": 0, "totalCount": 25, "jobs": full})), "x", 1)
    second = site.fetch_page(FakeSession(FakeResponse({"offset": 20, "totalCount": 25, "jobs": full[:5]})), "x", 2)
    no_total = site.fetch_page(FakeSession(FakeResponse({"jobs": full})), "x", 1)

    assert (first.has_more, second.has_more, no_total.has_more) == (True, False, True)


def test_himalayas_handles_other_shapes_of_its_fields():
    site = HimalayasSite("https://himalayas.app/jobs/api/search", country=US)
    job = _himalayas_job(
        locationRestrictions=[{"alpha2": "CA", "name": "Canada"}],
        currency="EUR",
        pubDate=int(_recent().timestamp() * 1000),
        description=None,
        employmentType="Part Time",
    )

    (posting,) = site.fetch_page(FakeSession(FakeResponse({"jobs": [job]})), "x", 1).postings

    assert posting.city == "Canada"
    assert job_search._is_outside_job_country(posting)
    assert (posting.salary_low, posting.salary_high) == (0, 0)
    assert posting.description == "Python and React."  # the excerpt
    assert posting.job_type == "Part-time"
    assert job_search._parse_posted_date(posting.posted_date).year >= 2026


# --- Remote OK ----------------------------------------------------------------------


def test_remoteok_skips_the_legal_notice_and_keeps_each_company():
    payload = [
        {"last_updated": 1793000000, "legal": "API Terms of Service: ..."},
        {
            "slug": "remote-full-stack-engineer-initech-1001",
            "id": "1001",
            "epoch": int(_recent().timestamp()),
            "date": _recent().isoformat(),
            "company": "Initech",
            "position": "Full Stack Engineer",
            "tags": ["react", "node.js", "python"],
            "description": "<p>Join us.</p>",
            "location": "United States",
            "salary_min": 100000,
            "salary_max": 130000,
            "url": "https://remoteOK.com/remote-jobs/remote-full-stack-engineer-initech-1001",
            "apply_url": "https://initech.example/apply",
        },
    ]
    session = FakeSession(FakeResponse(payload))
    site = RemoteOkSite("https://remoteok.com/api")

    (posting,) = site.fetch_page(session, "Full Stack Engineer", 1).postings

    assert session.calls == [("https://remoteok.com/api", None)]
    assert posting.job_id == "remote-ok-1001"
    assert posting.company == "Initech"
    assert posting.url == "https://remoteOK.com/remote-jobs/remote-full-stack-engineer-initech-1001"
    assert posting.is_remote is True
    assert posting.city == "United States"
    assert posting.description == "Join us.\nTags: react, node.js, python"
    assert (posting.salary_low, posting.salary_high) == (100000, 130000)


# --- Jobicy -------------------------------------------------------------------------


def test_jobicy_reads_its_filters_and_job_types():
    payload = {
        "apiVersion": "2",
        "jobCount": 2,
        "jobs": [
            {
                "id": 501,
                "url": "https://jobicy.com/jobs/501-react-developer",
                "jobTitle": "React Developer &amp; Mentor",
                "companyName": "Hooli",
                "jobIndustry": ["Programming"],
                "jobType": ["part-time"],
                "jobGeo": "USA",
                "jobLevel": "Midweight",
                "jobExcerpt": "Short.",
                "jobDescription": "<p>React and TypeScript.</p>",
                "pubDate": _recent().strftime("%Y-%m-%d %H:%M:%S"),
                "annualSalaryMin": "70000",
                "annualSalaryMax": "90000",
                "salaryCurrency": "USD",
            },
            {"id": 502, "jobTitle": "No currency", "jobType": "full-time", "jobGeo": "Anywhere",
             "annualSalaryMin": 50000, "salaryCurrency": "GBP"},
        ],
    }
    session = FakeSession(FakeResponse(payload))
    site = JobicySite("https://jobicy.com/api/v2/remote-jobs?count=100&geo=usa&industry=engineering",
                      country=US)

    postings = site.fetch_all(session)

    assert session.calls == [("https://jobicy.com/api/v2/remote-jobs",
                              {"count": "100", "geo": "usa", "industry": "engineering"})]
    react, other = postings
    assert react.job_id == "jobicy-501"
    assert react.title == "React Developer & Mentor"
    assert react.company == "Hooli"
    assert react.url == "https://jobicy.com/jobs/501-react-developer"
    assert react.job_type == "Part-time"
    assert react.city == "USA"
    assert react.description == "React and TypeScript."
    assert (react.salary_low, react.salary_high) == (70000, 90000)
    assert job_search._parse_posted_date(react.posted_date) is not None
    assert other.job_type == "Full-time"
    assert (other.salary_low, other.salary_high) == (0, 0)


# --- We Work Remotely ---------------------------------------------------------------

WWR_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel>
  <title>We Work Remotely: Programming Jobs</title>
  <item>
    <title>Umbrella Corp: Senior Backend Engineer</title>
    <region>Anywhere in the World</region>
    <country></country>
    <skills>Python, PostgreSQL</skills>
    <category>Back-End Programming</category>
    <type>Full-Time</type>
    <description>&lt;p&gt;&lt;strong&gt;Headquarters:&lt;/strong&gt; Raccoon City&lt;/p&gt;&lt;p&gt;Python and React.&lt;/p&gt;</description>
    <pubDate>{date}</pubDate>
    <guid>https://weworkremotely.com/remote-jobs/umbrella-corp-senior-backend-engineer</guid>
    <link>https://weworkremotely.com/remote-jobs/umbrella-corp-senior-backend-engineer</link>
    <media:content url="https://example.com/logo.png" type="image/png"/>
  </item>
  <item>
    <title>Contract React Developer</title>
    <region>Europe Only</region>
    <description>&lt;p&gt;React.&lt;/p&gt;</description>
    <pubDate>{date}</pubDate>
    <link>https://weworkremotely.com/remote-jobs/contract-react-developer</link>
  </item>
</channel>
</rss>
"""


def _wwr_feed():
    date = _recent().strftime("%a, %d %b %Y %H:%M:%S +0000")
    return WWR_FEED.format(date=date).encode()


def test_we_work_remotely_reads_its_rss_feed():
    session = FakeSession(FakeResponse(content=_wwr_feed()))
    site = WeWorkRemotelySite("https://weworkremotely.com/categories/remote-programming-jobs.rss")

    backend, other = site.fetch_all(session)

    assert session.calls == [("https://weworkremotely.com/categories/remote-programming-jobs.rss", None)]
    assert backend.job_id == "we-work-remotely-umbrella-corp-senior-backend-engineer"
    assert (backend.company, backend.title) == ("Umbrella Corp", "Senior Backend Engineer")
    assert backend.url == "https://weworkremotely.com/remote-jobs/umbrella-corp-senior-backend-engineer"
    assert backend.is_remote is True
    assert backend.job_type == "Full-time"
    assert backend.city == "Anywhere in the World"
    assert backend.description == "Headquarters: Raccoon City\nPython and React.\nSkills: Python, PostgreSQL"
    assert job_search._parse_posted_date(backend.posted_date) is not None
    # A title without "Company: " keeps the whole title.
    assert (other.company, other.title, other.job_type) == ("", "Contract React Developer", "")
    assert job_search._is_outside_job_country(other)


def test_a_broken_rss_feed_fails_like_a_failed_request():
    site = WeWorkRemotelySite("https://weworkremotely.com/remote-jobs.rss")

    with pytest.raises(requests.RequestException, match="isn't a readable RSS feed"):
        site.fetch_all(FakeSession(FakeResponse(content=b"<html>Just a moment...</html")))


# --- In the search ------------------------------------------------------------------


@pytest.fixture
def no_delay(monkeypatch):
    monkeypatch.setattr(job_search, "MIN_SECONDS_BETWEEN_REQUESTS", 0)


def test_search_saves_job_board_matches_under_their_own_company(no_delay):
    payload = {"jobs": [
        _himalayas_job("python-dev", company="Globex", title="Python Developer",
                       description="<p>Python, React, and AWS.</p>"),
        _himalayas_job("python-dev-ca", company="Maple", title="Python Developer",
                       description="<p>Python, React, and AWS.</p>",
                       locationRestrictions=["Canada"]),
        _himalayas_job("python-dev-hybrid", company="Hybridco", title="Python Developer",
                       description="<p>Python and React. This role is hybrid, 3 days a week in our NYC office.</p>"),
    ]}
    site = HimalayasSite("https://himalayas.app/jobs/api/search", country=US)

    result = job_search.search_site(
        FakeSession(FakeResponse(payload)), site, [(CORE_TRACK, "Python Developer")]
    )

    (match,) = result.matches
    assert match.job_id == "himalayas-globex-python-dev"
    assert match.company == "Globex"
    assert match.url == "https://himalayas.app/companies/globex/jobs/python-dev"
    # The description's on-site wording still wins over the board being remote-only.
    assert "himalayas-hybridco-python-dev-hybrid" in result.onsite


def test_a_job_board_that_cant_be_downloaded_is_asked_once_and_logged_once(no_delay, capsys):
    session = FakeSession(FakeResponse(status=404))
    site = AshbySite("Nope", "https://jobs.ashbyhq.com/nope", "nope")
    searches = [(CORE_TRACK, term) for term in CORE_TRACK.terms]

    result = job_search.search_site(session, site, searches)

    assert len(session.calls) == 1
    assert result.matches == []
    assert result.failed_terms == list(CORE_TRACK.terms)
    out = capsys.readouterr().out
    assert out.count("Nope: couldn't be searched, skipping it: HTTPError: 404") == 1
    assert "FAILED" not in out


def test_rechecking_saved_jobs_skips_boards_that_cant_load_one_job(monkeypatch, tmp_path, capsys):
    # Remote OK has no single-job API, so a saved job it no longer lists
    # can't be re-checked. It's left out, rather than reported as a job that
    # "couldn't be loaded" on every run.
    from job_store import FirestoreJobStore

    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)
    job = job_search.JobMatch(
        job_id="remote-ok-1001", title="Python Developer", city="", state="",
        is_remote=True, job_type="", salary_low=0, salary_high=0,
        url="https://remoteok.com/remote-jobs/1001", track=CORE_TRACK.name, company="Initech",
    )
    store.save_matches([job], {job.job_id})
    monkeypatch.setattr(job_search, "JOB_SEARCH_URLS", ["https://remoteok.com/api"])
    monkeypatch.setattr(job_search, "build_session", lambda: _ClosingSession())

    assert not RemoteOkSite("https://remoteok.com/api").supports_lookup
    assert job_search.recheck_saved_jobs(store) == 0
    assert "Re-check" not in capsys.readouterr().out


class _ClosingSession(NoNetworkSession):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --- Salary periods -----------------------------------------------------------------


def test_ashby_keeps_hourly_and_monthly_pay_with_its_period_and_prefers_yearly():
    site = AshbySite("Acme", "https://jobs.ashbyhq.com/acme", "acme")

    def pay(*components):
        return _ashby_job(compensation={"summaryComponents": [
            {"compensationType": "Salary", "currencyCode": "USD", "minValue": low, "maxValue": high,
             "interval": interval}
            for interval, low, high in components
        ]})

    hourly, monthly, both, fortnightly = site.fetch_all(FakeSession(FakeResponse({"jobs": [
        pay(("1 HOUR", 60, 75)),
        pay(("1 MONTH", 1200, 3000)),
        pay(("1 HOUR", 60, 75), ("1 YEAR", 125000, 156000)),
        pay(("2 WEEK", 4000, 5000)),
    ]})))

    assert (hourly.salary_low, hourly.salary_high, hourly.salary_period) == (60, 75, "hour")
    assert (monthly.salary_low, monthly.salary_high, monthly.salary_period) == (1200, 3000, "month")
    assert (both.salary_low, both.salary_high, both.salary_period) == (125000, 156000, "year")
    assert (fortnightly.salary_low, fortnightly.salary_period) == (0, "")


def test_remote_board_salary_periods():
    remoteok = RemoteOkSite("https://remoteok.com/api").fetch_all(FakeSession(FakeResponse([
        {"id": "1", "position": "Dev", "salary_min": 100000, "salary_max": 130000},
        {"id": "2", "position": "Dev"},
    ])))
    jobicy = JobicySite("https://jobicy.com/api/v2/remote-jobs").fetch_all(FakeSession(FakeResponse({"jobs": [
        {"id": 1, "jobTitle": "Dev", "salaryMin": 1200, "salaryMax": 3000, "salaryCurrency": "USD",
         "salaryPeriod": "monthly"},
        # "annualSalary" fields without a period: the amount alone decides.
        {"id": 2, "jobTitle": "Dev", "annualSalaryMin": 1200, "annualSalaryMax": 3000, "salaryCurrency": "USD"},
    ]})))
    himalayas = HimalayasSite("https://himalayas.app/jobs/api/search").fetch_page(
        FakeSession(FakeResponse({"jobs": [_himalayas_job(salaryPeriod="hourly", minSalary=50, maxSalary=70)]})),
        "x", 1,
    ).postings

    # Remote OK asks for an annual salary; no salary, no period.
    assert [(p.salary_low, p.salary_period) for p in remoteok] == [(100000, "year"), (0, "")]
    assert [(p.salary_low, p.salary_high, p.salary_period) for p in jobicy] == [
        (1200, 3000, "month"), (1200, 3000, ""),
    ]
    assert himalayas[0].salary_period == "hour"


def test_a_match_gets_its_salary_period_from_the_site_the_posting_or_the_amount(no_delay):
    # Python Developer jobs on Himalayas; only the pay differs.
    def job(slug, **pay):
        return _himalayas_job(slug, title="Python Developer", description=pay.pop("text", desc), **pay)

    desc = "<p>Python, React, and AWS.</p>"
    payload = {"jobs": [
        job("site-says", minSalary=1200, maxSalary=3000, salaryPeriod="monthly"),
        job("text-says", minSalary=1200, maxSalary=3000,
            text="<p>Python, React, and AWS.</p><p>Pay: $1,200 - $3,000 per month</p>"),
        job("amount-says", minSalary=64, maxSalary=0),
        job("nothing-says", minSalary=1200, maxSalary=3000),
    ]}
    site = HimalayasSite("https://himalayas.app/jobs/api/search", country=US)

    matches = job_search.search_site(
        FakeSession(FakeResponse(payload)), site, [(CORE_TRACK, "Python Developer")]
    ).matches

    found = {m.job_id.rsplit("-", 2)[-2]: m for m in matches}
    assert {k: (m.salary_period, m.salary_period_estimated) for k, m in found.items()} == {
        "site": ("month", False),
        "text": ("month", False),
        "amount": ("hour", True),
        "nothing": ("year", True),
    }
    assert [job_search.format_salary(found[k]) for k in ("site", "amount", "nothing")] == [
        "$1,200 - $3,000/mo", "From $64/hr (est.)", "$1,200 - $3,000/yr (est.)",
    ]
    assert "$1,200 - $3,000/mo" in job_search.build_email_body([found["site"]])
