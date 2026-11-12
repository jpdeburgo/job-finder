import { describe, expect, it } from "vitest";
import {
  DEFAULT_SEARCH_SKILLS,
  InvalidSkillsError,
  MAX_SKILLS,
  PROFICIENCY_LABELS,
  addSkills,
  cleanSkills,
  parseSkillsBody,
  removeSkill,
  sameSkills,
  setCore,
  setProficiency,
  skillSettingsFromDocument,
  skillsProblem,
  sortSkillNames,
  splitSkillInput,
} from "./skills";

/** A list with every skill at the default 3 stars, unless `stars` says otherwise. */
const list = (skills: string[], core_skills: string[], stars: Record<string, number> = {}) => ({
  skills,
  core_skills,
  proficiency: Object.fromEntries(skills.map((name) => [name, stars[name] ?? 3])),
});

describe("cleanSkills", () => {
  it("trims, collapses spaces, and drops blanks and repeats in any case (first spelling wins)", () => {
    expect(cleanSkills(["  Python ", "REST   API", "", "python", "Go"], ["PYTHON"])).toEqual(
      list(["Python", "REST API", "Go"], ["Python"]),
    );
  });

  it("keeps core skills in the list's order and spelling", () => {
    expect(cleanSkills(["Python", "Go", "SQL"], ["go", "Python", "Go"])).toEqual(list(["Python", "Go", "SQL"], ["Python", "Go"]));
  });

  it.each([
    [[], ["Python"], "Add at least one skill"],
    [["  "], [], "Add at least one skill"],
    [["Python", "SQL"], [], "Mark at least one skill as core"],
    [["Python"], ["Go"], 'Core skill "Go" is not in the skill list'],
    [["x".repeat(61)], [], "too long"],
    [Array.from({ length: MAX_SKILLS + 1 }, (_, i) => `Skill ${i}`), ["Skill 0"], `At most ${MAX_SKILLS} skills`],
    [[42], [], "Skills must be text"],
  ])("rejects %j / %j", (skills, core, message) => {
    expect(() => cleanSkills(skills, core)).toThrow(InvalidSkillsError);
    expect(() => cleanSkills(skills, core)).toThrow(message);
  });

  it("accepts the defaults as they are", () => {
    expect(cleanSkills(DEFAULT_SEARCH_SKILLS.skills, DEFAULT_SEARCH_SKILLS.core_skills)).toEqual(DEFAULT_SEARCH_SKILLS);
  });
});

describe("proficiency", () => {
  it("fills in 3 stars for skills you haven't rated, and takes the list's spelling", () => {
    expect(cleanSkills(["Python", "SQL", "Go"], ["Python"], { python: 5, SQL: 1 })).toEqual(
      list(["Python", "SQL", "Go"], ["Python"], { Python: 5, SQL: 1 }),
    );
    // Lists saved before ratings existed read exactly as before.
    expect(parseSkillsBody({ skills: ["Go"], core_skills: ["Go"] }).proficiency).toEqual({ Go: 3 });
  });

  it.each([
    [{ Rust: 4 }, 'Proficiency is given for "Rust", which is not in the skill list'],
    [{ Go: 0 }, 'Proficiency for "Go" must be 1 to 5 stars, not 0'],
    [{ Go: 6 }, 'Proficiency for "Go" must be 1 to 5 stars, not 6'],
    [{ Go: 2.5 }, "must be a whole number of stars"],
    [{ Go: "5" }, "must be a whole number of stars"],
    [{ Go: true }, "must be a whole number of stars"],
  ])("rejects %j", (proficiency, message) => {
    expect(() => cleanSkills(["Go"], ["Go"], proficiency)).toThrow(message);
  });

  it("labels every level", () => {
    expect([1, 2, 3, 4, 5].map((stars) => PROFICIENCY_LABELS[stars])).toEqual([
      "Beginner",
      "Familiar",
      "Proficient",
      "Advanced",
      "Expert",
    ]);
  });

  it("gives the defaults 3 stars each", () => {
    expect(Object.values(DEFAULT_SEARCH_SKILLS.proficiency)).toEqual(DEFAULT_SEARCH_SKILLS.skills.map(() => 3));
  });
});

