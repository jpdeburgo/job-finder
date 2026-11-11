"""Insight Global: any On-Site makes a job not remote, in its data or on its page."""

import pytest

import job_search
from job_sites import (
    GreenhouseSite,
    InsightGlobalSite,
    Posting,
    job_section,
    onsite_evidence,
    onsite_in_fields,
    onsite_mention,
    page_to_text,
)
from job_store import FirestoreJobStore

# --- The rule ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "On-Site",
        "ONSITE",
        "Location: Miramar, FL - On-Site (Mon-Fri)",
        "This position is On-Site.",
        "Onsite Monday - Friday, 8-5",
        "Work will be on-site at our Tampa office",
        "Candidates will sit ON SITE daily",
        "Schedule: M-F, On Site",
    ],
)
def test_any_on_site_that_says_where_you_work_counts(text):
    assert onsite_mention(text)


@pytest.mark.parametrize(
    "text",
    [
        "Benefits include an on-site gym",
        "occasional on-site visits",
        "Quarterly onsite meetings",
        "Remote or On-Site",
        "On-Site/Remote",
        "provide on-site and remote support",
        "On-Site: No",
        "This role is not on-site",
        "On-site interviews required",
        "Fully remote. On-site for onboarding week",
        "Travel to client on-site 10%",
        "focus on site reliability",  # SRE, not a workplace
        "100% remote",
    ],
)
def test_on_site_that_isnt_about_where_you_work_doesnt(text):
    assert onsite_mention(text) is None


def test_the_quote_shows_the_words_around_it():
    assert onsite_mention("Benefits are great.\nLocation: Miramar, FL - On-Site (Mon-Fri)") == (
        "Location: Miramar, FL - On-Site (Mon-Fri)"
    )


def test_fields_mentioning_on_site_count_but_not_ids_titles_or_long_text():
    assert onsite_in_fields({"location": {"display": "Miramar, FL - On-Site"}}) == (
        'location.display = "Miramar, FL - On-Site"'
    )
    assert onsite_in_fields({"tags": ["Contract", "Onsite"]}) == 'tags = "Onsite"'
    assert onsite_in_fields({"jobTitle": "Dev (On-Site)", "id": "onsite-1", "url": "https://x/onsite"}) is None
    assert onsite_in_fields({"about": "This role is onsite. " * 10}) is None
    assert onsite_in_fields({"description": "On-Site"}, skip=("description",)) is None


# --- In Insight Global's data ---------------------------------------------------------------------


class FakeResponse:
    def __init__(self, payload=None, text="", status=200):
        self.payload, self.text, self.status_code = payload, text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise job_search.requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self.payload


def _record(job_id, title, **fields):
    return {
        "requisitionId": job_id, "jobTitle": title, "workRemote": True, "jobType": "Contract",
        "workAddress": {"locality": "Miramar", "administrativeArea": "FL"}, **fields,
    }


class FakeIG:
    """Insight Global's search, details, and job pages."""

    def __init__(self, records, details, pages=None):
        self.records, self.details, self.pages = records, details, pages or {}
        self.gets = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.gets.append(url)
        if url.endswith("/all/jobs"):
            return FakeResponse({"jobs": self.records, "pageMetadata": {"totalPages": 1}})
        if "/all/jobs/" in url:
            return FakeResponse(self.details[url.split("/all/jobs/")[1].split("/")[0]])
        job = url.rsplit("/jobs/", 1)[1]
        if job not in self.pages:
            return FakeResponse(status=404)
        return FakeResponse(text=self.pages[job])

    def page_gets(self):
        return [url for url in self.gets if "/all/" not in url]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


SITE = InsightGlobalSite(job_search.INSIGHT_GLOBAL_URL)
MISSED_BEFORE = "<p>Python, React, TypeScript and AWS.</p><p>Location: Miramar, FL - On-Site (Mon-Fri)</p>"


def test_a_description_mentioning_on_site_isnt_remote():
    # The general rules, for every site, let this line through.
    assert onsite_evidence("Python Developer", "Location: Miramar, FL - On-Site (Mon-Fri)") is None
    session = FakeIG([_record("a", "Python Developer")], {"a": {"description": MISSED_BEFORE}})

    (listed,) = SITE.fetch_page(session, "Python", 1).postings
    detailed = SITE.fetch_details(session, listed)

    assert (detailed.is_remote, detailed.remote_note) == (
        False, 'description: "Location: Miramar, FL - On-Site (Mon-Fri)"'
    )


