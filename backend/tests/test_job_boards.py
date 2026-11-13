"""The boards in job_boards.py are the ones the search uses, and each one can be read."""

import pytest

import job_boards
import job_search
from job_sites import (
    AshbySite,
    GreenhouseSite,
    HimalayasSite,
    InsightGlobalSite,
    JobicySite,
    RemoteOkSite,
    WeWorkRemotelySite,
    WorkdaySite,
    resolve_job_site,
)

BOARD_CONSTANTS = {
    name: value
    for name, value in vars(job_boards).items()
    if name.endswith("_URL") and isinstance(value, str)
}


class NoNetworkSession:
    def get(self, *args, **kwargs):
        raise AssertionError(f"unexpected GET {args}")

    def post(self, *args, **kwargs):
        raise AssertionError(f"unexpected POST {args}")


@pytest.mark.real_boards
def test_job_search_uses_the_list_from_job_boards():
    # job_search must not keep its own copy of the list.
    assert job_search.JOB_SEARCH_URLS is job_boards.JOB_SEARCH_URLS
    assert job_search.INSIGHT_GLOBAL_URL == job_boards.INSIGHT_GLOBAL_URL
    assert job_search.ACCENTURE_SEARCH_URL == job_boards.ACCENTURE_SEARCH_URL


@pytest.mark.real_boards
def test_resolve_sites_defaults_to_every_board():
    sites = job_search.resolve_sites(NoNetworkSession())

    assert [site.search_url for site in sites] == job_boards.JOB_SEARCH_URLS


def test_every_board_constant_is_searched():
    missing = [name for name, url in BOARD_CONSTANTS.items() if url not in job_boards.JOB_SEARCH_URLS]
    assert missing == [], f"defined in job_boards.py but not in JOB_SEARCH_URLS: {missing}"
    assert len(job_boards.JOB_SEARCH_URLS) == len(set(job_boards.JOB_SEARCH_URLS)), "duplicate URL"
    assert len(job_boards.JOB_SEARCH_URLS) == 43


@pytest.mark.parametrize("url", job_boards.JOB_SEARCH_URLS)
def test_every_board_resolves_without_the_network(url):
    # Direct ATS board URLs (and the two known careers pages) never need to
    # download a page to work out which API to use.
    site = resolve_job_site(url, NoNetworkSession(), country=job_search.JOB_COUNTRY)

    assert site.search_url == url
    assert site.name


def test_boards_resolve_to_the_expected_readers():
    sites = job_search.resolve_sites(NoNetworkSession(), urls=job_boards.JOB_SEARCH_URLS)
    kinds = {}
    for site in sites:
        kinds.setdefault(type(site), []).append(site.name)

    assert kinds[InsightGlobalSite] == ["Insight Global"]
    assert kinds[WorkdaySite] == [
        "Accenture", "Nvidia", "Salesforce", "Adobe", "Paypal", "Mastercard", "Walmart",
    ]
    assert kinds[GreenhouseSite] == [
        "Gitlab", "Cloudflare", "Datadog", "Reddit", "Duolingo", "Databricks", "Figma",
        "Vercel", "Robinhood", "Coinbase", "Discord", "Greenhouse",
        "Airbnb", "Anthropic", "Doordashusa", "Stripe", "Automattic", "Webflow",
        "Pinterest", "Instacart", "Brex",
    ]
    assert kinds[AshbySite] == ["Supabase", "Posthog", "Zapier", "Linear", "Ashby", "Openai"]
    assert kinds[HimalayasSite] == ["Himalayas", "Himalayas (Part Time)"]
    assert kinds[RemoteOkSite] == ["Remote OK"]
    assert kinds[JobicySite] == ["Jobicy"]
    assert kinds[WeWorkRemotelySite] == [
        "We Work Remotely (Programming)", "We Work Remotely (Full Stack Programming)",
        "We Work Remotely (Back End Programming)", "We Work Remotely (Front End Programming)",
    ]
    # Job IDs are prefixed per company (or job board), so two sources can't
    # collide. Feeds of one job board share its prefix, so a job listed in
    # two of them is saved once.
    sources: dict[str, set[type]] = {}
    for site in sites:
        sources.setdefault(site.id_prefix, set()).add(type(site))
    assert all(len(types) == 1 for types in sources.values()), sources
    shared = {prefix for prefix in sources if sum(s.id_prefix == prefix for s in sites) > 1}
    assert shared == {"himalayas-", "we-work-remotely-"}


def test_greenhouse_and_workday_boards_point_at_their_apis():
    sites = {
        site.search_url: site
        for site in job_search.resolve_sites(NoNetworkSession(), urls=job_boards.JOB_SEARCH_URLS)
    }

    assert sites[job_boards.GITLAB_URL].api_url == (
        "https://boards-api.greenhouse.io/v1/boards/gitlab/jobs"
    )
    assert sites[job_boards.NVIDIA_URL].api_url == (
        "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite"
    )
    # Workday boards are narrowed to JOB_COUNTRY by the board's own filter.
    assert sites[job_boards.WALMART_URL].country == job_search.JOB_COUNTRY


def test_ashby_and_remote_boards_point_at_their_apis():
    sites = {
        site.search_url: site
        for site in job_search.resolve_sites(NoNetworkSession(), urls=job_boards.JOB_SEARCH_URLS)
    }

    assert sites[job_boards.SUPABASE_URL].api_url == (
        "https://api.ashbyhq.com/posting-api/job-board/supabase"
    )
    assert sites[job_boards.HIMALAYAS_URL].params == {"sort": "recent", "country": "US"}
    assert sites[job_boards.HIMALAYAS_PART_TIME_URL].params["employment_type"] == "Part Time"
    assert sites[job_boards.JOBICY_URL].params == {
        "count": "100", "geo": "usa", "industry": "engineering",
    }
    assert sites[job_boards.WWR_BACK_END_URL].api_url == job_boards.WWR_BACK_END_URL
