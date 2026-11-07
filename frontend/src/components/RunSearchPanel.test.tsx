import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SearchRun } from "@/lib/types";
import { makeFinishedRun, makeRun, makeSummary } from "@/test/factories";
import { setupUser } from "@/test/user";
import { RunSearchPanel } from "./RunSearchPanel";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** Answer the panel's calls by URL; `runs` are returned in order by GET /api/runs/:id. */
function serveApi({
  latest = null,
  start,
  runs = [],
}: {
  latest?: SearchRun | null | Response;
  start?: Response;
  runs?: (SearchRun | Response)[];
}) {
  const polls = [...runs];
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === "/api/runs/latest") return latest instanceof Response ? latest : jsonResponse({ run: latest });
    if (url === "/api/runs" && init?.method === "POST") return start ?? jsonResponse({ run: makeRun() }, 202);
    if (url.startsWith("/api/runs/")) {
      const next = polls.length > 1 ? polls.shift()! : polls[0];
      if (!next) throw new Error(`no poll response queued for ${url}`);
      return next instanceof Response ? next : jsonResponse({ run: next });
    }
    throw new Error(`unexpected fetch ${url}`);
  });
}

function renderPanel(onFinished = vi.fn()) {
  render(<RunSearchPanel onFinished={onFinished} pollIntervalMs={10} />);
  return onFinished;
}

const runButton = () => screen.getByRole("button", { name: /Run search|Searching…|Starting…/ });

beforeEach(() => {
  fetchMock.mockReset();
});

describe("on load", () => {
  it("explains the button when nothing has run yet", async () => {
    serveApi({});
    renderPanel();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/runs/latest", { cache: "no-store" }));
    expect(screen.getByText(/Run the job search now instead of waiting for the daily cron job/)).toBeInTheDocument();
    expect(runButton()).toHaveTextContent("Run search");
    expect(runButton()).toBeEnabled();
  });

  it("shows the last run's result", async () => {
    serveApi({ latest: makeFinishedRun({ summary: makeSummary({ total_matches: 12, new_matches: 3, emailed_matches: 3 }) }) });
    const onFinished = renderPanel();
    expect(await screen.findByText(/12 matches, 3 new\. Emailed 3 jobs\./)).toBeInTheDocument();
    expect(onFinished).not.toHaveBeenCalled(); // the page's jobs are already current
  });

  it("shows why the last run failed", async () => {
    serveApi({ latest: makeRun({ status: "failed", finished_at: "2026-11-06T14:01:00+00:00", error: "RuntimeError: Every search failed" }) });
    renderPanel();
    expect(await screen.findByText(/Last search failed .*RuntimeError: Every search failed/)).toBeInTheDocument();
  });

  it("follows a run that is already going (e.g. started in another tab)", async () => {
    serveApi({ latest: makeRun({ sites: ["accenture"] }), runs: [makeRun(), makeFinishedRun()] });
    const onFinished = renderPanel();

    expect(await screen.findByText(/Searching accenture/)).toBeInTheDocument();
    expect(runButton()).toBeDisabled();
    await waitFor(() => expect(onFinished).toHaveBeenCalledWith(expect.objectContaining({ status: "succeeded" })));
    expect(runButton()).toHaveTextContent("Run search");
    expect(runButton()).toBeEnabled();
  });

  it("says how to start the API when it isn't running, without blocking the button", async () => {
    serveApi({
      latest: jsonResponse({ error: "The search API isn't reachable at http://127.0.0.1:8000. Start it with ..." }, 503),
    });
    renderPanel();
    expect(await screen.findByTestId("run-unavailable")).toHaveTextContent("The search API isn't reachable");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // a hint, not an error
    expect(runButton()).toBeEnabled();
  });
});

describe("running a search", () => {
  it("starts a run, follows it, and reports the result", async () => {
    const user = setupUser();
    serveApi({
      runs: [
        makeRun({ output: ["Searching Insight Global (insight-global) for 24 term(s) ..."] }),
        makeFinishedRun({ output: ["Searching Insight Global (insight-global) for 24 term(s) ...", "Saved 4 match(es)."] }),
      ],
    });
    const onFinished = renderPanel();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await user.click(runButton());

    expect(fetchMock).toHaveBeenCalledWith("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    await waitFor(() => expect(onFinished).toHaveBeenCalledTimes(1));
    expect(onFinished.mock.calls[0][0]).toMatchObject({ id: "abc123", status: "succeeded" });
    expect(screen.getByText(/Last search finished at .*4 matches, 1 new\. Emailed 1 job\./)).toBeInTheDocument();
    expect(runButton()).toBeEnabled();
  });

  it("shows the run's output on demand", async () => {
    const user = setupUser();
    const output = ["Job state: local Firestore stand-in", "Saved 4 match(es).", "Email sent (m)."];
    serveApi({ latest: makeFinishedRun({ output, output_truncated: 7 }) });
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Show output" }));

    const pre = screen.getByLabelText("Search output");
    expect(pre).toHaveTextContent("… 7 earlier line(s) not shown");
    expect(pre).toHaveTextContent("Saved 4 match(es). Email sent (m).");
    await user.click(screen.getByRole("button", { name: "Hide output" }));
    expect(screen.queryByLabelText("Search output")).not.toBeInTheDocument();
  });

  it("follows the run that's already going when the API says 409", async () => {
    const user = setupUser();
    const other = makeRun({ id: "other1" });
    serveApi({
      start: jsonResponse({ error: "A search is already running (run other1).", run: other }, 409),
      runs: [makeFinishedRun({ id: "other1" })],
    });
    const onFinished = renderPanel();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await user.click(runButton());

    await waitFor(() => expect(onFinished).toHaveBeenCalledWith(expect.objectContaining({ id: "other1" })));
    expect(fetchMock).toHaveBeenCalledWith("/api/runs/other1", { cache: "no-store" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reports a search that fails", async () => {
    const user = setupUser();
    serveApi({
      runs: [makeRun({ status: "failed", finished_at: "2026-11-06T14:01:00+00:00", error: "SiteSelectionError: --site nope matched nothing." })],
    });
    const onFinished = renderPanel();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await user.click(runButton());

    expect(await screen.findByText(/Last search failed .*--site nope matched nothing/)).toBeInTheDocument();
    expect(onFinished).toHaveBeenCalledTimes(1); // the run may still have saved jobs before failing
    expect(runButton()).toBeEnabled();
  });

  it("reports a search that couldn't be started", async () => {
    const user = setupUser();
    serveApi({ start: jsonResponse({ error: "The search API isn't reachable at http://127.0.0.1:8000." }, 503) });
    renderPanel();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await user.click(runButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not start the search: The search API isn't reachable at http://127.0.0.1:8000.",
    );
    expect(runButton()).toBeEnabled();
  });

  it("stops following a run the API has forgotten (e.g. it restarted) and lets you start another", async () => {
    const user = setupUser();
    serveApi({ latest: makeRun(), runs: [jsonResponse({ error: "No run abc123" }, 404)] });
    const onFinished = renderPanel();

    expect(await screen.findByRole("alert")).toHaveTextContent("Lost track of the search: No run abc123");
    expect(screen.getByText(/may still be running/)).toBeInTheDocument();
    expect(onFinished).not.toHaveBeenCalled();
    expect(runButton()).toBeEnabled();

    serveApi({ runs: [makeFinishedRun({ id: "new1" })], start: jsonResponse({ run: makeRun({ id: "new1" }) }, 202) });
    await user.click(runButton());
    await waitFor(() => expect(onFinished).toHaveBeenCalledWith(expect.objectContaining({ id: "new1" })));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
