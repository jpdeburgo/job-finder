/**
 * Browser-side client for the dashboard's API routes.
 *
 * Everything the UI needs from the server goes through these calls. Jobs are
 * read and written by this app's own routes; searches are started through
 * /api/runs, which forwards to the FastAPI service in backend/api.py.
 */

import type { Job, JobPatch, RunRequest, SearchRun, StoreInfo } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    /** The parsed error body, e.g. the run that's already going on a 409. */
    public readonly body: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function handle<T>(response: Response): Promise<T> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Non-JSON error page; fall through to the status text.
  }
  if (!response.ok) {
    const message =
      body && typeof body === "object" && typeof (body as { error?: unknown }).error === "string"
        ? (body as { error: string }).error
        : `${response.status} ${response.statusText}`.trim();
    throw new ApiError(message, response.status, body);
  }
  return body as T;
}

export async function fetchJobs(): Promise<{ store: StoreInfo; jobs: Job[] }> {
  return handle(await fetch("/api/jobs", { cache: "no-store" }));
}

export async function patchJob(id: string, patch: JobPatch): Promise<Job> {
  const response = await fetch(`/api/jobs/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return (await handle<{ job: Job }>(response)).job;
}

/** Start a search. Rejects with a 409 `ApiError` (whose body has the current `run`) if one is already going. */
export async function startRun(request: RunRequest = {}): Promise<SearchRun> {
  const response = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return (await handle<{ run: SearchRun }>(response)).run;
}

/** The newest search started from the dashboard, or null if there hasn't been one since the API started. */
export async function fetchLatestRun(): Promise<SearchRun | null> {
  return (await handle<{ run: SearchRun | null }>(await fetch("/api/runs/latest", { cache: "no-store" }))).run;
}

export async function fetchRun(id: string): Promise<SearchRun> {
  const response = await fetch(`/api/runs/${encodeURIComponent(id)}`, { cache: "no-store" });
  return (await handle<{ run: SearchRun }>(response)).run;
}

/** The run an `ApiError` is about, if the server sent one (a 409 from `startRun`). */
export function runFromError(error: unknown): SearchRun | null {
  if (!(error instanceof ApiError) || !error.body || typeof error.body !== "object") return null;
  const run = (error.body as { run?: unknown }).run;
  return run && typeof run === "object" ? (run as SearchRun) : null;
}
