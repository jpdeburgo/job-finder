"""The careers pages and job boards the search scans (``JOB_SEARCH_URLS``).

``job_search`` searches every URL in ``JOB_SEARCH_URLS``; ``job_sites.resolve_job_site``
works out how to read each one. Workday (``<company>.wdN.myworkdayjobs.com/<site>``),
Greenhouse (``boards.greenhouse.io/<company>``), Lever (``jobs.lever.co/<company>``),
and Ashby (``jobs.ashbyhq.com/<company>``) board URLs work as-is, and so do the
remote job boards below (Himalayas, Remote OK, Jobicy, We Work Remotely). Check how
each URL resolves with ``python job_search.py --list-sites``, and try a single board
with ``python job_search.py --local --site <url or name>``.

A board that can't be read (a wrong board name, say) is skipped with one warning
line per run; the other sites still run.
"""

INSIGHT_GLOBAL_URL = "https://insightglobal.com/jobs/search/all/all"
ACCENTURE_SEARCH_URL = "https://www.accenture.com/us-en/careers/jobsearch"

# Workday boards
NVIDIA_URL = "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"
SALESFORCE_URL = "https://salesforce.wd12.myworkdayjobs.com/External_Career_Site"
ADOBE_URL = "https://adobe.wd5.myworkdayjobs.com/external_experienced"
PAYPAL_URL = "https://paypal.wd1.myworkdayjobs.com/jobs"
MASTERCARD_URL = "https://mastercard.wd1.myworkdayjobs.com/CorporateCareers"
WALMART_URL = "https://walmart.wd5.myworkdayjobs.com/WalmartExternal"  # may have moved data centers

# Greenhouse boards
GITLAB_URL = "https://boards.greenhouse.io/gitlab"
CLOUDFLARE_URL = "https://boards.greenhouse.io/cloudflare"
DATADOG_URL = "https://boards.greenhouse.io/datadog"
REDDIT_URL = "https://boards.greenhouse.io/reddit"
DUOLINGO_URL = "https://boards.greenhouse.io/duolingo"
DATABRICKS_URL = "https://boards.greenhouse.io/databricks"
FIGMA_URL = "https://boards.greenhouse.io/figma"
VERCEL_URL = "https://boards.greenhouse.io/vercel"
ROBINHOOD_URL = "https://boards.greenhouse.io/robinhood"
COINBASE_URL = "https://boards.greenhouse.io/coinbase"
DISCORD_URL = "https://boards.greenhouse.io/discord"
GREENHOUSE_URL = "https://boards.greenhouse.io/greenhouse"
# "confirmed": seen working in public sources. "guess": the board name is the
# company name, which is usually but not always right (DoorDash's is
# "doordashusa"). Drop one that warns it couldn't be searched.
AIRBNB_URL = "https://boards.greenhouse.io/airbnb"  # confirmed
ANTHROPIC_URL = "https://boards.greenhouse.io/anthropic"  # confirmed
DOORDASH_URL = "https://boards.greenhouse.io/doordashusa"  # confirmed
STRIPE_URL = "https://boards.greenhouse.io/stripe"  # confirmed; one source says Stripe also uses Workday
AUTOMATTIC_URL = "https://boards.greenhouse.io/automattic"  # guess; fully remote company
WEBFLOW_URL = "https://boards.greenhouse.io/webflow"  # guess; remote-first
PINTEREST_URL = "https://boards.greenhouse.io/pinterest"  # guess
INSTACART_URL = "https://boards.greenhouse.io/instacart"  # guess
BREX_URL = "https://boards.greenhouse.io/brex"  # guess

# Ashby boards (api.ashbyhq.com/posting-api/job-board/<company>)
SUPABASE_URL = "https://jobs.ashbyhq.com/supabase"  # confirmed; fully remote
POSTHOG_URL = "https://jobs.ashbyhq.com/posthog"  # confirmed; fully remote (US/EU)
ZAPIER_URL = "https://jobs.ashbyhq.com/zapier"  # confirmed; fully remote
LINEAR_URL = "https://jobs.ashbyhq.com/linear"  # confirmed
ASHBY_URL = "https://jobs.ashbyhq.com/ashby"  # confirmed; Ashby hires on its own board, remote
OPENAI_URL = "https://jobs.ashbyhq.com/openai"  # guess

# Remote-only job boards: jobs from many companies, each saved under its own
# company, linking back to the board's listing (the boards ask for that).
# Himalayas is searched per term on its server; with JOB_COUNTRY set to the
# US, country=US is added. Docs: https://himalayas.app/docs/remote-jobs-api
HIMALAYAS_URL = "https://himalayas.app/jobs/api/search"
# Remote OK: its newest jobs, all at once.
REMOTEOK_URL = "https://remoteok.com/api"
# Jobicy: full-time, contract, part-time, and internships. It asks to be
# called only a few times a day; each run reads it once.
JOBICY_URL = "https://jobicy.com/api/v2/remote-jobs?count=100&geo=usa&industry=engineering"
# We Work Remotely RSS feeds. A job in several feeds is saved once. Only the
# all-jobs feed (remote-jobs.rss) says full- or part-time.
WWR_PROGRAMMING_URL = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
WWR_FULL_STACK_URL = "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss"
WWR_BACK_END_URL = "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss"
WWR_FRONT_END_URL = "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss"

# Part-time jobs. The search keeps every job type; these add part-time roles
# the searches above would miss. Jobicy (above) and Ashby boards include
# part-time jobs too, with their job type saved.
HIMALAYAS_PART_TIME_URL = (
    "https://himalayas.app/jobs/api/search?country=US&employment_type=Part%20Time&sort=recent"
)

JOB_SEARCH_URLS = [
    INSIGHT_GLOBAL_URL,
    ACCENTURE_SEARCH_URL,
    NVIDIA_URL,
    SALESFORCE_URL,
    ADOBE_URL,
    PAYPAL_URL,
    MASTERCARD_URL,
    WALMART_URL,
    GITLAB_URL,
    CLOUDFLARE_URL,
    DATADOG_URL,
    REDDIT_URL,
    DUOLINGO_URL,
    DATABRICKS_URL,
    FIGMA_URL,
    VERCEL_URL,
    ROBINHOOD_URL,
    COINBASE_URL,
    DISCORD_URL,
    GREENHOUSE_URL,
    AIRBNB_URL,
    ANTHROPIC_URL,
    DOORDASH_URL,
    STRIPE_URL,
    AUTOMATTIC_URL,
    WEBFLOW_URL,
    PINTEREST_URL,
    INSTACART_URL,
    BREX_URL,
    SUPABASE_URL,
    POSTHOG_URL,
    ZAPIER_URL,
    LINEAR_URL,
    ASHBY_URL,
    OPENAI_URL,
    HIMALAYAS_URL,
    REMOTEOK_URL,
    JOBICY_URL,
    WWR_PROGRAMMING_URL,
    WWR_FULL_STACK_URL,
    WWR_BACK_END_URL,
    WWR_FRONT_END_URL,
    HIMALAYAS_PART_TIME_URL,
]
