import { forwardToSearchApi, REASSESS_TIMEOUT_MS } from "@/lib/search-api";

/**
 * POST /api/jobs/reassess — re-score every saved job against your current
 * skills (forwarded to backend/api.py, which has the scoring code).
 *
 * 200 with the summary (`ReassessSummary`); 409 while a search is running
 * (it reassesses when it finishes); 503 if the search API isn't running.
 * The first call loads each job's description from its site, so it can take
 * a minute; after that it's quick.
 */
export async function POST() {
  return forwardToSearchApi("/jobs/reassess", { method: "POST", timeoutMs: REASSESS_TIMEOUT_MS });
}
