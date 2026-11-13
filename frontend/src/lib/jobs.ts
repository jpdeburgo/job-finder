/**
 * Pure helpers for job documents: normalising raw Firestore/JSON data into
 * the `Job` type, sorting, filtering, and display formatting. No I/O here, so
 * everything is trivially unit-testable and usable on both server and client.
 */

import type { Job, JobStatus, SalaryPeriod } from "./types";
import { JOB_STATUSES, WORK_ARRANGEMENT_LABELS, isSalaryPeriod, isWorkArrangement } from "./types";

// --- Normalisation ----------------------------------------------------------

/** Fields the Python store writes as datetimes (Firestore Timestamps). */
const TIMESTAMP_FIELDS = [
  "first_seen_at",
  "last_seen_at",
  "emailed_at",
  "applied_at",
  "status_updated_at",
  "work_arrangement_set_at",
] as const;

/**
 * Convert a Firestore `Timestamp`, a `Date`, or an ISO string into an ISO
 * string. Anything else becomes `null`.
 */
export function toIsoString(value: unknown): string | null {
  if (value == null) return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString();
  }
  if (typeof value === "object" && typeof (value as { toDate?: unknown }).toDate === "function") {
    return toIsoString((value as { toDate: () => Date }).toDate());
  }
  if (typeof value === "string") return value;
  return null;
}

function asString(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return null;
}

function asBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function asNumberRecord(value: unknown): Record<string, number> {
  if (value == null || typeof value !== "object" || Array.isArray(value)) return {};
  const record: Record<string, number> = {};
  for (const [key, item] of Object.entries(value)) {
    const number = asNumber(item);
    if (number !== null) record[key] = number;
  }
  return record;
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

/** Turn a raw document (from either store) into a `Job`. */
export function normalizeJob(id: string, data: Record<string, unknown>): Job {
  const matchedSkills = asStringList(data.matched_skills);
  const siteIsRemote = asBoolean(data.is_remote);
  const arrangement = isWorkArrangement(data.work_arrangement) ? data.work_arrangement : null;
  return {
    id,
    job_id: asString(data.job_id) ?? id,
    company: asString(data.company),
    title: asString(data.title),
    city: asString(data.city),
    state: asString(data.state),
    // Your say wins over the site's (same as normalize_job in backend/job_queries.py).
    is_remote: arrangement ? arrangement === "remote" : siteIsRemote,
    work_arrangement: arrangement,
    site_is_remote: siteIsRemote,
    work_arrangement_set_at: toIsoString(data.work_arrangement_set_at),
    job_type: asString(data.job_type),
    salary_low: asNumber(data.salary_low),
    salary_high: asNumber(data.salary_high),
    salary_period: isSalaryPeriod(data.salary_period) ? data.salary_period : null,
    salary_period_estimated: data.salary_period_estimated === true,
    url: asString(data.url),
    track: asString(data.track),
    posted_date: asString(data.posted_date),
    matched_skills: matchedSkills,
    score: asNumber(data.score) ?? (matchedSkills.length ? matchedSkills.length : null),
    min_years: asNumber(data.min_years),
    fit_score: asNumber(data.fit_score),
    fit_breakdown: asNumberRecord(data.fit_breakdown),
    fit_reasons: asStringList(data.fit_reasons),
    matches_skills: asBoolean(data.matches_skills),
    skills_mismatch_reason: asString(data.skills_mismatch_reason),
    not_remote_reason: asString(data.not_remote_reason),
    status: asString(data.status) ?? "unknown",
    notes: asString(data.notes),
    first_seen_at: toIsoString(data.first_seen_at),
    last_seen_at: toIsoString(data.last_seen_at),
    emailed_at: toIsoString(data.emailed_at),
    applied_at: toIsoString(data.applied_at),
    status_updated_at: toIsoString(data.status_updated_at),
    gmail_message_id: asString(data.gmail_message_id),
  };
}

export { TIMESTAMP_FIELDS };

// --- Classification -----------------------------------------------------------

/**
 * Whether a job is remote. "unmarked" means the site didn't say; the search
 * script only saves those when run with `--include-unmarked`.
 */
export type RemoteStatus = "remote" | "unmarked" | "not_remote";

export const REMOTE_STATUS_INFO: Record<RemoteStatus, { label: string; hint: string }> = {
  remote: { label: "Remote", hint: "The site marks this job remote." },
  unmarked: {
    label: "Remote not stated",
    hint: "The site doesn't say whether this job is remote, hybrid, or on-site. Check the posting.",
  },
  not_remote: { label: "Not remote", hint: "The site marks this job hybrid or on-site." },
};

/** "On-site (you)", when you've said how a job is worked; null otherwise. */
export function workArrangementLabel(job: Pick<Job, "work_arrangement">): string | null {
  return job.work_arrangement ? `${WORK_ARRANGEMENT_LABELS[job.work_arrangement]} (you)` : null;
}

export function remoteStatus(job: Pick<Job, "is_remote">): RemoteStatus {
  if (job.is_remote === true) return "remote";
  if (job.is_remote === false) return "not_remote";
  return "unmarked";
}

export function hasApplied(job: Job): boolean {
  return job.status === "applied" || job.applied_at != null;
}

/** Short label for the track column ("Core", "Java", "iOS", ".NET"). */
export function trackLabel(track: string | null): string {
  if (!track) return "—";
  const lower = track.toLowerCase();
  if (lower.startsWith("core")) return "Core";
  if (lower.startsWith("java")) return "Java";
  if (lower.startsWith("ios")) return "iOS";
  if (lower.startsWith(".net")) return ".NET";
  return track.split(" ")[0];
}

// --- Links --------------------------------------------------------------------

/** Deep link that opens the digest email this job was sent in. */
export function gmailMessageUrl(messageId: string | null): string | null {
  if (!messageId) return null;
  return `https://mail.google.com/mail/u/0/#all/${encodeURIComponent(messageId)}`;
}

/** Insight Global search for the job's title, handy when a posting has moved. */
export function insightGlobalSearchUrl(title: string | null): string | null {
  if (!title) return null;
  return `https://insightglobal.com/jobs/search/all/all?keyword=${encodeURIComponent(title)}`;
}

export interface JobLink {
  label: string;
  href: string;
}

/** Every clickable destination for a job, in display order. */
export function jobLinks(job: Job): JobLink[] {
  const links: JobLink[] = [];
  if (job.url) links.push({ label: "Job posting", href: job.url });
  const gmail = gmailMessageUrl(job.gmail_message_id);
  if (gmail) links.push({ label: "Digest email", href: gmail });
  const search = insightGlobalSearchUrl(job.title);
  if (search) links.push({ label: "Search Insight Global", href: search });
  return links;
}

// --- Formatting -----------------------------------------------------------------

type SalaryFields = Pick<Job, "salary_low" | "salary_high"> &
  Partial<Pick<Job, "salary_period" | "salary_period_estimated">>;

// Same as PERIOD_SUFFIXES in backend/salary.py.
const PERIOD_SUFFIXES: Record<SalaryPeriod, string> = {
  hour: "/hr",
  day: "/day",
  week: "/wk",
  month: "/mo",
  year: "/yr",
};

const PERIOD_WORDS: Record<SalaryPeriod, string> = {
  hour: "per hour",
  day: "per day",
  week: "per week",
  month: "per month",
  year: "per year",
};

/** Same as MAX_HOURLY in backend/salary.py: with no stated period, amounts under this are hourly, the rest yearly. */
const MAX_HOURLY = 300;

/** The period assumed when nothing states one (`estimate_period` in backend/salary.py). */
function assumedPeriod(low: number, high: number): SalaryPeriod {
  return Math.max(low, high) < MAX_HOURLY ? "hour" : "year";
}

/** "$64", "$64.50", "$120,000" (same as `_money` in backend/salary.py). */
function money(value: number): string {
  const cents = !Number.isInteger(value) && value < 1000;
  return `$${value.toLocaleString("en-US", {
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  })}`;
}

/**
 * "$60 - $65/hr", "From $140,000/yr", "$1,200 - $3,000/mo", or "From $64/hr (est.)" /
 * "$1,200 - $3,000/yr (est.)" when the period is assumed (also for jobs saved
 * before periods were kept). Same wording as `format_salary` in backend/salary.py.
 */
export function formatSalary(job: SalaryFields): string {
  const low = job.salary_low ?? 0;
  const high = job.salary_high ?? 0;
  if (!low && !high) return "Not listed";
  let amount: string;
  if (!low) amount = `Up to ${money(high)}`;
  else if (!high) amount = `From ${money(low)}`;
  else if (high === low) amount = money(low);
  else amount = `${money(low)} - ${money(high)}`;
  const period = job.salary_period ?? assumedPeriod(low, high);
  const estimated = !job.salary_period || job.salary_period_estimated;
  return `${amount}${PERIOD_SUFFIXES[period]}${estimated ? " (est.)" : ""}`;
}

/**
 * Why a salary's period is marked "(est.)": the site and posting don't say,
 * so it's assumed. Null when the site or posting states it (or there's no salary).
 */
export function salaryPeriodNote(job: SalaryFields): string | null {
  const low = job.salary_low ?? 0;
  const high = job.salary_high ?? 0;
  if (!low && !high) return null;
  if (job.salary_period && !job.salary_period_estimated) return null;
  const period = job.salary_period ?? assumedPeriod(low, high);
  const why = period === "hour" ? "the amount looks like an hourly rate" : "salaries are taken as yearly unless stated";
  return `Assumed ${PERIOD_WORDS[period]}: the site and the posting don't say, and ${why}.`;
}

export function formatLocation(job: Pick<Job, "city" | "state">): string {
  const parts = [job.city, job.state].filter((part): part is string => !!part && part.trim() !== "");
  return parts.length ? parts.join(", ") : "—";
}

/** "2026-11-01" for any ISO timestamp or date string; "—" when absent. */
export function formatDate(value: string | null): string {
  if (!value) return "—";
  return value.length >= 10 ? value.slice(0, 10) : value;
}

// --- Fit score ------------------------------------------------------------------

/** Score bands; keep in sync with FIT_LABELS in backend/job_fit.py. */
export const FIT_LABELS = [
  { min: 75, label: "Strong" },
  { min: 60, label: "Good" },
  { min: 40, label: "Fair" },
  { min: 0, label: "Weak" },
] as const;

export type FitLabel = (typeof FIT_LABELS)[number]["label"];

/** "Strong", "Good", "Fair", or "Weak"; null for jobs saved before the fit score existed. */
export function fitLabel(score: number | null): FitLabel | null {
  if (score == null) return null;
  return (FIT_LABELS.find((band) => score >= band.min) ?? FIT_LABELS[FIT_LABELS.length - 1]).label;
}

/** Display names for the parts of `fit_breakdown`, in the order they're applied. */
export const FIT_PARTS: { key: string; label: string }[] = [
  { key: "skills", label: "Skills" },
  { key: "role", label: "Role" },
  { key: "experience", label: "Experience" },
  { key: "remote", label: "Remote" },
  { key: "stack", label: "Other tech" },
];

export function formatYears(minYears: number | null): string {
  return minYears == null ? "not stated" : `${minYears}+ yrs`;
}

// --- Sorting --------------------------------------------------------------------

/** `salary` is highest first, `salary_lowest` lowest first (same keys as backend/job_queries.py). */
export type SortKey = "last_seen" | "posted" | "salary" | "salary_lowest" | "score" | "fit" | "title" | "status";

const SALARY_SORT_HINT =
  'Pay is compared per year: $50/hr counts as $104,000, $3,000/mo as $36,000. "Not listed" goes last.';

export const SORT_OPTIONS: { value: SortKey; label: string; hint?: string }[] = [
  { value: "last_seen", label: "Last seen (newest)" },
  { value: "posted", label: "Posted (newest)" },
  { value: "salary", label: "Salary (highest)", hint: SALARY_SORT_HINT },
  { value: "salary_lowest", label: "Salary (lowest)", hint: SALARY_SORT_HINT },
  { value: "score", label: "Skill matches (most)" },
  { value: "fit", label: "Best fit" },
  { value: "title", label: "Title (A–Z)" },
  { value: "status", label: "Status" },
];

function seenKey(job: Job): string {
  return job.last_seen_at ?? job.first_seen_at ?? "";
}

/** Newest `last_seen_at` first, matching `FirestoreJobStore.list_jobs`. */
export function sortNewestFirst(jobs: Job[]): Job[] {
  return [...jobs].sort((a, b) => seenKey(b).localeCompare(seenKey(a)));
}

// How many of each period make a year (same as PER_YEAR in backend/salary.py).
const PER_YEAR: Record<SalaryPeriod, number> = { hour: 2080, day: 260, week: 52, month: 12, year: 1 };

/**
 * The listed amounts as yearly pay, so pay per hour, month, and year compare
 * fairly: $50/hr is 104,000, $3,000/mo 36,000. A job with no period gets the
 * assumed one, as it's shown. The search script saves a missing amount as 0,
 * so 0 and null both mean "not listed" (an empty list). Same as
 * `yearly_amounts` in backend/salary.py.
 */
export function yearlySalaries(job: SalaryFields): number[] {
  const amounts = [job.salary_low, job.salary_high].filter((value): value is number => value != null && value > 0);
  if (!amounts.length) return [];
  const period = job.salary_period ?? assumedPeriod(Math.max(...amounts), 0);
  return amounts.map((amount) => amount * PER_YEAR[period]);
}

/** Whether a job lists a salary (an amount above 0). */
export function hasSalary(job: SalaryFields): boolean {
  return yearlySalaries(job).length > 0;
}

/**
 * What "Salary (highest)" sorts by: the higher listed amount, per year, so
 * "From $140,000" counts as 140,000 and "$60/hr" as 124,800. Null when no
 * salary is listed.
 */
export function salarySortValue(job: SalaryFields): number | null {
  const amounts = yearlySalaries(job);
  return amounts.length ? Math.max(...amounts) : null;
}

/** What "Salary (lowest)" sorts by: the lower listed amount, per year. Null when no salary is listed. */
export function salaryLowestSortValue(job: SalaryFields): number | null {
  const amounts = yearlySalaries(job);
  return amounts.length ? Math.min(...amounts) : null;
}

/** Orders by `value` (1: lowest first, -1: highest first), "Not listed" (null) always last. */
function compareSalaries(value: (job: Job) => number | null, direction: 1 | -1) {
  return (a: Job, b: Job) => {
    const [salaryA, salaryB] = [value(a), value(b)];
    if (salaryA === null || salaryB === null) return (salaryA === null ? 1 : 0) - (salaryB === null ? 1 : 0);
    return direction * (salaryA - salaryB);
  };
}

const compareNumberDesc = (a: number | null, b: number | null) => (b ?? -1) - (a ?? -1);

/** How each sort key orders two jobs (negative: `a` first). Missing values always go last. */
const COMPARE: Record<SortKey, (a: Job, b: Job) => number> = {
  last_seen: (a, b) => seenKey(b).localeCompare(seenKey(a)),
  posted: (a, b) => (b.posted_date ?? "").localeCompare(a.posted_date ?? ""),
  // Highest first; "Not listed" always last.
  salary: compareSalaries(salarySortValue, -1),
  // Lowest first; "Not listed" still last.
  salary_lowest: compareSalaries(salaryLowestSortValue, 1),
  score: (a, b) => compareNumberDesc(a.score, b.score),
  fit: (a, b) => compareNumberDesc(a.fit_score, b.fit_score),
  title: (a, b) => (a.title ?? "\uffff").localeCompare(b.title ?? "\uffff"),
  status: (a, b) => statusOrder(a.status) - statusOrder(b.status),
};

/**
 * Sort by one key, or by several in order: each key orders the jobs the keys
 * before it tie on, so `["score", "salary"]` is most skill matches first, and
 * the highest salary first among jobs with the same number. Jobs that tie on
 * every key stay newest first. Same as `sort_jobs` in backend/job_queries.py.
 */
export function sortJobs(jobs: Job[], sort: SortKey | readonly SortKey[]): Job[] {
  const keys = typeof sort === "string" ? [sort] : sort;
  // Array sort is stable, so ties keep the newest-first order.
  return sortNewestFirst(jobs).sort((a, b) => {
    for (const key of keys) {
      const order = COMPARE[key](a, b);
      if (order !== 0) return order;
    }
    return 0;
  });
}

/**
 * What "Then by" offers after `primary`: every other sort, except "Last seen"
 * (ties already end newest first) and the other direction of a salary sort.
 */
export function thenByOptions(primary: SortKey): typeof SORT_OPTIONS {
  const salary: SortKey[] = ["salary", "salary_lowest"];
  return SORT_OPTIONS.filter(
    ({ value }) =>
      value !== primary && value !== "last_seen" && !(salary.includes(primary) && salary.includes(value)),
  );
}

function statusOrder(status: string): number {
  const index = (JOB_STATUSES as readonly string[]).indexOf(status);
  return index === -1 ? JOB_STATUSES.length : index;
}

// --- Filtering ------------------------------------------------------------------

export interface JobFilters {
  /** Case-insensitive match against title, company, skills, location, job type, notes, ID. */
  query: string;
  status: JobStatus | "all";
  /** Companies to show (any case); none selected shows every company. */
  companies: string[];
  remote: RemoteStatus | "all";
  track: string | "all";
  /** Matched skills to look for (any case); none selected shows every job. */
  skills: string[];
  /** "any": jobs with at least one of `skills`; "all": jobs with every one. */
  skillMatch: SkillMatch;
  /** Only jobs with a salary listed, or only "Not listed" ones. */
  salary: SalaryFilter;
}

export type SkillMatch = "any" | "all";

export type SalaryFilter = "all" | "listed" | "not_listed";

export const SALARY_FILTER_LABELS: Record<SalaryFilter, string> = {
  all: "Any",
  listed: "Listed",
  not_listed: "Not listed",
};

export const DEFAULT_FILTERS: JobFilters = {
  query: "",
  status: "all",
  companies: [],
  remote: "all",
  track: "all",
  skills: [],
  skillMatch: "any",
  salary: "all",
};

/** Whether ``value`` is one of ``options``, in any case. */
function isOneOf(value: string | null, options: string[]): boolean {
  const wanted = value?.toLowerCase();
  return wanted !== undefined && options.some((option) => option.toLowerCase() === wanted);
}

/** Whether a job's matched skills include the selected ones (any or all of them, in any case). */
export function hasSkills(job: Pick<Job, "matched_skills">, skills: string[], match: SkillMatch): boolean {
  if (skills.length === 0) return true;
  const have = new Set(job.matched_skills.map((skill) => skill.toLowerCase()));
  const wanted = skills.map((skill) => skill.toLowerCase());
  return match === "all" ? wanted.every((skill) => have.has(skill)) : wanted.some((skill) => have.has(skill));
}

export function filterJobs(jobs: Job[], filters: JobFilters): Job[] {
  const query = filters.query.trim().toLowerCase();
  return jobs.filter((job) => {
    if (filters.status !== "all" && job.status !== filters.status) return false;
    if (filters.companies.length > 0 && !isOneOf(job.company, filters.companies)) return false;
    if (filters.remote !== "all" && remoteStatus(job) !== filters.remote) return false;
    if (filters.track !== "all" && job.track !== filters.track) return false;
    if (!hasSkills(job, filters.skills, filters.skillMatch)) return false;
    if (filters.salary !== "all" && hasSalary(job) !== (filters.salary === "listed")) return false;
    if (!query) return true;
    const haystack = [
      job.title,
      job.company,
      job.city,
      job.state,
      job.job_type,
      job.notes,
      job.job_id,
      job.track,
      ...job.matched_skills,
    ]
      .filter((part): part is string => !!part)
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  });
}

/** How many jobs are in each status, for the summary chips. */
export function countByStatus(jobs: Job[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const job of jobs) counts[job.status] = (counts[job.status] ?? 0) + 1;
  return counts;
}

/**
 * The remote statuses your jobs actually have, in a fixed order, for the
 * remote filter. By default the search script only saves remote jobs, so
 * "Not remote" only shows up if remote-only was turned off for a site.
 */
export function distinctRemoteStatuses(jobs: Job[]): RemoteStatus[] {
  const present = new Set(jobs.map(remoteStatus));
  return (Object.keys(REMOTE_STATUS_INFO) as RemoteStatus[]).filter((status) => present.has(status));
}

/** One choice in a multi-select filter, with how many jobs have it. */
export interface FilterOption {
  value: string;
  count: number;
}

/** Each company once, alphabetically, with how many jobs it has, for the company filter. */
export function distinctCompanies(jobs: Job[]): FilterOption[] {
  const counts = new Map<string, number>();
  for (const job of jobs) if (job.company) counts.set(job.company, (counts.get(job.company) ?? 0) + 1);
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => a.value.localeCompare(b.value));
}

