# Insight Global Job Finder

Searches Insight Global for remote jobs matching configurable tracks:

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

Jobs come from the JSON API behind
<https://insightglobal.com/jobs/search/all/all> (an Angular app with no job data in
its HTML): `/all/jobs` for search results and `/all/jobs/<id>/details` for the
description, which is what skills and years of experience are matched against.
Job IDs are the API's UUIDs, and each job links to
`https://insightglobal.com/jobs/<id>`.

Only new matches are emailed. Every match is recorded in **Firebase
Firestore** along with its details and an application status, so you can track
which jobs you've applied to (see [Job tracking](#job-tracking)). Without
Firebase credentials the script transparently uses `local_firestore.json`, a
local stand-in with the same layout, so nothing needs to be set up to run or
test it on your machine.

## Install and run

```bash
pipenv install --dev
pipenv run python job_search.py
```

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
[local firestore]   set jobs/6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba (merge): status='unemailed', title='React Developer'
Saved 3 match(es).
[local firestore] batch commit (1 writes)
[local firestore]   set jobs/6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba (merge): status='emailed'
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
file-based configuration; the script loads `.env` automatically. Never commit
`credentials.json`, `token.json`, or `.env`.

## Job state: local file or Firebase Firestore

All job-tracking logic lives in `job_store.py` (`FirestoreJobStore`) and talks
to a Firestore client. Which client is chosen by `IG_STATE_BACKEND`:

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

```json
{
  "jobs": {
    "6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba": { "job_id": "6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba", "title": "...", "status": "emailed", "first_seen_at": "...", ... }
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

   (`migrate` also accepts the old `seen_jobs.json` list of IDs.)

The free Spark plan allows 20k writes and 50k reads per day; a daily run uses
a few hundred at most. For the Firebase emulator, set
`FIRESTORE_EMULATOR_HOST=127.0.0.1:8080` and no credentials are needed.

## Job tracking

Each job is a document in the `jobs` collection, keyed by its Insight Global
Job ID, with the details shown in the email (title, URL, track, matched skills,
salary, posted date, req number, ...) and these workflow fields:

| Field | Meaning |
| --- | --- |
| `status` | `unemailed` → `emailed` → `applied`, `skipped`, `interviewing`, `rejected`, `offer`. IDs imported from `seen_jobs.json` are `seen`. |
| `first_seen_at` | When the job was first matched. |
| `emailed_at`, `gmail_message_id` | Set once Gmail accepts the digest. |
| `last_seen_at` | Refreshed every run the job still matches, so you can tell when a posting disappears. |
| `applied_at`, `status_updated_at`, `notes` | Set when you change the status. |

Matches are saved **before** the email goes out, as `unemailed`, then flipped
to `emailed` once Gmail accepts the digest. If the send fails, nothing is lost:
the jobs stay `unemailed`, the failure is logged in the `runs` collection, and
they're included in the next run's email. Re-running the search never
overwrites a status you've set by hand.

Update statuses with the CLI (or edit documents in the Firebase console). It
uses the same backend selection as the script:

```bash
pipenv run python jobs_cli.py help                    # every command and its usage
pipenv run python jobs_cli.py list                    # newest first
pipenv run python jobs_cli.py list --status emailed   # not acted on yet
pipenv run python jobs_cli.py show 6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba
pipenv run python jobs_cli.py applied 6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba --note "Applied via IG site"
pipenv run python jobs_cli.py skip 6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba
pipenv run python jobs_cli.py status 6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba interviewing
```

## Render deployment

`render.yaml` defines a daily cron job at `13:00 UTC`. Create a Render
Blueprint, then:

1. Add secret file `credentials.json` with the OAuth client JSON.
2. Add secret file `token.json` with the token generated by the local run.
3. Add secret file `firebase-service-account.json` with the Firebase
   service-account key.
4. Set `IG_EMAIL_TO`.

The Blueprint mounts the secret files at `/etc/secrets`, pins Python 3.11.9 via
`PYTHON_VERSION`, and sets `IG_STATE_BACKEND=firestore` so a missing key fails
the run instead of silently writing to a local file. Render secret files are
read-only; refreshed Gmail credentials are used in memory without attempting to
modify the mounted token.

## Tests

```bash
pipenv run pytest
```
