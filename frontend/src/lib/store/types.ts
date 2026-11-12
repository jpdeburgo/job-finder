import type { SearchSkills } from "../skills";
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
  /**
   * Your saved skill list (`settings/search_skills`) as stored, or null when
   * you haven't saved one and the search uses its defaults.
   */
  getSearchSkills(): Promise<Record<string, unknown> | null>;
  /** Save your skill list (already validated), stamped with `updated_at`. */
  saveSearchSkills(skills: SearchSkills, now?: Date): Promise<void>;
  /** Delete the saved list, so the search goes back to its defaults. */
  resetSearchSkills(): Promise<void>;
  /**
   * Your saved resume (`settings/resume`) as stored, or null without one.
   * Only backend/resume.py writes it (uploads go through the search API);
   * `resumeFromDocument` reads it.
   */
  getResume(): Promise<Record<string, unknown> | null>;
}

export class JobNotFoundError extends Error {
  constructor(public readonly jobId: string) {
    super(`Job ${jobId} is not in the store`);
    this.name = "JobNotFoundError";
  }
}
