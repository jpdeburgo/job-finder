# Job Tracker dashboard (frontend)

A Next.js dashboard for the jobs that [`../backend`](../backend/README.md)
finds and records. It reads the same Firestore database (or the same
`local_firestore.json` stand-in) the script writes, so there is nothing to
sync: run the script, refresh the page.

What you can do:

- See every tracked job with its track, matched skills, salary, posted date,
  and when the script last saw it. Search, filter by status/track, and sort.
- Change a job's **status** inline (`unemailed` → `emailed` → `applied`,
  `skipped`, `interviewing`, `rejected`, `offer`) or use the **Mark applied**
  button; applied jobs show the date you applied.
- Expand a row for every field, a **notes** editor, and all of the job's links:
  the Insight Global posting (to apply), the digest email it arrived in
  (Gmail), and a search for its title. Every link opens in a new tab.
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
  `FIRESTORE_RUNS_COLLECTION` — same meaning as in the script.

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
│   ├── page.tsx                 server component: reads the store, renders the dashboard
│   ├── api/jobs/route.ts        GET  /api/jobs          → { store, jobs }
│   └── api/jobs/[id]/route.ts   GET  /api/jobs/:id      → { job }
│                                PATCH /api/jobs/:id     { status?, notes? } → { job }
├── components/                  client UI (JobsDashboard, JobRow, JobDetails drawer, FilterBar, ...)
│   └── ui/                      shadcn/ui primitives (button, select, sheet, table, ...)
└── lib/
    ├── config.ts                IG_STATE_BACKEND / Firebase env resolution (port of job_store.py)
    ├── store/                   JobStore interface + Firestore (firebase-admin) and JSON-file implementations
    ├── status-update.ts         validates PATCH bodies; builds the same fields jobs_cli.py writes
    ├── jobs.ts                  normalising, sorting, filtering, formatting (pure functions)
    └── client.ts                the browser's fetch wrapper for the two API routes
```

- **UI components are [shadcn/ui](https://ui.shadcn.com)** on Radix
  primitives, styled with Tailwind v4 — see [Component library](#component-library).
- All database access happens **on the server** (route handlers and the
  server component) through the Firebase **Admin SDK** with the script's
  service account. The browser only talks to `/api/jobs`; no Firebase
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
own machine. Don't deploy it publicly as-is.

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
