/**
 * Real Firebase Firestore job store, via the Admin SDK.
 *
 * The Admin SDK runs server-side only (route handlers and server components)
 * with the same service-account credentials the Python script uses, so the
 * browser never sees a key. Security rules don't apply to service accounts;
 * see frontend/README.md for the path to per-user Firebase Auth instead.
 */

import { applicationDefault, cert, getApps, initializeApp, type App } from "firebase-admin/app";
import { getFirestore, type Firestore } from "firebase-admin/firestore";
import type { FirestoreStoreConfig } from "../config";
import { normalizeJob, sortNewestFirst } from "../jobs";
import { SEARCH_SKILLS_DOCUMENT, type SearchSkills } from "../skills";
import type { Job, StoreInfo } from "../types";
import { JobNotFoundError, type JobStore } from "./types";

/** The slice of `firebase-admin/firestore` we rely on (kept small so tests can fake it). */
export interface DocumentSnapshotLike {
  id: string;
  exists: boolean;
  data(): Record<string, unknown> | undefined;
}

export interface DocumentReferenceLike {
  get(): Promise<DocumentSnapshotLike>;
  update(fields: Record<string, unknown>): Promise<unknown>;
  set(fields: Record<string, unknown>): Promise<unknown>;
  delete(): Promise<unknown>;
}

export interface CollectionReferenceLike {
  get(): Promise<{ docs: DocumentSnapshotLike[] }>;
  doc(id: string): DocumentReferenceLike;
}

export interface FirestoreLike {
  collection(name: string): CollectionReferenceLike;
}

export class FirestoreJobStore implements JobStore {
  envFile: string | null = null;

  constructor(
    private readonly db: FirestoreLike,
    private readonly config: FirestoreStoreConfig,
  ) {}

  info(): StoreInfo {
    const project = this.config.projectId ?? "(default credentials)";
    const database = this.config.databaseId ? ` database '${this.config.databaseId}'` : "";
    const emulator = this.config.emulatorHost ? ` (emulator at ${this.config.emulatorHost})` : "";
    return {
      backend: "firestore",
      description: `Firestore project '${project}'${database}${emulator}`,
      emulator: !!this.config.emulatorHost,
      envFile: this.envFile,
    };
  }

  private get jobs(): CollectionReferenceLike {
    return this.db.collection(this.config.collections.jobs);
  }

  private get searchSkills(): DocumentReferenceLike {
    return this.db.collection(this.config.collections.settings).doc(SEARCH_SKILLS_DOCUMENT);
  }

  async listJobs(): Promise<Job[]> {
    const snapshot = await this.jobs.get();
    return sortNewestFirst(snapshot.docs.map((doc) => normalizeJob(doc.id, doc.data() ?? {})));
  }

  async getJob(id: string): Promise<Job | null> {
    const snapshot = await this.jobs.doc(id).get();
    return snapshot.exists ? normalizeJob(id, snapshot.data() ?? {}) : null;
  }

  async updateJob(id: string, fields: Record<string, unknown>): Promise<Job> {
    const reference = this.jobs.doc(id);
    if (!(await reference.get()).exists) throw new JobNotFoundError(id);
    // Admin SDK `update` fails on missing docs (checked above) and stores
    // `Date` values as Firestore Timestamps, like the Python client.
    await reference.update(fields);
    const updated = await reference.get();
    return normalizeJob(id, updated.data() ?? {});
  }

  async getSearchSkills(): Promise<Record<string, unknown> | null> {
    const snapshot = await this.searchSkills.get();
    return snapshot.exists ? (snapshot.data() ?? {}) : null;
  }

  async saveSearchSkills(skills: SearchSkills, now: Date = new Date()): Promise<void> {
    // A whole-document set: the list is replaced, never merged with the old one.
    await this.searchSkills.set({
      skills: [...skills.skills],
      core_skills: [...skills.core_skills],
      proficiency: { ...skills.proficiency },
      updated_at: now,
    });
  }

  async resetSearchSkills(): Promise<void> {
    // Deleting a missing document is a no-op in Firestore.
    await this.searchSkills.delete();
  }
}

const APP_NAME = "job-tracker-dashboard";

/** Initialise (once) the Admin app described by `config` and return its Firestore. */
export function connectFirestore(config: FirestoreStoreConfig): Firestore {
  if (config.emulatorHost && !process.env.FIRESTORE_EMULATOR_HOST) {
    // The Admin SDK reads the emulator host from the environment only.
    process.env.FIRESTORE_EMULATOR_HOST = config.emulatorHost;
  }
  if (config.credentialsPath && !process.env.GOOGLE_APPLICATION_CREDENTIALS) {
    process.env.GOOGLE_APPLICATION_CREDENTIALS = config.credentialsPath;
  }

  const existing = getApps().find((app) => app.name === APP_NAME);
  const app: App =
    existing ??
    initializeApp(
      {
        credential: config.serviceAccount
          ? cert(config.serviceAccount as Parameters<typeof cert>[0])
          : config.emulatorHost && !config.credentialsPath
            ? undefined // emulator: no credentials needed
            : applicationDefault(),
        projectId: config.projectId,
      },
      APP_NAME,
    );

  return config.databaseId ? getFirestore(app, config.databaseId) : getFirestore(app);
}

export function createFirestoreStore(config: FirestoreStoreConfig): FirestoreJobStore {
  return new FirestoreJobStore(connectFirestore(config), config);
}
