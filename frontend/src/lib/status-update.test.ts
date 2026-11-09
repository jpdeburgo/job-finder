import { describe, expect, it } from "vitest";
import { InvalidPatchError, MAX_NOTES_LENGTH, buildUpdateFields, parseJobPatch } from "./status-update";

describe("parseJobPatch", () => {
  it("accepts a valid status", () => {
    expect(parseJobPatch({ status: "applied" })).toEqual({ status: "applied" });
  });

  it("accepts notes alone and trims them", () => {
    expect(parseJobPatch({ notes: "  Applied via IG site  " })).toEqual({ notes: "Applied via IG site" });
  });

  it("treats null notes as clearing them", () => {
    expect(parseJobPatch({ notes: null })).toEqual({ notes: "" });
  });

  it("accepts status and notes together", () => {
    expect(parseJobPatch({ status: "skipped", notes: "no" })).toEqual({ status: "skipped", notes: "no" });
  });

  it("ignores unknown keys", () => {
    expect(parseJobPatch({ status: "offer", title: "hacked" })).toEqual({ status: "offer" });
  });

  it.each([
    [null, "Request body must be a JSON object"],
    ["applied", "Request body must be a JSON object"],
    [[], "Request body must be a JSON object"],
    [{}, "Nothing to update"],
    [{ status: "bogus" }, "Unknown status \"bogus\"; expected one of unemailed, emailed, applied"],
    [{ status: 3 }, "Unknown status 3"],
    [{ notes: 42 }, "notes must be a string"],
    [{ notes: "x".repeat(MAX_NOTES_LENGTH + 1) }, `at most ${MAX_NOTES_LENGTH} characters`],
  ])("rejects %j", (body, message) => {
    expect(() => parseJobPatch(body)).toThrow(InvalidPatchError);
    expect(() => parseJobPatch(body)).toThrow(message);
  });
});

describe("buildUpdateFields", () => {
  const now = new Date("2026-11-01T09:30:00.000Z");

  it("writes status and status_updated_at, like jobs_cli.py", () => {
    expect(buildUpdateFields({ status: "skipped" }, now)).toEqual({
      status: "skipped",
      status_updated_at: now,
    });
  });

  it("also stamps applied_at when the status becomes applied", () => {
    expect(buildUpdateFields({ status: "applied" }, now)).toEqual({
      status: "applied",
      status_updated_at: now,
      applied_at: now,
    });
  });

  it("writes notes without touching status fields", () => {
    expect(buildUpdateFields({ notes: "hello" }, now)).toEqual({ notes: "hello" });
  });

  it("combines both", () => {
    expect(buildUpdateFields({ status: "interviewing", notes: "Tue 10am" }, now)).toEqual({
      status: "interviewing",
      status_updated_at: now,
      notes: "Tue 10am",
    });
  });
});

describe("work arrangement", () => {
  it("accepts on_site, hybrid, remote, or null (back to the site's word)", () => {
    expect(parseJobPatch({ work_arrangement: "on_site" })).toEqual({ work_arrangement: "on_site" });
    expect(parseJobPatch({ work_arrangement: null })).toEqual({ work_arrangement: null });
    expect(() => parseJobPatch({ work_arrangement: "moon" })).toThrow(InvalidPatchError);
    expect(() => parseJobPatch({})).toThrow("Nothing to update: provide status, notes, and/or work_arrangement");
  });

  it("writes it next to the site's is_remote, and clears it with null", () => {
    const now = new Date("2026-11-08T12:00:00Z");
    expect(buildUpdateFields({ work_arrangement: "hybrid" }, now)).toEqual({
      work_arrangement: "hybrid",
      work_arrangement_set_at: now,
    });
    expect(buildUpdateFields({ work_arrangement: null }, now)).toEqual({
      work_arrangement: null,
      work_arrangement_set_at: null,
    });
  });
});