def test_a_details_or_search_field_mentioning_on_site_isnt_remote():
    session = FakeIG(
        [_record("a", "Python Developer"), _record("b", "React Developer", locationLabel="Miramar, FL (On-Site)")],
        {"a": {"description": "<p>Python</p>", "locationDisplay": "Miramar, FL - On-Site"}},
    )

    listed_a, listed_b = SITE.fetch_page(session, "Python", 1).postings
    detailed = SITE.fetch_details(session, listed_a)

    assert (detailed.is_remote, detailed.remote_note) == (False, 'locationDisplay = "Miramar, FL - On-Site"')
    assert (listed_b.is_remote, listed_b.remote_note) == (False, 'locationLabel = "Miramar, FL (On-Site)"')


def test_a_remote_job_stays_remote():
    session = FakeIG(
        [_record("a", "Python Developer")],
        {"a": {"description": "<p>100% remote. Occasional on-site visits to Miramar.</p>"}},
    )
    (listed,) = SITE.fetch_page(session, "Python", 1).postings
    assert SITE.fetch_details(session, listed).is_remote is True


def test_other_sites_keep_the_general_rules():
    greenhouse = GreenhouseSite("Acme", "https://boards.greenhouse.io/acme", "acme")
    posting = greenhouse._posting({
        "id": 1, "title": "Python Developer", "location": {"name": "Remote - US"},
        "content": "&lt;p&gt;Location: Miramar, FL - On-Site (Mon-Fri)&lt;/p&gt;",
    })
    assert posting.is_remote is True
    assert job_search.check_work_arrangement(posting)[1] is None


# --- On the job's page ---------------------------------------------------------------------------

NAV = "<header><nav><a>Find a Job</a><a>On-Site Staffing Services</a></nav></header>"
FOOTER = "<footer><p>Similar jobs</p><ul><li>Java Developer</li><li>Plano, TX - On-Site</li></ul></footer>"


def _page(title, badge="", description="<p>Python, React, TypeScript and AWS, all day long.</p>"):
    return (
        f"<html><head><title>{title}</title><script>var x = 'On-Site';</script></head><body>"
        f"{NAV}<main><h1>{title}</h1><div class='badges'><span>Contract</span>{badge}</div>"
        f"<div class='description'>{description}</div></main>{FOOTER}</body></html>"
    )


def test_page_to_text_keeps_only_what_you_see():
    text = page_to_text(_page("Python Developer", "<span>On-Site</span>"))
    assert "var x" not in text
    assert text.split("\n")[:5] == ["Find a Job", "On-Site Staffing Services", "Python Developer", "Contract", "On-Site"]


def test_the_jobs_section_runs_from_its_title_to_the_end_of_its_description():
    text = page_to_text(_page("Python Developer", "<span>On-Site</span>"))
    assert job_section(text, "Python Developer", "Python, React, TypeScript and AWS, all day long.") == [
        "Python Developer", "Contract", "On-Site", "Python, React, TypeScript and AWS, all day long.",
    ]
    assert job_section(text, "Some Other Job", "") == []
    # Without a description to find, a few lines after the title.
    assert job_section(text, "Python Developer", "")[:3] == ["Python Developer", "Contract", "On-Site"]


def test_the_description_is_found_even_when_the_page_breaks_it_up_differently():
    description = ("Build APIs in Python and React for our claims platform.\n"
                   "Work with the data team on reporting, see our careers site for details.")
    page = page_to_text(
        "<nav>On-Site Staffing</nav><h1>Python Developer</h1><span>Remote</span>"
        "<p>Build APIs in Python and React for our claims platform.</p>"
        # A link splits this paragraph into three lines on the page.
        "<p>Work with the data team on reporting, see <a href='/c'>our careers site</a> for details.</p>"
        "<h2>Similar jobs</h2><ul><li>Java Developer</li><li>Dallas, TX</li><li>On-Site</li>"
        "<li>Work with the data team on reporting, see</li></ul>"
    )

    section = job_section(page, "Python Developer", description)

    # Up to its last line of real text (the description itself is read from the site's data).
    assert section == [
        "Python Developer", "Remote", "Build APIs in Python and React for our claims platform.",
        "Work with the data team on reporting, see",
    ]


def _search(session):
    return job_search.search_site(session, SITE, [(job_search.TRACKS[0], "Python Developer")])


DESCRIPTION = {"description": "<p>Python, React, TypeScript and AWS, all day long.</p>"}


@pytest.mark.job_pages
def test_a_matching_job_whose_page_says_on_site_is_dropped(capsys):
    session = FakeIG(
        [_record("badge", "Python Developer"), _record("fine", "React Developer"),
         _record("closed", "Full Stack Developer"), _record("nomatch", "Java Developer")],
        {job: {"description": "<p>Java and Spring.</p>" if job == "nomatch" else DESCRIPTION["description"]}
         for job in ("badge", "fine", "closed", "nomatch")},
        pages={"badge": _page("Python Developer", "<span>On-Site</span>"),
               # On-Site only in the site's menu and the similar jobs: not this job's.
               "fine": _page("React Developer", "<span>Remote</span>")},
    )
    site = InsightGlobalSite(job_search.INSIGHT_GLOBAL_URL)

    result = job_search.search_site(session, site, [(job_search.TRACKS[0], "Python Developer")])

    assert sorted(m.job_id for m in result.matches) == ["insight-global-closed", "insight-global-fine"]
    assert result.onsite["insight-global-badge"] == 'its job page says "On-Site"'
    # Only jobs that otherwise match have their page read.
    assert sorted(session.page_gets()) == [
        "https://insightglobal.com/jobs/badge", "https://insightglobal.com/jobs/closed",
        "https://insightglobal.com/jobs/fine",
    ]
    assert ("'Python Developer' (insight-global-badge) is marked remote, but its job page says "
            '"On-Site"; treating it as not remote.') in capsys.readouterr().out


