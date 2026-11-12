/**
 * Your resume and what was read from it: the skills it mentions (with years
 * for each) and your years of experience.
 *
 * backend/resume.py reads and saves it, as `settings/resume`; this side only
 * reads that document (the Resume page) and sends uploads to the search API
 * (backend/api.py), which has the PDF/Word readers, the parser, and the AI.
 * Two readings can be kept side by side:
 *
 * - "parse": rules, no AI. Runs on every upload.
 * - "ai": a language model (Claude or OpenAI), when an API key is set up.
 *
 * Both add years up the same way (in backend/resume_parser.py): from the
 * dates of your jobs, with overlapping jobs counted once.
 */

import { toIsoString } from "./jobs";
import {
  DEFAULT_PROFICIENCY,
  MAX_PROFICIENCY,
  MAX_SKILL_LENGTH,
  MAX_SKILLS,
  MIN_PROFICIENCY,
  cleanSkillName,
  compareSkillNames,
  fillProficiency,
  type SearchSkills,
} from "./skills";

export const RESUME_DOCUMENT = "resume";
export const RESUME_METHODS = ["parse", "ai"] as const;
export type ResumeMethod = (typeof RESUME_METHODS)[number];
export const METHOD_LABELS: Record<ResumeMethod, string> = { parse: "Parsed", ai: "AI" };

/** resume.MAX_RESUME_BYTES in backend/resume.py. */
export const MAX_RESUME_BYTES = 5 * 1024 * 1024;
/** What the file picker offers; backend/resume.py decides from the contents. */
export const RESUME_FILE_TYPES = ".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown";

export interface DetectedSkill {
  name: string;
  category: string;
  /** From the jobs that mention it, overlaps counted once; null when none do. */
  years: number | null;
  /** Times the resume mentions it; 0 when the AI inferred it. */
  mentions: number;
  /** "present", "YYYY-MM", or null. */
  last_used: string | null;
  /** Other spellings ("ReactJS"), to tell it's already on your list. */
  aliases: string[];
  /**
   * How well you know it, 1-5 stars like the Skills page's (inferred by
   * backend/skill_levels.py, or rated by the AI); null on readings saved
   * before levels existed.
   */
  level: number | null;
  /** Why: "5.9 years across 2 jobs; still using it". */
  level_reason: string;
}

export interface ResumePosition {
  title: string;
  company: string;
  /** "YYYY-MM" */
  start: string;
  /** "YYYY-MM", or null while you're still there. */
  end: string | null;
  months: number;
  skills: string[];
}

export interface ResumeAnalysis {
  method: ResumeMethod;
  years_experience: number | null;
  /** "positions": added up from your jobs' dates; "stated": what the resume says. */
  years_basis: "positions" | "stated" | null;
  stated_years: number | null;
  skills: DetectedSkill[];
  positions: ResumePosition[];
  notes: string[];
  analyzed_at: string | null;
  provider: string | null;
  model: string | null;
}

export interface Resume {
  filename: string;
  file_type: string;
  text: string;
  uploaded_at: string | null;
  analyses: Partial<Record<ResumeMethod, ResumeAnalysis>>;
}

// --- Reading the stored document ---------------------------------------------------

type Data = Record<string, unknown>;
const isObject = (value: unknown): value is Data => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): string => (typeof value === "string" ? value : "");
const textOrNull = (value: unknown): string | null => (typeof value === "string" && value ? value : null);
const numberOrNull = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const texts = (value: unknown): string[] => (Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : []);

function levelFrom(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= MIN_PROFICIENCY && value <= MAX_PROFICIENCY
    ? value
    : null;
}

function skillFrom(data: Data): DetectedSkill | null {
  const name = text(data.name).trim();
  if (!name) return null;
  return {
    name,
    category: text(data.category) || "Other",
    years: numberOrNull(data.years),
    mentions: numberOrNull(data.mentions) ?? 0,
    last_used: textOrNull(data.last_used),
    aliases: texts(data.aliases),
    level: levelFrom(data.level),
    level_reason: text(data.level_reason),
  };
}

