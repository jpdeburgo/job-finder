/**
 * Pure helpers for describing search runs (backend/api.py) in the dashboard.
 */

import type { RunSummary, SearchRun } from "./types";

function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

/** One sentence about what a finished run found and emailed. */
export function describeSummary(summary: RunSummary): string {
  const found =
    summary.total_matches === 0
      ? "No matching jobs found."
      : `${plural(summary.total_matches, "match", "matches")}, ${summary.new_matches} new.`;
  if (summary.email_sent) return `${found} Emailed ${plural(summary.emailed_matches, "job")}.`;
  if (summary.email_skipped_reason) return `${found} Not emailed: ${summary.email_skipped_reason}`;
  return summary.total_matches === 0 ? found : `${found} Nothing new to email.`;
}

/** e.g. "2:05 PM" (local time); pass `timeZone` for deterministic output. */
export function formatRunTime(iso: string | null, timeZone?: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone });
}

/** "every site" or "accenture, workday". */
export function describeSites(run: Pick<SearchRun, "sites">): string {
  return run.sites.length ? run.sites.join(", ") : "every site";
}
