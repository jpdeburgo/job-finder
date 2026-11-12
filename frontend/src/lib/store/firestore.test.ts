import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FirestoreStoreConfig } from "../config";
import { JobNotFoundError } from "./types";

// --- A tiny in-memory stand-in for the Admin SDK's Firestore -------------------

/** Mimics firebase-admin's Timestamp: the store only relies on `toDate()`. */
class FakeTimestamp {
  constructor(private readonly date: Date) {}
  toDate() {
    return this.date;
  }
  static fromDate(date: Date) {
    return new FakeTimestamp(date);
  }
}

type Doc = Record<string, unknown>;

/** The real SDK stores Dates as Timestamps. */
const encode = (fields: Doc): Doc =>
  Object.fromEntries(
    Object.entries(fields).map(([key, value]) => [key, value instanceof Date ? FakeTimestamp.fromDate(value) : value]),
  );

class FakeFirestore {
  constructor(public collections: Record<string, Record<string, Doc>> = {}) {}

  collection(name: string) {
    const docs = (this.collections[name] ??= {});
    const snapshot = (id: string) => ({
      id,
      exists: id in docs,
      data: () => (id in docs ? { ...docs[id] } : undefined),
    });
    return {
      get: async () => ({ docs: Object.keys(docs).map(snapshot) }),
      doc: (id: string) => ({
        get: async () => snapshot(id),
        update: async (fields: Doc) => {
          if (!(id in docs)) throw new Error("NOT_FOUND: no document to update");
          const encoded = encode(fields);
          docs[id] = { ...docs[id], ...encoded };
        },
        set: async (fields: Doc) => {
          docs[id] = encode(fields);
        },
        delete: async () => {
          delete docs[id];
        },
      }),
    };
  }
}

function config(overrides: Partial<FirestoreStoreConfig> = {}): FirestoreStoreConfig {
  return {
    backend: "firestore",
    projectId: "my-proj",
    databaseId: undefined,
    serviceAccount: undefined,
    credentialsPath: "/keys/sa.json",
    emulatorHost: undefined,
    collections: { jobs: "jobs", runs: "runs", settings: "settings" },
    ...overrides,
  };
}

const seen = FakeTimestamp.fromDate(new Date("2026-10-31T13:00:05.123Z"));

function seededDb() {
  return new FakeFirestore({
    jobs: {
      new: { job_id: "new", title: "Newer", status: "emailed", last_seen_at: FakeTimestamp.fromDate(new Date("2026-10-31T00:00:00Z")) },
      old: { job_id: "old", title: "Older", status: "applied", last_seen_at: seen, applied_at: seen, matched_skills: ["Python"] },
    },
  });
}

// --- FirestoreJobStore against the fake -----------------------------------------

