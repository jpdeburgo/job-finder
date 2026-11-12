/**
 * JSON-file job store, sharing `local_firestore.json` with the Python script.
 *
 * Mirrors `LocalFirestoreClient` in backend/job_store.py: top-level keys are
 * collections mapping document IDs to documents, timestamps are ISO strings,
 * and the file is written atomically with sorted keys and two-space indent so
 * the two sides produce byte-compatible output.
 */

import fs from "node:fs/promises";
import path from "node:path";
import type { LocalStoreConfig } from "../config";
import { normalizeJob, sortNewestFirst } from "../jobs";
import { RESUME_DOCUMENT } from "../resume";
import { SEARCH_SKILLS_DOCUMENT, type SearchSkills } from "../skills";
import type { Job, StoreInfo } from "../types";
import { JobNotFoundError, type JobStore } from "./types";

type Document = Record<string, unknown>;
type Database = Record<string, Record<string, Document>>;

/**
 * ISO-8601 with a `+00:00` offset instead of `Z`, i.e. what Python's
 * `datetime.isoformat()` produces and what every Python version's
 * `fromisoformat` can read back.
 */
export function encodeTimestamp(date: Date): string {
  return date.toISOString().replace(/Z$/, "+00:00");
}

function encodeValue(value: unknown): unknown {
  if (value instanceof Date) return encodeTimestamp(value);
  return value;
}

/** Recursively sort object keys, like `json.dumps(sort_keys=True)`. */
export function sortKeysDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (value && typeof value === "object" && !(value instanceof Date)) {
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(value as object).sort()) {
      sorted[key] = sortKeysDeep((value as Record<string, unknown>)[key]);
    }
    return sorted;
  }
  return value;
}

/** Serialise exactly like `json.dumps(data, indent=2, sort_keys=True) + "\n"`. */
export function serializeDatabase(data: Database): string {
  return JSON.stringify(sortKeysDeep(data), null, 2) + "\n";
}

export class LocalJsonJobStore implements JobStore {
  envFile: string | null = null;

  constructor(private readonly config: LocalStoreConfig) {}

  get path(): string {
    return this.config.path;
  }

  info(): StoreInfo {
    return {
      backend: "local",
      description: `local Firestore stand-in at ${this.config.path}`,
      emulator: false,
      envFile: this.envFile,
    };
  }

  async listJobs(): Promise<Job[]> {
    const docs = (await this.load())[this.config.collections.jobs] ?? {};
    return sortNewestFirst(Object.entries(docs).map(([id, data]) => normalizeJob(id, data)));
  }

  async getJob(id: string): Promise<Job | null> {
    const docs = (await this.load())[this.config.collections.jobs] ?? {};
    const data = docs[id];
    return data ? normalizeJob(id, data) : null;
  }

  async updateJob(id: string, fields: Record<string, unknown>): Promise<Job> {
    const data = await this.load();
    const docs = data[this.config.collections.jobs] ?? {};
    const existing = docs[id];
    if (!existing) throw new JobNotFoundError(id);
    const updated: Document = { ...existing };
    for (const [key, value] of Object.entries(fields)) updated[key] = encodeValue(value);
    docs[id] = updated;
    data[this.config.collections.jobs] = docs;
    await this.save(data);
    return normalizeJob(id, updated);
  }

  async getSearchSkills(): Promise<Record<string, unknown> | null> {
    const docs = (await this.load())[this.config.collections.settings] ?? {};
    return docs[SEARCH_SKILLS_DOCUMENT] ?? null;
  }

  async saveSearchSkills(skills: SearchSkills, now: Date = new Date()): Promise<void> {
    const data = await this.load();
    const docs = data[this.config.collections.settings] ?? {};
    docs[SEARCH_SKILLS_DOCUMENT] = {
      skills: [...skills.skills],
      core_skills: [...skills.core_skills],
      proficiency: { ...skills.proficiency },
      updated_at: encodeTimestamp(now),
    };
    data[this.config.collections.settings] = docs;
    await this.save(data);
  }

  async resetSearchSkills(): Promise<void> {
    const data = await this.load();
    const docs = data[this.config.collections.settings];
    if (!docs || !(SEARCH_SKILLS_DOCUMENT in docs)) return;
    delete docs[SEARCH_SKILLS_DOCUMENT];
    // Like Firestore, a collection with no documents left doesn't exist.
    if (Object.keys(docs).length === 0) delete data[this.config.collections.settings];
    await this.save(data);
  }

  async getResume(): Promise<Record<string, unknown> | null> {
    const docs = (await this.load())[this.config.collections.settings] ?? {};
    return docs[RESUME_DOCUMENT] ?? null;
  }

  // Internals ----------------------------------------------------------------

  private async load(): Promise<Database> {
    let text: string;
    try {
      text = await fs.readFile(this.config.path, "utf-8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return {};
      throw error;
    }
    const parsed: unknown = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(
        `${path.basename(this.config.path)} should map collection names to documents, ` +
          'e.g. {"jobs": {...}, "runs": {...}}',
      );
    }
    return parsed as Database;
  }

  private async save(data: Database): Promise<void> {
    const dir = path.dirname(this.config.path);
    await fs.mkdir(dir, { recursive: true });
    const temporary = path.join(
      dir,
      `.${path.basename(this.config.path)}.${process.pid}.${Date.now()}.tmp`,
    );
    await fs.writeFile(temporary, serializeDatabase(data), "utf-8");
    await fs.rename(temporary, this.config.path);
  }
}
