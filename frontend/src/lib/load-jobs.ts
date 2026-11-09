/**
 * Server-side loading shared by the pages (home and jobs). Route handlers use
 * the store directly; pages go through this so a misconfigured database
 * becomes a message on the page instead of a crash.
 */

import { getJobStore } from "./store";
import type { Job, StoreInfo } from "./types";

export type LoadResult = { ok: true; jobs: Job[]; store: StoreInfo } | { ok: false; message: string };

/** Open the store and list jobs, turning configuration problems into a message. */
export async function loadJobs(): Promise<LoadResult> {
  try {
    const store = getJobStore();
    return { ok: true, jobs: await store.listJobs(), store: store.info() };
  } catch (error) {
    return { ok: false, message: (error as Error).message };
  }
}
