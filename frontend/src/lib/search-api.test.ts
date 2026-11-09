/**
 * The proxy to backend/api.py, exercised against a real HTTP server on a
 * random port (and a closed port for "the API isn't running").
 */

import fs from "node:fs";
import http from "node:http";
import type { AddressInfo } from "node:net";
import os from "node:os";
import path from "node:path";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_API_URL,
  forwardToSearchApi,
  resetSearchApiConfig,
  resolveSearchApiConfig,
  type SearchApiConfig,
} from "./search-api";

interface Seen {
  method?: string;
  url?: string;
  headers: http.IncomingHttpHeaders;
  body: string;
}

let server: http.Server;
let baseUrl: string;
let seen: Seen[] = [];
let reply: (res: http.ServerResponse) => void;

beforeAll(async () => {
  server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      seen.push({ method: req.method, url: req.url, headers: req.headers, body });
      reply(res);
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

afterAll(() => new Promise<void>((resolve) => server.close(() => resolve())));

beforeEach(() => {
  seen = [];
  reply = (res) => {
    res.writeHead(202, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ run: { id: "abc", status: "running" } }));
  };
});

const config = (token?: string): SearchApiConfig => ({ baseUrl, token });

describe("resolveSearchApiConfig", () => {
  it("defaults to a local API without a token", () => {
    expect(resolveSearchApiConfig({})).toEqual({ baseUrl: DEFAULT_API_URL, token: undefined });
  });

  it("reads IG_API_URL (trailing slashes dropped) and IG_API_TOKEN", () => {
    expect(resolveSearchApiConfig({ IG_API_URL: " https://api.example.com/ ", IG_API_TOKEN: " t0k " })).toEqual({
      baseUrl: "https://api.example.com",
      token: "t0k",
    });
    expect(resolveSearchApiConfig({ IG_API_URL: "", IG_API_TOKEN: "  " })).toEqual({
      baseUrl: DEFAULT_API_URL,
      token: undefined,
    });
  });
});

describe("forwardToSearchApi", () => {
  it("forwards the method, path, and JSON body, and passes the answer back", async () => {
    const response = await forwardToSearchApi("/runs", { method: "POST", body: '{"sites":["accenture"]}' }, config());

    expect(response.status).toBe(202);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(await response.json()).toEqual({ run: { id: "abc", status: "running" } });
    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatchObject({ method: "POST", url: "/runs", body: '{"sites":["accenture"]}' });
    expect(seen[0].headers["content-type"]).toBe("application/json");
    expect(seen[0].headers.authorization).toBeUndefined();
  });

  it("sends the token when one is configured", async () => {
    await forwardToSearchApi("/runs/latest", {}, config("s3cret"));
    expect(seen[0]).toMatchObject({ method: "GET", url: "/runs/latest" });
    expect(seen[0].headers.authorization).toBe("Bearer s3cret");
    expect(seen[0].headers["content-type"]).toBeUndefined(); // no body, no content type
  });

  it("passes API errors through unchanged", async () => {
    reply = (res) => {
      res.writeHead(409, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "A search is already running (run abc).", run: { id: "abc" } }));
    };
    const response = await forwardToSearchApi("/runs", { method: "POST" }, config());
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ error: "A search is already running (run abc).", run: { id: "abc" } });
  });

  it("turns a non-JSON error page into a JSON error", async () => {
    reply = (res) => {
      res.writeHead(502, { "Content-Type": "text/html" });
      res.end("<html>Bad Gateway</html>");
    };
    const response = await forwardToSearchApi("/runs/latest", {}, config());
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ error: "Search API: 502 Bad Gateway" });
  });

  it("treats a successful non-JSON answer as a bad gateway", async () => {
    reply = (res) => {
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end("<html>not the API</html>");
    };
    const response = await forwardToSearchApi("/runs/latest", {}, config());
    expect(response.status).toBe(502);
    expect((await response.json()).error).toMatch(/isn't JSON/);
  });

  it("says how to start the API when nothing is listening", async () => {
    // Grab a free port, then close it so the connection is refused.
    const closed = http.createServer();
    await new Promise<void>((resolve) => closed.listen(0, "127.0.0.1", resolve));
    const port = (closed.address() as AddressInfo).port;
    await new Promise<void>((resolve) => closed.close(() => resolve()));

    const response = await forwardToSearchApi("/runs/latest", {}, { baseUrl: `http://127.0.0.1:${port}`, token: undefined });

    expect(response.status).toBe(503);
    const { error } = await response.json();
    expect(error).toContain(`The search API isn't reachable at http://127.0.0.1:${port}.`);
    expect(error).toContain("pipenv run uvicorn api:app");
  });
});

describe("configuration from the script's .env", () => {
  const KEYS = ["IG_API_URL", "IG_API_TOKEN", "IG_BACKEND_DIR"];
  const saved: Record<string, string | undefined> = {};
  let dir: string;

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "search-api-"));
    for (const key of KEYS) {
      saved[key] = process.env[key];
      delete process.env[key];
    }
    resetSearchApiConfig();
  });

  afterEach(() => {
    for (const key of KEYS) {
      if (saved[key] === undefined) delete process.env[key];
      else process.env[key] = saved[key];
    }
    resetSearchApiConfig();
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("uses IG_API_URL and IG_API_TOKEN from backend/.env, so one file configures both sides", async () => {
    fs.writeFileSync(path.join(dir, ".env"), `IG_API_URL=${baseUrl}\nIG_API_TOKEN=from-dotenv\n`);
    process.env.IG_BACKEND_DIR = dir;

    const response = await forwardToSearchApi("/runs/latest");

    expect(response.status).toBe(202);
    expect(seen[0].headers.authorization).toBe("Bearer from-dotenv");
  });
});
