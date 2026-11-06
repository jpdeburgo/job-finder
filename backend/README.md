# Job Finder (backend)

The search script, job store, and CLI. The Next.js dashboard that reads the
same data lives in [`../frontend`](../frontend/README.md); the repository
overview is in the [root README](../README.md). Run every command below from
this `backend/` directory.

Searches every careers page in `JOB_SEARCH_URLS` (Insight Global and Accenture
out of the box; see [Job sites](#job-sites)) for remote jobs matching
configurable tracks:

- **Core stack:** software engineering roles scored against the skills in
  `RESUME_SKILLS`. A job needs at least two matches, one of them a core
  language (`CORE_LANGUAGE_SKILLS`: Python, JavaScript, TypeScript, Java,
  React, Node.js), so postings that only mention cloud tooling or SQL
  don't qualify.
- **Growth tracks (Java, iOS, .NET):** junior and entry-level roles in a
  single skill that do not explicitly require more than three years of
  experience.

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
its Job ID alongside the usual details.

Only new matches are emailed. Every match is recorded in **Firebase
Firestore** along with its details and an application status, so you can track
which jobs you've applied to (see [Job tracking](#job-tracking)). Without
Firebase credentials the script transparently uses `local_firestore.json`, a
local stand-in with the same layout, so nothing needs to be set up to run or
test it on your machine.

## Job sites

`JOB_SEARCH_URLS` in `job_search.py` lists the pages to scan:

```python
INSIGHT_GLOBAL_URL = "https://insightglobal.com/jobs/search/all/all"
ACCENTURE_SEARCH_URL = "https://www.accenture.com/us-en/careers/jobsearch"
JOB_SEARCH_URLS = [INSIGHT_GLOBAL_URL, ACCENTURE_SEARCH_URL]
```

Careers pages like these render their results in the browser, so their HTML
has no jobs in it. `job_sites.resolve_job_site` maps each URL to the JSON API
the page itself calls. Every site returns the same `Posting` fields, and the
filters, tracks, and skill scoring above treat every site the same way.

| URL | Read through | Job IDs | Notes |
| --- | --- | --- | --- |
| Insight Global | `/all/jobs` search and `/all/jobs/<id>/details` on insightglobal.com | `insight-global-<uuid>` | Contract / contract-to-perm only. Links to `https://insightglobal.com/jobs/<id>`. |
| Accenture | its Workday board, `accenture.wd103.myworkdayjobs.com/AccentureCareers` (via `KNOWN_CAREER_SITES`) | `accenture-<requisition>` | Any job type (Accenture hires directly). Narrowed to `JOB_COUNTRY` (United States). Links to the Workday posting. |
| Any Workday board: `https://<company>.wdN.myworkdayjobs.com/<site>` | Workday's `/wday/cxs/...` search API | `<company>-<requisition>` | Narrowed to `JOB_COUNTRY` when the board has a country filter. |
| Any Greenhouse board: `https://boards.greenhouse.io/<company>` | Greenhouse Job Board API | `<company>-<id>` | The whole board is downloaded once per run; search terms are matched against titles and descriptions locally. |
| Any Lever board: `https://jobs.lever.co/<company>` | Lever Postings API | `<company>-<id>` | Same as Greenhouse. |
| Any other careers page | the page's HTML is checked for a Workday/Greenhouse/Lever board link | as above | If no link is found, the site is skipped with a warning. Add its board to `KNOWN_CAREER_SITES` in `job_sites.py`. |

To add a company, append its careers page or ATS board URL to
`JOB_SEARCH_URLS`. Each run prints how many matches every site produced. A
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
details request) or a location saying "Remote"; Lever's `workplaceType`, with
the location as a fallback; and Greenhouse's location text, since Greenhouse
has no remote field. About half of Accenture's US postings are unmarked, and
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
```

`--site` takes a site name (`accenture`, `"insight global"`), a board kind
(`insight-global`, `workday`, `greenhouse`, `lever`), or any careers page or
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
| `MAX_PAGES_PER_SEARCH` | 10 | result pages per term (Workday pages hold 20 results, Insight Global's 50) |

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

Tune search terms, skills, remote-only behavior, page depth, and matching
thresholds at the top of `job_search.py`.

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
4. Copy what you've tracked locally, statuses included:

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
```

## Render deployment

`../render.yaml` defines a daily cron job at `13:00 UTC` with `rootDir:
backend`, so only this directory is built. Create a Render Blueprint, then:

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
The suite includes a round-trip check that documents written by the dashboard
(`../frontend`) read back correctly here.
