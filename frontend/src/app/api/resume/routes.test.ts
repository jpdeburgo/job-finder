/**
 * /api/resume and /api/resume/analyze forward to backend/api.py (fetch is
 * stubbed): an uploaded file goes on as base64 JSON, with a timeout long
 * enough for the AI.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MAX_RESUME_BYTES } from "@/lib/resume";
import { RESUME_TIMEOUT_MS, resetSearchApiConfig } from "@/lib/search-api";
import { POST as analyze } from "./analyze/route";
import { DELETE, POST } from "./route";

const fetchMock = vi.fn();
const KEYS = ["IG_API_URL", "IG_API_TOKEN", "IG_BACKEND_DIR"];
const saved: Record<string, string | undefined> = {};
let dir: string;

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  fetchMock.mockImplementation(async () => Response.json({ resume: { text: "Python" } }));
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "resume-"));
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

function upload(file: File | string | null) {
  const form = new FormData();
  if (file !== null) form.append("file", file);
  return new Request("http://localhost/api/resume", { method: "POST", body: form });
}

const json = (url: string, body: unknown) =>
  new Request(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: typeof body === "string" ? body : JSON.stringify(body) });

const forwarded = () => {
  const [url, init] = fetchMock.mock.calls[0];
  return { url, init, body: JSON.parse(init.body) };
};
const forwardedUrlAndMethod = () => [fetchMock.mock.calls[0][0], fetchMock.mock.calls[0][1].method];

describe("POST /api/resume", () => {
  it("sends an uploaded file on as base64, with the token and a long timeout", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const bytes = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x00, 0xff]); // "%PDF", then binary
    const response = await POST(upload(new File([bytes], "jane doe.pdf", { type: "application/pdf" })));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ resume: { text: "Python" } });
    const { url, init, body } = forwarded();
    expect(url).toBe("http://api.test:8000/resume");
    expect(init).toMatchObject({ method: "POST", headers: { Authorization: "Bearer s3cret", "Content-Type": "application/json" } });
    expect(body).toEqual({ filename: "jane doe.pdf", content_base64: Buffer.from(bytes).toString("base64") });
    expect(timeout).toHaveBeenCalledWith(RESUME_TIMEOUT_MS);
  });

  it("sends pasted text as text", async () => {
    await POST(json("http://localhost/api/resume", { text: "Jane Doe\nPython" }));
    expect(forwarded().body).toEqual({ text: "Jane Doe\nPython" });
  });

  it.each([
    ["no file", () => upload(null), 400, "Choose a resume file"],
    ["an empty file", () => upload(new File([], "cv.pdf")), 400, "Choose a resume file"],
    ["a form field that isn't a file", () => upload("just text"), 400, "Choose a resume file"],
    ["JSON without text", () => json("http://localhost/api/resume", { file: "x" }), 400, "Send a file"],
    ["malformed JSON", () => json("http://localhost/api/resume", "{oops"), 400, "valid JSON"],
  ])("refuses %s without calling the API", async (_name, request, status, message) => {
    const response = await POST(request());
    expect(response.status).toBe(status);
    expect((await response.json()).error).toMatch(message);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a file over the limit before reading it", async () => {
    const response = await POST(upload(new File([new Uint8Array(MAX_RESUME_BYTES + 1)], "huge.pdf")));
    expect(response.status).toBe(413);
    expect((await response.json()).error).toMatch(/at most 5 MB/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("passes the API's answer on: a file it can't read, or the API being down", async () => {
    fetchMock.mockImplementation(async () => Response.json({ error: "Word 97-2003 (.doc) files can't be read" }, { status: 422 }));
    let response = await POST(upload(new File(["x"], "cv.doc")));
    expect(response.status).toBe(422);
    expect((await response.json()).error).toMatch(/\.doc/);

    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    response = await POST(upload(new File(["x"], "cv.txt")));
    expect(response.status).toBe(503);
    expect((await response.json()).error).toMatch(/isn't reachable at http:\/\/api\.test:8000\. Start it with/);
  });
});

describe("DELETE /api/resume", () => {
  it("forwards", async () => {
    fetchMock.mockImplementation(async () => Response.json({ resume: null }));
    const response = await DELETE();
    expect(await response.json()).toEqual({ resume: null });
    expect(forwardedUrlAndMethod()).toEqual(["http://api.test:8000/resume", "DELETE"]);
  });
});

describe("POST /api/resume/analyze", () => {
  it.each(["ai", "parse"])("forwards method %s with the long timeout", async (method) => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const response = await analyze(json("http://localhost/api/resume/analyze", { method, extra: "dropped" }));
    expect(response.status).toBe(200);
    expect(forwarded().url).toBe("http://api.test:8000/resume/analyze");
    expect(forwarded().body).toEqual({ method });
    expect(timeout).toHaveBeenCalledWith(RESUME_TIMEOUT_MS);
  });

  it("refuses an unknown method", async () => {
    const response = await analyze(json("http://localhost/api/resume/analyze", { method: "guess" }));
    expect(response.status).toBe(400);
    expect((await response.json()).error).toBe("method must be one of: parse, ai");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("passes on that AI isn't set up", async () => {
    fetchMock.mockImplementation(async () => Response.json({ error: "AI isn't set up" }, { status: 503 }));
    const response = await analyze(json("http://localhost/api/resume/analyze", { method: "ai" }));
    expect(response.status).toBe(503);
  });
});
