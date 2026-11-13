"""New job boards to add to the search (input for the next task).

Everything here is a candidate: none of it is wired into ``JOB_SEARCH_URLS`` in
``job_boards.py`` yet. Test each company board before adding it:

    pipenv run python job_search.py --local --site <url>

Drop any board that errors or returns no jobs. Notes on each line say how sure
the URL is:
    confirmed  - seen working (API response or a live job link) in public sources
    guess      - the board name is the company name, which is usually but not
                 always right (DoorDash is "doordashusa", not "doordash")

None of these need an API key, an account, or a login.
"""

# =============================================================================
# 1. Greenhouse company boards (already supported by GreenhouseSite)
# =============================================================================
AIRBNB_URL = "https://boards.greenhouse.io/airbnb"  # confirmed
ANTHROPIC_URL = "https://boards.greenhouse.io/anthropic"  # confirmed
DOORDASH_URL = "https://boards.greenhouse.io/doordashusa"  # confirmed
STRIPE_URL = "https://boards.greenhouse.io/stripe"  # confirmed board; one source says Stripe also uses Workday
AUTOMATTIC_URL = "https://boards.greenhouse.io/automattic"  # guess; fully remote company
WEBFLOW_URL = "https://boards.greenhouse.io/webflow"  # guess; remote-first
PINTEREST_URL = "https://boards.greenhouse.io/pinterest"  # guess
INSTACART_URL = "https://boards.greenhouse.io/instacart"  # guess
BREX_URL = "https://boards.greenhouse.io/brex"  # guess

GREENHOUSE_BOARDS = [
    AIRBNB_URL,
    ANTHROPIC_URL,
    DOORDASH_URL,
    STRIPE_URL,
    AUTOMATTIC_URL,
    WEBFLOW_URL,
    PINTEREST_URL,
    INSTACART_URL,
    BREX_URL,
]

# =============================================================================
# 2. Workday company boards (already supported by WorkdaySite)
# =============================================================================
# Confirmed on Workday, but the site name after the hostname is still missing.
# Open any job on the company's careers page and copy the path segment after
# ".myworkdayjobs.com/" (and the wdN number for Capital One). Until then these
# stay commented out; WorkdaySite can't read a hostname alone.
# DELL_URL = "https://dell.wd1.myworkdayjobs.com/<site>"
# TARGET_URL = "https://target.wd5.myworkdayjobs.com/<site>"
# GENERAL_MOTORS_URL = "https://generalmotors.wd5.myworkdayjobs.com/<site>"
# WORKDAY_INC_URL = "https://workday.wd5.myworkdayjobs.com/<site>"
# CAPITAL_ONE_URL = "https://capitalone.<wdN>.myworkdayjobs.com/<site>"

WORKDAY_BOARDS: list[str] = []

# =============================================================================
# 3. Ashby company boards (NEW: needs an AshbySite adapter)
# =============================================================================
# Public, keyless JSON API, one call returns the whole board with descriptions:
#   GET https://api.ashbyhq.com/posting-api/job-board/<board>?includeCompensation=true
# Docs: https://developers.ashbyhq.com/docs/public-job-posting-api
# Each job has isRemote / workplaceType ("Remote"), employmentType
# ("FullTime", "PartTime", "Contract", ...), and compensation when published,
# so remote and part-time filtering don't need text guessing.
# Careers pages live at https://jobs.ashbyhq.com/<board>; the adapter should
# accept that URL and turn it into the API URL above.
ASHBY_API_BASE = "https://api.ashbyhq.com/posting-api/job-board/"

SUPABASE_URL = "https://jobs.ashbyhq.com/supabase"  # confirmed; fully remote
POSTHOG_URL = "https://jobs.ashbyhq.com/posthog"  # confirmed; fully remote (US/EU)
ZAPIER_URL = "https://jobs.ashbyhq.com/zapier"  # confirmed; fully remote
LINEAR_URL = "https://jobs.ashbyhq.com/linear"  # confirmed
ASHBY_URL = "https://jobs.ashbyhq.com/ashby"  # confirmed; Ashby hires on its own board, remote
OPENAI_URL = "https://jobs.ashbyhq.com/openai"  # guess; OpenAI is a large Ashby customer

