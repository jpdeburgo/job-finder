/**
 * Translate a `JobPatch` from the browser into the document fields to write.
 *
 * Mirrors `FirestoreJobStore._status_fields` in backend/job_store.py so a
 * status set from the dashboard looks exactly like one set by `jobs_cli.py`:
 *
 *   status            -> status, status_updated_at (and applied_at when "applied")
 *   notes             -> notes
 *   work_arrangement  -> work_arrangement, work_arrangement_set_at (null clears both)
 */

import type { JobPatch } from "./types";
import { JOB_STATUSES, WORK_ARRANGEMENTS, isJobStatus, isWorkArrangement } from "./types";

export class InvalidPatchError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidPatchError";
  }
}

export const MAX_NOTES_LENGTH = 5000;

/** Validate an untrusted request body and return a clean `JobPatch`. */
export function parseJobPatch(body: unknown): JobPatch {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new InvalidPatchError("Request body must be a JSON object");
  }
  const input = body as Record<string, unknown>;
  const patch: JobPatch = {};

  if ("status" in input && input.status !== undefined) {
    if (!isJobStatus(input.status)) {
      throw new InvalidPatchError(
        `Unknown status ${JSON.stringify(input.status)}; expected one of ${JOB_STATUSES.join(", ")}`,
      );
    }
    patch.status = input.status;
  }

  if ("notes" in input && input.notes !== undefined) {
    if (input.notes !== null && typeof input.notes !== "string") {
      throw new InvalidPatchError("notes must be a string");
    }
    const notes = (input.notes ?? "").trim();
    if (notes.length > MAX_NOTES_LENGTH) {
      throw new InvalidPatchError(`notes must be at most ${MAX_NOTES_LENGTH} characters`);
    }
    patch.notes = notes;
  }

  if ("work_arrangement" in input && input.work_arrangement !== undefined) {
    if (input.work_arrangement !== null && !isWorkArrangement(input.work_arrangement)) {
      throw new InvalidPatchError(
        `Unknown work_arrangement ${JSON.stringify(input.work_arrangement)}; expected one of ${WORK_ARRANGEMENTS.join(", ")}, or null`,
      );
    }
    patch.work_arrangement = input.work_arrangement;
  }

  if (patch.status === undefined && patch.notes === undefined && patch.work_arrangement === undefined) {
    throw new InvalidPatchError("Nothing to update: provide status, notes, and/or work_arrangement");
  }
  return patch;
}

/**
 * Fields to merge into the job document. Timestamps are `Date`s; each store
 * encodes them in its own format (Firestore Timestamp / ISO string).
 */
export function buildUpdateFields(patch: JobPatch, now: Date = new Date()): Record<string, unknown> {
  const fields: Record<string, unknown> = {};
  if (patch.status !== undefined) {
    fields.status = patch.status;
    fields.status_updated_at = now;
    if (patch.status === "applied") fields.applied_at = now;
  }
  if (patch.notes !== undefined) {
    fields.notes = patch.notes;
  }
  if (patch.work_arrangement !== undefined) {
    // Next to the site's is_remote, not instead of it: searches keep refreshing
    // the site's value, and readers use yours while it's set.
    fields.work_arrangement = patch.work_arrangement;
    fields.work_arrangement_set_at = patch.work_arrangement ? now : null;
  }
  return fields;
}
