# Job Finder

A personal job-hunting pipeline in two parts:

| Directory | What it is | Docs |
| --- | --- | --- |
| [`backend/`](backend/) | Python script that searches the careers pages in `JOB_SEARCH_URLS` (`backend/job_boards.py`: Insight Global contract roles, Accenture, 33 company Workday/Greenhouse/Ashby boards, and the remote job boards Himalayas, Remote OK, Jobicy, and We Work Remotely; more Workday, Greenhouse, Lever, and Ashby boards can be added by URL) for matching remote roles, ranks each by a 0-100 fit score, emails you a digest through the Gmail API, and records every match in Firebase Firestore (or a local JSON stand-in). Includes a CLI for updating statuses and a FastAPI app (`api.py`) so the dashboard can start a search. Runs daily on Render as a cron job. | [backend/README.md](backend/README.md) |
| [`frontend/`](frontend/) | Next.js + shadcn/ui dashboard over the same database: a home screen with where your search stands (totals, newest matches, recent activity) and a button to run a search on demand, a Skills page to edit the skills the search looks for, a Resume page that works out your skills and years of experience from your resume (by parsing it, or with AI) and adds them to that list, plus a tracker to browse every job, search/filter/sort, change statuses, mark jobs applied, keep notes, and jump to the posting, the digest email, or an Insight Global search in a new tab. | [frontend/README.md](frontend/README.md) |

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
virtualenvs, caches, earlier archives, and your own `alignerr.txt` in the
project root (`PERSONAL_FILES` in `archive.py`):

```bash
python3 archive.py            # writes job-finder-<timestamp>.zip in this directory
python3 archive.py --list     # preview the file list
python3 archive.py --exclude local_firestore.json -o ~/Desktop/job-finder.zip
```

`local_firestore.json` (your tracking data) is included by default since it
contains no secrets; use `--exclude` as above to leave it out. If you've
uploaded your resume on the dashboard while using the local file, its text
(with your contact details) is in there too.

### Applying an updated zip

When you get an updated zip back, `apply_update.py` finds it in your Downloads
folder and applies it:

```bash
python3 apply_update.py --dry-run     # which zip it picked and what would change
python3 apply_update.py               # apply only what the zip changed (asks first)
python3 apply_update.py --all         # take every file from the zip, your edits included
python3 apply_update.py --zip PATH    # use a specific zip (or unzipped folder)
python3 apply_update.py --candidates  # every project zip found, newest first
python3 apply_update.py --undo        # put back what the last update changed
```

It picks the most recently downloaded bundle (a zip, or a folder if your
browser unzipped it) that holds this project's files, whatever it's called,
and works out what kind it is:

| In the download | What it does |
| --- | --- |
| `changes.diff` at the root (the chat's "changed files") | Applies just the diff: the files it adds, changes, renames, and deletes. Everything else stays as it is. If you've edited a file, the diff is applied to your version, so your edits are kept when they don't overlap the changes. |
| The whole project, no diff (the chat's "all code", or an `archive.py` zip) | Replaces the entire project: every file is updated, and files it doesn't have are deleted, except ones you created and ones git ignores. |
| Some files, no diff | Adds and updates those files; nothing is deleted. |

To keep edits you made yourself, it compares each file with earlier copies of
the project: archives in the project root, updates it applied before, and
older bundles in Downloads. A file matching one of those copies hasn't been
edited by you, so it's brought up to date. A file that has had the same
version in every copy (like a notes file only you change) is certainly yours
and is kept. Any other difference is *possibly* yours, or from an update
that's no longer in Downloads, so it asks whether to take the zip's versions
(`--force`: yes, `--keep-mine`: no; `--yes` alone keeps yours). `--all` takes
the zip's version of everything in it.

Secrets, `node_modules`, `backend/local_firestore.json`, and `alignerr.txt`
are never touched (archives leave `alignerr.txt` out, so an update that has
one isn't yours and mustn't replace it). A bundle of all the code deletes only files it removed, never files
you created, and an update that would delete more than 5 files stops unless
you add `--allow-deletes`. Folders in Downloads that someone has worked in
(with `.git`, `node_modules`, `__pycache__`, ...) are never taken for a
download. Everything it overwrites or deletes is backed up to
`.update-backups/` first, and every changed file is checked against the zip
afterwards. It also removes files an older version of it put in the wrong
place (a bundle's `files/` folder copied in as-is): it knows them from that
update's own record, and leaves any you've edited since. If `package.json` or the `Pipfile` changed, it tells you to
reinstall dependencies.

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
