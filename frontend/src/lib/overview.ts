/**
 * Pure helpers for the home screen: headline counts, the newest matches, and
 * your latest status changes. Also the `/jobs?status=...` links the home
 * screen uses to open the tracker pre-filtered.
 */

import { DEFAULT_FILTERS, type JobFilters } from "./jobs";
import { isJobStatus, type Job, type JobStatus } from "./types";

/** Statuses you set yourself (everything after the digest email). */
const USER_STATUSES: readonly string[] = ["applied", "skipped", "interviewing", "rejected", "offer"];

export interface JobCounts {
  total: number;
  /** In a digest email and not acted on yet. */
  toReview: number;
  /** Saved, but the digest didn't go out (usually: Gmail isn't set up). */
  unemailed: number;
  applied: number;
  interviewing: number;
  offers: number;
}

export function countJobs(jobs: Job[]): JobCounts {
  const count = (status: JobStatus) => jobs.filter((job) => job.status === status).length;
  return {
    total: jobs.length,
    toReview: count("emailed"),
    unemailed: count("unemailed"),
    applied: count("applied"),
    interviewing: count("interviewing"),
    offers: count("offer"),
  };
}

const newestBy =
  (field: "first_seen_at" | "status_updated_at") =>
  (a: Job, b: Job): number =>
    (b[field] ?? "").localeCompare(a[field] ?? "");

/** The jobs the search found most recently. */
export function latestMatches(jobs: Job[], limit = 5): Job[] {
  return jobs
    .filter((job) => job.first_seen_at)
    .sort(newestBy("first_seen_at"))
    .slice(0, limit);
}

/** Your most recent status changes (applied, interviewing, skipped, ...). */
export function recentActivity(jobs: Job[], limit = 5): Job[] {
  return jobs
    .filter((job) => USER_STATUSES.includes(job.status) && job.status_updated_at)
    .sort(newestBy("status_updated_at"))
    .slice(0, limit);
}

/** The tracker, optionally filtered to one status: `/jobs` or `/jobs?status=applied`. */
export function jobsHref(status?: JobStatus): string {
  return status ? `/jobs?status=${status}` : "/jobs";
}

/**
 * The tracker's starting filters from its URL (`/jobs?status=applied`).
 * Unknown values are ignored rather than producing an empty table.
 */
export function filtersFromSearchParams(params: Record<string, string | string[] | undefined>): JobFilters {
  const status = Array.isArray(params.status) ? params.status[0] : params.status;
  return { ...DEFAULT_FILTERS, status: isJobStatus(status) ? status : "all" };
}
