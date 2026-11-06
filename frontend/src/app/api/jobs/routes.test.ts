/**
 * Route handlers exercised directly (no HTTP server) against a temporary copy
 * of the fixture database, with the store selected through the same
 * environment variables a real deployment would use.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { resetJobStore } from "@/lib/store";
import { GET as listJobs } from "./route";
import { GET as getJob, PATCH as patchJob } from "./[id]/route";

const FIXTURE = path.join(__dirname, "..", "..", "..", "test", "fixtures", "local_firestore.json");
const REACT_ID = "6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba";

let dir: string;
let dbPath: string;
const saved: Record<string, string | undefined> = {};
const ENV_KEYS = ["IG_STATE_BACKEND", "IG_LOCAL_DB_PATH", "IG_BACKEND_DIR", "GOOGLE_APPLICATION_CREDENTIALS"];

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "api-"));
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

const context = (id: string) => ({ params: Promise.resolve({ id }) });
const request = (method: string, body?: unknown, raw?: string) =>
  new Request(`http://localhost/api/jobs/${REACT_ID}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: raw ?? (body === undefined ? undefined : JSON.stringify(body)),
  });

describe("GET /api/jobs", () => {
  it("returns every job and the store description, uncached", async () => {
    const response = await listJobs(new Request("http://localhost/api/jobs"));
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    const body = await response.json();
    expect(body.store).toEqual({
      backend: "local",
      description: `local Firestore stand-in at ${dbPath}`,
      emulator: false,
      envFile: null,
    });
    expect(body.jobs).toHaveLength(4);
    expect(body.jobs.map((job: { id: string }) => job.id)).toContain(REACT_ID);
  });

  it("turns store problems into a 500 with a message", async () => {
    process.env.IG_STATE_BACKEND = "firestore";
    resetJobStore();
    const response = await listJobs(new Request("http://localhost/api/jobs"));
    expect(response.status).toBe(500);
    expect((await response.json()).error).toMatch(/No Firebase credentials found/);
  });
});

describe("GET /api/jobs/:id", () => {
  it("returns one job", async () => {
    const response = await getJob(request("GET"), context(REACT_ID));
    expect(response.status).toBe(200);
    expect((await response.json()).job).toMatchObject({ id: REACT_ID, title: "React Developer", status: "emailed" });
  });

  it("404s for unknown IDs", async () => {
    const response = await getJob(request("GET"), context("nope"));
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "Job nope is not in the store" });
  });
});

describe("PATCH /api/jobs/:id", () => {
  it("updates the status and stamps applied_at, persisting to the file", async () => {
    const before = Date.now();
    const response = await patchJob(request("PATCH", { status: "applied" }), context(REACT_ID));
    expect(response.status).toBe(200);
    const { job } = await response.json();
    expect(job.status).toBe("applied");
    expect(job.applied_at).toMatch(/\+00:00$/);
    expect(new Date(job.applied_at).getTime()).toBeGreaterThanOrEqual(before - 1000);

    const onDisk = JSON.parse(fs.readFileSync(dbPath, "utf-8")).jobs[REACT_ID];
    expect(onDisk.status).toBe("applied");
    expect(onDisk.applied_at).toBe(job.applied_at);
    expect(onDisk.status_updated_at).toBe(job.applied_at);
    expect(onDisk.title).toBe("React Developer");
  });

  it("updates notes alone without touching the status", async () => {
    const response = await patchJob(request("PATCH", { notes: "  Recruiter: Sam " }), context(REACT_ID));
    const { job } = await response.json();
    expect(job.notes).toBe("Recruiter: Sam");
    expect(job.status).toBe("emailed");
    expect(job.status_updated_at).toBe("2026-10-31T13:00:05.123456+00:00");
  });

  it("400s on an unknown status", async () => {
    const response = await patchJob(request("PATCH", { status: "hired" }), context(REACT_ID));
    expect(response.status).toBe(400);
    expect((await response.json()).error).toMatch(/Unknown status "hired"/);
  });

  it("400s on an empty patch or malformed JSON", async () => {
    expect((await patchJob(request("PATCH", {}), context(REACT_ID))).status).toBe(400);
    const malformed = await patchJob(request("PATCH", undefined, "{not json"), context(REACT_ID));
    expect(malformed.status).toBe(400);
    expect((await malformed.json()).error).toBe("Request body must be valid JSON");
  });

  it("404s for unknown IDs", async () => {
    const response = await patchJob(request("PATCH", { status: "applied" }), context("nope"));
    expect(response.status).toBe(404);
  });

  it("leaves other documents untouched", async () => {
    const before = JSON.parse(fs.readFileSync(dbPath, "utf-8"));
    await patchJob(request("PATCH", { status: "skipped" }), context(REACT_ID));
    const after = JSON.parse(fs.readFileSync(dbPath, "utf-8"));
    delete before.jobs[REACT_ID];
    delete after.jobs[REACT_ID];
    expect(after).toEqual(before);
  });
});
