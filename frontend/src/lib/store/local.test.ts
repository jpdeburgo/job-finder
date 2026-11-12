import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { LocalStoreConfig } from "../config";
import { LocalJsonJobStore, encodeTimestamp, serializeDatabase, sortKeysDeep } from "./local";
import { JobNotFoundError } from "./types";

const FIXTURE = path.join(__dirname, "..", "..", "test", "fixtures", "local_firestore.json");

let dir: string;
let dbPath: string;

function config(overrides: Partial<LocalStoreConfig> = {}): LocalStoreConfig {
  return { backend: "local", path: dbPath, collections: { jobs: "jobs", runs: "runs", settings: "settings" }, ...overrides };
}

function readDb() {
  return JSON.parse(fs.readFileSync(dbPath, "utf-8"));
}

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "local-store-"));
  dbPath = path.join(dir, "local_firestore.json");
  fs.copyFileSync(FIXTURE, dbPath);
});

afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

describe("encodeTimestamp", () => {
  it("uses a +00:00 offset like Python's datetime.isoformat()", () => {
    expect(encodeTimestamp(new Date("2026-11-01T09:30:00.123Z"))).toBe("2026-11-01T09:30:00.123+00:00");
  });
});

describe("serializeDatabase", () => {
  it("matches json.dumps(data, indent=2, sort_keys=True) + newline byte for byte", () => {
    const data = { jobs: { b: { z: 1, a: { y: [3, { k: "v", a: 1 }], b: null } }, a: { title: "x" } }, runs: {} };
    // Expected string generated with CPython's json module.
    expect(serializeDatabase(data)).toBe(
      '{\n  "jobs": {\n    "a": {\n      "title": "x"\n    },\n    "b": {\n      "a": {\n        "b": null,\n        "y": [\n          3,\n          {\n            "a": 1,\n            "k": "v"\n          }\n        ]\n      },\n      "z": 1\n    }\n  },\n  "runs": {}\n}\n',
    );
  });

  it("sortKeysDeep leaves arrays ordered and primitives alone", () => {
    expect(sortKeysDeep([{ b: 1, a: 2 }, "x", null])).toEqual([{ a: 2, b: 1 }, "x", null]);
    expect(Object.keys(sortKeysDeep({ b: 1, a: 2 }) as object)).toEqual(["a", "b"]);
  });
});

