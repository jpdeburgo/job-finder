# Job Finder

A personal job-hunting pipeline in two parts:

| Directory | What it is | Docs |
| --- | --- | --- |
| [`backend/`](backend/) | Python script that searches the careers pages in `JOB_SEARCH_URLS` (Insight Global contract roles and Accenture out of the box; Workday, Greenhouse, and Lever boards can be added by URL) for matching remote roles, emails you a digest through the Gmail API, and records every match in Firebase Firestore (or a local JSON stand-in). Includes a CLI for updating statuses. Runs daily on Render. | [backend/README.md](backend/README.md) |
| [`frontend/`](frontend/) | Next.js + shadcn/ui dashboard over the same database: browse every job, search/filter/sort, change statuses, mark jobs applied, keep notes, and jump to the posting, the digest email, or an Insight Global search in a new tab. | [frontend/README.md](frontend/README.md) |

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

# Frontend: dashboard on http://localhost:3000
cd ../frontend
npm install
npm run dev
```

## Tests

```bash
pytest                       # repo root: archive.py tests + backend suite (needs backend deps)
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

## Repository layout

```
.
├── archive.py            share-safe zip of the project
├── pytest.ini            runs tests/ and backend/tests together
├── render.yaml           Render cron Blueprint (rootDir: backend)
├── tests/                tests for archive.py only
├── backend/              search script, job store, CLI, and their tests (backend/tests)
└── frontend/             Next.js dashboard and its tests
```

Secrets (`credentials.json`, `token.json`, `.env`, service-account keys) and
`local_firestore.json` are git-ignored at the root.
