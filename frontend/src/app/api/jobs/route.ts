import { errorResponse, jsonResponse } from "@/lib/api";
import { getJobStore } from "@/lib/store";

/** GET /api/jobs — every tracked job plus which database they came from. */
export async function GET(request: Request) {
  // Touching the request keeps this handler request-time (never prerendered).
  void request.url;
  try {
    const store = getJobStore();
    const jobs = await store.listJobs();
    return jsonResponse({ store: store.info(), jobs });
  } catch (error) {
    return errorResponse(error);
  }
}