describe("parseSkillsBody", () => {
  it("needs an object with two lists", () => {
    expect(() => parseSkillsBody(null)).toThrow("Request body must be a JSON object");
    expect(() => parseSkillsBody(["Python"])).toThrow("Request body must be a JSON object");
    expect(() => parseSkillsBody({ skills: "Python", core_skills: [] })).toThrow("must both be lists");
    expect(parseSkillsBody({ skills: ["Go"], core_skills: ["Go"], extra: 1 })).toEqual(list(["Go"], ["Go"]));
    expect(() => parseSkillsBody({ skills: ["Go"], core_skills: ["Go"], proficiency: [5] })).toThrow(
      "proficiency must map skills to stars",
    );
  });
});

describe("skillSettingsFromDocument", () => {
  it("reads saved stars", () => {
    expect(skillSettingsFromDocument({ skills: ["Go", "SQL"], core_skills: ["Go"], proficiency: { Go: 5 } }).proficiency).toEqual({
      Go: 5,
      SQL: 3,
    });
  });

  it("uses the defaults when nothing is saved", () => {
    expect(skillSettingsFromDocument(null)).toEqual({
      ...DEFAULT_SEARCH_SKILLS,
      source: "default",
      updated_at: null,
      defaults: DEFAULT_SEARCH_SKILLS,
    });
  });

  it("reads a saved list, with a Firestore Timestamp or an ISO string", () => {
    const timestamp = { toDate: () => new Date("2026-11-08T22:00:00Z") };
    expect(skillSettingsFromDocument({ skills: ["Go", "SQL"], core_skills: ["Go"], updated_at: timestamp })).toMatchObject({
      skills: ["Go", "SQL"],
      core_skills: ["Go"],
      source: "saved",
      updated_at: "2026-11-08T22:00:00.000Z",
    });
    expect(
      skillSettingsFromDocument({ skills: ["Go"], core_skills: ["Go"], updated_at: "2026-11-08T22:00:00+00:00" }).updated_at,
    ).toBe("2026-11-08T22:00:00+00:00");
  });

  it("ignores a document that can't be used, like the search does", () => {
    expect(skillSettingsFromDocument({ skills: ["Go"], core_skills: [] }).source).toBe("default");
    expect(skillSettingsFromDocument({ skills: "Go" }).source).toBe("default");
  });

  it("hands out copies of the defaults", () => {
    const settings = skillSettingsFromDocument(null);
    settings.skills.push("Mutated");
    expect(DEFAULT_SEARCH_SKILLS.skills).not.toContain("Mutated");
  });
});

