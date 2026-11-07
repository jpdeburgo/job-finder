import { forwardToSearchApi } from "@/lib/search-api";

/** GET /api/runs/latest — the newest search started from the dashboard: `{ run }` (null if none yet). */
export async function GET(request: Request) {
  // Touching the request keeps this handler request-time (never prerendered).
  void request.url;
  return forwardToSearchApi("/runs/latest");
}
