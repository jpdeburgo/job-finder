import { describe, expect, it } from "vitest";
import { makeSummary } from "@/test/factories";
import { describeSites, describeSummary, formatRunTime } from "./runs";

describe("describeSummary", () => {
  it("counts matches and what was emailed", () => {
    expect(describeSummary(makeSummary({ total_matches: 12, new_matches: 3, emailed_matches: 3 }))).toBe(
      "12 matches, 3 new. Emailed 3 jobs.",
    );
    expect(describeSummary(makeSummary({ total_matches: 1, new_matches: 1, emailed_matches: 1 }))).toBe(
      "1 match, 1 new. Emailed 1 job.",
    );
  });

  it("counts retried jobs from an earlier failed email", () => {
    expect(describeSummary(makeSummary({ total_matches: 5, new_matches: 0, emailed_matches: 2 }))).toBe(
      "5 matches, 0 new. Emailed 2 jobs.",
    );
  });

  it("says when there was nothing to email", () => {
    const summary = makeSummary({ total_matches: 5, new_matches: 0, emailed_matches: 0, email_sent: false, gmail_message_id: null });
    expect(describeSummary(summary)).toBe("5 matches, 0 new. Nothing new to email.");
    expect(describeSummary({ ...summary, total_matches: 0 })).toBe("No matching jobs found.");
  });

  it("says why email was skipped", () => {
    const summary = makeSummary({
      new_matches: 2,
      emailed_matches: 0,
      email_sent: false,
      gmail_message_id: null,
      email_skipped_reason: "IG_EMAIL_TO is not set.",
    });
    expect(describeSummary(summary)).toBe("4 matches, 2 new. Not emailed: IG_EMAIL_TO is not set.");
  });
});

describe("formatRunTime", () => {
  it("formats a timestamp as a clock time", () => {
    expect(formatRunTime("2026-11-06T14:05:09+00:00", "UTC")).toBe("2:05 PM");
    expect(formatRunTime("2026-11-06T14:05:09+00:00", "America/New_York")).toBe("9:05 AM");
  });

  it("handles missing or unparseable values", () => {
    expect(formatRunTime(null)).toBe("");
    expect(formatRunTime("soon")).toBe("soon");
  });
});

describe("describeSites", () => {
  it("lists the chosen sites, or every site", () => {
    expect(describeSites({ sites: [] })).toBe("every site");
    expect(describeSites({ sites: ["accenture", "workday"] })).toBe("accenture, workday");
  });
});