describe("editing a list", () => {
  const start = list(["Python", "SQL", "AWS"], ["Python"]);

  it("splits what's typed on commas, semicolons, and new lines", () => {
    expect(splitSkillInput(" Go,  Kotlin ;Rust\n\n , ")).toEqual(["Go", "Kotlin", "Rust"]);
  });

  it("rates a skill, keeping it within 1-5 stars", () => {
    expect(setProficiency(start, "SQL", 5)).toEqual(list(["Python", "SQL", "AWS"], ["Python"], { SQL: 5 }));
    expect(setProficiency(start, "SQL", 9).proficiency.SQL).toBe(5);
    expect(setProficiency(start, "SQL", 0).proficiency.SQL).toBe(1);
  });

  it("keeps ratings when skills move or others are removed, and drops a removed skill's", () => {
    const rated = setProficiency(start, "AWS", 1);
    expect(setCore(rated, "AWS", true).proficiency.AWS).toBe(1);
    expect(removeSkill(rated, "SQL").proficiency).toEqual({ Python: 3, AWS: 1 });
    expect(removeSkill(rated, "AWS").proficiency).not.toHaveProperty("AWS");
  });

  it("adds skills as core or other, keeping core skills in list order", () => {
    expect(addSkills(start, "Go, Kotlin", true)).toEqual({
      list: list(["Python", "SQL", "AWS", "Go", "Kotlin"], ["Python", "Go", "Kotlin"]),
      added: ["Go", "Kotlin"],
      problem: null,
    });
    expect(addSkills(start, "Kubernetes", false).list).toEqual(list(["Python", "SQL", "AWS", "Kubernetes"], ["Python"]));
  });

  it("doesn't add a skill that's already listed, in any case, and says so", () => {
    const result = addSkills(start, "aws, Go, go, sql", false);
    expect(result.list.skills).toEqual(["Python", "SQL", "AWS", "Go"]);
    expect(result.added).toEqual(["Go"]);
    expect(result.problem).toBe('"AWS", "SQL" are already in your list');
    expect(addSkills(start, "python", true).problem).toBe('"Python" is already in your list');
  });

  it("refuses names that are too long and lists that are full", () => {
    expect(addSkills(start, "y".repeat(61), false)).toMatchObject({ added: [], problem: expect.stringMatching(/too long/) });
    const full = list(
      Array.from({ length: MAX_SKILLS }, (_, i) => `S${i}`),
      ["S0"],
    );
    expect(addSkills(full, "One more", false)).toMatchObject({
      added: [],
      problem: `You can have at most ${MAX_SKILLS} skills`,
    });
  });

  it("removes a skill from both lists", () => {
    expect(removeSkill(start, "Python")).toEqual(list(["SQL", "AWS"], []));
    expect(removeSkill(start, "AWS")).toEqual(list(["Python", "SQL"], ["Python"]));
  });

  it("moves a skill between core and other", () => {
    expect(setCore(start, "AWS", true)).toEqual(list(["Python", "SQL", "AWS"], ["Python", "AWS"]));
    expect(setCore(start, "Python", false)).toEqual(list(["Python", "SQL", "AWS"], []));
  });

  it("says why a list can't be saved", () => {
    expect(skillsProblem(start)).toBeNull();
    expect(skillsProblem(list(["SQL"], []))).toMatch(/Mark at least one skill as core/);
    expect(skillsProblem(list([], []))).toBe("Add at least one skill");
  });

  it("compares lists, stars included", () => {
    expect(sameSkills(start, setProficiency(start, "SQL", 4))).toBe(false);
    expect(sameSkills(start, setProficiency(start, "SQL", 3))).toBe(true);
  });

  it("compares lists, order included", () => {
    expect(sameSkills(start, list(["Python", "SQL", "AWS"], ["Python"]))).toBe(true);
    expect(sameSkills(start, list(["SQL", "Python", "AWS"], ["Python"]))).toBe(false);
    expect(sameSkills(start, list(["Python", "SQL", "AWS"], ["Python", "SQL"]))).toBe(false);
  });
});

describe("sortSkillNames", () => {
  const names = ["react", "AWS", "Java 11", ".NET", "Java 8", "Go"];
  const stars = { react: 5, AWS: 2, "Java 11": 5, ".NET": 2, "Java 8": 4 }; // Go: unrated (3)

  it("keeps the list's order", () => {
    expect(sortSkillNames(names, "list", stars)).toEqual(names);
  });

  it("sorts A–Z in any case, numbers in order", () => {
    expect(sortSkillNames(names, "name", stars)).toEqual([".NET", "AWS", "Go", "Java 8", "Java 11", "react"]);
  });

  it("sorts by stars, A–Z among equals, unrated counting as the default", () => {
    expect(sortSkillNames(names, "proficiency", stars)).toEqual(["Java 11", "react", "Java 8", "Go", ".NET", "AWS"]);
  });

  it("doesn't change the list it's given", () => {
    const copy = [...names];
    sortSkillNames(copy, "name", stars);
    expect(copy).toEqual(names);
  });
});

