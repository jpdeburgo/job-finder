import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  ConfigError,
  DEFAULT_EMULATOR_PROJECT_ID,
  backendDir,
  findDotenv,
  firebaseConfigured,
  loadBackendEnv,
  localDbPath,
  resolveStoreConfig,
  type Env,
} from "./config";

const CWD = "/repo/frontend";

describe("backendDir", () => {
  it("defaults to the sibling backend/ directory", () => {
    expect(backendDir({}, CWD)).toBe("/repo/backend");
  });

  it("honours IG_BACKEND_DIR (relative to cwd)", () => {
    expect(backendDir({ IG_BACKEND_DIR: "../script" }, CWD)).toBe("/repo/script");
    expect(backendDir({ IG_BACKEND_DIR: "/elsewhere" }, CWD)).toBe("/elsewhere");
  });
});

describe("localDbPath", () => {
  it("defaults to backend/local_firestore.json", () => {
    expect(localDbPath({}, CWD)).toBe("/repo/backend/local_firestore.json");
  });

  it("honours IG_LOCAL_DB_PATH, ignoring blanks", () => {
    expect(localDbPath({ IG_LOCAL_DB_PATH: "/data/db.json" }, CWD)).toBe("/data/db.json");
    expect(localDbPath({ IG_LOCAL_DB_PATH: "db.json" }, CWD)).toBe("/repo/frontend/db.json");
    expect(localDbPath({ IG_LOCAL_DB_PATH: "   " }, CWD)).toBe("/repo/backend/local_firestore.json");
  });
});

describe("firebaseConfigured", () => {
  it.each(["GOOGLE_APPLICATION_CREDENTIALS", "FIREBASE_SERVICE_ACCOUNT_JSON", "FIRESTORE_EMULATOR_HOST", "FIREBASE_PROJECT_ID"])(
    "is true when %s is set",
    (name) => {
      expect(firebaseConfigured({ [name]: "x" })).toBe(true);
    },
  );

  it("is false with nothing (or only blanks) set", () => {
    expect(firebaseConfigured({})).toBe(false);
    expect(firebaseConfigured({ GOOGLE_APPLICATION_CREDENTIALS: "  " })).toBe(false);
  });
});