describe("LocalJsonJobStore", () => {
  it("describes itself like the Python stand-in", () => {
    const store = new LocalJsonJobStore(config());
    expect(store.info()).toEqual({
      backend: "local",
      description: `local Firestore stand-in at ${dbPath}`,
      emulator: false,
      envFile: null,
    });
    expect(store.path).toBe(dbPath);
    store.envFile = "/repo/.env";
    expect(store.info().envFile).toBe("/repo/.env");
  });

  it("lists every job", async () => {
    const jobs = await new LocalJsonJobStore(config()).listJobs();
    expect(jobs).toHaveLength(4);
    expect(jobs.map((job) => job.title)).toContain("React Developer");
    const react = jobs.find((job) => job.title === "React Developer")!;
    expect(react).toMatchObject({
      id: "6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba",
      company: "Insight Global",
      status: "emailed",
      matched_skills: ["React", "JavaScript", "TypeScript", "Node.js", "GraphQL"],
      score: 5,
      emailed_at: "2026-10-31T13:00:05.123456+00:00",
      gmail_message_id: "19a1b2c3d4e5f607",
    });
  });

  it("reads Python's \\u escapes back into real characters", async () => {
    const jobs = await new LocalJsonJobStore(config()).listJobs();
    expect(jobs.map((job) => job.title)).toContain("Full Stack Engineer — Node/React");
  });

  it("returns one job or null", async () => {
    const store = new LocalJsonJobStore(config());
    expect((await store.getJob("f3c2a1b0-7e6d-4c5b-9a8f-1e2d3c4b5a69"))?.title).toBe("Junior Java Developer");
    expect(await store.getJob("missing")).toBeNull();
  });

  it("treats a missing file as an empty database", async () => {
    fs.unlinkSync(dbPath);
    const store = new LocalJsonJobStore(config());
    expect(await store.listJobs()).toEqual([]);
    expect(await store.getJob("x")).toBeNull();
  });

  it("rejects a file that isn't a collections map", async () => {
    fs.writeFileSync(dbPath, "[1, 2]\n");
    await expect(new LocalJsonJobStore(config()).listJobs()).rejects.toThrow(/should map collection names to documents/);
  });

  it("honours a custom jobs collection name", async () => {
    fs.writeFileSync(dbPath, JSON.stringify({ ig_jobs: { x: { job_id: "x", title: "Custom", status: "emailed" } } }));
    const store = new LocalJsonJobStore(config({ collections: { jobs: "ig_jobs", runs: "runs", settings: "settings" } }));
    expect((await store.listJobs()).map((job) => job.title)).toEqual(["Custom"]);
  });

  describe("updateJob", () => {
    const id = "6a506de5-fa1b-4df7-b3a1-b4e2dfe149ba";
    const now = new Date("2026-11-01T09:30:00.123Z");

    it("merges fields, encodes Dates as ISO +00:00, and returns the updated job", async () => {
      const store = new LocalJsonJobStore(config());
      const job = await store.updateJob(id, { status: "applied", status_updated_at: now, applied_at: now });

      expect(job.status).toBe("applied");
      expect(job.applied_at).toBe("2026-11-01T09:30:00.123+00:00");
      const doc = readDb().jobs[id];
      expect(doc.status).toBe("applied");
      expect(doc.applied_at).toBe("2026-11-01T09:30:00.123+00:00");
      expect(doc.status_updated_at).toBe("2026-11-01T09:30:00.123+00:00");
      // Untouched fields survive the merge.
      expect(doc.title).toBe("React Developer");
      expect(doc.emailed_at).toBe("2026-10-31T13:00:05.123456+00:00");
    });

    it("leaves every other document and collection intact", async () => {
      const before = readDb();
      await new LocalJsonJobStore(config()).updateJob(id, { notes: "hi" });
      const after = readDb();
      expect(Object.keys(after)).toEqual(Object.keys(before));
      for (const docId of Object.keys(before.jobs)) {
        if (docId !== id) expect(after.jobs[docId]).toEqual(before.jobs[docId]);
      }
      expect(after.jobs[id]).toEqual({ ...before.jobs[id], notes: "hi" });
    });

    it("writes the file in the Python layout: sorted keys, 2-space indent, trailing newline", async () => {
      await new LocalJsonJobStore(config()).updateJob(id, { notes: "hi" });
      const text = fs.readFileSync(dbPath, "utf-8");
      expect(text.endsWith("}\n")).toBe(true);
      expect(text).toBe(serializeDatabase(JSON.parse(text)));
      const keys = Object.keys(JSON.parse(text).jobs[id]);
      expect(keys).toEqual([...keys].sort());
    });

    it("throws JobNotFoundError for unknown IDs without touching the file", async () => {
      const before = fs.readFileSync(dbPath, "utf-8");
      await expect(new LocalJsonJobStore(config()).updateJob("nope", { notes: "x" })).rejects.toThrow(JobNotFoundError);
      expect(fs.readFileSync(dbPath, "utf-8")).toBe(before);
    });

    it("leaves no temporary files behind", async () => {
      await new LocalJsonJobStore(config()).updateJob(id, { notes: "x" });
      expect(fs.readdirSync(dir)).toEqual(["local_firestore.json"]);
    });
  });

  describe("skill list", () => {
    const skills = { skills: ["Python", "Go", "SQL"], core_skills: ["Python", "Go"], proficiency: { Python: 5, Go: 3, SQL: 1 } };

    it("is null until one is saved", async () => {
      expect(await new LocalJsonJobStore(config()).getSearchSkills()).toBeNull();
    });

    it("saves settings/search_skills like the Python store, leaving the jobs alone", async () => {
      const before = readDb();
      const store = new LocalJsonJobStore(config());
      await store.saveSearchSkills(skills, new Date("2026-11-08T22:00:00.000Z"));

      const after = readDb();
      expect(after.settings).toEqual({
        search_skills: { ...skills, updated_at: "2026-11-08T22:00:00.000+00:00" },
      });
      expect(after.jobs).toEqual(before.jobs);
      expect(await store.getSearchSkills()).toEqual(after.settings.search_skills);
      const text = fs.readFileSync(dbPath, "utf-8");
      expect(text).toBe(serializeDatabase(JSON.parse(text)));
    });

    it("replaces the whole list on every save", async () => {
      const store = new LocalJsonJobStore(config());
      await store.saveSearchSkills({ skills: ["Old", "Older"], core_skills: ["Old"], proficiency: { Old: 3, Older: 3 } });
      await store.saveSearchSkills(skills);
      expect(await store.getSearchSkills()).toMatchObject(skills);
    });

    it("resets by removing the document, and the collection once it's empty", async () => {
      const store = new LocalJsonJobStore(config());
      const before = fs.readFileSync(dbPath, "utf-8");
      await store.resetSearchSkills(); // nothing saved: the file isn't rewritten
      expect(fs.readFileSync(dbPath, "utf-8")).toBe(before);

      await store.saveSearchSkills(skills);
      await store.resetSearchSkills();
      expect(await store.getSearchSkills()).toBeNull();
      expect(readDb()).not.toHaveProperty("settings");
    });

    it("works before the file exists", async () => {
      fs.rmSync(dbPath);
      const store = new LocalJsonJobStore(config());
      expect(await store.getSearchSkills()).toBeNull();
      await store.saveSearchSkills(skills);
      expect(Object.keys(readDb())).toEqual(["settings"]);
    });
  });

  describe("resume", () => {
    it("is null until backend/resume.py saves one", async () => {
      expect(await new LocalJsonJobStore(config()).getResume()).toBeNull();
      fs.rmSync(dbPath);
      expect(await new LocalJsonJobStore(config()).getResume()).toBeNull();
    });

    it("reads settings/resume as stored, next to the skill list", async () => {
      const resume = { filename: "cv.pdf", text: "Python", analyses: {} };
      fs.writeFileSync(dbPath, JSON.stringify({ ...readDb(), settings: { resume, search_skills: { skills: ["Go"] } } }));
      expect(await new LocalJsonJobStore(config()).getResume()).toEqual(resume);
      const other = new LocalJsonJobStore(config({ collections: { jobs: "jobs", runs: "runs", settings: "ig_settings" } }));
      expect(await other.getResume()).toBeNull();
    });
  });
});
