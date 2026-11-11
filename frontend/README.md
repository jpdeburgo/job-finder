# Job Finder dashboard (frontend)

A Next.js dashboard for the jobs that [`../backend`](../backend/README.md)
finds and records. It reads the same Firestore database (or the same
`local_firestore.json` stand-in) the script writes, so there is nothing to
sync: run the script, refresh the page.

It has three pages, linked from the header:

- **Home (`/`)** shows where your search stands. At the top are the **Run
  search** button and the result of the last run. Below that are totals for
  jobs to review, applied, interviewing, and offers. Each total opens the
  tracker filtered to that status. Last come the newest matches and your
  latest status changes. If some matches were saved but never emailed (Gmail
  isn't set up yet), a notice links to them. With nothing tracked yet, the
  page explains how it works instead.
- **Jobs (`/jobs`)** is the tracker. `/jobs?status=applied` opens it filtered
  to one status, and the address bar follows the status filter as you change
  it, so a reload or a bookmark keeps the view.
- **Skills (`/skills`)** is where you choose what the search looks for. Add
  skills (type one, or several separated by commas), move the ones that are
  your main stack up to **Core skills** (the arrow buttons), rate how well
  you know each one from 1 to 5 **stars** (click a star, or use the arrow
  keys), remove the rest, and **Save skills**. The next search, whether
  it's the daily run or **Run search**, uses your list. A Core-track job
  needs at least two of your skills, one of them core; core skills count
  twice as much toward the fit score, and stars scale that (3 stars, where
  new skills start, counts as is). Stars never change which jobs match.
  Saving also re-scores the jobs you've already saved, when the search API
  is running; otherwise click **Refresh** on the Jobs page later. Until you
  save, the page shows the defaults from `backend/job_search.py`, and
  **Reset to defaults** goes back to them. See
  [Your skills](../backend/README.md#your-skills) for what the list and the
  stars change.

In the tracker you can:

- See every tracked job with its company, fit score, track, matched skills,
  salary, posted date, and when the script last saw it. Search, filter by
  status/remote/track and by **company** and **skills**, and sort (**Best fit** puts the jobs that suit
  you best first; the details drawer explains each score, see
  [Fit score](../backend/README.md#fit-score)). Results come 25 to a page
  (or 50 or 100: **Rows per page** under the table). A new filter, sort, or
  page size starts again at page 1, and the page is kept in the address
  (`/jobs?page=2&per_page=50`), so a reload or a bookmark opens the same page. Like Company and Track, the Remote
  filter only offers what your jobs have: "Remote", plus "Remote not stated"
  for jobs saved by `job_search.py --include-unmarked`, plus "Not remote" only
  if remote-only was turned off for a site.
- The **Company** filter is a multi-select: tick any number of companies
  (each shows how many jobs it has) to see jobs from any of them; **Clear
  companies** shows them all again.
- The **Skills** filter is a multi-select too: tick any number of the skills
  your jobs matched (each shows how many jobs have it, most common first)
  and choose whether a job needs **any** of them or **all** of them. Case
  doesn't matter, and the menu stays open while you pick; **Clear skills**
  empties it.
- Mark a job **On-site**, **Hybrid**, or **Remote** when the site gets it
  wrong (the **Work arrangement** menu in the details drawer). Your choice
  overrides the site's everywhere, including the Remote filter, and searches
  never undo it; "As the site says" goes back.
- Change a job's **status** inline (`unemailed` → `emailed` → `applied`,
  `skipped`, `interviewing`, `rejected`, `offer`) or use the **Mark applied**
  button; applied jobs show the date you applied.
- Expand a row for every field, a **notes** editor, and all of the job's links:
  the Insight Global posting (to apply), the digest email it arrived in
  (Gmail), and a search for its title. Every link opens in a new tab.
- **Refresh** re-scores every saved job against your current skills (the
  Skills page), then reloads the list. Each job's matched skills and fit
  score are updated, and jobs that wouldn't match any more get a **No longer
  matches your skills** badge; the details drawer says why. Nothing is
  deleted, and statuses and notes are left alone. A notice says what
  changed. Re-scoring runs in the search API (`backend/api.py`), so it needs
  the API running (see [Running a search](#running-a-search)); without it,
  Refresh still reloads the list and the notice says how to start the API.
  The first time, each job's description is loaded from its site, which can
  take a minute; after that it's quick. Searches reassess saved jobs too.
- **Run search** starts the search script right away instead of waiting for
  the daily cron job. The panel shows the run's progress and output and, when
  it finishes, what it found and emailed. New matches appear in the table
  automatically. This needs the search API running (see
  [Running a search](#running-a-search)).
- The banner at the top says which database you're looking at (local file,
  Firestore, or the emulator). Light/dark/system theme toggle in the header.

Status changes write exactly the fields `backend/jobs_cli.py` would
(`status`, `status_updated_at`, and `applied_at` for "applied"), so the
script, the CLI, and the dashboard can be used interchangeably.

## Run it

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

With nothing configured the dashboard opens `../backend/local_firestore.json`
— the same file the script uses when Firebase isn't set up — and edits it in
place. Run `pipenv run python job_search.py` in `backend/` and refresh to see
new matches.

## Running a search

The **Run search** button talks to the search API in `backend/api.py`
(FastAPI), which runs the same code as `job_search.py`. Start it alongside the
dashboard:

```bash
cd backend
pipenv run uvicorn api:app --reload      # http://127.0.0.1:8000
```

The browser never calls the API directly. It calls this app's `/api/runs` and `/api/jobs/reassess`
routes, and the server forwards them. So there's no CORS to set up, and the
API token stays on the server. Two optional variables, read like the others
(from `frontend/.env.local`, else the script's `.env`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `IG_API_URL` | `http://127.0.0.1:8000` | Where the API listens. |
| `IG_API_TOKEN` | none | Sent as `Authorization: Bearer ...`. It must match the API's `IG_API_TOKEN`. Setting it once in `backend/.env` configures both. |

If the API isn't running, the panel says so and how to start it. Everything
else on the page still works. Only one search runs at a time. Clicking
**Run search** while one is going (say, from another tab) follows that run
instead of starting a second. The daily cron job doesn't go through the API,
so it runs whether or not the API is up.

## Choosing the database

The dashboard resolves its database exactly like the script
(`get_job_store()` in `backend/job_store.py`), from the same variables:

| `IG_STATE_BACKEND` | Behavior |
| --- | --- |
| `auto` (default) | Real Firestore if `GOOGLE_APPLICATION_CREDENTIALS`, `FIREBASE_SERVICE_ACCOUNT_JSON`, `FIRESTORE_EMULATOR_HOST`, or `FIREBASE_PROJECT_ID` is set; otherwise `local_firestore.json`. |
| `local` | Always the local JSON file. |
| `firestore` | Always real Firestore; fails with a clear message if credentials are missing. |

Variables are looked up in this order:

1. `frontend/.env.local` (or the shell environment) — see
   [`.env.example`](.env.example).
2. The script's `.env` — found exactly the way `python-dotenv` finds it for
   `job_search.py`: `backend/.env` if it exists, otherwise the nearest `.env`
   in a parent directory (typically the **repository root**). Anything not
   set in step 1 is read from there, so if the script already works against
   Firebase, the dashboard does too with **no extra configuration**. Relative
   paths (for example `GOOGLE_APPLICATION_CREDENTIALS=firebase-service-account.json`)
   are resolved against the `.env` file's directory, falling back to
   `backend/` if the file only exists there.

The banner at the top of the page says which `.env` was read, so if you end
up on the local file unexpectedly, that's the first thing to check.

Useful overrides:

- `IG_LOCAL_DB_PATH` — where the JSON stand-in lives (the script honours the
  same variable).
- `IG_BACKEND_DIR` — where the script lives, if you move it (default
  `../backend`).
- `FIRESTORE_DATABASE`, `FIRESTORE_JOBS_COLLECTION`,
  `FIRESTORE_RUNS_COLLECTION`, `FIRESTORE_SETTINGS_COLLECTION` — same
  meaning as in the script.

### Real Firestore

Follow "Switching to Firebase" in [`../backend/README.md`](../backend/README.md)
once; the dashboard picks the service account up from the same `.env` the
script uses. Or set it for the frontend only:

```bash
# frontend/.env.local
GOOGLE_APPLICATION_CREDENTIALS=../backend/firebase-service-account.json
```

### Firebase emulator

```bash
firebase emulators:start --only firestore     # in any directory with a firebase.json
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIREBASE_PROJECT_ID=demo-job-finder npm run dev
```

No credentials are needed. Set the same two variables when running the script
so both talk to the emulator. (`FIREBASE_PROJECT_ID` defaults to
`demo-job-finder` in the dashboard when only the emulator host is set.)

## How it's built

```
src/
├── app/
│   ├── page.tsx                 home screen (/): reads the store, renders HomeOverview
│   ├── jobs/page.tsx            the tracker (/jobs, ?status=...): reads the store, renders JobsDashboard
│   ├── api/jobs/route.ts        GET  /api/jobs          → { store, jobs }
│   ├── api/jobs/reassess/…      POST /api/jobs/reassess → forwarded to backend/api.py → summary
│   ├── api/jobs/[id]/route.ts   GET  /api/jobs/:id      → { job }
│   │                            PATCH /api/jobs/:id     { status?, notes? } → { job }
│   ├── skills/page.tsx          the Skills page (/skills): reads your skill list, renders SkillsEditor
│   ├── api/skills/route.ts      GET /api/skills, PUT { skills, core_skills }, DELETE (back to the defaults)
│   │                            → { skills, core_skills, source, updated_at, defaults }
│   └── api/runs/…               POST /api/runs, GET /api/runs/latest, GET /api/runs/:id
│                                → forwarded to backend/api.py (FastAPI) → { run }
├── components/                  client UI (HomeOverview, JobsDashboard, RunSearchPanel, SkillsEditor (with its star rating), SiteNav, JobRow, JobDetails drawer, ...)
│   └── ui/                      shadcn/ui primitives (button, select, sheet, table, ...)
└── lib/
    ├── config.ts                IG_STATE_BACKEND / Firebase env resolution (port of job_store.py)
    ├── store/                   JobStore interface + Firestore (firebase-admin) and JSON-file implementations
    ├── status-update.ts         validates PATCH bodies; builds the same fields jobs_cli.py writes
    ├── skills.ts                the default skills, validating a list (port of search_skills.py), editing helpers
    ├── search-api.ts            server-side forwarding to the search API (IG_API_URL / IG_API_TOKEN)
    ├── runs.ts                  describing search runs (pure functions)
    ├── reassess.ts              describing a reassessment for the Refresh notice (pure functions)
    ├── overview.ts              home-screen totals and lists; /jobs?status= links (pure functions)
    ├── load-jobs.ts             the pages' store read, with config errors turned into a message
    ├── jobs.ts                  normalising, sorting, filtering, formatting (pure functions)
    └── client.ts                the browser's fetch wrapper for the API routes
```

- **UI components are [shadcn/ui](https://ui.shadcn.com)** on Radix
  primitives, styled with Tailwind v4 — see [Component library](#component-library).
- All database access happens **on the server** (route handlers and the
  server component) through the Firebase **Admin SDK** with the script's
  service account. The browser only talks to `/api/jobs`, `/api/skills`, and `/api/runs`; no Firebase
  credentials or config are shipped to the client.
- The page is rendered at request time (`connection()` + `<Suspense>`), so
  it's never frozen into a static build.
- `LocalJsonJobStore` writes `local_firestore.json` in the same layout as the
  Python stand-in (sorted keys, 2-space indent, ISO timestamps with `+00:00`)
  and atomically (temp file + rename). Both sides do whole-file
  read-modify-write, so don't edit in the dashboard at the exact moment the
  script is saving — fine for a once-a-day cron.

### Component library

The UI is built with [shadcn/ui](https://ui.shadcn.com) (style `new-york-v4`,
Radix primitives, Lucide icons, `next-themes` for dark mode). It was chosen
over MUI/Chakra because it is the standard pairing for the Next.js App Router:
accessible Radix components styled with the Tailwind setup already in the
project, no CSS-in-JS runtime or provider, and server-component friendly.

The components live in `src/components/ui/` and are yours to edit. Add more
with the CLI (`components.json` is configured):

```bash
npx shadcn@latest add dialog tooltip card   # any component from ui.shadcn.com
```

Theme tokens (colours, radius) are CSS variables in `src/app/globals.css`;
regenerate a different palette from the shadcn theme editor and paste it in.

### Authentication — current state and the path forward

Today there is **no login**: the dashboard trusts whoever can reach it and
uses server-side admin credentials, which is appropriate for running on your
own machine. Don't deploy it publicly as-is: anyone who can open it can also
click **Run search**, which sends digest emails.

When you want to host it, the cleanest upgrade is **Firebase Authentication**
with the Admin SDK verifying the session:

1. Enable a provider (Google sign-in is the obvious one) in the Firebase
   console and add a sign-in page using the client `firebase/auth` SDK.
2. Exchange the ID token for a session cookie (`auth().createSessionCookie`)
   in a route handler; verify it in `proxy.ts` (Next 16's middleware) or at
   the top of each route handler and allow only your UID/email.
3. Keep all Firestore access server-side as it is now. Security rules stay
   locked down, the service account stays on the server, and the browser
   never gets direct database access.

Because `src/lib/store` is an interface, the alternative — client-side
Firestore with security rules keyed to `request.auth.uid` — is also a contained
change, but it means shipping Firebase config to the browser and maintaining
rules, so the session-cookie approach above is recommended.

## Scripts

```bash
npm run dev            # development server
npm run build && npm start
npm test               # vitest: lib, API routes (Node) + components (jsdom)
npm run test:watch
npm run test:coverage
npm run lint
npm run typecheck
```

Tests never touch a real database: the data layer is exercised against a
temporary copy of `src/test/fixtures/local_firestore.json` (generated by the
Python store, so the format is authoritative) and an in-memory fake of the
Admin SDK. Component tests drive the real Radix widgets (selects, drawer,
toggle chips) through Testing Library; `src/test/setup.ts` adds the few DOM
APIs jsdom lacks for them.