describe("resolveStoreConfig", () => {
  it("auto: local when no Firebase variable is set", () => {
    expect(resolveStoreConfig({}, CWD)).toEqual({
      backend: "local",
      path: "/repo/backend/local_firestore.json",
      collections: { jobs: "jobs", runs: "runs" },
    });
  });

  it("auto: firestore when credentials are present", () => {
    const config = resolveStoreConfig({ GOOGLE_APPLICATION_CREDENTIALS: "/keys/sa.json" }, CWD);
    expect(config).toMatchObject({
      backend: "firestore",
      credentialsPath: "/keys/sa.json",
      projectId: undefined,
      databaseId: undefined,
      emulatorHost: undefined,
    });
  });

  it("resolves a relative GOOGLE_APPLICATION_CREDENTIALS against cwd", () => {
    const config = resolveStoreConfig({ GOOGLE_APPLICATION_CREDENTIALS: "sa.json" }, CWD);
    expect(config).toMatchObject({ backend: "firestore", credentialsPath: "/repo/frontend/sa.json" });
  });

  it("IG_STATE_BACKEND=local wins even with credentials set", () => {
    const config = resolveStoreConfig(
      { IG_STATE_BACKEND: "local", GOOGLE_APPLICATION_CREDENTIALS: "/keys/sa.json", IG_LOCAL_DB_PATH: "/x.json" },
      CWD,
    );
    expect(config).toMatchObject({ backend: "local", path: "/x.json" });
  });

  it("is case- and whitespace-insensitive about the selector", () => {
    expect(resolveStoreConfig({ IG_STATE_BACKEND: "  LOCAL " }, CWD).backend).toBe("local");
    expect(resolveStoreConfig({ IG_STATE_BACKEND: "" }, CWD).backend).toBe("local");
  });

  it("IG_STATE_BACKEND=firestore without credentials fails with the same hint as the script", () => {
    expect(() => resolveStoreConfig({ IG_STATE_BACKEND: "firestore" }, CWD)).toThrow(ConfigError);
    expect(() => resolveStoreConfig({ IG_STATE_BACKEND: "firestore" }, CWD)).toThrow(
      /No Firebase credentials found.*GOOGLE_APPLICATION_CREDENTIALS.*IG_STATE_BACKEND=local/,
    );
  });

  it("rejects unknown selectors", () => {
    expect(() => resolveStoreConfig({ IG_STATE_BACKEND: "sqlite" }, CWD)).toThrow(
      'Unknown IG_STATE_BACKEND="sqlite"; expected \'auto\', \'firestore\', or \'local\'',
    );
  });

  it("parses FIREBASE_SERVICE_ACCOUNT_JSON and takes the project ID from it", () => {
    const config = resolveStoreConfig(
      { FIREBASE_SERVICE_ACCOUNT_JSON: JSON.stringify({ type: "service_account", project_id: "my-proj" }) },
      CWD,
    );
    expect(config).toMatchObject({
      backend: "firestore",
      projectId: "my-proj",
      serviceAccount: { type: "service_account", project_id: "my-proj" },
    });
  });

  it("rejects malformed FIREBASE_SERVICE_ACCOUNT_JSON", () => {
    expect(() => resolveStoreConfig({ FIREBASE_SERVICE_ACCOUNT_JSON: "{nope" }, CWD)).toThrow(
      /FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON/,
    );
  });

  it("FIREBASE_PROJECT_ID overrides the service account's project", () => {
    const config = resolveStoreConfig(
      { FIREBASE_PROJECT_ID: "override", FIREBASE_SERVICE_ACCOUNT_JSON: JSON.stringify({ project_id: "sa" }) },
      CWD,
    );
    expect(config).toMatchObject({ projectId: "override" });
  });

  it("emulator mode needs no credentials and falls back to a demo project ID", () => {
    const config = resolveStoreConfig({ FIRESTORE_EMULATOR_HOST: "127.0.0.1:8080" }, CWD);
    expect(config).toMatchObject({
      backend: "firestore",
      emulatorHost: "127.0.0.1:8080",
      projectId: DEFAULT_EMULATOR_PROJECT_ID,
      credentialsPath: undefined,
    });
  });

  it("uses GOOGLE_CLOUD_PROJECT / GCLOUD_PROJECT as project fallbacks", () => {
    const env = { FIRESTORE_EMULATOR_HOST: "127.0.0.1:8080" };
    expect(resolveStoreConfig({ ...env, GOOGLE_CLOUD_PROJECT: "gcp" }, CWD)).toMatchObject({ projectId: "gcp" });
    expect(resolveStoreConfig({ ...env, GCLOUD_PROJECT: "gcloud" }, CWD)).toMatchObject({ projectId: "gcloud" });
  });

  it("maps FIRESTORE_DATABASE, treating (default) as unset, and custom collection names", () => {
    const base = { FIRESTORE_EMULATOR_HOST: "127.0.0.1:8080" };
    expect(resolveStoreConfig({ ...base, FIRESTORE_DATABASE: "(default)" }, CWD)).toMatchObject({ databaseId: undefined });
    expect(
      resolveStoreConfig(
        { ...base, FIRESTORE_DATABASE: "jobs-db", FIRESTORE_JOBS_COLLECTION: "ig_jobs", FIRESTORE_RUNS_COLLECTION: "ig_runs" },
        CWD,
      ),
    ).toMatchObject({ databaseId: "jobs-db", collections: { jobs: "ig_jobs", runs: "ig_runs" } });
  });
});

