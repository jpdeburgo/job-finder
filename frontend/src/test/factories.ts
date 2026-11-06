import type { Job } from "@/lib/types";

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