@pytest.mark.job_pages
def test_pages_that_dont_include_the_job_stop_being_read(capsys):
    jobs = [f"j{i}" for i in range(6)]
    session = FakeIG(
        [_record(job, f"Python Developer {job}") for job in jobs],
        {job: DESCRIPTION for job in jobs},
        # Filled in by the browser: the HTML is an empty shell.
        pages={job: "<html><body><div id='app'></div></body></html>" for job in jobs},
    )
    site = InsightGlobalSite(job_search.INSIGHT_GLOBAL_URL)
    site_workers = job_search.MAX_CONCURRENT_REQUESTS_PER_SITE
    job_search.MAX_CONCURRENT_REQUESTS_PER_SITE = 1  # one at a time, so the count is exact
    try:
        result = job_search.search_site(session, site, [(job_search.TRACKS[0], "Python Developer")])
    finally:
        job_search.MAX_CONCURRENT_REQUESTS_PER_SITE = site_workers

    assert len(result.matches) == 6  # nothing on the pages: the site's data stands
    assert len(session.page_gets()) == InsightGlobalSite.PAGE_MISSES_BEFORE_GIVING_UP
    assert not site.reads_job_pages
    assert "its job pages don't include the job in their HTML" in capsys.readouterr().out


def test_job_pages_can_be_turned_off():
    session = FakeIG([_record("a", "Python Developer")], {"a": DESCRIPTION},
                     pages={"a": _page("Python Developer", "<span>On-Site</span>")})
    assert InsightGlobalSite.READ_JOB_PAGES is False  # tests turn it off (conftest.py)

    result = _search(session)

    assert [m.job_id for m in result.matches] == ["insight-global-a"]
    assert session.page_gets() == []


@pytest.mark.job_pages
def test_saved_jobs_are_rechecked_against_their_page(tmp_path, monkeypatch):
    session = FakeIG(
        [], {"a": {"jobTitle": "Python Developer", **DESCRIPTION}, "b": {"jobTitle": "React Developer", **DESCRIPTION}},
        pages={"a": _page("Python Developer", "<span>On-Site</span>"), "b": _page("React Developer")},
    )
    monkeypatch.setattr(job_search, "build_session", lambda: session)
    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)
    store.import_documents({
        f"insight-global-{job}": {"job_id": f"insight-global-{job}", "title": title, "is_remote": True,
                                  "status": "emailed", "url": f"https://insightglobal.com/jobs/{job}"}
        for job, title in (("a", "Python Developer"), ("b", "React Developer"))
    })

    assert job_search.recheck_saved_jobs(store) == 1

    saved = store.get_job("insight-global-a")
    assert (saved["is_remote"], saved["not_remote_reason"]) == (False, 'its job page says "On-Site"')
    assert store.get_job("insight-global-b")["is_remote"] is True


@pytest.mark.job_pages
def test_check_remote_shows_what_the_page_says(monkeypatch, capsys):
    session = FakeIG(
        [_record("a", "Python Developer")], {"a": {"jobTitle": "Python Developer", **DESCRIPTION}},
        pages={"a": _page("Python Developer", "<span>On-Site</span>")},
    )
    monkeypatch.setattr(job_search, "build_session", lambda: session)

    assert job_search.cli(["--check-remote", "https://insightglobal.com/jobs/a"]) == 0

    out = capsys.readouterr().out
    assert 'VERDICT: NOT REMOTE. Its job page says "On-Site".' in out
    assert "Job page (https://insightglobal.com/jobs/a), lines about where you'd work:\n  | On-Site" in out


@pytest.mark.job_pages
def test_check_remote_says_when_the_page_has_no_job(monkeypatch, capsys):
    session = FakeIG([_record("a", "Python Developer")], {"a": {"jobTitle": "Python Developer", **DESCRIPTION}},
                     pages={"a": "<html><body><div id='app'></div></body></html>"})
    monkeypatch.setattr(job_search, "build_session", lambda: session)

    job_search.cli(["--check-remote", "https://insightglobal.com/jobs/a"])

    assert "doesn't include the job in its HTML (the browser fills it in)" in capsys.readouterr().out
