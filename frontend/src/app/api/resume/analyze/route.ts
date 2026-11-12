import { errorResponse, jsonResponse, readJsonBody } from "@/lib/api";
import { RESUME_METHODS } from "@/lib/resume";
import { forwardToSearchApi, RESUME_TIMEOUT_MS } from "@/lib/search-api";

/**
 * POST /api/resume/analyze — read the saved resume again (forwarded to
 * backend/api.py). Body: `{ "method": "ai" | "parse" }`.
 *
 * Answers `{ resume }` with the new reading next to the others; 404 without
 * a resume, 503 for "ai" when no API key is set up, 502/504 when the AI
 * fails or is too slow. Reading with AI can take a minute.
 */
export async function POST(request: Request) {
  try {
    const body = await readJsonBody(request);
    const method = body && typeof body === "object" ? (body as { method?: unknown }).method : undefined;
    if (!(RESUME_METHODS as readonly unknown[]).includes(method)) {
      return jsonResponse({ error: `method must be one of: ${RESUME_METHODS.join(", ")}` }, 400);
    }
    return forwardToSearchApi("/resume/analyze", {
      method: "POST",
      body: JSON.stringify({ method }),
      timeoutMs: RESUME_TIMEOUT_MS,
    });
  } catch (error) {
    return errorResponse(error);
  }
}