function positionFrom(data: Data): ResumePosition | null {
  const start = text(data.start);
  if (!start) return null;
  return {
    title: text(data.title),
    company: text(data.company),
    start,
    end: textOrNull(data.end),
    months: numberOrNull(data.months) ?? 0,
    skills: texts(data.skills),
  };
}

function analysisFrom(method: ResumeMethod, data: unknown): ResumeAnalysis | null {
  if (!isObject(data)) return null;
  const basis = data.years_basis;
  const list = <T>(value: unknown, read: (item: Data) => T | null) =>
    Array.isArray(value) ? value.filter(isObject).map(read).filter((item): item is T => item !== null) : [];
  return {
    method,
    years_experience: numberOrNull(data.years_experience),
    years_basis: basis === "positions" || basis === "stated" ? basis : null,
    stated_years: numberOrNull(data.stated_years),
    skills: list(data.skills, skillFrom),
    positions: list(data.positions, positionFrom),
    notes: texts(data.notes),
    analyzed_at: toIsoString(data.analyzed_at),
    provider: textOrNull(data.provider),
    model: textOrNull(data.model),
  };
}

/**
 * The resume in a stored `settings/resume` document (or an API response),
 * or null when there isn't one. Anything missing or malformed (say, edited
 * by hand in the Firebase console) is left out rather than trusted.
 */
export function resumeFromDocument(data: unknown): Resume | null {
  if (!isObject(data) || typeof data.text !== "string") return null;
  const stored = isObject(data.analyses) ? data.analyses : {};
  const analyses: Resume["analyses"] = {};
  for (const method of RESUME_METHODS) {
    const analysis = analysisFrom(method, stored[method]);
    if (analysis) analyses[method] = analysis;
  }
  return {
    filename: text(data.filename) || "Resume",
    file_type: text(data.file_type),
    text: data.text,
    uploaded_at: toIsoString(data.uploaded_at),
    analyses,
  };
}

// --- Showing it ---------------------------------------------------------------------

