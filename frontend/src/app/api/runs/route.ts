import { forwardToSearchApi } from "@/lib/search-api";

/**
 * POST /api/runs — start a search (forwarded to backend/api.py).
 *
 * Body (optional): `{ "sites": ["accenture"], "include_unmarked": false }`.
 * 202 `{ run }` once it has started; 409 `{ error, run }` if one is already
 * running; 503 if the search API isn't running.
 */
export async function POST(request: Request) {
  const body = await request.text();
  return forwardToSearchApi("/runs", { method: "POST", body: body.trim() ? body : undefined });
}
