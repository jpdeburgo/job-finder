/**
 * The skills the search looks for: the defaults, your saved list, and the
 * rules a list must follow. A port of backend/search_skills.py; keep the two
 * in sync.
 *
 * Your list is saved in the `settings` collection as `settings/search_skills`
 * (`skills`, `core_skills`, `proficiency`, `updated_at`). Every search (the cron job, Run
 * search, the command line) reads it when it starts; with no document, the
 * search uses the defaults in backend/job_search.py.
 */

import { toIsoString } from "./jobs";

export const SEARCH_SKILLS_DOCUMENT = "search_skills";
export const MAX_SKILLS = 100;
export const MAX_SKILL_LENGTH = 60;
/** A Core match needs this many of your skills (MIN_SKILL_MATCHES in job_search.py). */
export const MIN_SKILL_MATCHES = 2;

// Proficiency: how well you know a skill, in stars. Unrated skills count as
// DEFAULT_PROFICIENCY, which leaves the fit score as it was. Same scale as
// backend/search_skills.py; backend/job_fit.py turns stars into weight.
export const MIN_PROFICIENCY = 1;
export const MAX_PROFICIENCY = 5;
export const DEFAULT_PROFICIENCY = 3;
export const PROFICIENCY_LABELS: Record<number, string> = {
  1: "Beginner",
  2: "Familiar",
  3: "Proficient",
  4: "Advanced",
  5: "Expert",
};

export interface SearchSkills {
  /** Every skill to look for, in your order. */
  skills: string[];
  /** Your main stack: a subset of `skills`, in the same order. */
  core_skills: string[];
  /** Stars (1-5) for every skill in `skills`. */
  proficiency: Record<string, number>;
}

/** What GET/PUT/DELETE /api/skills return. */
export interface SkillSettings extends SearchSkills {
  /** "saved": your list from the dashboard; "default": job_search.py's. */
  source: "saved" | "default";
  /** When you last saved, or null while the defaults are in use. */
  updated_at: string | null;
  defaults: SearchSkills;
}

// Mirrors RESUME_SKILLS and CORE_LANGUAGE_SKILLS in backend/job_search.py
// (backend/tests/test_search_skills.py checks that they match). Only shown
// until you save your own list; the search itself reads the Python ones.
const DEFAULT_SKILL_LISTS = {
  skills: [
    "Python",
    "JavaScript",
    "TypeScript",
    "React",
    "ReactJS",
    "React Native",
    "Node.js",
    "NodeJS",
    "SQL",
    "Java",
    "GraphQL",
    "Full Stack",
    "REST API",
    "Docker",
    "Terraform",
    "Azure",
    "AWS",
    "Firebase",
  ],
  core_skills: [
    "Python",
    "JavaScript",
    "TypeScript",
    "React",
    "ReactJS",
    "React Native",
    "Node.js",
    "NodeJS",
    "Java",
  ],
};

/** `proficiency` for every skill: the stars given, else DEFAULT_PROFICIENCY. */
export function fillProficiency(skills: string[], given: Record<string, number> = {}): Record<string, number> {
  return Object.fromEntries(skills.map((name) => [name, given[name] ?? DEFAULT_PROFICIENCY]));
}

export const DEFAULT_SEARCH_SKILLS: SearchSkills = {
  ...DEFAULT_SKILL_LISTS,
  proficiency: fillProficiency(DEFAULT_SKILL_LISTS.skills),
};

export class InvalidSkillsError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidSkillsError";
  }
}

/** Trim and collapse spaces, like the search does. */
export function cleanSkillName(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function cleanName(value: unknown): string {
  if (typeof value !== "string") throw new InvalidSkillsError(`Skills must be text, not ${JSON.stringify(value)}`);
  return cleanSkillName(value);
}

function cleanLevel(name: string, value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new InvalidSkillsError(`Proficiency for "${name}" must be a whole number of stars, not ${JSON.stringify(value)}`);
  }
  if (value < MIN_PROFICIENCY || value > MAX_PROFICIENCY) {
    throw new InvalidSkillsError(`Proficiency for "${name}" must be ${MIN_PROFICIENCY} to ${MAX_PROFICIENCY} stars, not ${value}`);
  }
  return value;
}

