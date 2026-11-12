import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  describeReader,
  describeYearsBasis,
  formatMonth,
  canApply,
  formatYears,
  listedAs,
  ratingChange,
  resumeFromDocument,
  withDetectedSkills,
  type DetectedSkill,
} from "./resume";
import { DEFAULT_PROFICIENCY, MAX_SKILLS, type SearchSkills } from "./skills";

/** settings/resume exactly as backend/resume.py writes it (backend/tests/test_resume.py keeps it current). */
const FIXTURE = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "test", "fixtures", "resume.json"), "utf-8"),
) as Record<string, unknown>;

const list: SearchSkills = {
  skills: ["Python", "ReactJS", "SQL"],
  core_skills: ["Python", "ReactJS"],
  proficiency: { Python: 5, ReactJS: 4, SQL: 2 },
};

function skill(overrides: Partial<DetectedSkill> = {}): DetectedSkill {
  return {
    name: "React",
    category: "Frontend",
    years: 2,
    mentions: 3,
    last_used: "present",
    aliases: ["ReactJS", "React.js"],
    level: 4,
    level_reason: "2 years across 1 job; still using it",
    ...overrides,
  };
}

describe("resumeFromDocument", () => {
  it("reads what the Python store writes, both readings", () => {
    const resume = resumeFromDocument(FIXTURE);
    expect(resume).not.toBeNull();
    if (!resume) return;
    expect(resume).toMatchObject({ filename: "jane-doe.pdf", file_type: "pdf", uploaded_at: "2026-11-11T09:30:00+00:00" });
    expect(resume.text).toContain("Senior Software Engineer");

    const parsed = resume.analyses.parse!;
    expect(parsed).toMatchObject({ method: "parse", years_experience: 10.5, years_basis: "positions", stated_years: 8, provider: null });
    expect(parsed.positions[0]).toEqual({
      title: "Senior Software Engineer · Acme Corp · Austin, TX",
      company: "",
      start: "2021-01",
      end: null,
      months: 71,
      skills: expect.arrayContaining(["Python", "React"]),
    });
    expect(parsed.skills.find((s) => s.name === "Go")).toMatchObject({
      years: null,
      last_used: null,
      mentions: 1,
      level: 2,
      level_reason: "Listed, but no job on the resume mentions using it",
    });
    expect(parsed.skills.find((s) => s.name === "JavaScript")?.level_reason).toMatch(/through TypeScript, React/);

    const ai = resume.analyses.ai!;
    expect(ai).toMatchObject({ method: "ai", provider: "anthropic", model: "claude-test", years_experience: 8.8 });
    expect(ai.positions.map((p) => p.company)).toEqual(["Acme Corp", "Beta LLC"]);
    // Named by the AI but not in the text: 0 mentions, and the AI's category.
    expect(ai.skills.find((s) => s.name === "Code review")).toMatchObject({ mentions: 0, category: "Practice" });
    // Rated by the AI itself.
    expect(ai.skills.find((s) => s.name === "Python")).toMatchObject({ level: 5, level_reason: "6 years; led the API work" });
  });

  it("is null without a resume", () => {
    expect(resumeFromDocument(null)).toBeNull();
    expect(resumeFromDocument({ filename: "x.pdf" })).toBeNull();
    expect(resumeFromDocument("nope")).toBeNull();
  });

  it("leaves out what it can't trust (a document edited by hand)", () => {
    const resume = resumeFromDocument({
      text: "Python",
      uploaded_at: { toDate: () => new Date("2026-11-11T09:30:00Z") }, // a Firestore Timestamp
      analyses: {
        parse: {
          years_experience: "ten",
          years_basis: "vibes",
          skills: [{ name: "Python", years: 2, mentions: 1, level: 9 }, { name: "  " }, "SQL", { years: 3 }],
          positions: [{ title: "No dates" }, { title: "Dev", start: "2020-01", end: null, months: 12, skills: ["Python", 7] }],
          notes: ["ok", 3],
        },
        ai: "broken",
        guess: {},
      },
    });
    expect(resume).toMatchObject({ filename: "Resume", file_type: "", uploaded_at: "2026-11-11T09:30:00.000Z" });
    expect(Object.keys(resume!.analyses)).toEqual(["parse"]);
    const parsed = resume!.analyses.parse!;
    expect(parsed).toMatchObject({ years_experience: null, years_basis: null, notes: ["ok"] });
    // A level outside 1-5 (or missing, on readings saved before levels) is null.
    expect(parsed.skills).toEqual([
      { name: "Python", category: "Other", years: 2, mentions: 1, last_used: null, aliases: [], level: null, level_reason: "" },
    ]);
    expect(parsed.positions).toEqual([{ title: "Dev", company: "", start: "2020-01", end: null, months: 12, skills: ["Python"] }]);
  });
});

