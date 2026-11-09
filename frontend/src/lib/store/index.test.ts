import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fakeFirestoreStore = vi.hoisted(() => ({ kind: "firestore-store", envFile: null as string | null }));
vi.mock("./firestore", () => ({
  createFirestoreStore: vi.fn(() => fakeFirestoreStore),
}));

import { createFirestoreStore } from "./firestore";
import { createJobStore, getJobStore, resetJobStore } from "./index";
import { LocalJsonJobStore } from "./local";

const ENV_KEYS = [
  "IG_STATE_BACKEND",
  "IG_LOCAL_DB_PATH",
  "IG_BACKEND_DIR",
  "GOOGLE_APPLICATION_CREDENTIALS",
  "FIREBASE_SERVICE_ACCOUNT_JSON",
  "FIRESTORE_EMULATOR_HOST",
  "FIREBASE_PROJECT_ID",
  "IG_EMAIL_TO",
];
const saved: Record<string, string | undefined> = {};
let backend: string;

beforeEach(() => {
  for (const key of ENV_KEYS) {
    saved[key] = process.env[key];
    delete process.env[key];
  }
  // A fake repo: <tmp>/backend, with <tmp> standing in for the repository root.
  backend = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "repo-")), "backend");
  fs.mkdirSync(backend);
  process.env.IG_BACKEND_DIR = backend;
  resetJobStore();
  vi.clearAllMocks();
});

afterEach(() => {
  for (const key of ENV_KEYS) {
    if (saved[key] === undefined) delete process.env[key];
    else process.env[key] = saved[key];
  }
  fs.rmSync(path.dirname(backend), { recursive: true, force: true });
  resetJobStore();
});

describe("createJobStore", () => {
  it("builds a local store from a local config", () => {
    const store = createJobStore({ backend: "local", path: "/x.json", collections: { jobs: "jobs", runs: "runs" } });
    expect(store).toBeInstanceOf(LocalJsonJobStore);
  });

  it("delegates Firestore configs to createFirestoreStore", () => {
    const config = {
      backend: "firestore" as const,
      projectId: "p",
      databaseId: undefined,
      serviceAccount: undefined,
      credentialsPath: "/k.json",
      emulatorHost: undefined,
      collections: { jobs: "jobs", runs: "runs" },
    };
    expect(createJobStore(config)).toBe(fakeFirestoreStore);
    expect(createFirestoreStore).toHaveBeenCalledWith(config);
  });
});

describe("getJobStore", () => {
  it("defaults to backend/local_firestore.json and caches the instance", () => {
    const store = getJobStore();
    expect(store).toBeInstanceOf(LocalJsonJobStore);
    expect((store as LocalJsonJobStore).path).toBe(path.join(backend, "local_firestore.json"));
    expect(getJobStore()).toBe(store);
  });

  it("picks up Firebase settings from backend/.env", () => {
    fs.writeFileSync(path.join(backend, ".env"), "GOOGLE_APPLICATION_CREDENTIALS=firebase-service-account.json\n");
    expect(getJobStore()).toBe(fakeFirestoreStore);
    expect(createFirestoreStore).toHaveBeenCalledWith(
      expect.objectContaining({ backend: "firestore", credentialsPath: path.join(backend, "firebase-service-account.json") }),
    );
  });

  it("picks up a .env at the repository root (the script's python-dotenv behaviour)", () => {
    // backend = <tmp>/backend so the parent is the "repo root".
    const root = path.dirname(backend);
    fs.writeFileSync(path.join(root, ".env"), "FIREBASE_PROJECT_ID=root-proj\nFIRESTORE_EMULATOR_HOST=127.0.0.1:8080\n");
    try {
      const store = getJobStore();
      expect(store).toBe(fakeFirestoreStore);
      expect(store.envFile).toBe(path.join(root, ".env"));
      expect(createFirestoreStore).toHaveBeenCalledWith(expect.objectContaining({ projectId: "root-proj" }));
    } finally {
      fs.unlinkSync(path.join(root, ".env"));
    }
  });

  it("reports the .env it read on a local store too", () => {
    fs.writeFileSync(path.join(backend, ".env"), "IG_EMAIL_TO=me@example.com\n");
    expect(getJobStore().info().envFile).toBe(path.join(backend, ".env"));
  });

  it("lets the frontend environment override backend/.env", () => {
    fs.writeFileSync(path.join(backend, ".env"), "GOOGLE_APPLICATION_CREDENTIALS=sa.json\n");
    process.env.IG_STATE_BACKEND = "local";
    expect(getJobStore()).toBeInstanceOf(LocalJsonJobStore);
  });

  it("resetJobStore forgets the cached store so env changes apply", () => {
    const first = getJobStore();
    process.env.IG_LOCAL_DB_PATH = "/elsewhere.json";
    expect(getJobStore()).toBe(first);
    resetJobStore();
    expect((getJobStore() as LocalJsonJobStore).path).toBe("/elsewhere.json");
  });

  it("surfaces configuration errors", () => {
    process.env.IG_STATE_BACKEND = "firestore";
    expect(() => getJobStore()).toThrow(/No Firebase credentials found/);
  });
});
