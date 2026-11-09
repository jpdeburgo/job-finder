/**
 * Server-side access to the search API (backend/api.py, FastAPI).
 *
 * The browser never calls FastAPI directly: it calls this app's /api/runs
 * routes, which forward here. That keeps the browser on one origin (no CORS)
 * and keeps `IG_API_TOKEN` on the server, like the Firebase credentials.
 *
 *   IG_API_URL    where the API listens (default http://127.0.0.1:8000)
 *   IG_API_TOKEN  sent as `Authorization: Bearer ...` when set; must match the
 *                 API's own IG_API_TOKEN
 *
 * Both are read from frontend/.env.local or, failing that, the script's .env
 * (see `loadBackendEnv`), so one backend/.env can configure both sides.
 */

import { backendDir, loadBackendEnv, type Env } from "./config";

export const API_URL_ENV_VAR = "IG_API_URL";
export const API_TOKEN_ENV_VAR = "IG_API_TOKEN";
export const DEFAULT_API_URL = "http://127.0.0.1:8000";
/** Every call here is quick (starting a run returns immediately), so don't hang the page on a stuck API. */
export const API_TIMEOUT_MS = 10_000;

export const START_API_HINT = "Start it with `cd backend && pipenv run uvicorn api:app` (see backend/README.md).";

export interface SearchApiConfig {
  baseUrl: string;
  token: string | undefined;
}

export function resolveSearchApiConfig(env: Env = process.env): SearchApiConfig {
  const baseUrl = (env[API_URL_ENV_VAR]?.trim() || DEFAULT_API_URL).replace(/\/+$/, "");
  const token = env[API_TOKEN_ENV_VAR]?.trim() || undefined;
  return { baseUrl, token };
}

let envLoaded = false;

function currentConfig(): SearchApiConfig {
  if (!envLoaded) {
    loadBackendEnv(backendDir());
    envLoaded = true;
  }
  return resolveSearchApiConfig();
}

/** Forget that the script's .env was read (tests). */
export function resetSearchApiConfig(): void {
  envLoaded = false;
}

function errorJson(message: string, status: number): Response {
  return Response.json({ error: message }, { status, headers: { "Cache-Control": "no-store" } });
}

/**
 * Forward a request to the search API and hand its answer back unchanged
 * (status and JSON body). An unreachable API becomes a 503, and a slow one a
 * 504, each with a message saying how to fix it.
 */
export async function forwardToSearchApi(
  path: string,
  init: { method?: string; body?: string } = {},
  config: SearchApiConfig = currentConfig(),
): Promise<Response> {
  const url = `${config.baseUrl}${path}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (config.token) headers.Authorization = `Bearer ${config.token}`;

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: init.method ?? "GET",
      headers,
      body: init.body,
      cache: "no-store",
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
  } catch (error) {
    if (error instanceof Error && error.name === "TimeoutError") {
      return errorJson(`The search API at ${config.baseUrl} didn't answer within ${API_TIMEOUT_MS / 1000}s.`, 504);
    }
    return errorJson(`The search API isn't reachable at ${config.baseUrl}. ${START_API_HINT}`, 503);
  }

  let body: unknown;
  try {
    body = await upstream.json();
  } catch {
    if (upstream.ok) return errorJson(`The search API at ${config.baseUrl} sent a response that isn't JSON.`, 502);
    return errorJson(`Search API: ${upstream.status} ${upstream.statusText}`.trim(), upstream.status);
  }
  return Response.json(body, { status: upstream.status, headers: { "Cache-Control": "no-store" } });
}