describe("findDotenv and loadBackendEnv", () => {
  let root: string;
  let backend: string;

  beforeEach(() => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), "repo-"));
    backend = path.join(root, "backend");
    fs.mkdirSync(backend);
  });

  afterEach(() => {
    fs.rmSync(root, { recursive: true, force: true });
  });

  it("findDotenv prefers backend/.env, then walks up like python-dotenv", () => {
    expect(findDotenv(backend)).toBeNull();
    fs.writeFileSync(path.join(root, ".env"), "A=1\n");
    expect(findDotenv(backend)).toBe(path.join(root, ".env"));
    fs.writeFileSync(path.join(backend, ".env"), "A=2\n");
    expect(findDotenv(backend)).toBe(path.join(backend, ".env"));
  });

  it("findDotenv ignores a directory called .env", () => {
    fs.mkdirSync(path.join(backend, ".env"));
    expect(findDotenv(backend)).toBeNull();
  });

  it("does nothing when no .env exists anywhere up the tree", () => {
    const env: Env = {};
    expect(loadBackendEnv(backend, env)).toEqual({ file: null, applied: [] });
    expect(env).toEqual({});
  });

  it("reads a .env at the repository root when backend/ has none", () => {
    fs.writeFileSync(path.join(root, ".env"), "GOOGLE_APPLICATION_CREDENTIALS=/keys/sa.json\nIG_EMAIL_TO=me@example.com\n");
    const env: Env = {};
    const loaded = loadBackendEnv(backend, env);
    expect(loaded.file).toBe(path.join(root, ".env"));
    expect(loaded.applied.sort()).toEqual(["GOOGLE_APPLICATION_CREDENTIALS", "IG_EMAIL_TO"]);
    expect(resolveStoreConfig(env, backend)).toMatchObject({ backend: "firestore", credentialsPath: "/keys/sa.json" });
  });

  it("fills in unset variables and resolves relative paths against the .env's directory", () => {
    fs.writeFileSync(
      path.join(backend, ".env"),
      [
        "IG_EMAIL_TO=me@example.com",
        "GOOGLE_APPLICATION_CREDENTIALS=firebase-service-account.json",
        "IG_LOCAL_DB_PATH=./local_firestore.json",
        "FIREBASE_PROJECT_ID=proj",
        "",
      ].join("\n"),
    );
    const env: Env = {};
    const loaded = loadBackendEnv(backend, env);
    expect(loaded.file).toBe(path.join(backend, ".env"));
    expect(loaded.applied.sort()).toEqual(["FIREBASE_PROJECT_ID", "GOOGLE_APPLICATION_CREDENTIALS", "IG_EMAIL_TO", "IG_LOCAL_DB_PATH"]);
    expect(env.GOOGLE_APPLICATION_CREDENTIALS).toBe(path.join(backend, "firebase-service-account.json"));
    expect(env.IG_LOCAL_DB_PATH).toBe(path.join(backend, "local_firestore.json"));
    expect(env.FIREBASE_PROJECT_ID).toBe("proj");
  });

  it("resolves a relative key path from the root .env against backend/ when it only exists there", () => {
    fs.writeFileSync(path.join(root, ".env"), "GOOGLE_APPLICATION_CREDENTIALS=firebase-service-account.json\n");
    fs.writeFileSync(path.join(backend, "firebase-service-account.json"), "{}");
    const env: Env = {};
    loadBackendEnv(backend, env);
    expect(env.GOOGLE_APPLICATION_CREDENTIALS).toBe(path.join(backend, "firebase-service-account.json"));

    // ...but the .env's own directory wins when the file exists in both.
    fs.writeFileSync(path.join(root, "firebase-service-account.json"), "{}");
    const env2: Env = {};
    loadBackendEnv(backend, env2);
    expect(env2.GOOGLE_APPLICATION_CREDENTIALS).toBe(path.join(root, "firebase-service-account.json"));
  });

  it("never overrides variables that are already set (frontend/.env wins)", () => {
    fs.writeFileSync(path.join(backend, ".env"), "IG_STATE_BACKEND=firestore\nFIREBASE_PROJECT_ID=from-backend\n");
    const env: Env = { IG_STATE_BACKEND: "local" };
    expect(loadBackendEnv(backend, env).applied).toEqual(["FIREBASE_PROJECT_ID"]);
    expect(env.IG_STATE_BACKEND).toBe("local");
  });

  it("leaves absolute paths alone", () => {
    fs.writeFileSync(path.join(backend, ".env"), "GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/sa.json\n");
    const env: Env = {};
    loadBackendEnv(backend, env);
    expect(env.GOOGLE_APPLICATION_CREDENTIALS).toBe("/etc/secrets/sa.json");
  });
});
