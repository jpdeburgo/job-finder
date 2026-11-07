import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Job, StoreInfo } from "@/lib/types";
import { makeFinishedRun, makeJob, makeRun } from "@/test/factories";
import { HomeOverview } from "./HomeOverview";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

// Only the search panel fetches (GET /api/runs/latest, then polls a running search).
const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);
const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const store: StoreInfo = { backend: "local", description: "local Firestore stand-in at /repo/backend/local_firestore.json", emulator: false, envFile: null };

const jobs: Job[] = [
  makeJob({ id: "r1", title: "React Developer", status: "emailed", first_seen_at: "2026-11-05T13:00:00+00:00" }),
  makeJob({ id: "r2", title: "Node Engineer", status: "emailed", first_seen_at: "2026-11-01T13:00:00+00:00" }),
  makeJob({ id: "u1", title: "Python Developer", status: "unemailed", first_seen_at: "2026-11-06T13:00:00+00:00" }),
  makeJob({
    id: "a1",
    title: "Full Stack Engineer",
    company: "Accenture",
    status: "applied",
    first_seen_at: "2026-10-20T13:00:00+00:00",
    status_updated_at: "2026-11-03T09:00:00+00:00",
  }),
  makeJob({
    id: "i1",
    title: "Junior Java Developer",
    track: "Java growth track (entry-level / lower bar)",
    status: "interviewing",
    first_seen_at: "2026-10-10T13:00:00+00:00",
    status_updated_at: "2026-11-04T09:00:00+00:00",
  }),
];

beforeEach(() => {
  refresh.mockReset();
  fetchMock.mockReset();
  fetchMock.mockImplementation(async () => jsonResponse({ run: null }));
});

const totals = () => within(screen.getByRole("region", { name: "Totals" }));

describe("with tracked jobs", () => {
  it("shows how many jobs are tracked and which database they come from", () => {
    render(<HomeOverview jobs={jobs} store={store} />);
    expect(screen.getByRole("heading", { level: 1, name: "Your job search" })).toBeInTheDocument();
    expect(screen.getByText(/5 jobs tracked/)).toHaveTextContent("5 jobs tracked · reading the local file");
  });

  it("links each total to the tracker filtered to that status", () => {
    render(<HomeOverview jobs={jobs} store={store} />);
    const expected = [
      ["To review: 2. Show these jobs", "/jobs?status=emailed"],
      ["Applied: 1. Show these jobs", "/jobs?status=applied"],
      ["Interviewing: 1. Show these jobs", "/jobs?status=interviewing"],
      ["Offers: 0. Show these jobs", "/jobs?status=offer"],
    ];
    for (const [name, href] of expected) {
      expect(totals().getByRole("link", { name })).toHaveAttribute("href", href);
    }
  });

  it("flags matches whose digest didn't go out", () => {
    render(<HomeOverview jobs={jobs} store={store} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("1 match hasn't been emailed");
    expect(within(alert).getByRole("link", { name: "See them" })).toHaveAttribute("href", "/jobs?status=unemailed");
  });

  it("counts several unemailed matches", () => {
    const more = [...jobs, makeJob({ id: "u2", status: "unemailed" }), makeJob({ id: "u3", status: "unemailed" })];
    render(<HomeOverview jobs={more} store={store} />);
    expect(screen.getByRole("alert")).toHaveTextContent("3 matches haven't been emailed");
  });

  it("says when it's reading the Firestore emulator", () => {
    render(<HomeOverview jobs={jobs} store={{ ...store, backend: "firestore", emulator: true }} />);
    expect(screen.getByText(/5 jobs tracked/)).toHaveTextContent("reading the Firestore emulator");
  });

  it("shows a job without a posting URL as plain text", () => {
    const noUrl = makeJob({ id: "n1", title: "Mystery Role", url: null, first_seen_at: "2026-11-07T13:00:00+00:00" });
    render(<HomeOverview jobs={[noUrl]} store={store} />);
    const item = within(screen.getByRole("list", { name: "Latest matches" })).getByRole("listitem");
    expect(item).toHaveTextContent("Mystery Role");
    expect(within(item).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(/1 job tracked/)).toBeInTheDocument(); // singular
  });

  it("has no unemailed notice when everything went out", () => {
    render(<HomeOverview jobs={jobs.filter((job) => job.status !== "unemailed")} store={store} />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("lists the newest matches, linking to the postings", () => {
    render(<HomeOverview jobs={jobs} store={store} />);
    const list = within(screen.getByRole("list", { name: "Latest matches" }));
    const items = list.getAllByRole("listitem");
    expect(items.map((item) => within(item).getByRole("link").textContent)).toEqual([
      "Python Developer",
      "React Developer",
      "Node Engineer",
      "Full Stack Engineer",
      "Junior Java Developer",
    ]);
    expect(within(items[0]).getByRole("link")).toHaveAttribute("href", "https://insightglobal.com/jobs/u1");
    expect(within(items[0]).getByRole("link")).toHaveAttribute("target", "_blank");
    expect(items[0]).toHaveTextContent("Insight Global · Core · Found 2026-11-06");
    expect(items[0]).toHaveTextContent("Unemailed");
  });

  it("lists your latest status changes", () => {
    render(<HomeOverview jobs={jobs} store={store} />);
    const items = within(screen.getByRole("list", { name: "Recent activity" })).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Junior Java Developer");
    expect(items[0]).toHaveTextContent("Java · Updated 2026-11-04");
    expect(items[0]).toHaveTextContent("Interviewing");
    expect(items[1]).toHaveTextContent("Accenture · Core · Updated 2026-11-03");
  });

  it("explains the empty activity list", () => {
    render(<HomeOverview jobs={jobs.filter((job) => job.status === "emailed")} store={store} />);
    expect(screen.getByText(/Mark jobs applied, skipped, or interviewing in the tracker/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Recent activity" })).not.toBeInTheDocument();
  });
});

describe("with nothing tracked", () => {
  it("explains how it works instead of showing empty totals", () => {
    render(<HomeOverview jobs={[]} store={{ ...store, backend: "firestore", description: "Firestore project 'p'" }} />);
    expect(screen.getByText(/Nothing tracked yet/)).toHaveTextContent("Nothing tracked yet · reading the Firestore");
    expect(screen.getByText("Welcome to Job Finder")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").map((item) => item.querySelector("p")?.textContent)).toEqual([
      "Run a search",
      "Get the digest",
      "Track them",
    ]);
    expect(screen.queryByRole("region", { name: "Totals" })).not.toBeInTheDocument();
  });
});

describe("running a search", () => {
  it("has the Run search button", async () => {
    render(<HomeOverview jobs={jobs} store={store} />);
    expect(await screen.findByRole("button", { name: "Run search" })).toBeEnabled();
  });

  it("reloads the page's data when a search finishes", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url === "/api/runs/latest" ? jsonResponse({ run: makeRun() }) : jsonResponse({ run: makeFinishedRun() }),
    );
    render(<HomeOverview jobs={jobs} store={store} />);

    // The panel checks on a running search every 2s.
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1), { timeout: 5000 });
  }, 10_000);
});
