import { describe, expect, it } from "vitest";
import { ApiError } from "./client";
import { describeReassess, reassessProblem } from "./reassess";
import type { ReassessSummary } from "./types";

const summary = (overrides: Partial<ReassessSummary> = {}): ReassessSummary => ({
  total_jobs: 10,
  reassessed: 10,
  changed: 0,
  no_longer_match: 0,
  fetched: 0,
  unavailable: 0,
  skills_source: "saved",
  ...overrides,
});

describe("describeReassess", () => {
  it("says nothing changed", () => {
    expect(describeReassess(summary())).toEqual({
      tone: "info",
      title: "Reassessed 10 jobs against your skills",
      details: ["Nothing changed."],
    });
  });

  it("counts changes, jobs that no longer match, loads, and jobs left alone", () => {
    expect(
      describeReassess(summary({ reassessed: 9, changed: 1, no_longer_match: 2, fetched: 1, unavailable: 1, skills_source: "default" })),
    ).toEqual({
      tone: "info",
      title: "Reassessed 9 jobs against the default skills",
      details: [
        "1 job changed; 2 no longer match (marked in the list).",
        "Loaded 1 job description from the job sites; they're kept, so next time is quicker.",
        "1 job couldn't be reassessed because the posting couldn't be loaded (closed?). It keeps its old score.",
      ],
    });
    expect(describeReassess(summary({ changed: 3, no_longer_match: 1 })).details[0]).toBe(
      "3 jobs changed; 1 no longer matches (marked in the list).",
    );
    expect(describeReassess(summary({ reassessed: 8, unavailable: 2 })).details.at(-1)).toMatch(/They keep their old score/);
  });

  it("handles an empty tracker", () => {
    expect(describeReassess(summary({ total_jobs: 0, reassessed: 0 }))).toEqual({
      tone: "info",
      title: "No saved jobs to reassess",
      details: [],
    });
  });
});

describe("reassessProblem", () => {
  it("explains that the search API is needed", () => {
    expect(reassessProblem(new ApiError("The search API isn't reachable at http://x. Start it with ...", 503))).toEqual({
      tone: "warning",
      title: "Jobs reloaded, but not reassessed against your skills",
      details: ["Re-scoring needs the search API. The search API isn't reachable at http://x. Start it with ..."],
    });
  });

  it("says what did happen on the Skills page: the save", () => {
    expect(reassessProblem(new ApiError("The search API isn't reachable at http://x.", 503), "save")).toEqual({
      tone: "warning",
      title: "Skills saved, but your saved jobs weren't re-scored",
      details: [
        "Re-scoring needs the search API. The search API isn't reachable at http://x. Once it's running, click Refresh on the Jobs page.",
      ],
    });
    expect(reassessProblem(new ApiError("A search is already running.", 409), "save").title).toBe("Skills saved");
  });

  it("passes on why it's busy (a search is running)", () => {
    const busy = "A search is already running (run abc). It reassesses saved jobs when it finishes.";
    expect(reassessProblem(new ApiError(busy, 409))).toEqual({ tone: "info", title: "Jobs reloaded", details: [busy] });
  });

  it("reports anything else as is", () => {
    expect(reassessProblem(new Error("boom"))).toMatchObject({ tone: "warning", details: ["boom"] });
  });
});
