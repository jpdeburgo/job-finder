# Job Finder (backend)

The search script, job store, CLI, and the HTTP API the dashboard uses to
start searches (`api.py`). The Next.js dashboard that reads the
same data lives in [`../frontend`](../frontend/README.md); the repository
overview is in the [root README](../README.md). Run every command below from
this `backend/` directory.

Searches every careers page in `JOB_SEARCH_URLS` (in `job_boards.py`: Insight
Global, Accenture, 33 company Workday/Greenhouse/Ashby boards, and the remote
job boards Himalayas, Remote OK, Jobicy, and We Work Remotely; see
[Job sites](#job-sites)) for remote jobs matching configurable tracks:

- **Core stack:** software engineering roles scored against your skills. A
  job needs at least two matches, one of them a core skill (by default
  Python, JavaScript, TypeScript, Java, React, Node.js), so postings that
  only mention cloud tooling or SQL don't qualify. Edit the list on the
  dashboard's **Skills** page (see [Your skills](#your-skills)); until you
  do, the search uses `RESUME_SKILLS` and `CORE_LANGUAGE_SKILLS`.
- **Growth tracks (Java, iOS, .NET):** junior and entry-level roles in a
  single skill that do not explicitly require more than three years of
  experience.

Upload your resume on the dashboard's **Resume** page (or with `resume.py`)
to see the skills and years of experience it shows, worked out by parsing it
or with AI, and add the skills it finds to your list (see
[Your resume](#your-resume)).

International/LATAM/India/Nearshore-titled postings are always filtered out
(the feed has no country, and these listings carry placeholder US locations),
as are listings tagged Alaska whose city isn't actually in Alaska (a recurring
placeholder Insight Global uses for offshore postings). Titles naming a
stack outside the resume (Drupal, Android, SAP, Snowflake, etc. — see
`NON_RESUME_TITLE_TECH`) are dropped too, along with "COPY - ..." duplicate
listings and postings older than `MAX_POSTED_AGE_DAYS` (30). A title that
names a growth-track stack (Java/iOS/.NET) is only ever evaluated under that
stack's own growth-track rules, even if it racks up enough incidental
core-skill matches to otherwise pass as a Core match. Each emailed job shows
its Job ID alongside the usual details, plus a **fit score** that ranks how
well it suits you (see [Fit score](#fit-score)).

Only new matches are emailed. Every match is recorded in **Firebase
Firestore** along with its details and an application status, so you can track
which jobs you've applied to (see [Job tracking](#job-tracking)). Without
Firebase credentials the script transparently uses `local_firestore.json`, a
local stand-in with the same layout, so nothing needs to be set up to run or
test it on your machine.

## Job sites

`JOB_SEARCH_URLS` in `job_boards.py` lists the pages to scan:

```python
INSIGHT_GLOBAL_URL = "https://insightglobal.com/jobs/search/all/all"
ACCENTURE_SEARCH_URL = "https://www.accenture.com/us-en/careers/jobsearch"
NVIDIA_URL = "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"   # Workday
GITLAB_URL = "https://boards.greenhouse.io/gitlab"                              # Greenhouse
SUPABASE_URL = "https://jobs.ashbyhq.com/supabase"                              # Ashby
HIMALAYAS_URL = "https://himalayas.app/jobs/api/search"                         # remote job board
...
JOB_SEARCH_URLS = [INSIGHT_GLOBAL_URL, ACCENTURE_SEARCH_URL, NVIDIA_URL, ..., GITLAB_URL, ...]
```

Out of the box that's 43 URLs:

- Insight Global and Accenture.
- Six more Workday boards: NVIDIA, Salesforce, Adobe, PayPal, Mastercard, Walmart.
- 21 Greenhouse boards: GitLab, Cloudflare, Datadog, Reddit, Duolingo,
  Databricks, Figma, Vercel, Robinhood, Coinbase, Discord, Greenhouse, Airbnb,
  Anthropic, DoorDash (`doordashusa`), Stripe, Automattic, Webflow, Pinterest,
  Instacart, Brex.
- Six Ashby boards: Supabase, PostHog, Zapier, Linear, Ashby, OpenAI.
- Remote job boards, which list many companies' jobs: Himalayas (plus a
  second, part-time-only Himalayas search), Remote OK, Jobicy (US
  engineering), and four We Work Remotely feeds (programming, full stack,
  back end, front end).

Some of the newer company boards are guesses at the board name (marked
`# guess` in `job_boards.py`). A board that can't be read is skipped with a
single `couldn't be searched` line per run while the other sites still run.
Delete it from `job_boards.py` if that keeps happening.
`python job_search.py --list-sites` shows how each one is read. A test
(`tests/test_job_boards.py`) fails if a `*_URL` constant in `job_boards.py`
is missing from `JOB_SEARCH_URLS`, or if a URL stops resolving to a board.

Careers pages like these render their results in the browser, so their HTML
has no jobs in it. `job_sites.resolve_job_site` maps each URL to the JSON API
the page itself calls. Every site returns the same `Posting` fields, and the
filters, tracks, and skill scoring above treat every site the same way.

| URL | Read through | Job IDs | Notes |
| --- | --- | --- | --- |
| Insight Global | `/all/jobs` search and `/all/jobs/<id>/details` on insightglobal.com | `insight-global-<uuid>` | Contract / contract-to-perm only. Links to `https://insightglobal.com/jobs/<id>`. |
| Accenture | its Workday board, `accenture.wd103.myworkdayjobs.com/AccentureCareers` (via `KNOWN_CAREER_SITES`) | `accenture-<requisition>` | Any job type (Accenture hires directly). Narrowed to `JOB_COUNTRY` (United States). Links to the Workday posting. |
| Any Workday board: `https://<company>.wdN.myworkdayjobs.com/<site>` | Workday's `/wday/cxs/...` search API | `<company>-<requisition>` | Narrowed to `JOB_COUNTRY` when the board has a country filter. |
| Any Greenhouse board: `https://boards.greenhouse.io/<company>` | Greenhouse Job Board API | `<company>-<id>` | The whole board is downloaded once per run; search terms are matched against titles and descriptions locally. No country filter, so jobs whose location names another country or region ("Remote - Canada", "Remote, EMEA") are dropped (see `NON_US_LOCATION_WORDS`). |
| Any Lever board: `https://jobs.lever.co/<company>` | Lever Postings API | `<company>-<id>` | Same as Greenhouse. |
| Any Ashby board: `https://jobs.ashbyhq.com/<company>` | Ashby's public job posting API (`api.ashbyhq.com/posting-api/job-board/<company>?includeCompensation=true`) | `<company>-<id>` | Same as Greenhouse. Each job states whether it's remote (`workplaceType`), its employment type (full-time, part-time, contract, ...), and a salary when the company publishes one. |
| Himalayas: `https://himalayas.app/jobs/api/search` | Himalayas search API | `himalayas-<company>-<slug>` | Searched per term on Himalayas' server, newest first. Filters in the URL (`employment_type=Part%20Time`) are kept; `country=US` is added when `JOB_COUNTRY` is the US. |
| Remote OK: `https://remoteok.com/api` | Remote OK API | `remote-ok-<id>` | Its newest jobs, all at once, matched locally like Greenhouse. No job type. |
| Jobicy: `https://jobicy.com/api/v2/remote-jobs?...` | Jobicy API | `jobicy-<id>` | Up to 100 jobs at once (the URL's `geo`, `industry`, `tag` filters are kept; `geo=usa` is added for the US), matched locally. Jobicy asks to be called only a few times a day. |
| We Work Remotely: any `https://weworkremotely.com/...rss` feed | the RSS feed | `we-work-remotely-<slug>` | Matched locally. Every feed shares one ID space, so a job in several category feeds is saved once. Only the all-jobs feed says the job type. |
| Any other careers page | the page's HTML is checked for a Workday/Greenhouse/Lever/Ashby board link | as above | If no link is found, the site is skipped with a warning. Add its board to `KNOWN_CAREER_SITES` in `job_sites.py`. |

**Remote job boards** (Himalayas, Remote OK, Jobicy, We Work Remotely) list
jobs from many companies, so each job is saved under the company that's
hiring, not the board. Its link goes to the board's own listing, because each
board asks for a visible link back. These jobs are all remote, but many are
limited to certain countries. The board's location restriction ("Europe
Only", "Canada", "USA") is saved as the job's location, so the same
`NON_US_LOCATION_WORDS` check as Greenhouse drops jobs outside the US. None of
these boards has an API for loading one job, so saved jobs from them are only
re-checked when a search finds them again (`--check-remote` can't load them
either; Lever is the same). The same job can show up on a company board and
on a job board; each copy is saved separately.

**Part-time jobs.** The search keeps every job type and saves it in
`job_type`, which the dashboard shows and searches. Ashby boards, Jobicy, and
Himalayas report it per job. `HIMALAYAS_PART_TIME_URL` adds a Himalayas search
limited to part-time roles. Greenhouse and Workday give no reliable type, so
those jobs show whatever the board says (often nothing).

To add a company, add its careers page or ATS board URL to `job_boards.py`
and to `JOB_SEARCH_URLS` there. Each run prints how many matches every site produced. A
URL that can't be resolved is skipped with a warning, and the other sites
still run.

**Remote only.** `REMOTE_ONLY` applies to every site. Each job gets one of
three remote statuses, saved in its `is_remote` field:

| Status | `is_remote` | When | With `REMOTE_ONLY` |
| --- | --- | --- | --- |
| Remote | `true` | The site marks it remote. | kept |
| Not remote | `false` | The site marks it hybrid or on-site. | dropped |
| Unmarked | `null` | The site doesn't say. | dropped, unless you ask for unmarked jobs |

Where the status comes from: Insight Global's `workRemote`; Workday's
`remoteType` (only on the job's details page, so every Workday posting gets a
details request; it overrides a "Remote" location in the search results) or a
location saying "Remote"; Lever's `workplaceType`, with the location as a
fallback; Ashby's `workplaceType`, then its `isRemote` flag; for Greenhouse,
the company's own "Workplace Type" field if it has one, else the location
text; and the remote job boards are remote-only, so their jobs start out
remote.

Those flags are often wrong, so two more things are checked. Any other
work-arrangement field in a site's data (`workType`, `isHybrid`,
`remoteWork: "No"`, `workLocation.type`, ...; `structured_remote` in
`job_sites.py`), or any field whose whole value is an arrangement (a badge or
tag like "Onsite" or "Hybrid"), wins over the main flag when it says on-site
or hybrid. Yes/no flags are read as sites send them (`true`, `"false"`,
`"No"`, `1`). And every posting is **read for an on-site
or hybrid requirement** once its details are loaded (`onsite_evidence`). A job is treated as not remote, whatever its site says, when
its title says "On-Site", "Onsite", "In-Office", or "Hybrid"; its location
says hybrid or on-site; or its description says so outright, e.g. "This role
is onsite in Dallas", "a hybrid position", "must be onsite", "3 days a week in
office", "Work arrangement: Hybrid", or "This is not a remote position". Only
clear statements count: benefits ("on-site gym"), occasional visits ("onsite
once a quarter", "travel to the office for onboarding"), choices ("remote or
hybrid"), answers in the negative ("Onsite: No"), and tech ("Hybrid Cloud
Engineer") don't. Descriptions keep their line breaks, so a line that is just
a label ("Onsite", "Hybrid - Dallas, TX", "100% Onsite") counts, and so does
recruiter shorthand: "Onsite in Atlanta", "(Hybrid)", "will sit onsite",
"onsite 3x a week", "No remote.".

**Insight Global is read more strictly.** Its remote flag is wrong often
enough that any mention of On-Site (or Onsite, ON SITE) about where you'd
work makes one of its jobs not remote (`onsite_mention` in `job_sites.py`),
however it's worded: "Location: Miramar, FL - On-Site (Mon-Fri)", "ONSITE",
"this is an On-Site role". It's looked for in three places:

- the description;
- every short field in Insight Global's data, not just the ones named for
  the work arrangement (`"locationDisplay": "Miramar, FL - On-Site"`);
- the job's own page (`https://insightglobal.com/jobs/<id>`), for each job
  that otherwise matches (one extra request per match). Only the job's part
  of the page counts, from its title to the end of its description, so the
  site's menus and footer and the "similar jobs" listed under it don't. If
  the pages turn out to be filled in by the browser (their HTML has no job
  in it), the page check stops for the rest of the run and says so. Set
  `InsightGlobalSite.READ_JOB_PAGES = False` in `job_sites.py` to skip it.

Mentions that aren't about where you'd work still don't count: "on-site
gym", "occasional on-site visits", "on-site for onboarding", "On-Site: No",
"Remote or On-Site", "on-site and remote support". Other sites keep the
rules above. A job dropped this way says why in the dashboard, e.g. "Listed
as remote, but its job page says "On-Site"".

To see how one job is read, and why, check it by URL or by its saved job ID:

```bash
pipenv run python job_search.py --check-remote https://insightglobal.com/jobs/<id>
pipenv run python job_search.py --check-remote insight-global-<id>     # a saved job
```

It prints the verdict, every field in the site's data, and the description
lines about where you'd work (for Insight Global, the job page's too). If a job says on-site and the verdict is
"remote", that output shows exactly what the check missed. Each job dropped this way
is printed with the words that gave it away, e.g.

```
Insight Global: 'React Developer' (insight-global-...) is marked remote but its
description: "This position is onsite in Plano, TX"; treating it as not remote.
```

Jobs saved before a check existed are corrected too. After each search, every
saved job still marked remote that the search didn't check (postings it
didn't see again: closed, or past the pages it reads) has its posting loaded
and checked the same way (`RECHECK_SAVED_JOBS`). Any that turn out on-site or
hybrid are set to not remote, with the reason in `not_remote_reason` (shown in
the dashboard's details drawer); their status is left alone. To do just that,
without searching or emailing:

```bash
pipenv run python job_search.py --recheck-saved                 # every saved remote job
pipenv run python job_search.py --recheck-saved --site insight-global
```

It prints each job it marks not remote, and writes every re-checked job's
verdict, site fields, and description lines to `remote_check_report.txt`.
For Insight Global, a job's details leave out `workRemote`, so each re-check
also finds the job's own entry in Insight Global's search results (by its
title, with the remote filter off) and reads its flags there.

**When the checks get it wrong, say so yourself.** Mark a job On-site, Hybrid,
or Remote in the dashboard (the **Work arrangement** menu in its details
drawer), with `jobs_cli.py onsite|hybrid|remote <job id>`, or with
`PATCH /jobs/<id> {"work_arrangement": "on_site"}`. Your choice is saved as
`work_arrangement`, next to the site's `is_remote`, and wins everywhere the
job is read: the Remote filter, labels, stats, and the API. Searches and
re-checks never change it. Choose "As the site says" (or `jobs_cli.py
arrangement <job id> site`) to go back to the site's word. About half of Accenture's US postings are unmarked, and
about 1 in 10 is marked remote.

To see the unmarked ones too:

```bash
pipenv run python job_search.py --include-unmarked          # every site, this run
```

or keep them for one site on every run (Render included):

```python
SITE_SETTINGS = {ACCENTURE_SEARCH_URL: {"include_unmarked_remote": True}}
```

Unmarked jobs say **Remote not stated: check the posting** in the email, and
the dashboard's **Remote** filter can show just them. To also keep hybrid and
on-site jobs for a site, turn off remote-only for it:
`SITE_SETTINGS = {ACCENTURE_SEARCH_URL: {"remote_only": False}}`.

`contract_only` works the same way. It's on for Insight Global, a staffing
agency, and off for every other site, since companies hiring directly mostly
post full-time roles.

## Your skills

The skills the Core track matches on, which of them are core, and how well
you know each are edited on the dashboard's **Skills** page (`/skills`): add
skills (several at once, comma-separated), move the ones that are your main
stack up to **Core skills**, rate each one 1 to 5 stars, remove the rest,
and **Save**. The list is saved in the database, next to your jobs:

```
settings/search_skills
    skills        ["Python", "Go", "Kubernetes", ...]   every skill to look for
    core_skills   ["Python", "Go"]                      your main stack (a subset of skills)
    proficiency   {"Python": 5, "Go": 2, ...}           how well you know each, 1-5 stars
    updated_at
```

Saving also re-scores the jobs you've already saved (see
[Reassessing saved jobs](#reassessing-saved-jobs)), when the API is running.

Every search reads it when it starts (the cron job, the dashboard's **Run
search**, and `python job_search.py` alike), and prints which list it's using:

```
Skills (saved in the dashboard; * = core): Python*, Go*, Kubernetes, SQL
```

What the list changes:

- **Matching.** A Core-track job needs `MIN_SKILL_MATCHES` (2) of your
  skills, at least one of them core. Matching only matches whole words, so
  "Java" doesn't match "JavaScript". Case never matters, anywhere: "python"
  on your list matches "Python" and "PYTHON" in a posting, scores the same,
  and can't be added twice; "react" and "REACTJS" are still one skill in
  the fit score (`SKILL_ALIASES`).
- **Fit score.** Core skills count 1 and the others 0.5, each scaled by your
  stars for it (see [Proficiency](#proficiency) and [Fit score](#fit-score)).
- **Unfamiliar tech.** A skill you add that's in `NON_RESUME_TITLE_TECH`
  (Kotlin, PHP, Snowflake, ...) stops counting as off your resume, so titles
  naming it are no longer dropped and descriptions naming it no longer cost
  fit points.

The growth tracks (Java, iOS, .NET) keep their own single skill.
**Reset to defaults** on the Skills page deletes the document, and searches
go back to `RESUME_SKILLS` and `CORE_LANGUAGE_SKILLS` in `job_search.py`. A
list that can't be used (say, edited by hand in the Firebase console so it
has no core skill) is ignored with a warning and the defaults are used.
`frontend/src/lib/skills.ts` mirrors the two default lists to show them before
you save your own (a test checks they match), and both sides validate a list
the same way (`search_skills.py`).

### Proficiency

Stars say how well you know a skill. They never change which jobs match,
only how well a match fits: each matched skill's weight in the fit score
(core 1, other 0.5) is multiplied by its stars' factor
(`PROFICIENCY_FACTORS` in `job_fit.py`):

| Stars | Label | Factor |
| --- | --- | --- |
| 1 | Beginner | 0.25 |
| 2 | Familiar | 0.6 |
| 3 | Proficient | 1.0 (the default) |
| 4 | Advanced | 1.25 |
| 5 | Expert | 1.5 |

So a posting built on skills you're expert in reaches full skill points
sooner, and one that leans on skills you barely know scores lower. A core
skill in the title ("React Developer") earns its 15 role points in full at 3
stars or more, and a share at fewer (15 x 0.6 at 2 stars). New skills, and
every skill in a list saved before stars existed, count as 3 stars, so
their fit scores are unchanged until you rate them. The fit reasons show the
stars you've set, e.g. "Skills: Python 5★, React, SQL 1★ (2 core)". Each
spelling of a skill (React, ReactJS) has its own stars; a posting that uses
both is scored with the better one.

### Reassessing saved jobs

Jobs you've already saved are re-scored against your current skills and
stars when you save your skills on the dashboard's Skills page or click
**Refresh** on its Jobs page (both call `POST /jobs/reassess`, so the
[API](#running-a-search-from-the-dashboard-http-api) must be running), at
the end of every search, or with:

```bash
pipenv run python job_search.py --reassess
```

Each job's matched skills, `score`, and fit score are worked out again from
its description, on the track it was found on, and the job is marked with
whether it would still match:

| Field | Meaning |
| --- | --- |
| `matches_skills` | `true`: still a match. `false`: it wouldn't be found with your skills now. Missing until the job is first reassessed. |
| `skills_mismatch_reason` | Why not, e.g. "it mentions only SQL; a match needs 2 of your skills" or "its title names Kotlin, which isn't one of your skills". |

Jobs that no longer match are **flagged, never deleted**, and their status,
notes, and everything else are left alone. The dashboard shows a "No longer
matches your skills" badge on them. Only jobs whose fields actually change
are written.

Re-scoring needs each job's description. Searches keep it, in the
`job_descriptions` collection (one document per job ID, apart from the job so
the dashboard's job list stays small). Jobs saved before that have theirs
loaded from their job site the first time you reassess (one request per job,
so it can take a minute) and kept for next time. A posting that has closed
can't be loaded; that job keeps its old score and the summary counts it. A
search's own reassessment only uses descriptions already saved, and the
re-check of saved jobs (`RECHECK_SAVED_JOBS`) saves the ones it loads.

## Your resume

Upload your resume on the dashboard's **Resume** page (`/resume`) and it
works out **the skills you have** and **your years of experience**, two ways:

| Reading | How | Needs |
| --- | --- | --- |
| **Parsed** | Rules (`resume_parser.py`): finds the work history's date ranges and the skills in `skill_catalog.py` (about 170, with their spellings) plus every skill on your list. Runs on every upload, instantly. | Nothing |
| **AI** | A language model (`resume_ai.py`) reads the work history and skills; better with unusual layouts, and at telling an employer ("Oracle", "Salesforce") from a skill. Skills on your own list are always included when the resume names them, even if the model passes over one it doesn't recognize (a note says so). Click **Read with AI**. | An API key (below) |

Both give the same things, so you can compare them on the page:

- **Years of experience**: the dates of the jobs in your work history added
  up, with **overlapping jobs counted once** (a freelance gig alongside a
  full-time job doesn't double those years). Education, projects, and dates
  inside bullet points don't count. A range given in years only ("2016 -
  2019") runs from January to December. With no dates at all, the years the
  resume states ("8+ years of experience") are used, and when the two
  disagree by 2 years or more, a note says so.
- **Skills**, each with **years**: the time covered by the jobs whose
  entries mention it (overlaps counted once), and when you last used it. A
  skill only named in a Skills section is found but has no years. Spellings
  are merged ("ReactJS", "React.js" -> React), and the page shows which
  skills are **on your list already**, in any spelling.
- **A level for each skill**, in the Skills page's stars (1 Beginner ... 5
  Expert), with the reason ("7.9 years across 2 jobs; still using it").
  Parsing infers it (`skill_levels.py`): a level the resume gives the skill
  itself wins ("Expert: Python", "familiar with Docker", "Go (advanced)");
  otherwise years of use set it (under 1 year Familiar, 1-3 Proficient, 3-5
  Advanced, 5+ Expert, which also needs the skill named 3+ times, in 2+ jobs,
  or in a job title), counting the jobs that used something built on it
  (React and TypeScript work is JavaScript work; PostgreSQL is SQL) and
  years stated for it ("5+ years of Python"). A job title naming it means
  at least Advanced; not used for 4+ years costs a star, unless the Skills
  section still lists it; only listed is Familiar. The AI rates each skill
  itself, weighing what the work shows ("led the migration" vs. "some
  exposure to"), and the rules fill in any it doesn't rate.
- **The jobs counted**, with their dates, so you can check the arithmetic.

The AI only *reads*: it returns each job's title, company, dates, and skills,
and the years are added up in code exactly like the parser's (models are
unreliable at date arithmetic). Select skills on the page and **Add to your
list** to add them to [your skills](#your-skills) as **core** skills at the
stars the resume suggests. A skill already on your list stays core or other
as you have it; when the resume suggests different stars, it can be ticked
too, to take them ("Update ReactJS to 5 stars"). Nothing on your list
changes unless you tick it. Saving re-scores your saved jobs, like the
Skills page. Move any that aren't your main stack
down to other skills on the Skills page: a Core match needs one core skill,
so a core "Docker" lets a posting that's only about Docker and SQL match. The years of
experience are shown, not used: the fit score still compares jobs with
`YEARS_OF_EXPERIENCE` in `job_search.py`.

Files: PDF (with real text; a scanned image has none), Word `.docx`, or
plain text, up to 5 MB, or paste the text. Old `.doc` files and
password-protected PDFs can't be read; the page says why. The text read from
the file is shown under the results, to check it came through.

**Setting up AI.** Add an API key for either provider to `backend/.env` and
restart the API:

```bash
ANTHROPIC_API_KEY=sk-ant-...     # Claude (default model claude-sonnet-4-5)
OPENAI_API_KEY=sk-...            # or OpenAI (default model gpt-4.1-mini)
RESUME_AI_PROVIDER=openai        # optional: which one, when both keys are set (Anthropic otherwise)
RESUME_AI_MODEL=...              # optional: another model from that provider
```

Only the resume's text is sent, and only when you click **Read with AI**.

The resume is kept in the database with its readings; uploading another
replaces it, and **Remove** deletes it (your skill list stays as it is):

```
settings/resume
    filename, file_type (pdf | docx | text), text, fingerprint, uploaded_at
    analyses      {"parse": {...}, "ai": {...}}: years_experience, years_basis,
                  stated_years, skills [{name, category, years, mentions, last_used,
                  aliases, level, level_reason}], positions [{title, company, start,
                  end, months, skills}],
                  notes, analyzed_at, provider, model
```

From the command line:

```bash
pipenv run python resume.py ~/Documents/resume.pdf          # parse it and print what it found
pipenv run python resume.py ~/Documents/resume.pdf --ai     # read it with AI instead
pipenv run python resume.py ~/Documents/resume.pdf --save   # also save it for the Resume page
```

## Fit score

Every match gets a **fit score** from 0 to 100 (`job_fit.py`) that ranks how
well the job suits you, so the best jobs rise to the top. The email sorts each
track's jobs best fit first and shows the score on each one (e.g. **Fit 82/100
(Strong)**). The dashboard shows it in a **Fit** column, sorts by it with
**Best fit**, and the details drawer explains it. The old `score` field (the
number of matched skills) is still saved, but a raw count can't tell a
"Network Engineer" posting that mentions four of your tools from a "Full Stack
Developer" built on your main languages.

| Part | Points | What it measures |
| --- | --- | --- |
| `skills` | 0 to 55 | [Your skills](#your-skills) the posting mentions. Core skills count 1, other skills 0.5, times your [stars](#proficiency) for each (1 star 0.25x ... 5 stars 1.5x), and spellings of one skill (`SKILL_ALIASES`: React/ReactJS) count once. Full marks at 4. |
| `role` | 0 to 45 | The title is a role you target (`TARGET_ROLE_TITLES`: Software Engineer, Full Stack, Backend, ...) = 30, or a generic one (`GENERIC_ROLE_TITLES`: Developer) = 15; a core skill in the title adds 15 (a share of it if you've rated that skill under 3 stars). |
| `experience` | 0 or less | Years asked for (or implied by the title: Senior ~5, Lead/Staff ~7, Principal ~9, whichever is more) against `YEARS_OF_EXPERIENCE`. 1 year short keeps 90%, 2 keep 75%, 3 keep 60%, 4+ keep 45%. |
| `remote` | 0 or less | Remote keeps 100%, "remote not stated" 85%, hybrid/on-site 60%. |
| `stack` | 0 or less | The description names tech not on your resume (`NON_RESUME_TITLE_TECH`): -5% each, at most -15%. |

The parts are saved in `fit_breakdown` and add up to `fit_score`
(`fit_reasons` says the same in words). Bands: **Strong** 75+, **Good** 60+,
**Fair** 40+, **Weak** below 40. Set `YEARS_OF_EXPERIENCE` in `job_search.py`
to your own number. Growth-track jobs (Java/iOS/.NET) score lower because
those stacks aren't your main one; they still appear in their own section of
the email. Jobs saved before the fit score existed show a dash until a search
sees them again.

## Install and run

```bash
cd backend
pipenv install --dev
pipenv run python job_search.py                       # every site in JOB_SEARCH_URLS
pipenv run python job_search.py --local               # use local_firestore.json, even if Firebase is configured
pipenv run python job_search.py --site accenture      # only Accenture
pipenv run python job_search.py --site workday        # every Workday board
pipenv run python job_search.py --local --site https://boards.greenhouse.io/acme   # try a new board
pipenv run python job_search.py --include-unmarked    # also keep jobs whose remote status isn't stated
pipenv run python job_search.py --list-sites          # what's configured and how each is read
pipenv run python job_search.py --reassess            # re-score saved jobs against your skills (no search, no email)
pipenv run uvicorn api:app --reload                   # let the dashboard's Run search button start runs (see below)
```

`--site` takes a site name (`accenture`, `"insight global"`), a board kind
(`insight-global`, `workday`, `greenhouse`, `lever`, `ashby`, `himalayas`,
`remoteok`, `jobicy`, `weworkremotely`), or any careers page or
board URL, including one that isn't in `JOB_SEARCH_URLS`. Repeat it to search
several. It matches case-insensitively and ignores spaces and dashes. A value
that matches nothing exits with the list of available sites. `--local`
overrides `IG_STATE_BACKEND` for that run; use `jobs_cli.py --local` to read
the same file afterwards. The dashboard still picks its database from
`backend/.env`, so set `IG_STATE_BACKEND=local` there to point it at the file.

### Speed

Sites are searched at the same time. Within a site, the search terms are
listed several at a time, then every distinct posting that survives the cheap
title/date/remote checks has its description loaded once (also several at a
time), and finally everything is scored. Politeness is enforced per host
instead of by fixed sleeps:

| Setting in `job_search.py` | Default | Meaning |
| --- | --- | --- |
| `MAX_CONCURRENT_REQUESTS_PER_SITE` | 4 | requests in flight per site |
| `MIN_SECONDS_BETWEEN_REQUESTS` | 0.25 | minimum gap between request starts to the same host (so at most 4 per second) |
| `MAX_PAGES_PER_SEARCH` | 10 | result pages per term (Workday and Himalayas pages hold 20 results, Insight Global's 50) |

A timing line is printed per site. Accenture dominates: Workday sorts by
relevance, so every term reads all its pages, and most postings need a details
request to learn whether they're remote. If a site starts answering 429 or
403, raise `MIN_SECONDS_BETWEEN_REQUESTS`.

The Pipfile accepts any Python 3 (the committed `Pipfile.lock` was resolved on
3.12 and its pinned wheels need 3.11+; on an older interpreter run
`pipenv lock` first to re-resolve). Run locally with no Firebase configured and
you'll see each database call the script would have made:

```
Firebase is not configured; using the local Firestore stand-in (local_firestore.json). ...
[local firestore] list_documents jobs
[local firestore] query jobs where status == 'unemailed'
...
[local firestore] batch commit (3 writes)
[local firestore]   set jobs/insight-global-6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba (merge): status='unemailed', title='React Developer'
Saved 3 match(es).
[local firestore] batch commit (1 writes)
[local firestore]   set jobs/insight-global-6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba (merge): status='emailed'
Email sent (...).
[local firestore] set runs/4yDsBPXRANBbEYCFdI1R
```

Tune search terms, the default skills, remote-only behavior, page depth, and
matching thresholds at the top of `job_search.py`. Your own skill list is
edited in the dashboard (see [Your skills](#your-skills)).

## Running a search from the dashboard (HTTP API)

`api.py` is a small FastAPI app that lets the [dashboard](../frontend/README.md)'s
**Run search** button start a search, and lets anything else (scripts,
another app) list, filter, and update the tracked jobs
([Jobs endpoints](#jobs-endpoints)). It calls the same `job_search.main()`
the command line does, so a run started there searches, saves, and emails
exactly like the scheduled one. **The cron job doesn't use the API.** It keeps
running `python job_search.py`, so scheduled runs don't depend on a web server
being up.

```bash
cd backend
pipenv run uvicorn api:app --reload     # http://127.0.0.1:8000 (interactive docs at /docs)
```

Leave it running next to `npm run dev` in `../frontend`. The dashboard finds
it at `http://127.0.0.1:8000` unless you set `IG_API_URL`.

| Endpoint | What it does |
| --- | --- |
| `GET /health` | Liveness check. Never needs the token. |
| `POST /runs` | Starts a search in the background and returns `202 {"run": ...}` at once. The optional body `{"sites": ["accenture"], "include_unmarked": true}` works like `--site` / `--include-unmarked`. Returns `409` (with the current run) if a search is already going. |
| `GET /runs/{id}` | One run: `status` (`running`, `succeeded`, `failed`), `summary` (matches, new, emailed), `error`, and everything the run printed so far (`output`). Poll it until `status` isn't `running`. |
| `GET /runs/latest` | The newest run, or `{"run": null}`. |
| `GET /runs` | Recent runs, newest first, without their output. |

### Jobs endpoints

The API also reads and updates the tracked jobs, in the same database the
search writes to (see [Job state](#job-state-local-file-or-firebase-firestore)).
Jobs come back in the same shape the dashboard uses: every field present,
timestamps as ISO strings.

| Endpoint | What it does |
| --- | --- |
| `GET /jobs` | Jobs matching the filters below, sorted, paged: `{"jobs": [...], "total", "limit", "offset"}`. `sort`: `last_seen` (default), `posted`, `salary` (highest first), `salary_lowest`, `score`, `fit`, `title`, `status`, the same orders as the dashboard's Sort menu (salaries compared per year, "Not listed" last). Give several, comma-separated or repeated, and each orders the ties of the ones before it, like the dashboard's **Then by**: `sort=score,salary` is most skill matches first, then the highest salary among jobs with the same number. Jobs that tie on every key stay newest first. `limit` 1-500 (default 100), `offset`. |
| `GET /jobs/stats` | Counts by status (every status, zeros included), company, track, and remote status, plus `total` and `applied`. Takes the same filters. |
| `POST /jobs/reassess` | Re-scores every saved job against your current skills (see [Reassessing saved jobs](#reassessing-saved-jobs)) and returns a summary: `total_jobs`, `reassessed`, `changed`, `no_longer_match`, `fetched` (descriptions loaded from the sites), `unavailable`, `skills_source`. `?fetch=false` skips loading missing descriptions. `409` while a search runs (a search can't start during one either). The dashboard's **Refresh** calls it. |
| `GET /jobs/{job_id}` | One job: `{"job": ...}`, or `404`. |
| `PATCH /jobs/{job_id}` | `{"status": "applied", "notes": "..."}` (either or both). Writes exactly what the dashboard and `jobs_cli.py` write: `status_updated_at`, and `applied_at` for `applied`. `""` or `null` notes clear them. Returns the updated job. |

Filters (all optional; they combine with AND, and a filter given several
values matches any of them):

| Parameter | Matches |
| --- | --- |
| `q` | Text anywhere in the title, company, skills, city/state, job type, notes, track, or ID (any case). |
| `status` | Workflow status. Repeat it or comma-separate: `status=emailed,unemailed`. |
| `company` | Company name, any case. Repeat for several. |
| `track` | Track name or its start: `core`, `java`, `ios`, `.net`. |
| `remote` | `remote`, `unmarked` (the site didn't say), `not_remote`. |
| `skill` | Matched skill. Repeat for several; the job needs **all** of them. |
| `min_salary` | Highest listed amount, per year, at least this (`$50/hr` counts as 104,000); excludes "Not listed". |
| `salary_listed` | `true`: only jobs with a salary listed; `false`: only "Not listed" ones. |
| `posted_since`, `seen_since` | `YYYY-MM-DD`: posted, or last seen by the search, on or after. |
| `applied` | `true`: jobs you've applied to (status `applied`, or `applied_at` set). `false`: the rest. |

```bash
curl 'http://127.0.0.1:8000/jobs?status=emailed&company=Accenture&sort=salary'
curl 'http://127.0.0.1:8000/jobs?skill=React&skill=TypeScript&remote=remote&limit=10'
curl 'http://127.0.0.1:8000/jobs/stats?seen_since=2026-11-01'
curl -X PATCH http://127.0.0.1:8000/jobs/accenture-R00212345 \
     -H 'Content-Type: application/json' -d '{"status": "applied", "notes": "Applied via site"}'
# With IG_API_TOKEN set, add: -H "Authorization: Bearer $IG_API_TOKEN"
```

### Resume endpoints

The dashboard's **Resume** page uploads and reads your resume through these
(see [Your resume](#your-resume)). Resumes come back with timestamps as ISO
strings.

| Endpoint | What it does |
| --- | --- |
| `GET /resume` | `{"resume": ... or null, "ai": {"configured", "provider", "model", "problem"}}` (never the key). |
| `POST /resume` | `{"filename": "cv.pdf", "content_base64": "..."}` or `{"text": "..."}`: saves it (replacing the last one and its readings), parses it, and returns `{"resume": ...}`. `422` when it can't be read (not PDF/.docx/text, no text, over 5 MB). |
| `POST /resume/analyze` | `{"method": "ai"}` (or `"parse"`, say after changing your skills): reads the saved resume again and keeps that reading next to the other. `404` without a resume, `503` for AI with no API key, `502` when the AI fails (its message is passed on), `504` when it's too slow, `409` if a new resume was uploaded meanwhile. |
| `DELETE /resume` | Forgets it: `{"resume": null}`. |

The full list, with every parameter, is at `/docs` while the API runs. The
dashboard uses only `POST /jobs/reassess` (its **Refresh** button). It still
reads and updates jobs through its own `/api/jobs` routes, so both keep
working side by side.

Things to know:

- **One search at a time, one worker.** A second `POST /runs` while one is
  running gets a `409`. Run history lives in memory (the last 20 runs), so a
  restart forgets it. Run uvicorn with the default single worker. The jobs
  and the `runs` log in the database are unaffected either way.
- **The API and the cron job don't coordinate.** If you click **Run search**
  while the scheduled run is going, both run. Firestore merges the writes
  safely, but the same new jobs may go out in two digests. With
  `local_firestore.json`, the two could overwrite each other's saves. Avoid
  clicking it around `13:00 UTC`.
- **Token.** Set `IG_API_TOKEN` and every endpoint except `/health` requires
  `Authorization: Bearer <token>`. The dashboard reads the same variable
  (from `backend/.env` too) and sends it for you. Without a token, anyone who
  can reach the port can start searches and send digests, read your jobs
  and notes, and change their statuses. `sites` can also make the server
  fetch any URL. So set a token before the API listens
  anywhere but `127.0.0.1`.
- **Gmail's first sign-in is interactive.** If `credentials.json` exists but
  `token.json` doesn't, the first run opens a consent page in a browser *on
  the machine running the API*, and waits there. Do that first sign-in with
  `pipenv run python job_search.py` instead.

## Gmail API setup

The bot uses the Gmail API's narrow `gmail.send` OAuth scope instead of an app
password or SMTP.

1. Enable the Gmail API in a Google Cloud project.
2. Configure the OAuth consent screen as **External / Testing** and add your
   Gmail address as a test user.
3. Create a **Desktop app** OAuth client and download it as `credentials.json`.
4. Run the bot locally once. A browser opens for consent and writes
   `token.json`, which contains the reusable refresh token.

Override the paths when needed:

```bash
export GMAIL_CREDENTIALS_PATH=/path/to/credentials.json
export GMAIL_TOKEN_PATH=/path/to/token.json
export IG_EMAIL_TO=you@example.com
```

Copy `.env.example` to `.env` and replace the example recipient if you prefer
file-based configuration; the script loads `.env` automatically — from this
directory or, failing that, the nearest parent such as the repository root —
and the dashboard in `../frontend` reads the Firebase variables from the same
file.
Never commit `credentials.json`, `token.json`, or `.env` — they're
git-ignored, and `../archive.py` leaves them out of shared archives.

**Email is optional.** Until Gmail is set up (no `credentials.json`, or no
`IG_EMAIL_TO`), the script still searches and saves every match, then prints
`Email is not set up, so no email was sent: ...` and exits normally. The jobs
stay `unemailed` and go out in the first email after Gmail is set up. The
`runs` log records the skipped email. A Gmail that *is* set up but fails (an
expired token, an API error) still stops the run with an error. Set
`IG_REQUIRE_EMAIL=true` to make missing setup an error too; Render does.

## Job state: local file or Firebase Firestore

All job-tracking logic lives in `job_store.py` (`FirestoreJobStore`) and talks
to a Firestore client. Which client is chosen by `IG_STATE_BACKEND`:

`job_search.py --local` and `jobs_cli.py --local` force the local stand-in for
one run, whatever `IG_STATE_BACKEND` says.

| `IG_STATE_BACKEND` | Behavior |
| --- | --- |
| `auto` (default) | Real Firestore if `GOOGLE_APPLICATION_CREDENTIALS` (or another Firebase variable) is set, otherwise the local stand-in. |
| `local` | Always `local_firestore.json`. |
| `firestore` | Always real Firestore; fails loudly if credentials are missing (used on Render). |

### The local stand-in

`local_firestore.json` mirrors Firestore's layout — top-level keys are
collections, each mapping document IDs to documents — and `LocalFirestoreClient`
implements the slice of the `google.cloud.firestore` client API the store uses,
logging each call. The test suite runs the store against it, so what's tested
locally is what runs against the real database. Timestamps are stored as ISO
strings and read back as `datetime`s, like Firestore's Timestamp fields.

The file lives next to `job_store.py` by default; set `IG_LOCAL_DB_PATH` to
move it. The dashboard reads and edits the same file (it honours the same
variable), so status changes made in the browser show up in `jobs_cli.py list`
and vice versa. The file is git-ignored — it's your personal tracking data.

```json
{
  "jobs": {
    "insight-global-6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba": { "job_id": "insight-global-6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba", "title": "...", "status": "emailed", "first_seen_at": "...", ... }
  },
  "runs": {
    "4yDsBPXRANBbEYCFdI1R": { "ran_at": "...", "total_matches": 12, "new_matches": 3, "email_sent": true, ... }
  },
  "settings": {
    "search_skills": { "skills": ["Python", "Go", ...], "core_skills": ["Python"], "updated_at": "..." }
  },
  "job_descriptions": {
    "insight-global-6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba": { "text": "...", "saved_at": "..." }
  }
}
```

### Switching to Firebase

1. Create a Firebase project at <https://console.firebase.google.com>, open
   **Build > Firestore Database**, and click **Create database** (Native mode;
   production rules are fine — a service account bypasses security rules).
2. **Project settings > Service accounts > Generate new private key**; save the
   JSON outside the repo (or as `firebase-service-account.json`, which is
   git-ignored).
3. `export GOOGLE_APPLICATION_CREDENTIALS=/path/to/firebase-service-account.json`
   (or paste the file's contents into `FIREBASE_SERVICE_ACCOUNT_JSON`).
4. Copy what you've tracked locally, statuses (and your skill list) included:

   ```bash
   pipenv run python jobs_cli.py migrate local_firestore.json
   ```

The free Spark plan allows 20k writes and 50k reads per day; a daily run uses
a few hundred at most. For the Firebase emulator, set
`FIRESTORE_EMULATOR_HOST=127.0.0.1:8080` and no credentials are needed.

## Job tracking

Each job is a document in the `jobs` collection, keyed by its job ID (see
[Job sites](#job-sites)), with the details shown in the email (company, title,
URL, track, matched skills, salary, posted date, ...) and these workflow
fields:

| Field | Meaning |
| --- | --- |
| `status` | `unemailed` → `emailed` → `applied`, `skipped`, `interviewing`, `rejected`, `offer`. |
| `first_seen_at` | When the job was first matched. |
| `emailed_at`, `gmail_message_id` | Set once Gmail accepts the digest. |
| `last_seen_at` | Refreshed every run the job still matches, so you can tell when a posting disappears. |
| `applied_at`, `status_updated_at`, `notes` | Set when you change the status. |
| `work_arrangement`, `work_arrangement_set_at` | How you say the job is worked (`remote`, `hybrid`, `on_site`), overriding the site's `is_remote`; searches never change it. |
| `not_remote_reason` | Why the search marked a job the site called remote as not remote. |
| `matches_skills`, `skills_mismatch_reason` | Whether the job still matches your skills, and why not (see [Reassessing saved jobs](#reassessing-saved-jobs)). |
| `salary_period`, `salary_period_estimated` | What `salary_low`/`salary_high` are per (`hour`, `day`, `week`, `month`, `year`; empty when there's no salary), and whether it's assumed because neither the site nor the posting says (see [Salaries](#salaries)). |

### Salaries

A salary reads with what it's per, in the email and the dashboard:
`$60 - $65/hr`, `$1,200 - $3,000/mo`, `From $140,000/yr`. Sites only give two
numbers, so `salary.py` works out the period in this order:

1. **The site's own field**, when it has one: Lever's `interval`, Ashby's
   `interval`, a unit on Insight Global's `payRate` (`type`, `rateType`,
   `period`, ...), Jobicy's or Himalayas' `salaryPeriod`. Remote OK's salaries
   are yearly (it asks posters for an annual range).
2. **The posting's text**, when it gives a period next to the same amount:
   "Pay rate range: $60-64/hour", "$120k - $150k per year", "Monthly salary:
   $2,500". A different amount ("$75-85/hr" when the site says $86) doesn't
   count.
3. **Otherwise it's assumed**: an amount under $300 is an hourly rate
   (Insight Global's unlabelled contract rates), and anything else is a
   yearly salary, so `$1,200 - $3,000/yr (est.)`. Assumed periods are marked
   `(est.)`; the dashboard's tooltip and details say why.

Ashby boards can publish pay per hour, month, or year; a yearly range wins
when there are several. Jobs saved before periods were kept read with the
assumed period right away, and get their period from their description the
next time saved jobs are reassessed (after every search, or the dashboard's
**Refresh**).

Sorting and filtering compare pay **per year** (`salary.PER_YEAR`: hourly ×
2,080, daily × 260, weekly × 52, monthly × 12), using the same period the
salary shows, so `$91/hr` ($189,280) ranks above `$80,000 - $90,000/yr`, and
`$1,200 - $3,000/mo` below both. "Salary (highest)" goes by the top of each
range, "Salary (lowest)" by the bottom, and "Not listed" is last in both. The
dashboard's **Salary** filter (`salary_listed` in `GET /jobs`) shows only jobs
with a salary listed, or only the "Not listed" ones.

Matches are saved **before** the email goes out, as `unemailed`, then flipped
to `emailed` once Gmail accepts the digest. If the send fails, nothing is lost:
the jobs stay `unemailed`, the failure is logged in the `runs` collection, and
they're included in the next run's email. Re-running the search never
overwrites a status you've set by hand.

Update statuses in the [dashboard](../frontend/README.md), with the CLI, or by
editing documents in the Firebase console. The CLI uses the same backend
selection as the script:

```bash
pipenv run python jobs_cli.py help                    # every command and its usage
pipenv run python jobs_cli.py list                    # newest first
pipenv run python jobs_cli.py list --local            # read local_firestore.json even if Firebase is configured
pipenv run python jobs_cli.py list --status emailed   # not acted on yet
pipenv run python jobs_cli.py show insight-global-6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba
pipenv run python jobs_cli.py applied insight-global-6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba --note "Applied via IG site"
pipenv run python jobs_cli.py skip insight-global-6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba
pipenv run python jobs_cli.py status insight-global-6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba interviewing
pipenv run python jobs_cli.py onsite insight-global-98f09cc8-df65-482e-9fff-701b877de516   # not actually remote
pipenv run python jobs_cli.py hybrid accenture-R00212345
pipenv run python jobs_cli.py arrangement accenture-R00212345 site   # back to what the site says
```

## Render deployment

`../render.yaml` defines a daily cron job at `13:00 UTC` with `rootDir:
backend`, so only this directory is built. The cron job runs
`python -u job_search.py` and doesn't need the HTTP API. The Blueprint doesn't
deploy `api.py` (or the dashboard). Create a Render Blueprint, then:

1. Add secret file `credentials.json` with the OAuth client JSON.
2. Add secret file `token.json` with the token generated by the local run.
3. Add secret file `firebase-service-account.json` with the Firebase
   service-account key.
4. Set `IG_EMAIL_TO`.

The Blueprint mounts the secret files at `/etc/secrets`, pins Python 3.11.9 via
`PYTHON_VERSION`, and sets `IG_STATE_BACKEND=firestore` so a missing key fails
the run instead of silently writing to a local file. It also sets
`IG_REQUIRE_EMAIL=true`, so a missing Gmail secret or `IG_EMAIL_TO` fails the
run instead of just printing that email isn't set up. Render secret files are
read-only; refreshed Gmail credentials are used in memory without attempting to
modify the mounted token.

## Tests

```bash
pipenv run pytest          # from backend/
```

or `pytest` from the repository root to also run the archive-script tests.
`tests/test_api.py` covers the HTTP API with FastAPI's test client, a fake
search, and a temporary local store, so it needs neither network access nor a
running server. The resume tests (`tests/test_resume*.py`) build their PDF and
Word files by hand (`tests/resume_files.py`) and answer for the AI providers
with a fake session, so they don't call any AI either.
`tests/test_resume.py` also checks that `../frontend/src/test/fixtures/resume.json`
(what the dashboard's tests read) is what this side writes; after changing the
resume document, regenerate it with `UPDATE_RESUME_FIXTURE=1 pipenv run pytest tests/test_resume.py`. `tests/test_job_queries.py` covers the filtering and sorting
behind `GET /jobs`. `tests/test_salary.py` and the dashboard's tests both check
every case in `../frontend/src/test/fixtures/salary_formats.json`, so the email
and the dashboard word salaries the same way.
The suite includes a round-trip check that documents written by the dashboard
(`../frontend`) read back correctly here.
