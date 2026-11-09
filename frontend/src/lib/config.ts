/**
 * Decide which database the dashboard talks to.
 *
 * This is a line-for-line port of `get_job_store` / `FirestoreJobStore.from_env`
 * in backend/job_store.py, so the dashboard and the search script always
 * agree:
 *
 *   IG_STATE_BACKEND=auto       real Firestore if any Firebase variable is
 *                               set, otherwise backend/local_firestore.json
 *   IG_STATE_BACKEND=local      always the local JSON stand-in
 *   IG_STATE_BACKEND=firestore  always real Firestore (fails if unconfigured)
 *
 * Firebase credentials, in order: FIREBASE_SERVICE_ACCOUNT_JSON (inline),
 * GOOGLE_APPLICATION_CREDENTIALS (file path), FIRESTORE_EMULATOR_HOST.
 *
 * Variables are read from the process environment, which Next.js fills from
 * frontend/.env*. Anything not set there is read from the script's `.env` —
 * found the way python-dotenv finds it: `backend/.env`, else the nearest
 * `.env` in a parent directory (typically the repository root) — so Firebase
 * only has to be configured once (see `loadBackendEnv`).
 */

import fs from "node:fs";
import path from "node:path";
import { parse as parseDotenv } from "dotenv";

export const BACKEND_SELECTOR_ENV_VAR = "IG_STATE_BACKEND";
export const LOCAL_DB_PATH_ENV_VAR = "IG_LOCAL_DB_PATH";
export const BACKEND_DIR_ENV_VAR = "IG_BACKEND_DIR";

/** Same list as FIREBASE_ENV_VARS in backend/job_store.py. */
export const FIREBASE_ENV_VARS = [
  "GOOGLE_APPLICATION_CREDENTIALS",
  "FIREBASE_SERVICE_ACCOUNT_JSON",
  "FIRESTORE_EMULATOR_HOST",
  "FIREBASE_PROJECT_ID",
] as const;

/** Variables whose values are file paths, resolved relative to the .env's directory. */
const PATH_ENV_VARS = ["GOOGLE_APPLICATION_CREDENTIALS", "GMAIL_CREDENTIALS_PATH", "GMAIL_TOKEN_PATH", LOCAL_DB_PATH_ENV_VAR];

export const DEFAULT_JOBS_COLLECTION = "jobs";
export const DEFAULT_RUNS_COLLECTION = "runs";
export const LOCAL_DB_FILENAME = "local_firestore.json";
/** Project ID used with the emulator when none is configured. */
export const DEFAULT_EMULATOR_PROJECT_ID = "demo-job-finder";

export type Env = Record<string, string | undefined>;

export interface CollectionNames {
  jobs: string;
  runs: string;
}

export interface LocalStoreConfig {
  backend: "local";
  /** Absolute path to local_firestore.json. */
  path: string;
  collections: CollectionNames;
}

export interface FirestoreStoreConfig {
  backend: "firestore";
  projectId: string | undefined;
  /** `undefined` means Firestore's "(default)" database. */
  databaseId: string | undefined;
  /** Parsed FIREBASE_SERVICE_ACCOUNT_JSON, when provided. */
  serviceAccount: Record<string, unknown> | undefined;
  /** GOOGLE_APPLICATION_CREDENTIALS, when provided. */
  credentialsPath: string | undefined;
  emulatorHost: string | undefined;
  collections: CollectionNames;
}

export type StoreConfig = LocalStoreConfig | FirestoreStoreConfig;

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

/** `<repo>/backend`, where the Python script and local_firestore.json live. */
export function backendDir(env: Env = process.env, cwd: string = process.cwd()): string {
  const configured = env[BACKEND_DIR_ENV_VAR]?.trim();
  return configured ? path.resolve(cwd, configured) : path.resolve(cwd, "..", "backend");
}

