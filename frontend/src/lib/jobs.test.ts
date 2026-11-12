import { describe, expect, it } from "vitest";
import { makeJob } from "@/test/factories";
import {
  DEFAULT_FILTERS,
  FIT_LABELS,
  countByStatus,
  distinctCompanies,
  distinctRemoteStatuses,
  distinctSkills,
  remoteStatus,
  distinctTracks,
  filterJobs,
  formatDate,
  formatLocation,
  formatSalary,
  formatYears,
  fitLabel,
  gmailMessageUrl,
  hasApplied,
  insightGlobalSearchUrl,
  jobLinks,
  normalizeJob,
  salarySortValue,
  sortJobs,
  sortNewestFirst,
  toIsoString,
  trackLabel,
  hasSkills,
  type JobFilters,
} from "./jobs";

describe("toIsoString", () => {
  it("passes ISO strings through untouched", () => {
    expect(toIsoString("2026-11-01T04:36:13.055143+00:00")).toBe("2026-11-01T04:36:13.055143+00:00");
  });

  it("converts Dates and Firestore Timestamps (anything with toDate)", () => {
    const date = new Date("2026-11-01T04:36:13.055Z");
    expect(toIsoString(date)).toBe("2026-11-01T04:36:13.055Z");
    expect(toIsoString({ toDate: () => date })).toBe("2026-11-01T04:36:13.055Z");
  });

  it("returns null for missing or unusable values", () => {
    expect(toIsoString(null)).toBeNull();
    expect(toIsoString(undefined)).toBeNull();
    expect(toIsoString(42)).toBeNull();
    expect(toIsoString(new Date("garbage"))).toBeNull();
  });
});

describe("normalizeJob", () => {
  it("maps a full document written by the Python store", () => {
    const job = normalizeJob("abc", {
      job_id: "abc",
      company: "Accenture",
      title: "React Developer",
      city: "Austin",
      state: "TX",
      is_remote: true,
      job_type: "Contract",
      salary_low: 55.0,
      salary_high: 65.0,
      url: "https://insightglobal.com/jobs/abc",
      track: "Core matches (your main stack)",
      posted_date: "2026-10-30",
      matched_skills: ["React", "TypeScript"],
      score: 2,
      min_years: 3,
      status: "emailed",
      first_seen_at: "2026-10-31T13:00:05+00:00",
      last_seen_at: "2026-10-31T13:00:05+00:00",
      emailed_at: "2026-10-31T13:00:05+00:00",
      gmail_message_id: "19a1",
    });
    expect(job).toMatchObject({
      id: "abc",
      job_id: "abc",
      company: "Accenture",
      title: "React Developer",
      salary_low: 55,
      matched_skills: ["React", "TypeScript"],
      score: 2,
      status: "emailed",
      applied_at: null,
      notes: null,
      gmail_message_id: "19a1",
    });
  });

  it("reads whether the job still matches your skills (null until it's been assessed)", () => {
    expect(
      normalizeJob("a", { matches_skills: false, skills_mismatch_reason: "it doesn't mention any of your skills" }),
    ).toMatchObject({ matches_skills: false, skills_mismatch_reason: "it doesn't mention any of your skills" });
    expect(normalizeJob("b", { matches_skills: true })).toMatchObject({ matches_skills: true, skills_mismatch_reason: null });
    expect(normalizeJob("c", {}).matches_skills).toBeNull();
    expect(normalizeJob("d", { matches_skills: "no" }).matches_skills).toBeNull();
  });

  it("leaves company null on documents saved before it existed", () => {
    expect(normalizeJob("old", { job_id: "old", title: "React Developer" }).company).toBeNull();
  });

  it("falls back to the document ID and 'unknown' status for junk documents", () => {
    const job = normalizeJob("x", { matched_skills: "not a list", salary_low: "abc", is_remote: "yes" });
    expect(job.job_id).toBe("x");
    expect(job.status).toBe("unknown");
    expect(job.matched_skills).toEqual([]);
    expect(job.salary_low).toBeNull();
    expect(job.is_remote).toBeNull();
  });

  it("reads the fit score, its breakdown, and its reasons", () => {
    const job = normalizeJob("x", {
      fit_score: 72,
      fit_breakdown: { skills: 48, role: 30, experience: -6, junk: "x" },
      fit_reasons: ["Skills: Python", 3],
    });
    expect(job.fit_score).toBe(72);
    expect(job.fit_breakdown).toEqual({ skills: 48, role: 30, experience: -6 });
    expect(job.fit_reasons).toEqual(["Skills: Python"]);
  });

  it("uses your work arrangement over the site's remote flag", () => {
    const onsite = normalizeJob("x", { is_remote: true, work_arrangement: "on_site" });
    expect([onsite.is_remote, onsite.site_is_remote, onsite.work_arrangement]).toEqual([false, true, "on_site"]);
    expect(remoteStatus(onsite)).toBe("not_remote");
    expect(normalizeJob("x", { is_remote: false, work_arrangement: "remote" }).is_remote).toBe(true);
    const ignored = normalizeJob("x", { is_remote: true, work_arrangement: "moon" });
    expect([ignored.is_remote, ignored.work_arrangement]).toEqual([true, null]);
  });

  it("reads why a job was marked not remote", () => {
    expect(normalizeJob("x", { not_remote_reason: 'title says "On-Site"' }).not_remote_reason).toBe('title says "On-Site"');
    expect(normalizeJob("x", {}).not_remote_reason).toBeNull();
  });

  it("leaves the fit score empty on jobs saved before it existed", () => {
    const job = normalizeJob("x", { title: "Old", fit_breakdown: ["not", "a", "record"] });
    expect(job.fit_score).toBeNull();
    expect(job.fit_breakdown).toEqual({});
    expect(job.fit_reasons).toEqual([]);
  });

  it("derives score from matched_skills when the field is missing", () => {
    expect(normalizeJob("x", { matched_skills: ["A", "B", "C"] }).score).toBe(3);
    expect(normalizeJob("x", { matched_skills: ["A"], score: 7 }).score).toBe(7);
  });
});