describe("FirestoreJobStore", () => {
  // Import lazily so the firebase-admin mock below (for the connection tests)
  // doesn't interfere; the class itself never touches the SDK.
  async function load() {
    return (await import("./firestore")).FirestoreJobStore;
  }

  it("describes project, database, and emulator", async () => {
    const FirestoreJobStore = await load();
    expect(new FirestoreJobStore(new FakeFirestore(), config()).info()).toEqual({
      backend: "firestore",
      description: "Firestore project 'my-proj'",
      emulator: false,
      envFile: null,
    });
    expect(
      new FirestoreJobStore(new FakeFirestore(), config({ databaseId: "jobs-db", emulatorHost: "127.0.0.1:8080" })).info(),
    ).toEqual({
      backend: "firestore",
      description: "Firestore project 'my-proj' database 'jobs-db' (emulator at 127.0.0.1:8080)",
      emulator: true,
      envFile: null,
    });
    expect(new FirestoreJobStore(new FakeFirestore(), config({ projectId: undefined })).info().description).toBe(
      "Firestore project '(default credentials)'",
    );
  });

  it("lists jobs newest-first with Timestamps converted to ISO strings", async () => {
    const FirestoreJobStore = await load();
    const jobs = await new FirestoreJobStore(seededDb(), config()).listJobs();
    expect(jobs.map((job) => job.id)).toEqual(["old", "new"]);
    expect(jobs[0].last_seen_at).toBe("2026-10-31T13:00:05.123Z");
    expect(jobs[0].applied_at).toBe("2026-10-31T13:00:05.123Z");
    expect(jobs[0].matched_skills).toEqual(["Python"]);
  });

  it("reads from a custom collection name", async () => {
    const FirestoreJobStore = await load();
    const db = new FakeFirestore({ ig_jobs: { x: { job_id: "x", title: "Custom", status: "emailed" } } });
    const store = new FirestoreJobStore(db, config({ collections: { jobs: "ig_jobs", runs: "runs", settings: "settings" } }));
    expect((await store.listJobs()).map((job) => job.title)).toEqual(["Custom"]);
  });

  it("gets one job or null", async () => {
    const FirestoreJobStore = await load();
    const store = new FirestoreJobStore(seededDb(), config());
    expect((await store.getJob("old"))?.title).toBe("Older");
    expect(await store.getJob("missing")).toBeNull();
  });

  it("updates a job and returns the fresh document", async () => {
    const FirestoreJobStore = await load();
    const db = seededDb();
    const now = new Date("2026-11-01T09:30:00Z");
    const job = await new FirestoreJobStore(db, config()).updateJob("new", {
      status: "applied",
      status_updated_at: now,
      applied_at: now,
    });
    expect(job).toMatchObject({ id: "new", status: "applied", applied_at: "2026-11-01T09:30:00.000Z", title: "Newer" });
    expect(db.collections.jobs.new.status).toBe("applied");
    expect(db.collections.jobs.new.applied_at).toBeInstanceOf(FakeTimestamp);
  });

  it("throws JobNotFoundError before attempting an update on a missing job", async () => {
    const FirestoreJobStore = await load();
    await expect(new FirestoreJobStore(seededDb(), config()).updateJob("missing", { notes: "x" })).rejects.toThrow(
      JobNotFoundError,
    );
  });
  describe("skill list", () => {
    const skills = { skills: ["Python", "Go", "SQL"], core_skills: ["Python", "Go"], proficiency: { Python: 5, Go: 3, SQL: 1 } };

    it("is null until one is saved", async () => {
      const FirestoreJobStore = await load();
      expect(await new FirestoreJobStore(seededDb(), config()).getSearchSkills()).toBeNull();
    });

    it("saves the whole list to settings/search_skills with a Timestamp, replacing the old one", async () => {
      const FirestoreJobStore = await load();
      const db = seededDb();
      const store = new FirestoreJobStore(db, config());
      await store.saveSearchSkills({ skills: ["Old"], core_skills: ["Old"], proficiency: { Old: 3 } });
      await store.saveSearchSkills(skills, new Date("2026-11-08T22:00:00Z"));

      const doc = db.collections.settings.search_skills;
      expect(doc).toMatchObject(skills);
      expect(doc.updated_at).toBeInstanceOf(FakeTimestamp);
      expect(await store.getSearchSkills()).toEqual(doc);
      expect(Object.keys(db.collections.jobs)).toEqual(["new", "old"]); // jobs untouched
    });

    it("uses the configured settings collection", async () => {
      const FirestoreJobStore = await load();
      const db = seededDb();
      const store = new FirestoreJobStore(db, config({ collections: { jobs: "jobs", runs: "runs", settings: "ig_settings" } }));
      await store.saveSearchSkills(skills);
      expect(Object.keys(db.collections.ig_settings)).toEqual(["search_skills"]);
    });

    it("resets by deleting the document (and doesn't mind when there is none)", async () => {
      const FirestoreJobStore = await load();
      const db = seededDb();
      const store = new FirestoreJobStore(db, config());
      await store.resetSearchSkills();
      await store.saveSearchSkills(skills);
      await store.resetSearchSkills();
      expect(await store.getSearchSkills()).toBeNull();
    });
  });

  describe("resume", () => {
    it("reads settings/resume from the configured settings collection, or null", async () => {
      const FirestoreJobStore = await load();
      const db = seededDb();
      const store = new FirestoreJobStore(db, config({ collections: { jobs: "jobs", runs: "runs", settings: "ig_settings" } }));
      expect(await store.getResume()).toBeNull();
      const resume = { filename: "cv.pdf", text: "Python", uploaded_at: FakeTimestamp.fromDate(new Date()) };
      db.collections.ig_settings = { resume };
      expect(await store.getResume()).toEqual(resume);
    });
  });
});

