import { errorResponse, jsonResponse, readJsonBody } from "@/lib/api";
import { MAX_RESUME_BYTES } from "@/lib/resume";
import { forwardToSearchApi, RESUME_TIMEOUT_MS } from "@/lib/search-api";

/**
 * POST /api/resume — upload your resume, replacing the last one; the search
 * API (backend/api.py) reads it, parses it, and saves it.
 *
 * Body: a form with a `file` (PDF, Word .docx, or text; at most 5 MB), or
 * JSON `{ "text": "..." }` for pasted text. Answers `{ resume }`, or 422 for a
 * file that can't be read and 503 when the search API isn't running.
 */
export async function POST(request: Request) {
  try {
    let body: { filename: string; content_base64: string } | { text: string };
    if ((request.headers.get("content-type") ?? "").includes("multipart/form-data")) {
      let file: FormDataEntryValue | null;
      try {
        file = (await request.formData()).get("file");
      } catch {
        return jsonResponse({ error: "The upload didn't arrive intact; try again." }, 400);
      }
      if (!(file instanceof File) || file.size === 0) return jsonResponse({ error: "Choose a resume file to upload." }, 400);
      if (file.size > MAX_RESUME_BYTES) {
        return jsonResponse({ error: `The file is too big: a resume can be at most ${MAX_RESUME_BYTES / (1024 * 1024)} MB.` }, 413);
      }
      body = { filename: file.name, content_base64: Buffer.from(await file.arrayBuffer()).toString("base64") };
    } else {
      const json = await readJsonBody(request);
      const text = json && typeof json === "object" ? (json as { text?: unknown }).text : undefined;
      if (typeof text !== "string") return jsonResponse({ error: 'Send a file, or JSON { "text": "..." }.' }, 400);
      body = { text };
    }
    return forwardToSearchApi("/resume", { method: "POST", body: JSON.stringify(body), timeoutMs: RESUME_TIMEOUT_MS });
  } catch (error) {
    return errorResponse(error);
  }
}

/** DELETE /api/resume — forget your resume and what was read from it. */
export async function DELETE() {
  return forwardToSearchApi("/resume", { method: "DELETE" });
}