describe("formatting", () => {
  it.each([
    [null, "Unknown"],
    [0, "0 years"],
    [0.05, "1 month"],
    [0.5, "6 months"],
    [1, "1 year"],
    [6.46, "6.5 years"],
    [10, "10 years"],
  ])("formatYears(%s) is %s", (years, text) => {
    expect(formatYears(years)).toBe(text);
  });

  it("formats months", () => {
    expect(formatMonth("2021-03")).toBe("Mar 2021");
    expect(formatMonth(null)).toBe("Present");
    expect(formatMonth("present")).toBe("Present");
    expect(formatMonth("2021-13")).toBe("2021-13");
  });

  it("says who read it and where the years came from", () => {
    const resume = resumeFromDocument(FIXTURE)!;
    expect(describeReader(resume.analyses.parse!)).toBe("Parsed with rules (no AI)");
    expect(describeReader(resume.analyses.ai!)).toBe("Read by Claude (claude-test)");
    expect(describeReader({ ...resume.analyses.ai!, provider: "openai", model: null })).toBe("Read by OpenAI");
    expect(describeYearsBasis(resume.analyses.parse!)).toBe("Added up from the dates of 4 jobs, overlaps counted once");
    expect(describeYearsBasis({ ...resume.analyses.parse!, years_basis: "stated" })).toMatch(/As the resume states/);
    expect(describeYearsBasis({ ...resume.analyses.parse!, years_basis: null })).toMatch(/No job dates/);
  });
});

describe("your skill list", () => {
  it("knows a skill on your list by any of its spellings", () => {
    expect(listedAs(skill(), list)).toBe("ReactJS");
    expect(listedAs(skill({ name: "python", aliases: [] }), list)).toBe("Python");
    expect(listedAs(skill({ name: "Go", aliases: ["Golang"] }), list)).toBeNull();
  });

  it("knows when the resume would change your stars", () => {
    // ReactJS is 4 stars on the list.
    expect(ratingChange(skill({ level: 5 }), list)).toEqual({ name: "ReactJS", from: 4, to: 5 });
    expect(ratingChange(skill({ level: 4 }), list)).toBeNull();
    expect(ratingChange(skill({ level: null }), list)).toBeNull();
    expect(ratingChange(skill({ name: "Go", aliases: [] }), list)).toBeNull(); // not on the list
    expect(canApply(skill({ level: 4 }), list)).toBe(false);
    expect(canApply(skill({ level: 2 }), list)).toBe(true);
    expect(canApply(skill({ name: "Go", aliases: [] }), list)).toBe(true);
  });

  it("adds new skills as core skills at the stars the resume suggests", () => {
    const result = withDetectedSkills(list, [
      skill({ name: "Go", aliases: ["Golang"], level: 2 }),
      skill({ name: "Kubernetes", aliases: ["K8s"], level: 5 }),
      skill({ name: "Legacy", aliases: [], level: null }), // an old reading without levels
      skill({ name: "C/C++, embedded", aliases: [], level: 1 }), // a comma doesn't split a name
      skill({ name: "sql", aliases: [], level: 2 }), // on the list as SQL: a rating change, not a new skill
    ]);
    expect(result.added).toEqual(["Go", "Kubernetes", "Legacy", "C/C++, embedded"]);
    expect(result.updated).toEqual([]); // SQL is already 2 stars: nothing to change
    expect(result.list).toEqual({
      skills: ["Python", "ReactJS", "SQL", "Go", "Kubernetes", "Legacy", "C/C++, embedded"],
      // SQL was already an other skill and stays one; only new skills are made core.
      core_skills: ["Python", "ReactJS", "Go", "Kubernetes", "Legacy", "C/C++, embedded"],
      proficiency: { Python: 5, ReactJS: 4, SQL: 2, Go: 2, Kubernetes: 5, Legacy: DEFAULT_PROFICIENCY, "C/C++, embedded": 1 },
    });
    expect(result.problem).toBeNull();
  });

  it("updates the stars of skills already on your list, leaving them core or other", () => {
    const result = withDetectedSkills(list, [skill({ level: 5 }), skill({ name: "SQL", aliases: [], level: 3 })]);
    expect(result.added).toEqual([]);
    expect(result.updated).toEqual([
      { name: "ReactJS", from: 4, to: 5 },
      { name: "SQL", from: 2, to: 3 },
    ]);
    expect(result.list).toEqual({ ...list, proficiency: { Python: 5, ReactJS: 5, SQL: 3 } });
  });

  it("stops adding at the skill limit and says so, but still updates stars", () => {
    const full = {
      skills: ["Python", ...Array.from({ length: MAX_SKILLS - 2 }, (_, i) => `S${i}`)],
      core_skills: ["Python"],
      proficiency: { Python: 3 },
    };
    const result = withDetectedSkills(full, [
      skill({ name: "Go", aliases: [], level: 2 }),
      skill({ name: "Rust", aliases: [], level: 2 }),
      skill({ name: "x".repeat(61), aliases: [], level: 2 }),
      skill({ name: "Python", aliases: [], level: 5 }),
    ]);
    expect(result.added).toEqual(["Go"]);
    expect(result.updated).toEqual([{ name: "Python", from: 3, to: 5 }]);
    expect(result.problem).toMatch(/at most 100 skills, so the rest weren't added/);
  });
});