describe("classification helpers", () => {
  it("hasApplied is true for applied status or an applied_at timestamp", () => {
    expect(hasApplied(makeJob({ status: "applied" }))).toBe(true);
    expect(hasApplied(makeJob({ status: "interviewing", applied_at: "2026-11-01T00:00:00+00:00" }))).toBe(true);
    expect(hasApplied(makeJob({ status: "emailed" }))).toBe(false);
  });

  it("trackLabel shortens the track names used by the script", () => {
    expect(trackLabel("Core matches (your main stack)")).toBe("Core");
    expect(trackLabel("Java growth track (entry-level / lower bar)")).toBe("Java");
    expect(trackLabel("iOS growth track (entry-level / lower bar)")).toBe("iOS");
    expect(trackLabel(".NET growth track (entry-level / lower bar)")).toBe(".NET");
    expect(trackLabel("Rust track")).toBe("Rust");
    expect(trackLabel(null)).toBe("—");
  });
});

describe("links", () => {
  it("builds a Gmail deep link for the digest message", () => {
    expect(gmailMessageUrl("19a1b2c3")).toBe("https://mail.google.com/mail/u/0/#all/19a1b2c3");
    expect(gmailMessageUrl(null)).toBeNull();
  });

  it("builds an Insight Global search URL from the title", () => {
    expect(insightGlobalSearchUrl("React Developer")).toBe(
      "https://insightglobal.com/jobs/search/all/all?keyword=React%20Developer",
    );
    expect(insightGlobalSearchUrl(null)).toBeNull();
  });

  it("jobLinks lists posting, digest email, and search in order", () => {
    const links = jobLinks(makeJob());
    expect(links.map((link) => link.label)).toEqual(["Job posting", "Digest email", "Search Insight Global"]);
    expect(links[0].href).toBe("https://insightglobal.com/jobs/6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba");
  });

  it("jobLinks leaves out links a job has nothing for", () => {
    expect(jobLinks(makeJob({ url: null, gmail_message_id: null, title: null }))).toEqual([]);
  });
});

