import { describe, expect, it } from "vitest";
import { makeJob } from "@/test/factories";
import { DEFAULT_FILTERS } from "./jobs";
import { countJobs, filtersFromSearchParams, jobsHref, latestMatches, recentActivity } from "./overview";

const job = (id: string, overrides: Parameters<typeof makeJob>[0] = {}) => makeJob({ id, ...overrides });

describe("countJobs", () => {
  it("counts the headline statuses", () => {
    const jobs = [
      job("a", { status: "emailed" }),
      job("b", { status: "emailed" }),
      job("c", { status: "unemailed" }),
      job("d", { status: "applied" }),
      job("e", { status: "interviewing" }),
      job("f", { status: "offer" }),
      job("g", { status: "skipped" }),
      job("h", { status: "rejected" }),
    ];
    expect(countJobs(jobs)).toEqual({ total: 8, toReview: 2, unemailed: 1, applied: 1, interviewing: 1, offers: 1 });
  });

  it("is all zeros with no jobs", () => {
    expect(countJobs([])).toEqual({ total: 0, toReview: 0, unemailed: 0, applied: 0, interviewing: 0, offers: 0 });
  });
});

describe("latestMatches", () => {
  it("returns the most recently found jobs first, up to the limit", () => {
    const jobs = [
      job("old", { first_seen_at: "2026-10-01T13:00:00+00:00" }),
      job("newest", { first_seen_at: "2026-11-05T13:00:00+00:00" }),
      job("undated", { first_seen_at: null }),
      job("middle", { first_seen_at: "2026-10-20T13:00:00+00:00" }),
    ];
    expect(latestMatches(jobs).map((j) => j.id)).toEqual(["newest", "middle", "old"]);
    expect(latestMatches(jobs, 2).map((j) => j.id)).toEqual(["newest", "middle"]);
  });

  it("doesn't reorder the caller's array", () => {
    const jobs = [job("a", { first_seen_at: "2026-10-01" }), job("b", { first_seen_at: "2026-11-01" })];
    latestMatches(jobs);
    expect(jobs.map((j) => j.id)).toEqual(["a", "b"]);
  });
});

describe("recentActivity", () => {
  it("lists status changes you made, newest first", () => {
    const jobs = [
      job("applied", { status: "applied", status_updated_at: "2026-11-01T10:00:00+00:00" }),
      job("emailed", { status: "emailed", status_updated_at: "2026-11-06T10:00:00+00:00" }), // set by the script
      job("unemailed", { status: "unemailed", status_updated_at: "2026-11-06T11:00:00+00:00" }), // ditto
      job("offer", { status: "offer", status_updated_at: "2026-11-04T10:00:00+00:00" }),
      job("skipped", { status: "skipped", status_updated_at: "2026-11-02T10:00:00+00:00" }),
      job("undated", { status: "rejected", status_updated_at: null }),
    ];
    expect(recentActivity(jobs).map((j) => j.id)).toEqual(["offer", "skipped", "applied"]);
    expect(recentActivity(jobs, 1).map((j) => j.id)).toEqual(["offer"]);
  });
});

describe("jobsHref", () => {
  it("links to the tracker, optionally filtered", () => {
    expect(jobsHref()).toBe("/jobs");
    expect(jobsHref("applied")).toBe("/jobs?status=applied");
  });
});

describe("filtersFromSearchParams", () => {
  it("starts filtered to a known status", () => {
    expect(filtersFromSearchParams({ status: "interviewing" })).toEqual({ ...DEFAULT_FILTERS, status: "interviewing" });
    expect(filtersFromSearchParams({ status: ["offer", "applied"] })).toEqual({ ...DEFAULT_FILTERS, status: "offer" });
  });

  it("ignores missing or unknown values", () => {
    expect(filtersFromSearchParams({})).toEqual(DEFAULT_FILTERS);
    expect(filtersFromSearchParams({ status: "nope" })).toEqual(DEFAULT_FILTERS);
    expect(filtersFromSearchParams({ status: "" })).toEqual(DEFAULT_FILTERS);
  });
});