/**
 * Validate a skill list (`clean_skills` in backend/search_skills.py).
 *
 * Names are trimmed; blanks and repeats (any case: matching ignores case, and
 * the first spelling wins) are dropped. Core skills and ratings take the
 * list's spelling; core skills keep the list's order, and unrated skills get
 * DEFAULT_PROFICIENCY. Throws `InvalidSkillsError` when there are no skills,
 * no core skill, too many, a name is too long, a core skill or a rating's
 * skill isn't in the list, or a rating isn't 1-5 stars.
 */
export function cleanSkills(
  skills: readonly unknown[],
  coreSkills: readonly unknown[],
  proficiency: Record<string, unknown> = {},
): SearchSkills {
  const names: string[] = [];
  const spelling = new Map<string, string>();
  for (const value of skills) {
    const name = cleanName(value);
    if (!name || spelling.has(name.toLowerCase())) continue;
    if (name.length > MAX_SKILL_LENGTH) {
      throw new InvalidSkillsError(
        `"${name.slice(0, 20)}..." is too long: skills can be at most ${MAX_SKILL_LENGTH} characters`,
      );
    }
    names.push(name);
    spelling.set(name.toLowerCase(), name);
  }
  if (names.length === 0) throw new InvalidSkillsError("Add at least one skill");
  if (names.length > MAX_SKILLS) throw new InvalidSkillsError(`At most ${MAX_SKILLS} skills`);

  const core = new Set<string>();
  for (const value of coreSkills) {
    const name = cleanName(value);
    if (!name) continue;
    const listed = spelling.get(name.toLowerCase());
    if (!listed) throw new InvalidSkillsError(`Core skill "${name}" is not in the skill list`);
    core.add(listed);
  }
  if (core.size === 0) {
    throw new InvalidSkillsError("Mark at least one skill as core: a Core match needs one of them");
  }

  const levels: Record<string, number> = {};
  for (const [key, value] of Object.entries(proficiency)) {
    const name = cleanSkillName(key);
    const listed = spelling.get(name.toLowerCase());
    if (!listed) throw new InvalidSkillsError(`Proficiency is given for "${name}", which is not in the skill list`);
    levels[listed] = cleanLevel(name, value);
  }
  return {
    skills: names,
    core_skills: names.filter((name) => core.has(name)),
    proficiency: fillProficiency(names, levels),
  };
}

/** Validate an untrusted PUT /api/skills body: `{ skills: [...], core_skills: [...], proficiency?: {...} }`. */
export function parseSkillsBody(body: unknown): SearchSkills {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new InvalidSkillsError("Request body must be a JSON object");
  }
  const { skills, core_skills, proficiency } = body as Record<string, unknown>;
  if (!Array.isArray(skills) || !Array.isArray(core_skills)) {
    throw new InvalidSkillsError("skills and core_skills must both be lists");
  }
  if (proficiency != null && (typeof proficiency !== "object" || Array.isArray(proficiency))) {
    throw new InvalidSkillsError("proficiency must map skills to stars");
  }
  return cleanSkills(skills, core_skills, (proficiency ?? {}) as Record<string, unknown>);
}

/**
 * The settings to show for a stored `settings/search_skills` document (null:
 * none saved). A document that can't be used (say, edited by hand in the
 * Firebase console) is ignored, like the search ignores it.
 */
export function skillSettingsFromDocument(data: Record<string, unknown> | null | undefined): SkillSettings {
  const defaults: SearchSkills = {
    skills: [...DEFAULT_SEARCH_SKILLS.skills],
    core_skills: [...DEFAULT_SEARCH_SKILLS.core_skills],
    proficiency: { ...DEFAULT_SEARCH_SKILLS.proficiency },
  };
  if (data) {
    try {
      const saved = parseSkillsBody(data);
      return { ...saved, source: "saved", updated_at: toIsoString(data.updated_at), defaults };
    } catch (error) {
      if (!(error instanceof InvalidSkillsError)) throw error;
    }
  }
  return { ...defaults, source: "default", updated_at: null, defaults };
}

