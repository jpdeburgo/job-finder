import { errorResponse, jsonResponse, readJsonBody } from "@/lib/api";
import { buildUpdateFields, parseJobPatch } from "@/lib/status-update";
import { getJobStore, JobNotFoundError } from "@/lib/store";

type Context = { params: Promise<{ id: string }> };

/** GET /api/jobs/:id — one job's full record. */
export async function GET(_request: Request, context: Context) {
  try {
    const { id } = await context.params;
    const job = await getJobStore().getJob(id);
    if (!job) throw new JobNotFoundError(id);
    return jsonResponse({ job });
  } catch (error) {
    return errorResponse(error);
  }
}

/**
 * PATCH /api/jobs/:id — change a job's status and/or notes.
 *
 * Body: `{ "status": "applied", "notes": "..." }` (either key optional).
 * Writes the same fields `jobs_cli.py` would.
 */
export async function PATCH(request: Request, context: Context) {
  try {
    const { id } = await context.params;
    const patch = parseJobPatch(await readJsonBody(request));
    const job = await getJobStore().updateJob(id, buildUpdateFields(patch));
    return jsonResponse({ job });
  } catch (error) {
    return errorResponse(error);
  }
}
