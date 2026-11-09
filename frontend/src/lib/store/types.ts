import type { Job, StoreInfo } from "../types";

/**
 * The slice of job-tracker persistence the dashboard needs. Implemented for
 * the real Firestore (`firestore.ts`) and the JSON stand-in (`local.ts`).
 * Route handlers only ever see this interface, which is also the seam to
 * swap in a FastAPI backend later.
 */
export interface JobStore {
  info(): StoreInfo;
  /** Record which `.env` (if any) the configuration came from, for `info()`. */
  envFile: string | null;
  /** Every job, newest `last_seen_at` first. */
  listJobs(): Promise<Job[]>;
  getJob(id: string): Promise<Job | null>;
  /**
   * Merge `fields` into an existing job and return the updated document.
   * `Date` values are stored as timestamps. Throws `JobNotFoundError` when
   * the job doesn't exist.
   */
  updateJob(id: string, fields: Record<string, unknown>): Promise<Job>;
}

export class JobNotFoundError extends Error {
  constructor(public readonly jobId: string) {
    super(`Job ${jobId} is not in the store`);
    this.name = "JobNotFoundError";
  }
}