function nonEmpty(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

export function firebaseConfigured(env: Env = process.env): boolean {
  return FIREBASE_ENV_VARS.some((name) => nonEmpty(env[name]) !== undefined);
}

function collectionNames(env: Env): CollectionNames {
  return {
    jobs: nonEmpty(env.FIRESTORE_JOBS_COLLECTION) ?? DEFAULT_JOBS_COLLECTION,
    runs: nonEmpty(env.FIRESTORE_RUNS_COLLECTION) ?? DEFAULT_RUNS_COLLECTION,
  };
}

export function localDbPath(env: Env = process.env, cwd: string = process.cwd()): string {
  const configured = nonEmpty(env[LOCAL_DB_PATH_ENV_VAR]);
  if (configured) return path.resolve(cwd, configured);
  return path.join(backendDir(env, cwd), LOCAL_DB_FILENAME);
}

/** Resolve the store configuration from environment variables. */
export function resolveStoreConfig(env: Env = process.env, cwd: string = process.cwd()): StoreConfig {
  let backend = (env[BACKEND_SELECTOR_ENV_VAR] ?? "auto").trim().toLowerCase() || "auto";
  if (backend === "auto") {
    backend = firebaseConfigured(env) ? "firestore" : "local";
  }

  if (backend === "local") {
    return { backend: "local", path: localDbPath(env, cwd), collections: collectionNames(env) };
  }

  if (backend === "firestore") {
    const inlineJson = nonEmpty(env.FIREBASE_SERVICE_ACCOUNT_JSON);
    let serviceAccount: Record<string, unknown> | undefined;
    if (inlineJson) {
      try {
        serviceAccount = JSON.parse(inlineJson) as Record<string, unknown>;
      } catch (error) {
        throw new ConfigError(
          `FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON: ${(error as Error).message}`,
        );
      }
    }
    const credentialsPath = nonEmpty(env.GOOGLE_APPLICATION_CREDENTIALS);
    const emulatorHost = nonEmpty(env.FIRESTORE_EMULATOR_HOST);
    const projectId =
      nonEmpty(env.FIREBASE_PROJECT_ID) ??
      (typeof serviceAccount?.project_id === "string" ? serviceAccount.project_id : undefined) ??
      nonEmpty(env.GOOGLE_CLOUD_PROJECT) ??
      nonEmpty(env.GCLOUD_PROJECT) ??
      (emulatorHost ? DEFAULT_EMULATOR_PROJECT_ID : undefined);

    if (!serviceAccount && !credentialsPath && !emulatorHost) {
      throw new ConfigError(
        "No Firebase credentials found. Set GOOGLE_APPLICATION_CREDENTIALS to your " +
          "service-account JSON path (or FIREBASE_SERVICE_ACCOUNT_JSON to its contents), " +
          `or set ${BACKEND_SELECTOR_ENV_VAR}=local to use ${LOCAL_DB_FILENAME} instead. ` +
          "See backend/README.md for Firebase setup.",
      );
    }

    const database = nonEmpty(env.FIRESTORE_DATABASE);
    return {
      backend: "firestore",
      projectId,
      databaseId: database && database !== "(default)" ? database : undefined,
      serviceAccount,
      credentialsPath: credentialsPath ? path.resolve(cwd, credentialsPath) : undefined,
      emulatorHost,
      collections: collectionNames(env),
    };
  }

  throw new ConfigError(
    `Unknown ${BACKEND_SELECTOR_ENV_VAR}=${JSON.stringify(backend)}; expected 'auto', 'firestore', or 'local'`,
  );
}

/**
 * Find the `.env` the Python script would load: the first one in `startDir`
 * or any of its parents (python-dotenv's `find_dotenv`, starting from the
 * directory of `job_search.py`). Returns `null` when there is none.
 */
export function findDotenv(startDir: string): string | null {
  let dir = path.resolve(startDir);
  for (;;) {
    const candidate = path.join(dir, ".env");
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

export interface LoadedEnv {
  /** The `.env` file that was read, or `null` if none was found. */
  file: string | null;
  /** Variable names that were applied (not already set in `env`). */
  applied: string[];
}

/**
 * Fill `env` with variables from the script's `.env` (see `findDotenv`) that
 * aren't already set.
 *
 * Next.js loads frontend/.env* itself; this lets the dashboard reuse the
 * script's Firebase configuration without duplicating it. Relative file paths
 * are resolved against the `.env` file's own directory, falling back to the
 * backend directory when the file only exists there.
 */
export function loadBackendEnv(backendDirectory: string, env: Env = process.env): LoadedEnv {
  const file = findDotenv(backendDirectory);
  if (!file) return { file: null, applied: [] };
  const envDir = path.dirname(file);
  const parsed = parseDotenv(fs.readFileSync(file, "utf-8"));
  const applied: string[] = [];
  for (const [name, rawValue] of Object.entries(parsed)) {
    if (nonEmpty(env[name]) !== undefined) continue;
    let value = rawValue;
    if (PATH_ENV_VARS.includes(name) && value.trim()) {
      value = resolveConfiguredPath(value.trim(), [envDir, backendDirectory]);
    }
    env[name] = value;
    applied.push(name);
  }
  return { file, applied };
}

/** Resolve a path from a `.env` against the first base directory where it exists. */
function resolveConfiguredPath(value: string, baseDirs: string[]): string {
  if (path.isAbsolute(value)) return value;
  const candidates = baseDirs.map((base) => path.resolve(base, value));
  return candidates.find((candidate) => fs.existsSync(candidate)) ?? candidates[0];
}