describe("formatting", () => {
  it("formatSalary matches the wording of the Python email", () => {
    expect(formatSalary({ salary_low: 100000, salary_high: 120000 })).toBe("$100,000 - $120,000");
    expect(formatSalary({ salary_low: 0, salary_high: 90 })).toBe("Up to $90");
    expect(formatSalary({ salary_low: 140000, salary_high: 0 })).toBe("From $140,000");
    expect(formatSalary({ salary_low: 0, salary_high: 0 })).toBe("Not listed");
    expect(formatSalary({ salary_low: null, salary_high: null })).toBe("Not listed");
  });

  it("formatLocation joins city and state", () => {
    expect(formatLocation({ city: "Austin", state: "TX" })).toBe("Austin, TX");
    expect(formatLocation({ city: "", state: "TX" })).toBe("TX");
    expect(formatLocation({ city: null, state: null })).toBe("—");
  });

  it("formatDate keeps the date part of a timestamp", () => {
    expect(formatDate("2026-10-31T13:00:05+00:00")).toBe("2026-10-31");
    expect(formatDate("2026-10-31")).toBe("2026-10-31");
    expect(formatDate(null)).toBe("—");
  });

  it("formatYears", () => {
    expect(formatYears(3)).toBe("3+ yrs");
    expect(formatYears(null)).toBe("not stated");
  });
});

describe("sorting", () => {
  const older = makeJob({ id: "old", last_seen_at: "2026-10-01T00:00:00+00:00", posted_date: "2026-10-20", salary_high: 200, score: 1, fit_score: 90, title: "Zed" });
  const newer = makeJob({ id: "new", last_seen_at: "2026-10-31T00:00:00+00:00", posted_date: "2026-10-01", salary_high: 50, score: 5, fit_score: 40, title: "Alpha" });
  const undated = makeJob({ id: "undated", last_seen_at: null, first_seen_at: null, posted_date: null, salary_high: null, salary_low: null, score: null, fit_score: null, title: null });

  it("sortNewestFirst orders by last_seen_at descending, undated last", () => {
    expect(sortNewestFirst([undated, older, newer]).map((job) => job.id)).toEqual(["new", "old", "undated"]);
  });

  it("does not mutate its input", () => {
    const input = [older, newer];
    sortNewestFirst(input);
    expect(input.map((job) => job.id)).toEqual(["old", "new"]);
  });

  it("sortJobs supports every sort key", () => {
    const jobs = [undated, older, newer];
    expect(sortJobs(jobs, "last_seen").map((j) => j.id)).toEqual(["new", "old", "undated"]);
    expect(sortJobs(jobs, "posted").map((j) => j.id)).toEqual(["old", "new", "undated"]);
    expect(sortJobs(jobs, "salary").map((j) => j.id)).toEqual(["old", "new", "undated"]);
    expect(sortJobs(jobs, "score").map((j) => j.id)).toEqual(["new", "old", "undated"]);
    expect(sortJobs(jobs, "fit").map((j) => j.id)).toEqual(["old", "new", "undated"]);
    expect(sortJobs(jobs, "title").map((j) => j.id)).toEqual(["new", "old", "undated"]);
  });

  it("sortJobs by salary puts every \"Not listed\" job last", () => {
    const job = (id: string, salary_low: number | null, salary_high: number | null, day: number) =>
      makeJob({ id, salary_low, salary_high, last_seen_at: `2026-11-0${day}T00:00:00+00:00` });
    const jobs = [
      job("range", 55, 65, 1),
      job("not-listed-zeros", 0, 0, 6), // how the search script saves a missing salary
      job("from-only", 140000, 0, 2),
      job("up-to", 0, 90, 3),
      job("not-listed-nulls", null, null, 5),
      job("not-listed-old", 0, 0, 4),
    ];
    expect(sortJobs(jobs, "salary").map((j) => j.id)).toEqual([
      "from-only", // "From $140,000" ranks by its only amount, not as 0
      "up-to",
      "range",
      "not-listed-zeros", // then every "Not listed", newest first
      "not-listed-nulls",
      "not-listed-old",
    ]);
    expect(sortJobs(jobs, "salary").map(formatSalary).slice(-3)).toEqual(["Not listed", "Not listed", "Not listed"]);
  });

  it("salarySortValue uses the higher listed amount; 0 and null mean not listed", () => {
    expect(salarySortValue({ salary_low: 100000, salary_high: 120000 })).toBe(120000);
    expect(salarySortValue({ salary_low: 140000, salary_high: 0 })).toBe(140000);
    expect(salarySortValue({ salary_low: 0, salary_high: 90 })).toBe(90);
    expect(salarySortValue({ salary_low: null, salary_high: 90 })).toBe(90);
    expect(salarySortValue({ salary_low: 0, salary_high: 0 })).toBeNull();
    expect(salarySortValue({ salary_low: null, salary_high: null })).toBeNull();
  });

  it("sortJobs by status follows the workflow order, unknown statuses last", () => {
    const jobs = [
      makeJob({ id: "a", status: "offer" }),
      makeJob({ id: "b", status: "weird" }),
      makeJob({ id: "c", status: "unemailed" }),
      makeJob({ id: "d", status: "applied" }),
    ];
    expect(sortJobs(jobs, "status").map((j) => j.id)).toEqual(["c", "d", "a", "b"]);
  });
});