/** "6.5 years", "1 year", "4 months". */
export function formatYears(years: number | null): string {
  if (years === null) return "Unknown";
  if (years > 0 && years < 1) {
    const months = Math.max(1, Math.round(years * 12));
    return `${months} month${months === 1 ? "" : "s"}`;
  }
  const rounded = Math.round(years * 10) / 10;
  return `${rounded} year${rounded === 1 ? "" : "s"}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Mar 2021" for "2021-03"; "Present" for null. */
export function formatMonth(value: string | null): string {
  if (value === null || value === "present") return "Present";
  const match = /^(\d{4})-(\d{2})$/.exec(value);
  if (!match) return value;
  const month = MONTHS[Number(match[2]) - 1];
  return month ? `${month} ${match[1]}` : value;
}

/** "Claude (claude-sonnet-4-5)" for who read it with AI. */
export function describeReader(analysis: ResumeAnalysis): string {
  if (analysis.method === "parse") return "Parsed with rules (no AI)";
  const provider = analysis.provider === "anthropic" ? "Claude" : analysis.provider === "openai" ? "OpenAI" : "AI";
  return analysis.model ? `Read by ${provider} (${analysis.model})` : `Read by ${provider}`;
}

/** Where the total years came from, for under the number. */
export function describeYearsBasis(analysis: ResumeAnalysis): string {
  if (analysis.years_basis === "positions") {
    const jobs = analysis.positions.length;
    return `Added up from the dates of ${jobs} job${jobs === 1 ? "" : "s"}, overlaps counted once`;
  }
  if (analysis.years_basis === "stated") return "As the resume states it (no job dates found)";
  return "No job dates or stated years found";
}

/** How the skills found are listed: best known first (as read), or A–Z. */
export const DETECTED_SKILL_SORTS = ["level", "name"] as const;
export type DetectedSkillSort = (typeof DETECTED_SKILL_SORTS)[number];
export const DETECTED_SKILL_SORT_LABELS: Record<DetectedSkillSort, string> = { level: "Level", name: "A–Z" };

/**
 * The skills found, in the chosen order. "level" is the order they were
 * read in (backend/resume_parser.py: most stars, then most years, then most
 * mentions); "name" is A–Z.
 */
export function sortDetectedSkills(skills: readonly DetectedSkill[], sort: DetectedSkillSort): DetectedSkill[] {
  return sort === "name" ? [...skills].sort((a, b) => compareSkillNames(a.name, b.name)) : [...skills];
}

// --- Your skill list ----------------------------------------------------------------

/** The name a detected skill has on your list ("ReactJS" for React), or null when it isn't on it. */
export function listedAs(skill: DetectedSkill, list: SearchSkills): string | null {
  const names = new Set([skill.name, ...skill.aliases].map((name) => name.toLowerCase()));
  return list.skills.find((name) => names.has(name.toLowerCase())) ?? null;
}

/** A skill on your list whose stars the resume would change: from yours to what it suggests. */
export interface RatingChange {
  /** Its name on your list ("ReactJS"). */
  name: string;
  from: number;
  to: number;
}

/** How the resume would change your stars for a skill that's on your list, or null (not listed, or no change). */
export function ratingChange(skill: DetectedSkill, list: SearchSkills): RatingChange | null {
  const listed = listedAs(skill, list);
  if (!listed || skill.level === null) return null;
  const current = list.proficiency[listed] ?? DEFAULT_PROFICIENCY;
  return current === skill.level ? null : { name: listed, from: current, to: skill.level };
}

/** Whether there's something to apply from the resume: a new skill, or new stars for one of yours. */
export function canApply(skill: DetectedSkill, list: SearchSkills): boolean {
  return !listedAs(skill, list) || ratingChange(skill, list) !== null;
}

/**
 * Your list with the picked skills from your resume applied: new ones are
 * added as core skills (what your resume shows you've worked with is your
 * stack) at the stars the resume suggests, and ones already on your list get
 * those stars, staying core or other as you have them. `problem` says why
 * any were left out (the skill limit, say).
 */
export function withDetectedSkills(
  list: SearchSkills,
  picked: DetectedSkill[],
): { list: SearchSkills; added: string[]; updated: RatingChange[]; problem: string | null } {
  const skills = [...list.skills];
  const proficiency = { ...list.proficiency };
  const added: string[] = [];
  const updated: RatingChange[] = [];
  const problems: string[] = [];
  for (const skill of picked) {
    const change = ratingChange(skill, { ...list, skills, proficiency });
    if (change) {
      proficiency[change.name] = change.to;
      updated.push(change);
      continue;
    }
    const name = cleanSkillName(skill.name);
    if (!name || listedAs({ ...skill, name }, { ...list, skills })) continue;
    if (name.length > MAX_SKILL_LENGTH) {
      problems.push(`"${name.slice(0, 20)}..." is too long (at most ${MAX_SKILL_LENGTH} characters)`);
      continue;
    }
    if (skills.length >= MAX_SKILLS) {
      if (!problems.some((problem) => problem.startsWith("You can have at most"))) {
        problems.push(`You can have at most ${MAX_SKILLS} skills, so the rest weren't added`);
      }
      continue; // later picks may still be rating changes
    }
    skills.push(name);
    proficiency[name] = skill.level ?? DEFAULT_PROFICIENCY;
    added.push(name);
  }
  return {
    // Core skills keep the list's order, like the Skills page keeps them.
    list: {
      skills,
      core_skills: skills.filter((name) => list.core_skills.includes(name) || added.includes(name)),
      proficiency: fillProficiency(skills, proficiency),
    },
    added,
    updated,
    problem: problems.length ? problems.join(". ") : null,
  };
}