// --- connectFirestore: how the Admin app is initialised --------------------------

const admin = vi.hoisted(() => ({
  apps: [] as { name: string }[],
  initializeApp: vi.fn((_options: unknown, name: string) => {
    const app = { name };
    admin.apps.push(app);
    return app;
  }),
  getApps: vi.fn(() => admin.apps),
  cert: vi.fn((sa: unknown) => ({ kind: "cert", sa })),
  applicationDefault: vi.fn(() => ({ kind: "adc" })),
  getFirestore: vi.fn((app: unknown, databaseId?: string) => ({ app, databaseId })),
}));

vi.mock("firebase-admin/app", () => ({
  initializeApp: admin.initializeApp,
  getApps: admin.getApps,
  cert: admin.cert,
  applicationDefault: admin.applicationDefault,
}));
vi.mock("firebase-admin/firestore", () => ({ getFirestore: admin.getFirestore }));

describe("connectFirestore", () => {
  const ENV_KEYS = ["FIRESTORE_EMULATOR_HOST", "GOOGLE_APPLICATION_CREDENTIALS"] as const;
  const saved: Record<string, string | undefined> = {};

  beforeEach(() => {
    admin.apps.length = 0;
    vi.clearAllMocks();
    for (const key of ENV_KEYS) {
      saved[key] = process.env[key];
      delete process.env[key];
    }
  });

  afterEach(() => {
    for (const key of ENV_KEYS) {
      if (saved[key] === undefined) delete process.env[key];
      else process.env[key] = saved[key];
    }
  });

  it("uses an inline service account via cert()", async () => {
    const { connectFirestore } = await import("./firestore");
    const sa = { project_id: "my-proj", client_email: "x@y" };
    connectFirestore(config({ serviceAccount: sa, credentialsPath: undefined }));
    expect(admin.cert).toHaveBeenCalledWith(sa);
    expect(admin.initializeApp).toHaveBeenCalledWith(
      { credential: { kind: "cert", sa }, projectId: "my-proj" },
      "job-tracker-dashboard",
    );
    expect(admin.getFirestore).toHaveBeenCalledWith({ name: "job-tracker-dashboard" });
  });

  it("falls back to application default credentials and exports the key path", async () => {
    const { connectFirestore } = await import("./firestore");
    connectFirestore(config({ credentialsPath: "/keys/sa.json" }));
    expect(admin.applicationDefault).toHaveBeenCalled();
    expect(process.env.GOOGLE_APPLICATION_CREDENTIALS).toBe("/keys/sa.json");
  });

  it("emulator: no credentials, host exported for the SDK", async () => {
    const { connectFirestore } = await import("./firestore");
    connectFirestore(config({ credentialsPath: undefined, emulatorHost: "127.0.0.1:8080", projectId: "demo-job-finder" }));
    expect(admin.cert).not.toHaveBeenCalled();
    expect(admin.applicationDefault).not.toHaveBeenCalled();
    expect(admin.initializeApp.mock.calls[0][0]).toEqual({ credential: undefined, projectId: "demo-job-finder" });
    expect(process.env.FIRESTORE_EMULATOR_HOST).toBe("127.0.0.1:8080");
  });

  it("selects a named database", async () => {
    const { connectFirestore } = await import("./firestore");
    connectFirestore(config({ databaseId: "jobs-db" }));
    expect(admin.getFirestore).toHaveBeenCalledWith({ name: "job-tracker-dashboard" }, "jobs-db");
  });

  it("reuses an already-initialised app", async () => {
    const { connectFirestore } = await import("./firestore");
    connectFirestore(config());
    connectFirestore(config());
    expect(admin.initializeApp).toHaveBeenCalledTimes(1);
  });

  it("createFirestoreStore wires the connection into a store", async () => {
    const { createFirestoreStore, FirestoreJobStore } = await import("./firestore");
    expect(createFirestoreStore(config())).toBeInstanceOf(FirestoreJobStore);
  });
});