describe("filtering", () => {
  const react = makeJob({ id: "r", title: "React Developer", city: "Austin", matched_skills: ["React"], notes: "call recruiter" });
  const python = makeJob({ id: "p", title: "Python Engineer", city: "Chicago", status: "applied", track: "Java growth track", matched_skills: ["Python"] });
  const jobs = [react, python];

  it("shows every job with the default filters", () => {
    expect(filterJobs(jobs, DEFAULT_FILTERS).map((j) => j.id)).toEqual(["r", "p"]);
  });

  it("filters by one or several companies, in any case", () => {
    const accenture = makeJob({ id: "a", title: "Java Developer", company: "Accenture" });
    const nvidia = makeJob({ id: "n", company: "NVIDIA" });
    const unknown = makeJob({ id: "u", company: null });
    const mixed = [react, python, accenture, nvidia, unknown];
    const ids = (companies: string[]) => filterJobs(mixed, { ...DEFAULT_FILTERS, companies }).map((j) => j.id);
    expect(ids([])).toEqual(["r", "p", "a", "n", "u"]);
    expect(ids(["Accenture"])).toEqual(["a"]);
    expect(ids(["Insight Global"])).toEqual(["r", "p"]);
    expect(ids(["accenture", "Nvidia"])).toEqual(["a", "n"]);
    expect(ids(["Nobody"])).toEqual([]);
    // Search matches the company name too.
    expect(filterJobs(mixed, { ...DEFAULT_FILTERS, query: "accent" }).map((j) => j.id)).toEqual(["a"]);
  });

  it("filters by remote status, with null meaning the site didn't say", () => {
    const unmarked = makeJob({ id: "u", is_remote: null });
    const onsite = makeJob({ id: "o", is_remote: false });
    const mixed = [react, unmarked, onsite];
    expect(remoteStatus(react)).toBe("remote");
    expect(remoteStatus(unmarked)).toBe("unmarked");
    expect(remoteStatus(onsite)).toBe("not_remote");
    expect(filterJobs(mixed, { ...DEFAULT_FILTERS, remote: "remote" }).map((j) => j.id)).toEqual(["r"]);
    expect(filterJobs(mixed, { ...DEFAULT_FILTERS, remote: "unmarked" }).map((j) => j.id)).toEqual(["u"]);
    expect(filterJobs(mixed, { ...DEFAULT_FILTERS, remote: "not_remote" }).map((j) => j.id)).toEqual(["o"]);
    expect(filterJobs(mixed, DEFAULT_FILTERS)).toHaveLength(3);
  });

  it("distinctRemoteStatuses lists only the statuses present, in a fixed order", () => {
    expect(distinctRemoteStatuses([])).toEqual([]);
    expect(distinctRemoteStatuses([react, python])).toEqual(["remote"]);
    expect(
      distinctRemoteStatuses([makeJob({ is_remote: false }), makeJob({ is_remote: null }), react]),
    ).toEqual(["remote", "unmarked", "not_remote"]);
  });

  it("distinctCompanies lists each company once, alphabetically, with its job count, skipping unknowns", () => {
    const companies = distinctCompanies([
      makeJob({ company: "Insight Global" }),
      makeJob({ company: "Accenture" }),
      makeJob({ company: "Insight Global" }),
      makeJob({ company: null }),
    ]);
    expect(companies).toEqual([
      { value: "Accenture", count: 1 },
      { value: "Insight Global", count: 2 },
    ]);
  });

  it("filters by status and track", () => {
    expect(filterJobs(jobs, { ...DEFAULT_FILTERS, status: "applied" }).map((j) => j.id)).toEqual(["p"]);
    expect(filterJobs(jobs, { ...DEFAULT_FILTERS, track: "Java growth track" }).map((j) => j.id)).toEqual(["p"]);
  });

  it("searches title, skills, location, notes, and job ID case-insensitively", () => {
    const search = (query: string) => filterJobs(jobs, { ...DEFAULT_FILTERS, query }).map((j) => j.id);
    expect(search("react")).toEqual(["r"]);
    expect(search("CHICAGO")).toEqual(["p"]);
    expect(search("recruiter")).toEqual(["r"]);
    expect(search("  python ")).toEqual(["p"]);
    expect(search("nothing-here")).toEqual([]);
  });

  it("countByStatus and distinctTracks summarise the list", () => {
    expect(countByStatus(jobs)).toEqual({ emailed: 1, applied: 1 });
    expect(distinctTracks(jobs)).toEqual(["Core matches (your main stack)", "Java growth track"]);
  });
});

