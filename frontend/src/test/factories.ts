import type { Job, RunSummary, SearchRun } from "@/lib/types";

/** A fully-detailed job, overridable per test. */
export function makeJob(overrides: Partial<Job> = {}): Job {
  const id = overrides.id ?? "6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba";
  return {
    id,
    job_id: id,
    company: "Insight Global",
    title: "React Developer",
    city: "Austin",
    state: "TX",
    is_remote: true,
    job_type: "Contract",
    salary_low: 55,
    salary_high: 65,
    url: `https://insightglobal.com/jobs/${id}`,
    track: "Core matches (your main stack)",
    posted_date: "2026-10-30",
    matched_skills: ["React", "TypeScript"],
    score: 2,
    min_years: 3,
    fit_score: 71,
    fit_breakdown: { skills: 41, role: 30, experience: 0, remote: 0, stack: 0 },
    fit_reasons: ["Skills: TypeScript, React (2 core)", 'Title is a target role ("Developer")'],
    status: "emailed",
    notes: null,
    first_seen_at: "2026-10-31T13:00:05.123456+00:00",
    last_seen_at: "2026-10-31T13:00:05.123456+00:00",
    emailed_at: "2026-10-31T13:00:05.123456+00:00",
    applied_at: null,
    status_updated_at: "2026-10-31T13:00:05.123456+00:00",
    gmail_message_id: "19a1b2c3d4e5f607",
    ...overrides,
  };
}

/** A search run (backend/api.py), still going unless overridden. */
export function makeRun(overrides: Partial<SearchRun> = {}): SearchRun {
  return {
    id: "abc123",
    status: "running",
    sites: [],
    include_unmarked: false,
    started_at: "2026-11-06T14:00:00+00:00",
    finished_at: null,
    summary: null,
    error: null,
    output: [],
    output_truncated: 0,
    ...overrides,
  };
}

export function makeSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    total_matches: 4,
    new_matches: 1,
    emailed_matches: 1,
    email_sent: true,
    gmail_message_id: "19a1b2c3d4e5f607",
    email_skipped_reason: null,
    ...overrides,
  };
}

/** A run that finished successfully. */
export function makeFinishedRun(overrides: Partial<SearchRun> = {}): SearchRun {
  return makeRun({
    status: "succeeded",
    finished_at: "2026-11-06T14:03:00+00:00",
    summary: makeSummary(),
    ...overrides,
  });
}
