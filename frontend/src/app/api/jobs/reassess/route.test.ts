/**
 * POST /api/jobs/reassess forwards to backend/api.py (fetch is stubbed), with
 * a longer timeout than the other calls: the first reassessment loads every
 * job's description from its site.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { REASSESS_TIMEOUT_MS, resetSearchApiConfig } from "@/lib/search-api";
import { POST } from "./route";

const fetchMock = vi.fn();
const KEYS = ["IG_API_URL", "IG_API_TOKEN", "IG_BACKEND_DIR"];
const saved: Record<string, string | undefined> = {};
let dir: string;

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "reassess-"));
  for (const key of KEYS) {
    saved[key] = process.env[key];
    delete process.env[key];
  }
  process.env.IG_BACKEND_DIR = dir; // no backend/.env to pick up
  process.env.IG_API_URL = "http://api.test:8000";
  process.env.IG_API_TOKEN = "s3cret";
  resetSearchApiConfig();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  for (const key of KEYS) {
    if (saved[key] === undefined) delete process.env[key];
    else process.env[key] = saved[key];
  }
  resetSearchApiConfig();
  fs.rmSync(dir, { recursive: true, force: true });
});

describe("POST /api/jobs/reassess", () => {
  it("forwards to the search API with the token and a long timeout", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    fetchMock.mockImplementation(async () => Response.json({ reassessed: 3, changed: 1 }));

    const response = await POST();

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ reassessed: 3, changed: 1 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test:8000/jobs/reassess");
    expect(init).toMatchObject({ method: "POST", headers: { Authorization: "Bearer s3cret" } });
    expect(timeout).toHaveBeenCalledWith(REASSESS_TIMEOUT_MS);
    expect(REASSESS_TIMEOUT_MS).toBeGreaterThanOrEqual(60_000);
  });

  it("passes a 409 (a search is running) through", async () => {
    fetchMock.mockImplementation(async () => Response.json({ error: "A search is already running" }, { status: 409 }));
    const response = await POST();
    expect(response.status).toBe(409);
    expect((await response.json()).error).toBe("A search is already running");
  });

  it("is a 503 that says how to start the API when it isn't running", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const response = await POST();
    expect(response.status).toBe(503);
    expect((await response.json()).error).toMatch(/isn't reachable at http:\/\/api\.test:8000\. Start it with/);
  });
});
