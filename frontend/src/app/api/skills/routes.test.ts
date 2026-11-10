/**
 * GET/PUT/DELETE /api/skills, exercised directly against a temporary copy of
 * the fixture database (selected through the environment, like the jobs routes).
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_SEARCH_SKILLS } from "@/lib/skills";
import { resetJobStore } from "@/lib/store";
import { DELETE, GET, PUT } from "./route";

const FIXTURE = path.join(__dirname, "..", "..", "..", "test", "fixtures", "local_firestore.json");

let dir: string;
let dbPath: string;
const saved: Record<string, string | undefined> = {};
const ENV_KEYS = ["IG_STATE_BACKEND", "IG_LOCAL_DB_PATH", "IG_BACKEND_DIR", "GOOGLE_APPLICATION_CREDENTIALS"];

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "api-skills-"));
  dbPath = path.join(dir, "local_firestore.json");
  fs.copyFileSync(FIXTURE, dbPath);
  for (const key of ENV_KEYS) {
    saved[key] = process.env[key];
    delete process.env[key];
  }
  process.env.IG_STATE_BACKEND = "local";
  process.env.IG_LOCAL_DB_PATH = dbPath;
  process.env.IG_BACKEND_DIR = dir; // no backend/.env to pick up
  resetJobStore();
});

afterEach(() => {
  for (const key of ENV_KEYS) {
    if (saved[key] === undefined) delete process.env[key];
    else process.env[key] = saved[key];
  }
  resetJobStore();
  fs.rmSync(dir, { recursive: true, force: true });
});

const put = (body: unknown, raw?: string) =>
  PUT(
    new Request("http://localhost/api/skills", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: raw ?? JSON.stringify(body),
    }),
  );
const readDb = () => JSON.parse(fs.readFileSync(dbPath, "utf-8"));

describe("GET /api/skills", () => {
  it("returns the defaults, uncached, until you save a list", async () => {
    const response = await GET();
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(await response.json()).toEqual({
      ...DEFAULT_SEARCH_SKILLS,
      source: "default",
      updated_at: null,
      defaults: DEFAULT_SEARCH_SKILLS,
    });
  });

  it("turns store problems into a 500 with a message", async () => {
    process.env.IG_STATE_BACKEND = "firestore";
    resetJobStore();
    const response = await GET();
    expect(response.status).toBe(500);
    expect((await response.json()).error).toMatch(/No Firebase credentials found/);
  });
});

describe("PUT /api/skills", () => {
  it("saves a cleaned-up list and returns it", async () => {
    const response = await put({
      skills: [" Go ", "Python", "go", "SQL"],
      core_skills: ["python", "Go"],
      proficiency: { go: 5, SQL: 1 },
    });
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toMatchObject({
      skills: ["Go", "Python", "SQL"],
      core_skills: ["Go", "Python"],
      proficiency: { Go: 5, Python: 3, SQL: 1 },
      source: "saved",
    });
    expect(body.updated_at).toMatch(/^\d{4}-\d\d-\d\dT/);

    expect(readDb().settings.search_skills).toEqual({
      skills: ["Go", "Python", "SQL"],
      core_skills: ["Go", "Python"],
      proficiency: { Go: 5, Python: 3, SQL: 1 },
      updated_at: body.updated_at,
    });
    expect((await (await GET()).json()).source).toBe("saved");
  });

  it.each([
    [{ skills: ["SQL"], core_skills: [] }, "Mark at least one skill as core"],
    [{ skills: [], core_skills: [] }, "Add at least one skill"],
    [{ skills: ["SQL"], core_skills: ["Go"] }, 'Core skill "Go" is not in the skill list'],
    [{ skills: "SQL" }, "must both be lists"],
    [{ skills: ["SQL"], core_skills: ["SQL"], proficiency: { SQL: 7 } }, 'Proficiency for "SQL" must be 1 to 5 stars, not 7'],
  ])("rejects %j with a 400 and saves nothing", async (body, message) => {
    const before = fs.readFileSync(dbPath, "utf-8");
    const response = await put(body);
    expect(response.status).toBe(400);
    expect((await response.json()).error).toContain(message);
    expect(fs.readFileSync(dbPath, "utf-8")).toBe(before);
  });

  it("rejects malformed JSON with a 400", async () => {
    const response = await put(undefined, "{nope");
    expect(response.status).toBe(400);
    expect((await response.json()).error).toBe("Request body must be valid JSON");
  });
});

describe("DELETE /api/skills", () => {
  it("forgets your list and returns the defaults", async () => {
    await put({ skills: ["Go"], core_skills: ["Go"] });
    const response = await DELETE();
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ ...DEFAULT_SEARCH_SKILLS, source: "default", updated_at: null });
    expect(readDb()).not.toHaveProperty("settings");
  });
});
