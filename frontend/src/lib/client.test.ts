import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchJobs, fetchLatestRun, fetchRun, patchJob, runFromError, startRun } from "./client";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

afterEach(() => fetchMock.mockReset());

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("fetchJobs", () => {
  it("GETs /api/jobs without caching", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ store: { backend: "local" }, jobs: [] }));
    const result = await fetchJobs();
    expect(fetchMock).toHaveBeenCalledWith("/api/jobs", { cache: "no-store" });
    expect(result.jobs).toEqual([]);
  });

  it("throws ApiError with the server's message", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "No Firebase credentials found" }, 500));
    await expect(fetchJobs()).rejects.toThrow(
      new ApiError("No Firebase credentials found", 500, { error: "No Firebase credentials found" }),
    );
  });

  it("falls back to the status line for non-JSON errors", async () => {
    fetchMock.mockResolvedValue(new Response("<html>Bad Gateway</html>", { status: 502, statusText: "Bad Gateway" }));
    await expect(fetchJobs()).rejects.toThrow("502 Bad Gateway");
  });
});

describe("patchJob", () => {
  it("PATCHes the encoded job ID with a JSON body and unwraps the job", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ job: { id: "a b", status: "applied" } }));
    const job = await patchJob("a b", { status: "applied" });
    expect(fetchMock).toHaveBeenCalledWith("/api/jobs/a%20b", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "applied" }),
    });
    expect(job.status).toBe("applied");
  });

  it("surfaces validation errors", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "Unknown status" }, 400));
    await expect(patchJob("x", { status: "applied" })).rejects.toMatchObject({ status: 400, message: "Unknown status" });
  });
});

describe("search runs", () => {
  const run = { id: "abc", status: "running" };

  it("startRun POSTs the options and unwraps the run", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ run }, 202));
    expect(await startRun({ sites: ["accenture"] })).toEqual(run);
    expect(fetchMock).toHaveBeenCalledWith("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sites: ["accenture"] }),
    });
  });

  it("startRun's 409 carries the run that's already going", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "A search is already running (run abc).", run }, 409));
    const error = await startRun().catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, message: "A search is already running (run abc)." });
    expect(runFromError(error)).toEqual(run);
  });

  it("runFromError is null for anything else", () => {
    expect(runFromError(new ApiError("boom", 500, { error: "boom" }))).toBeNull();
    expect(runFromError(new ApiError("boom", 500))).toBeNull();
    expect(runFromError(new Error("boom"))).toBeNull();
  });

  it("fetchLatestRun and fetchRun GET without caching", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ run: null }));
    expect(await fetchLatestRun()).toBeNull();
    expect(fetchMock).toHaveBeenLastCalledWith("/api/runs/latest", { cache: "no-store" });

    fetchMock.mockResolvedValueOnce(jsonResponse({ run }));
    expect(await fetchRun("a/b")).toEqual(run);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/runs/a%2Fb", { cache: "no-store" });
  });
});
