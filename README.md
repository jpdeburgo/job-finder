# Job Finder

A personal job-hunting pipeline in two parts:

| Directory | What it is | Docs |
| --- | --- | --- |
| [`backend/`](backend/) | Python script that searches the careers pages in `JOB_SEARCH_URLS` (`backend/job_boards.py`: Insight Global contract roles, Accenture, and 18 company Workday/Greenhouse boards; more Workday, Greenhouse, and Lever boards can be added by URL) for matching remote roles, ranks each by a 0-100 fit score, emails you a digest through the Gmail API, and records every match in Firebase Firestore (or a local JSON stand-in). Includes a CLI for updating statuses and a FastAPI app (`api.py`) so the dashboard can start a search. Runs daily on Render as a cron job. | [backend/README.md](backend/README.md) |
| [`frontend/`](frontend/) | Next.js + shadcn/ui dashboard over the same database: a home screen with where your search stands (totals, newest matches, recent activity) and a button to run a search on demand, plus a tracker to browse every job, search/filter/sort, change statuses, mark jobs applied, keep notes, and jump to the posting, the digest email, or an Insight Global search in a new tab. | [frontend/README.md](frontend/README.md) |

Both halves choose the database the same way, from the same environment
variables (`IG_STATE_BACKEND`, `GOOGLE_APPLICATION_CREDENTIALS`, ...). With
nothing configured they share `backend/local_firestore.json`; point the script
at Firebase and the dashboard follows (it reads `backend/.env`).

## Quick start

```bash
# Backend: search once (uses backend/local_firestore.json until Firebase is configured)
cd backend
pipenv install --dev
pipenv run python job_search.py          # needs Gmail credentials; see backend/README.md
pipenv run python job_search.py --local --site accenture   # local file, one site
pipenv run python jobs_cli.py list
pipenv run uvicorn api:app --reload      # optional, in its own terminal: the dashboard's "Run search" button

# Frontend: dashboard on http://localhost:3000
cd ../frontend
npm install
npm run dev
```

The search runs two ways, both through the same `job_search.main()`:

- **On a schedule:** the cron job (`render.yaml`, or your own crontab) runs
  `python job_search.py`. It doesn't need the API or the dashboard.
- **On demand:** the dashboard's **Run search** button calls the FastAPI app
  in `backend/api.py`, which starts the same search in the background and
  reports its progress.

For a local crontab, call the script directly. Cron runs with a minimal
`PATH`, so give the full path to `pipenv` (`which pipenv`):

```cron
0 13 * * * cd /path/to/job-finder/backend && /path/to/pipenv run python job_search.py >> search.log 2>&1
```

## Tests

```bash
pytest                       # repo root: archive.py/apply_update.py tests + backend suite (needs backend deps)
cd backend && pipenv run pytest
cd frontend && npm test      # vitest; add --coverage for a report
```

## Sharing the project

`archive.py` zips the repository for sharing or backup, leaving out
`credentials.json`, `token.json`, `.git`, `.env` (and `.env.*` except
`.env.example`), Firebase service-account keys, `node_modules`, `.next`,
virtualenvs, caches, and earlier archives:

```bash
python3 archive.py            # writes job-finder-<timestamp>.zip in this directory
python3 archive.py --list     # preview the file list
python3 archive.py --exclude local_firestore.json -o ~/Desktop/job-finder.zip
```

`local_firestore.json` (your tracking data) is included by default since it
contains no secrets; use `--exclude` as above to leave it out.

### Applying an updated zip

When you get an updated zip back, `apply_update.py` finds it in your Downloads
folder and applies it:

```bash
python3 apply_update.py --dry-run     # which zip it picked and what would change
python3 apply_update.py               # apply only what the zip changed (asks first)
python3 apply_update.py --all         # make the project match the zip exactly
python3 apply_update.py --zip PATH    # use a specific zip (or unzipped folder)
python3 apply_update.py --candidates  # every project zip found, newest first
python3 apply_update.py --undo        # put back what the last update changed
```

It picks the most recently downloaded zip (or folder, if your browser unzipped
it) that contains this project, whatever it's called. To tell the update's
changes from edits you made after sharing, it compares against the archive
you shared, which `archive.py` left in the project root. Files only you
changed are kept. Files you both changed are conflicts: yours are kept unless
you pass `--force`. Secrets, `node_modules`, and `backend/local_firestore.json`
are never touched. Everything it overwrites or deletes is backed up to
`.update-backups/` first. If `package.json` or the `Pipfile` changed, it tells
you to reinstall dependencies.

## Repository layout

```
.
├── archive.py            share-safe zip of the project
├── apply_update.py       apply an updated zip of the project (finds it in Downloads)
├── pytest.ini            runs tests/ and backend/tests together
├── render.yaml           Render cron Blueprint (rootDir: backend)
├── tests/                tests for archive.py and apply_update.py
├── backend/              search script, job store, CLI, HTTP API (api.py), and their tests (backend/tests)
└── frontend/             Next.js dashboard and its tests
```

Secrets (`credentials.json`, `token.json`, `.env`, service-account keys) and
`local_firestore.json` are git-ignored at the root.