ASHBY_BOARDS = [
    SUPABASE_URL,
    POSTHOG_URL,
    ZAPIER_URL,
    LINEAR_URL,
    ASHBY_URL,
    OPENAI_URL,
]

# =============================================================================
# 4. Remote-only job boards (NEW: each needs its own adapter)
# =============================================================================
# Unlike company boards, these list jobs from many companies, so each posting
# must keep its own company name (not the board's name). Every one of them asks
# for a visible link back to the original listing; keep the job URL as-is.

# Himalayas: JSON, no key. Browse returns max 20 per request (offset/limit).
# The search endpoint filters server-side, e.g. country=US, q=python,
# employment_type=Full%20Time / Part%20Time, sort=recent, page=N.
# Requires a visible link back to himalayas.app. Docs: https://himalayas.app/docs/remote-jobs-api
HIMALAYAS_BROWSE_URL = "https://himalayas.app/jobs/api"
HIMALAYAS_SEARCH_URL = "https://himalayas.app/jobs/api/search"

# Remote OK: JSON, no key. The first array element is a legal notice, not a job;
# skip it. Requires linking back to the Remote OK listing.
REMOTEOK_API_URL = "https://remoteok.com/api"

# Jobicy: JSON, no key. count=1..100, geo=usa, industry=engineering, tag=python.
# Each job has jobType: full-time, contract, part-time, or internship.
# Jobicy asks clients to call it only a few times a day.
# Docs: https://jobicy.com/jobs-rss-feed
JOBICY_API_URL = "https://jobicy.com/api/v2/remote-jobs"
JOBICY_US_ENGINEERING_URL = "https://jobicy.com/api/v2/remote-jobs?count=100&geo=usa&industry=engineering"

# We Work Remotely: public RSS (XML), no key. Asks for links back to WWR.
# Employment type is only on the all-jobs feed, not the category feeds.
# Docs: https://weworkremotely.com/remote-job-rss-feed
WWR_ALL_JOBS_RSS = "https://weworkremotely.com/remote-jobs.rss"
WWR_PROGRAMMING_RSS = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
WWR_FULL_STACK_RSS = "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss"
WWR_BACK_END_RSS = "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss"
WWR_FRONT_END_RSS = "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss"
WWR_DEVOPS_RSS = "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"

# Skipped on purpose:
# - Remotive (https://remotive.com/api/remote-jobs): its whole public feed was
#   under 20 jobs in Sept 2026, it ignores its own search/category filters, and
#   listings are delayed 24 hours.

REMOTE_JOB_BOARDS = [
    HIMALAYAS_SEARCH_URL,
    REMOTEOK_API_URL,
    JOBICY_US_ENGINEERING_URL,
    WWR_PROGRAMMING_RSS,
    WWR_FULL_STACK_RSS,
    WWR_BACK_END_RSS,
    WWR_FRONT_END_RSS,
]

# =============================================================================
# 5. Part-time job sources
# =============================================================================
# There is no good free part-time-only board with an API. Indeed, ZipRecruiter,
# FlexJobs, and Remote Rocketship all list part-time remote developer jobs, but
# they have no free public API and scraping them breaks their terms, so they're
# left out. Part-time jobs come from these keyless sources instead:

# remotejobs.org: free JSON API, no key, up to 50 jobs per page, filters by
# keyword, category, and job type. Check the docs for the job-type parameter name.
# Docs: https://remotejobs.org/developers/api
REMOTEJOBS_ORG_API_URL = "https://remotejobs.org/api/v1/jobs"

# Himalayas search with employment_type set to part time.
HIMALAYAS_PART_TIME_URL = "https://himalayas.app/jobs/api/search?country=US&employment_type=Part%20Time&sort=recent"

# Jobicy: same API as above; keep jobs whose jobType includes "part-time".
JOBICY_PART_TIME_SOURCE = JOBICY_US_ENGINEERING_URL

# Ashby: every Ashby board above reports employmentType "PartTime" per job.
# Greenhouse and Workday: no reliable job-type field; look for "part-time" in
# the title or description.

PART_TIME_SOURCES = [
    REMOTEJOBS_ORG_API_URL,
    HIMALAYAS_PART_TIME_URL,
    JOBICY_PART_TIME_SOURCE,
]
