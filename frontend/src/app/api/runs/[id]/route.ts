import { jsonResponse } from "@/lib/api";
import { forwardToSearchApi } from "@/lib/search-api";

type Context = { params: Promise<{ id: string }> };

// Run IDs are hex strings from backend/api.py; anything else can't exist.
const RUN_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** GET /api/runs/:id — one run with its output so far; poll until `status` isn't "running". */
export async function GET(_request: Request, context: Context) {
  const { id } = await context.params;
  if (!RUN_ID.test(id)) return jsonResponse({ error: `No run ${id}` }, 404);
  return forwardToSearchApi(`/runs/${id}`);
}
