/**
 * Helpers shared by the route handlers under src/app/api.
 */

import { ConfigError } from "./config";
import { InvalidSkillsError } from "./skills";
import { InvalidPatchError } from "./status-update";
import { JobNotFoundError } from "./store";

export function jsonResponse(body: unknown, status = 200): Response {
  return Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

/** Map a thrown error to a JSON error response with a sensible status code. */
export function errorResponse(error: unknown): Response {
  if (error instanceof InvalidPatchError || error instanceof InvalidSkillsError) {
    return jsonResponse({ error: error.message }, 400);
  }
  if (error instanceof JobNotFoundError) return jsonResponse({ error: error.message }, 404);
  if (error instanceof ConfigError) return jsonResponse({ error: error.message }, 500);
  const message = error instanceof Error ? error.message : "Unexpected error";
  console.error("[api]", error);
  return jsonResponse({ error: message }, 500);
}

/** Parse a JSON body, turning malformed JSON into a 400 instead of a 500. */
export async function readJsonBody(request: Request): Promise<unknown> {
  try {
    return await request.json();
  } catch {
    throw new InvalidPatchError("Request body must be valid JSON");
  }
}
