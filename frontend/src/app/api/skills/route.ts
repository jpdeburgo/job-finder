import { errorResponse, jsonResponse, readJsonBody } from "@/lib/api";
import { parseSkillsBody, skillSettingsFromDocument } from "@/lib/skills";
import { getJobStore } from "@/lib/store";

/** The skills in effect: `{ skills, core_skills, source, updated_at, defaults }`. */
async function currentSettings() {
  return skillSettingsFromDocument(await getJobStore().getSearchSkills());
}

/** GET /api/skills — the skills the next search will look for. */
export async function GET() {
  try {
    return jsonResponse(await currentSettings());
  } catch (error) {
    return errorResponse(error);
  }
}

/**
 * PUT /api/skills — save your own skill list.
 *
 * Body: `{ "skills": ["Python", "Go", ...], "core_skills": ["Python"] }`.
 * Validated like backend/search_skills.py; the next search uses it.
 */
export async function PUT(request: Request) {
  try {
    const skills = parseSkillsBody(await readJsonBody(request));
    await getJobStore().saveSearchSkills(skills);
    return jsonResponse(await currentSettings());
  } catch (error) {
    return errorResponse(error);
  }
}

/** DELETE /api/skills — forget your list; searches go back to the defaults in job_search.py. */
export async function DELETE() {
  try {
    await getJobStore().resetSearchSkills();
    return jsonResponse(await currentSettings());
  } catch (error) {
    return errorResponse(error);
  }
}