describe("fit score", () => {
  it("fitLabel uses the same bands as backend/job_fit.py", () => {
    expect([100, 75, 74, 60, 59, 40, 39, 0].map(fitLabel)).toEqual([
      "Strong", "Strong", "Good", "Good", "Fair", "Fair", "Weak", "Weak",
    ]);
    expect(fitLabel(null)).toBeNull();
    expect(FIT_LABELS.map((band) => band.min)).toEqual([75, 60, 40, 0]);
  });
});

describe("the skills filter", () => {
  const jobs = [
    makeJob({ id: "both", matched_skills: ["Python", "React"] }),
    makeJob({ id: "python", matched_skills: ["python", "SQL"] }), // saved before a change of case
    makeJob({ id: "react", matched_skills: ["React"] }),
    makeJob({ id: "none", matched_skills: [] }),
  ];
  const ids = (filters: Partial<JobFilters>) => filterJobs(jobs, { ...DEFAULT_FILTERS, ...filters }).map((job) => job.id);

  it("shows every job when no skill is picked", () => {
    expect(ids({ skills: [] })).toEqual(["both", "python", "react", "none"]);
    expect(ids({ skills: [], skillMatch: "all" })).toEqual(["both", "python", "react", "none"]);
  });

  it("keeps jobs with any of the picked skills, in any case", () => {
    expect(ids({ skills: ["Python"] })).toEqual(["both", "python"]);
    expect(ids({ skills: ["PYTHON", "react"] })).toEqual(["both", "python", "react"]);
  });

  it("or only jobs with all of them", () => {
    expect(ids({ skills: ["Python", "React"], skillMatch: "all" })).toEqual(["both"]);
    expect(ids({ skills: ["Python", "Go"], skillMatch: "all" })).toEqual([]);
  });

  it("combines with the other filters", () => {
    expect(ids({ skills: ["React"], query: "both" })).toEqual(["both"]);
  });

  it("hasSkills works on its own", () => {
    expect(hasSkills({ matched_skills: ["Go"] }, [], "all")).toBe(true);
    expect(hasSkills({ matched_skills: ["Go"] }, ["go", "Rust"], "any")).toBe(true);
    expect(hasSkills({ matched_skills: ["Go"] }, ["go", "Rust"], "all")).toBe(false);
  });

  it("lists each skill once, A–Z, with how many jobs have it", () => {
    expect(distinctSkills([...jobs, makeJob({ id: "more", matched_skills: ["Python", "Python", "AWS"] })])).toEqual([
      { value: "AWS", count: 1 },
      { value: "Python", count: 3 }, // "python" is the same skill; most jobs spell it "Python"
      { value: "React", count: 2 },
      { value: "SQL", count: 1 },
    ]);
    expect(distinctSkills([])).toEqual([]);
  });

  it("sorts skills A–Z in any case, numbers in order", () => {
    const skillJobs = [makeJob({ id: "a", matched_skills: ["kubernetes", "Java 11", "Backstage", "Java 8", ".NET"] })];
    expect(distinctSkills(skillJobs).map((option) => option.value)).toEqual([
      ".NET", "Backstage", "Java 8", "Java 11", "kubernetes",
    ]);
  });
});
