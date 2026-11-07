/**
 * The /api/runs route handlers forward to backend/api.py; fetch is stubbed
 * so these check exactly what gets forwarded. (The forwarding itself is
 * tested against a real HTTP server in src/lib/search-api.test.ts.)
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetSearchApiConfig } from "@/lib/search-api";
import { GET as getRun } from "./[id]/route";
import { GET as latestRun } from "./latest/route";
import { POST as startRun } from "./route";

const fetchMock = vi.fn();
const KEYS = ["IG_API_URL", "IG_API_TOKEN", "IG_BACKEND_DIR"];
const saved: Record<string, string | undefined> = {};
let dir: string;

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  fetchMock.mockImplementation(async () => Response.json({ run: { id: "abc" } }, { status: 202 }));
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "runs-"));
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
  for (const key of KEYS) {
    if (saved[key] === undefined) delete process.env[key];
    else process.env[key] = saved[key];
  }
  resetSearchApiConfig();
  fs.rmSync(dir, { recursive: true, force: true });
});

const forwarded = () => {
  const [url, init] = fetchMock.mock.calls[0];
  return { url, method: init.method, body: init.body, headers: init.headers };
};

describe("POST /api/runs", () => {
  it("forwards the options to the search API with the token", async () => {
    const response = await startRun(
      new Request("http://localhost/api/runs", { method: "POST", body: '{"sites":["accenture"],"include_unmarked":true}' }),
    );

    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ run: { id: "abc" } });
    expect(forwarded()).toEqual({
      url: "http://api.test:8000/runs",
      method: "POST",
      body: '{"sites":["accenture"],"include_unmarked":true}',
      headers: { Accept: "application/json", "Content-Type": "application/json", Authorization: "Bearer s3cret" },
    });
  });

  it("sends no body when there isn't one (every site)", async () => {
    await startRun(new Request("http://localhost/api/runs", { method: "POST" }));
    expect(forwarded()).toMatchObject({ method: "POST", body: undefined });
  });
});

describe("GET /api/runs/latest", () => {
  it("forwards to /runs/latest", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ run: null }));
    const response = await latestRun(new Request("http://localhost/api/runs/latest"));
    expect(await response.json()).toEqual({ run: null });
    expect(forwarded()).toMatchObject({ url: "http://api.test:8000/runs/latest", method: "GET" });
  });
});

describe("GET /api/runs/:id", () => {
  const context = (id: string) => ({ params: Promise.resolve({ id }) });

  it("forwards to /runs/:id", async () => {
    await getRun(new Request("http://localhost/api/runs/abc123"), context("abc123"));
    expect(forwarded()).toMatchObject({ url: "http://api.test:8000/runs/abc123", method: "GET" });
  });

  it.each(["../health", "a b", "x".repeat(65), ""])("rejects %j without calling the API", async (id) => {
    const response = await getRun(new Request("http://localhost/api/runs/x"), context(id));
    expect(response.status).toBe(404);
    expect((await response.json()).error).toBe(`No run ${id}`);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
