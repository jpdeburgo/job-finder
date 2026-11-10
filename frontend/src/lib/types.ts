/**
 * Shared job-tracker types.
 *
 * The shape mirrors the documents `backend/job_store.py` writes to the `jobs`
 * collection (see its module docstring). Everything is normalised for the
 * browser: timestamps are ISO-8601 strings, missing fields are `null`, and
 * `job_id` is always a string.
 */

// Keep in sync with JOB_STATUSES in backend/job_store.py.
export const JOB_STATUSES = [
  "unemailed",
  "emailed",
  "applied",
  "skipped",
  "interviewing",
  "rejected",
  "offer",
] as const;

export type JobStatus = (typeof JOB_STATUSES)[number];

export function isJobStatus(value: unknown): value is JobStatus {
  return typeof value === "string" && (JOB_STATUSES as readonly string[]).includes(value);
}

/** Human-friendly labels and a short explanation for each workflow status. */
export const STATUS_INFO: Record<JobStatus, { label: string; hint: string }> = {
  unemailed: { label: "Unemailed", hint: "Matched and saved, but the digest email has not gone out yet." },
  emailed: { label: "Emailed", hint: "In a digest email; you have not acted on it yet." },
  applied: { label: "Applied", hint: "You applied for this job." },
  skipped: { label: "Skipped", hint: "Not applying." },
  interviewing: { label: "Interviewing", hint: "In the interview process." },
  rejected: { label: "Rejected", hint: "Turned down or the posting went away." },
  offer: { label: "Offer", hint: "You received an offer." },
};

// How you say a job is really worked, whatever the site claims. Keep in sync
// with WORK_ARRANGEMENTS in backend/job_store.py.
export const WORK_ARRANGEMENTS = ["remote", "hybrid", "on_site"] as const;

export type WorkArrangement = (typeof WORK_ARRANGEMENTS)[number];

export const WORK_ARRANGEMENT_LABELS: Record<WorkArrangement, string> = {
  remote: "Remote",
  hybrid: "Hybrid",
  on_site: "On-site",
};

export function isWorkArrangement(value: unknown): value is WorkArrangement {
  return typeof value === "string" && (WORK_ARRANGEMENTS as readonly string[]).includes(value);
}

export interface Job {
  /** Firestore document ID: `<company>-<the site's own ID>`, e.g. `accenture-R00212345`. */
  id: string;
  job_id: string;
  /** Who posted it ("Insight Global", "Accenture", ...); null on documents saved before it existed. */
  company: string | null;
  title: string | null;
  city: string | null;
  state: string | null;
  /**
   * Whether the job is remote: your `work_arrangement` when you've set one,
   * else the site's word (null when it doesn't say). See `remoteStatus`.
   */
  is_remote: boolean | null;
  /** How you've said the job is really worked; null if you haven't. */
  work_arrangement: WorkArrangement | null;
  /** What the site (and the search's on-site checks) say, before your say. */
  site_is_remote: boolean | null;
  work_arrangement_set_at: string | null;
  job_type: string | null;
  salary_low: number | null;
  salary_high: number | null;
  url: string | null;
  track: string | null;
  posted_date: string | null;
  matched_skills: string[];
  /** Number of matched skills. */
  score: number | null;
  min_years: number | null;
  /**
   * How well the job fits you, 0-100 (backend/job_fit.py). null on jobs saved
   * before the search computed it.
   */
  fit_score: number | null;
  /** Points behind `fit_score`, e.g. `{ skills: 48, role: 30, experience: -8 }`; they add up to it. */
  fit_breakdown: Record<string, number>;
  /** The same breakdown in words. */
  fit_reasons: string[];
  /**
   * Whether the job still matches your skills, as of the last reassessment
   * (Refresh, or a search); null until it's been assessed. Jobs that no
   * longer match are flagged, never removed.
   */
  matches_skills: boolean | null;
  /** Why it no longer matches, e.g. "it doesn't mention any of your skills"; null otherwise. */
  skills_mismatch_reason: string | null;
  /**
   * Why the search marked the job not remote although its site said remote,
   * e.g. `its title says "On-Site"` or `the site's workSetting = "Onsite"`; null otherwise.
   */
  not_remote_reason: string | null;
  status: JobStatus | string;
  notes: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  emailed_at: string | null;
  applied_at: string | null;
  status_updated_at: string | null;
  gmail_message_id: string | null;
}

/** What the browser may change about a job. */
export interface JobPatch {
  status?: JobStatus;
  notes?: string;
  /** null goes back to what the site says. */
  work_arrangement?: WorkArrangement | null;
}

/** Which database the dashboard is talking to, for the header banner. */
export interface StoreInfo {
  backend: "local" | "firestore";
  /** e.g. "local Firestore stand-in at /path/local_firestore.json". */
  description: string;
  emulator: boolean;
  /** The script's `.env` the settings were read from, if one was found. */
  envFile: string | null;
}

// --- Search runs (backend/api.py) -------------------------------------------------

/** Mirrors `RunSummary` in backend/job_search.py. */
export interface RunSummary {
  total_matches: number;
  new_matches: number;
  /** Jobs in this run's digest: the new ones plus any an earlier run failed to email. */
  emailed_matches: number;
  email_sent: boolean;
  gmail_message_id: string | null;
  /** Why no digest went out, when Gmail / IG_EMAIL_TO isn't set up. */
  email_skipped_reason: string | null;
}

export type RunStatus = "running" | "succeeded" | "failed";

/** One search started from the dashboard; mirrors `SearchRun.to_dict()` in backend/api.py. */
export interface SearchRun {
  id: string;
  status: RunStatus;
  sites: string[];
  include_unmarked: boolean;
  started_at: string;
  finished_at: string | null;
  summary: RunSummary | null;
  error: string | null;
  /** What the script printed so far (newest lines only). */
  output?: string[];
  /** How many older lines were dropped from `output`. */
  output_truncated?: number;
}

/** What re-scoring saved jobs against your skills did; mirrors `ReassessSummary` in backend/job_search.py. */
export interface ReassessSummary {
  total_jobs: number;
  reassessed: number;
  changed: number;
  no_longer_match: number;
  /** Descriptions loaded from the job sites this time (saved for next time). */
  fetched: number;
  /** Jobs left as they were: their posting couldn't be loaded. */
  unavailable: number;
  skills_source: "saved" | "default";
}

/** Options for a search; the same as job_search.py's --site and --include-unmarked. */
export interface RunRequest {
  sites?: string[];
  include_unmarked?: boolean;
}