/** Whether two lists hold the same skills, in the same order, with the same core ones and stars. */
export function sameSkills(a: SearchSkills, b: SearchSkills): boolean {
  const same = (x: string[], y: string[]) => x.length === y.length && x.every((value, i) => value === y[i]);
  const stars = (list: SearchSkills, name: string) => list.proficiency[name] ?? DEFAULT_PROFICIENCY;
  return (
    same(a.skills, b.skills) && same(a.core_skills, b.core_skills) && a.skills.every((name) => stars(a, name) === stars(b, name))
  );
}

// --- Editing a list (the Skills page) ------------------------------------------------

/** Keep `core_skills` a subset of `skills`, in the same order, and a rating for every skill. */
function withCore(skills: string[], core: Iterable<string>, proficiency: Record<string, number>): SearchSkills {
  const set = new Set(core);
  return { skills, core_skills: skills.filter((name) => set.has(name)), proficiency: fillProficiency(skills, proficiency) };
}

/** The names typed into an "Add" box: commas, semicolons, and new lines separate several. */
export function splitSkillInput(text: string): string[] {
  return text.split(/[,;\n]/).map(cleanSkillName).filter(Boolean);
}

/**
 * Add what was typed (one name, or several separated by commas) as core or
 * other skills. A name already listed (any case) isn't added twice; a name
 * that's too long, or one that would go past the limit, isn't added at all.
 * `problem` says why anything was left out.
 */
export function addSkills(
  list: SearchSkills,
  text: string,
  core: boolean,
): { list: SearchSkills; added: string[]; problem: string | null } {
  const skills = [...list.skills];
  const coreSkills = new Set(list.core_skills);
  const added: string[] = [];
  const already: string[] = [];
  const problems: string[] = [];
  for (const name of splitSkillInput(text)) {
    const existing = skills.find((skill) => skill.toLowerCase() === name.toLowerCase());
    if (existing) {
      if (!added.includes(existing)) already.push(existing);
      continue;
    }
    if (name.length > MAX_SKILL_LENGTH) {
      problems.push(`"${name.slice(0, 20)}..." is too long (at most ${MAX_SKILL_LENGTH} characters)`);
      continue;
    }
    if (skills.length >= MAX_SKILLS) {
      problems.push(`You can have at most ${MAX_SKILLS} skills`);
      break;
    }
    skills.push(name);
    added.push(name);
    if (core) coreSkills.add(name);
  }
  if (already.length > 0) {
    const names = already.map((name) => `"${name}"`).join(", ");
    problems.unshift(`${names} ${already.length === 1 ? "is" : "are"} already in your list`);
  }
  // New skills start at DEFAULT_PROFICIENCY; rate them afterwards.
  return { list: withCore(skills, coreSkills, list.proficiency), added, problem: problems.length ? problems.join(". ") : null };
}

export function removeSkill(list: SearchSkills, name: string): SearchSkills {
  return withCore(
    list.skills.filter((skill) => skill !== name),
    list.core_skills.filter((skill) => skill !== name),
    list.proficiency,
  );
}

/** Make a listed skill core (true) or other (false). */
export function setCore(list: SearchSkills, name: string, core: boolean): SearchSkills {
  const coreSkills = new Set(list.core_skills);
  if (core) coreSkills.add(name);
  else coreSkills.delete(name);
  return withCore(list.skills, coreSkills, list.proficiency);
}

/** Rate a listed skill 1-5 stars. */
export function setProficiency(list: SearchSkills, name: string, stars: number): SearchSkills {
  const level = Math.min(MAX_PROFICIENCY, Math.max(MIN_PROFICIENCY, Math.round(stars)));
  return withCore(list.skills, list.core_skills, { ...list.proficiency, [name]: level });
}

/** Why a list can't be saved yet, or null if it can. */
export function skillsProblem(list: SearchSkills): string | null {
  try {
    cleanSkills(list.skills, list.core_skills, list.proficiency);
    return null;
  } catch (error) {
    if (error instanceof InvalidSkillsError) return error.message;
    throw error;
  }
}
