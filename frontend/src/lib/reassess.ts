/**
 * Describing a reassessment (Refresh re-scoring your saved jobs against your
 * skills) for the notice under the filters. Pure functions.
 */

import { ApiError } from "./client";
import type { ReassessSummary } from "./types";

export interface ReassessNotice {
  tone: "info" | "warning";
  title: string;
  details: string[];
}

const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

/** What a reassessment did, e.g. "Reassessed 106 jobs against your skills" + "8 changed; 3 no longer match". */
export function describeReassess(summary: ReassessSummary): ReassessNotice {
  const skills = summary.skills_source === "saved" ? "your skills" : "the default skills";
  const details: string[] = [];
  if (summary.reassessed > 0) {
    const parts = [summary.changed === 0 ? "Nothing changed" : `${plural(summary.changed, "job")} changed`];
    if (summary.no_longer_match > 0) {
      parts.push(`${summary.no_longer_match} no longer ${summary.no_longer_match === 1 ? "matches" : "match"} (marked in the list)`);
    }
    details.push(`${parts.join("; ")}.`);
  }
  if (summary.fetched > 0) {
    details.push(
      `Loaded ${plural(summary.fetched, "job description")} from the job sites; they're kept, so next time is quicker.`,
    );
  }
  if (summary.unavailable > 0) {
    details.push(
      `${plural(summary.unavailable, "job")} couldn't be reassessed because the posting couldn't be loaded (closed?). ` +
        `${summary.unavailable === 1 ? "It keeps its" : "They keep their"} old score.`,
    );
  }
  return {
    tone: "info",
    title:
      summary.total_jobs === 0
        ? "No saved jobs to reassess"
        : `Reassessed ${plural(summary.reassessed, "job")} against ${skills}`,
    details,
  };
}

/**
 * Why jobs weren't reassessed. `after` is what did happen: the Jobs page's
 * Refresh still reloads the list; the Skills page still saved your skills.
 */
export function reassessProblem(error: unknown, after: "reload" | "save" = "reload"): ReassessNotice {
  const message = error instanceof Error ? error.message : String(error);
  const done = after === "reload" ? "Jobs reloaded" : "Skills saved";
  if (error instanceof ApiError && error.status === 409) {
    return { tone: "info", title: done, details: [message] };
  }
  const title =
    after === "reload"
      ? "Jobs reloaded, but not reassessed against your skills"
      : "Skills saved, but your saved jobs weren't re-scored";
  if (error instanceof ApiError && error.status === 503) {
    const later = after === "save" ? " Once it's running, click Refresh on the Jobs page." : "";
    return { tone: "warning", title, details: [`Re-scoring needs the search API. ${message}${later}`] };
  }
  return { tone: "warning", title, details: [message] };
}
