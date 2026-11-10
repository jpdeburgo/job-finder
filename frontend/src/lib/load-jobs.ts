/**
 * Server-side loading shared by the pages (home, jobs, and skills). Route handlers use
 * the store directly; pages go through this so a misconfigured database
 * becomes a message on the page instead of a crash.
 */

import { type SkillSettings, skillSettingsFromDocument } from "./skills";
import { getJobStore } from "./store";
import type { Job, StoreInfo } from "./types";

export type LoadResult = { ok: true; jobs: Job[]; store: StoreInfo } | { ok: false; message: string };

/** Open the store and list jobs, turning configuration problems into a message. */
export async function loadJobs(): Promise<LoadResult> {
  try {
    const store = getJobStore();
    return { ok: true, jobs: await store.listJobs(), store: store.info() };
  } catch (error) {
    return { ok: false, message: (error as Error).message };
  }
}

export type SkillsLoadResult = { ok: true; settings: SkillSettings; store: StoreInfo } | { ok: false; message: string };

/** Open the store and read the skill list in effect (the Skills page). */
export async function loadSkillSettings(): Promise<SkillsLoadResult> {
  try {
    const store = getJobStore();
    return { ok: true, settings: skillSettingsFromDocument(await store.getSearchSkills()), store: store.info() };
  } catch (error) {
    return { ok: false, message: (error as Error).message };
  }
}