// One collator for every comparison: localeCompare with options builds a new
// one each call, about 100 times slower, and lists re-sort on every render.
const skillNameCollator = new Intl.Collator("en", { sensitivity: "base", numeric: true });

/** Skill names in alphabetical order: any case, numbers in order ("Java 8" before "Java 11"). */
export function compareSkillNames(a: string, b: string): number {
  return skillNameCollator.compare(a, b);
}

/**
 * Every skill your jobs matched, A–Z, with how many matched it, for the
 * skills filter. Spellings that differ only in case ("Python", "python",
 * saved before and after a change to your list) are one skill, shown the way
 * most jobs have it.
 */
export function distinctSkills(jobs: Job[]): FilterOption[] {
  const counts = new Map<string, { count: number; spellings: Map<string, number> }>();
  for (const job of jobs) {
    const seen = new Set<string>();
    for (const skill of job.matched_skills) {
      const key = skill.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      const entry = counts.get(key) ?? { count: 0, spellings: new Map<string, number>() };
      entry.count += 1;
      entry.spellings.set(skill, (entry.spellings.get(skill) ?? 0) + 1);
      counts.set(key, entry);
    }
  }
  return [...counts.values()]
    .map(({ count, spellings }) => ({
      value: [...spellings.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0][0],
      count,
    }))
    .sort((a, b) => compareSkillNames(a.value, b.value));
}

/** Distinct track names in first-seen order, for the track filter. */
export function distinctTracks(jobs: Job[]): string[] {
  const tracks: string[] = [];
  for (const job of jobs) {
    if (job.track && !tracks.includes(job.track)) tracks.push(job.track);
  }
  return tracks;
}
