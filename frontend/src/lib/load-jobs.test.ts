import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { loadJobs } from "./load-jobs";
import { resetJobStore } from "./store";

const FIXTURE = path.join(__dirname, "..", "test", "fixtures", "local_firestore.json");
const KEYS = ["IG_STATE_BACKEND", "IG_LOCAL_DB_PATH", "IG_BACKEND_DIR", ...["GOOGLE_APPLICATION_CREDENTIALS", "FIREBASE_SERVICE_ACCOUNT_JSON", "FIRESTORE_EMULATOR_HOST", "FIREBASE_PROJECT_ID"]];
const saved: Record<string, string | undefined> = {};
let dir: string;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "load-jobs-"));
  for (const key of KEYS) {
    saved[key] = process.env[key];
    delete process.env[key];
  }
  process.env.IG_BACKEND_DIR = dir; // no backend/.env to pick up
  resetJobStore();
});

afterEach(() => {
  for (const key of KEYS) {
    if (saved[key] === undefined) delete process.env[key];
    else process.env[key] = saved[key];
  }
  resetJobStore();
  fs.rmSync(dir, { recursive: true, force: true });
});

describe("loadJobs", () => {
  it("returns the jobs and which store they came from", async () => {
    const db = path.join(dir, "local_firestore.json");
    fs.copyFileSync(FIXTURE, db);
    process.env.IG_STATE_BACKEND = "local";
    process.env.IG_LOCAL_DB_PATH = db;

    const result = await loadJobs();

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.jobs.length).toBeGreaterThan(0);
    expect(result.store).toMatchObject({ backend: "local", description: `local Firestore stand-in at ${db}` });
  });

  it("turns a configuration problem into a message instead of throwing", async () => {
    process.env.IG_STATE_BACKEND = "firestore"; // with no credentials

    const result = await loadJobs();

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.message).toMatch(/No Firebase credentials found/);
  });
});
