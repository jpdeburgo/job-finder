"""The careers pages and job boards the search scans (``JOB_SEARCH_URLS``).

``job_search`` searches every URL in ``JOB_SEARCH_URLS``; ``job_sites.resolve_job_site``
works out how to read each one. Workday (``<company>.wdN.myworkdayjobs.com/<site>``),
Greenhouse (``boards.greenhouse.io/<company>``), and Lever (``jobs.lever.co/<company>``)
board URLs work as-is. Check how each URL resolves with
``python job_search.py --list-sites``, and try a single board with
``python job_search.py --local --site <url or name>``.
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
]
