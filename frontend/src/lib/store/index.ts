/**
 * Store factory: pick local JSON or Firestore from the environment, exactly
 * like `get_job_store()` in backend/job_store.py.
 */

import { backendDir, loadBackendEnv, resolveStoreConfig, type StoreConfig } from "../config";
import { createFirestoreStore } from "./firestore";
import { LocalJsonJobStore } from "./local";
import type { JobStore } from "./types";

export { JobNotFoundError } from "./types";
export type { JobStore } from "./types";

export function createJobStore(config: StoreConfig): JobStore {
  return config.backend === "local" ? new LocalJsonJobStore(config) : createFirestoreStore(config);
}

// One store per server process; `next dev` keeps module state across
// requests, so this also keeps a single Firestore connection alive.
let cached: JobStore | undefined;

/** The store selected by the current environment (cached after first use). */
export function getJobStore(): JobStore {
  if (!cached) {
    const loaded = loadBackendEnv(backendDir());
    cached = createJobStore(resolveStoreConfig());
    cached.envFile = loaded.file;
  }
  return cached;
}

/** Forget the cached store (tests, or after changing environment variables). */
export function resetJobStore(): void {
  cached = undefined;
}
