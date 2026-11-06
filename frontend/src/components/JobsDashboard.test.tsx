import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Job, StoreInfo } from "@/lib/types";
import { makeJob } from "@/test/factories";
import { setupUser } from "@/test/user";
import { JobsDashboard } from "./JobsDashboard";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

const store: StoreInfo = {
  backend: "local",
  description: "local Firestore stand-in at /repo/backend/local_firestore.json",
  emulator: false,
  envFile: "/repo/.env",
};

const react = makeJob({ id: "react", title: "React Developer", status: "emailed", last_seen_at: "2026-10-31T13:00:05+00:00" });
const python = makeJob({
  id: "python",
  title: "Senior Python Engineer",
  status: "applied",
  applied_at: "2026-11-01T09:30:00+00:00",
  notes: "Applied via IG site",
  matched_skills: ["Python", "AWS"],
  track: "Core matches (your main stack)",
  last_seen_at: "2026-10-30T13:00:05+00:00",
});
const java = makeJob({
  id: "java",
  company: "Accenture",
  is_remote: null, // the site didn't say (saved by --include-unmarked)
  title: "Junior Java Developer",
  status: "skipped",
  track: "Java growth track (entry-level / lower bar)",
  matched_skills: ["Java"],
  city: "Dallas",
  last_seen_at: "2026-10-29T13:00:05+00:00",
  gmail_message_id: null,
});
const jobs: Job[] = [react, python, java];

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function renderDashboard(initialJobs: Job[] = jobs) {
  return render(<JobsDashboard initialJobs={initialJobs} initialStore={store} />);
}

const row = (id: string) => within(screen.getByTestId(`job-row-${id}`));
const rowIds = () => screen.getAllByTestId(/^job-row-/).map((r) => r.dataset.testid);
const chips = () => within(screen.getByRole("radiogroup", { name: "Filter by status" }));

/** Pick an option from a Radix Select identified by its trigger. */
async function choose(user: ReturnType<typeof setupUser>, trigger: HTMLElement, option: string | RegExp) {
  await user.click(trigger);
  await user.click(await screen.findByRole("option", { name: option }));
}

beforeEach(() => {
  fetchMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("rendering", () => {
  it("shows the store banner", () => {
    renderDashboard();
    expect(screen.getByRole("status")).toHaveTextContent("Local file");
    expect(screen.getByRole("status")).toHaveTextContent("local Firestore stand-in at /repo/backend/local_firestore.json");
  });

  it("lists jobs newest-first", () => {
    renderDashboard();
    expect(rowIds()).toEqual(["job-row-react", "job-row-python", "job-row-java"]);
    expect(screen.getByText("3 tracked · 3 shown")).toBeInTheDocument();
  });

  it("shows each job's company", () => {
    renderDashboard();
    expect(row("java").getByText("Accenture")).toBeInTheDocument();
    expect(row("react").getByText("Insight Global")).toBeInTheDocument();
  });

  it("flags jobs whose remote status the site didn't give", () => {
    renderDashboard();
    const unmarked = row("java").getByText("Remote not stated");
    expect(unmarked).toHaveAttribute("title", expect.stringMatching(/Check the posting/));
    expect(row("react").getByText("Remote")).toBeInTheDocument();
    expect(row("react").queryByText("Remote not stated")).not.toBeInTheDocument();
  });

  it("links each job title to the posting in a new tab, safely", () => {
    renderDashboard();
    const link = row("react").getByRole("link", { name: /React Developer/ });
    expect(link).toHaveAttribute("href", "https://insightglobal.com/jobs/react");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows status counts as toggle chips", () => {
    renderDashboard();
    expect(chips().getByRole("radio", { name: /Emailed 1/ })).toBeInTheDocument();
    expect(chips().getByRole("radio", { name: /Applied 1/ })).toBeInTheDocument();
    expect(chips().getByRole("radio", { name: /Skipped 1/ })).toBeInTheDocument();
  });

  it("renders the current status in each row's select, even before hydration", () => {
    renderDashboard();
    expect(row("react").getByRole("combobox", { name: "Status for job react" })).toHaveTextContent("Emailed");
    expect(row("java").getByRole("combobox", { name: "Status for job java" })).toHaveTextContent("Skipped");
    expect(screen.getByRole("combobox", { name: "Status" })).toHaveTextContent("All statuses");
    expect(screen.getByRole("combobox", { name: "Sort" })).toHaveTextContent("Last seen (newest)");
  });

  it("shows the applied date for applied jobs and a button otherwise", () => {
    renderDashboard();
    expect(row("python").getByText("2026-11-01")).toBeInTheDocument();
    expect(row("react").getByRole("button", { name: "Mark applied" })).toBeEnabled();
  });

  it("says 'no match' when the filters exclude everything", async () => {
    const user = setupUser();
    renderDashboard();
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "zzz-no-such-job");
    expect(screen.getByText("No jobs match the current filters.")).toBeInTheDocument();
  });

  it("explains an empty database", () => {
    renderDashboard([]);
    expect(screen.getByText(/No jobs tracked yet/)).toBeInTheDocument();
  });
});

describe("filtering and sorting", () => {
  it("searches across title, skills, and city", async () => {
    const user = setupUser();
    renderDashboard();
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "aws");
    expect(rowIds()).toEqual(["job-row-python"]);

    await user.clear(screen.getByRole("searchbox", { name: "Search" }));
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "dallas");
    expect(rowIds()).toEqual(["job-row-java"]);
  });

  it("filters by status from the select", async () => {
    const user = setupUser();
    renderDashboard();
    await choose(user, screen.getByRole("combobox", { name: "Status" }), "Skipped");
    expect(rowIds()).toEqual(["job-row-java"]);
    expect(screen.getByRole("combobox", { name: "Status" })).toHaveTextContent("Skipped");

    await choose(user, screen.getByRole("combobox", { name: "Status" }), "All statuses");
    expect(rowIds()).toHaveLength(3);
  });

  it("filters by status from a chip, toggling it off again", async () => {
    const user = setupUser();
    renderDashboard();
    const chip = chips().getByRole("radio", { name: /Applied 1/ });
    await user.click(chip);
    expect(chip).toHaveAttribute("aria-checked", "true");
    expect(rowIds()).toEqual(["job-row-python"]);
    // The status select reflects the chip.
    expect(screen.getByRole("combobox", { name: "Status" })).toHaveTextContent("Applied");

    await user.click(chip);
    expect(chip).toHaveAttribute("aria-checked", "false");
    expect(rowIds()).toHaveLength(3);
  });

  it("filters by company, listing each company once", async () => {
    const user = setupUser();
    renderDashboard();
    const trigger = screen.getByRole("combobox", { name: "Company" });
    expect(trigger).toHaveTextContent("All companies");

    await user.click(trigger);
    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(["All companies", "Accenture", "Insight Global"]);
    await user.click(screen.getByRole("option", { name: "Accenture" }));
    expect(rowIds()).toEqual(["job-row-java"]);
    expect(trigger).toHaveTextContent("Accenture");

    await choose(user, trigger, "Insight Global");
    expect(rowIds()).toEqual(["job-row-react", "job-row-python"]);

    await choose(user, trigger, "All companies");
    expect(rowIds()).toHaveLength(3);
  });

  const remoteOptions = async (user: ReturnType<typeof setupUser>) => {
    await user.click(screen.getByRole("combobox", { name: "Remote" }));
    const options = (await screen.findAllByRole("option")).map((option) => option.textContent);
    await user.keyboard("{Escape}");
    return options;
  };

  it("filters by remote status", async () => {
    const user = setupUser();
    renderDashboard();
    const trigger = screen.getByRole("combobox", { name: "Remote" });
    expect(trigger).toHaveTextContent("Any");

    await choose(user, trigger, "Remote not stated");
    expect(rowIds()).toEqual(["job-row-java"]);
    await choose(user, trigger, "Remote");
    expect(rowIds()).toEqual(["job-row-react", "job-row-python"]);
    await choose(user, trigger, "Any");
    expect(rowIds()).toHaveLength(3);
  });

  it("only offers the remote statuses the jobs have", async () => {
    const user = setupUser();
    // What a default run saves: remote jobs only.
    const { unmount } = renderDashboard([react, python]);
    expect(await remoteOptions(user)).toEqual(["Any", "Remote"]);
    unmount();

    // --include-unmarked adds "Remote not stated"; still no "Not remote".
    const second = renderDashboard();
    expect(await remoteOptions(user)).toEqual(["Any", "Remote", "Remote not stated"]);
    second.unmount();

    // Only a site with remote-only turned off saves jobs marked not remote.
    renderDashboard([...jobs, makeJob({ id: "office", is_remote: false })]);
    expect(await remoteOptions(user)).toEqual(["Any", "Remote", "Remote not stated", "Not remote"]);
  });

  it("combines the company filter with the others", async () => {
    const user = setupUser();
    renderDashboard();
    await choose(user, screen.getByRole("combobox", { name: "Company" }), "Insight Global");
    await choose(user, screen.getByRole("combobox", { name: "Status" }), "Applied");
    expect(rowIds()).toEqual(["job-row-python"]);
    await choose(user, screen.getByRole("combobox", { name: "Status" }), "Skipped");
    expect(screen.getByText("No jobs match the current filters.")).toBeInTheDocument();
  });

  it("filters by track", async () => {
    const user = setupUser();
    renderDashboard();
    await choose(user, screen.getByRole("combobox", { name: "Track" }), "Java growth track (entry-level / lower bar)");
    expect(rowIds()).toEqual(["job-row-java"]);
  });

  it("sorts by title", async () => {
    const user = setupUser();
    renderDashboard();
    await choose(user, screen.getByRole("combobox", { name: "Sort" }), "Title (A–Z)");
    expect(rowIds()).toEqual(["job-row-java", "job-row-react", "job-row-python"]);
  });
});

describe("updating jobs", () => {
  it("changes a status through the row dropdown and shows the server's result", async () => {
    const user = setupUser();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ job: { ...react, status: "interviewing", status_updated_at: "2026-11-02T10:00:00+00:00" } }),
    );
    renderDashboard();

    await choose(user, row("react").getByRole("combobox", { name: "Status for job react" }), "Interviewing");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/jobs/react",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ status: "interviewing" }) }),
    );
    await waitFor(() => expect(row("react").getByRole("combobox")).toHaveTextContent("Interviewing"));
    expect(chips().getByRole("radio", { name: /Interviewing 1/ })).toBeInTheDocument();
  });

  it("marks a job applied from the row button", async () => {
    const user = setupUser();
    fetchMock.mockResolvedValueOnce(jsonResponse({ job: { ...react, status: "applied", applied_at: "2026-11-02T10:00:00+00:00" } }));
    renderDashboard();

    await user.click(row("react").getByRole("button", { name: "Mark applied" }));

    expect(fetchMock).toHaveBeenCalledWith("/api/jobs/react", expect.objectContaining({ body: JSON.stringify({ status: "applied" }) }));
    await waitFor(() => expect(row("react").getByText("2026-11-02")).toBeInTheDocument());
  });

  it("shows an error and keeps the old status when the update fails", async () => {
    const user = setupUser();
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "Job react is not in the store" }, 404));
    renderDashboard();

    await choose(user, row("react").getByRole("combobox"), "Offer");

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not update job react: Job react is not in the store");
    expect(row("react").getByRole("combobox")).toHaveTextContent("Emailed");
  });
});

describe("details drawer", () => {
  it("opens with every link, the fields, and quick actions", async () => {
    const user = setupUser();
    renderDashboard();

    await user.click(row("python").getByRole("button", { name: "Show details for Senior Python Engineer" }));
    const dialog = await screen.findByRole("dialog");
    const details = within(dialog);

    expect(details.getByRole("heading", { name: /Senior Python Engineer/ })).toBeInTheDocument();
    const links = details.getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "https://insightglobal.com/jobs/python", // title
      "https://insightglobal.com/jobs/python", // "Open & apply"
      "https://insightglobal.com/jobs/python", // "Job posting"
      "https://mail.google.com/mail/u/0/#all/19a1b2c3d4e5f607",
      "https://insightglobal.com/jobs/search/all/all?keyword=Senior%20Python%20Engineer",
    ]);
    for (const link of links) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    }
    expect(details.getByText("Python")).toBeInTheDocument();
    expect(details.getByText("AWS")).toBeInTheDocument();
    expect(details.getByText("Core matches (your main stack)")).toBeInTheDocument();
    expect(details.getByRole("button", { name: "Mark applied" })).toBeDisabled(); // already applied
  });

  it("saves notes and keeps the drawer open with the saved value", async () => {
    const user = setupUser();
    fetchMock.mockResolvedValueOnce(jsonResponse({ job: { ...python, notes: "Recruiter: Sam" } }));
    renderDashboard();
    await user.click(row("python").getByRole("button", { name: /Show details/ }));
    // The drawer remounts once notes are saved, so always re-query it.
    const details = () => within(screen.getByRole("dialog"));

    const notes = details().getByRole("textbox", { name: "Notes for job python" });
    expect(notes).toHaveValue("Applied via IG site");
    expect(details().getByRole("button", { name: "Save notes" })).toBeDisabled();
    await user.clear(notes);
    await user.type(notes, "Recruiter: Sam");
    expect(details().getByText("Unsaved changes")).toBeInTheDocument();
    await user.click(details().getByRole("button", { name: "Save notes" }));

    expect(fetchMock).toHaveBeenCalledWith("/api/jobs/python", expect.objectContaining({ body: JSON.stringify({ notes: "Recruiter: Sam" }) }));
    await waitFor(() => expect(details().getByRole("textbox", { name: "Notes for job python" })).toHaveValue("Recruiter: Sam"));
    expect(details().getByRole("button", { name: "Save notes" })).toBeDisabled();
    expect(details().queryByText("Unsaved changes")).not.toBeInTheDocument();
  });

  it("offers Interviewing and Skip quick actions that update the row too", async () => {
    const user = setupUser();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ job: { ...react, status: "interviewing" } }))
      .mockResolvedValueOnce(jsonResponse({ job: { ...react, status: "skipped" } }));
    renderDashboard();
    await user.click(row("react").getByRole("button", { name: /Show details/ }));
    const details = () => within(screen.getByRole("dialog"));

    await user.click(details().getByRole("button", { name: "Interviewing" }));
    expect(fetchMock).toHaveBeenLastCalledWith("/api/jobs/react", expect.objectContaining({ body: JSON.stringify({ status: "interviewing" }) }));
    await waitFor(() => expect(details().getByRole("button", { name: "Interviewing" })).toBeDisabled());
    // The page behind the open drawer is aria-hidden, hence `hidden: true`.
    expect(row("react").getByRole("combobox", { hidden: true })).toHaveTextContent("Interviewing");

    await user.click(details().getByRole("button", { name: "Skip" }));
    expect(fetchMock).toHaveBeenLastCalledWith("/api/jobs/react", expect.objectContaining({ body: JSON.stringify({ status: "skipped" }) }));
    await waitFor(() => expect(details().getByRole("button", { name: "Skip" })).toBeDisabled());
    expect(details().getByRole("button", { name: "Interviewing" })).toBeEnabled();
  });

  it("shows the company first in the details summary", async () => {
    const user = setupUser();
    renderDashboard();
    await user.click(row("java").getByRole("button", { name: /Show details/ }));
    const details = within(await screen.findByRole("dialog"));
    expect(details.getByText(/^Accenture · Dallas, TX · Contract/)).toBeInTheDocument();
    expect(details.getByText("Remote not stated")).toBeInTheDocument();
  });

  it("says so when a job has no links", async () => {
    const user = setupUser();
    renderDashboard([makeJob({ id: "bare", job_id: "bare", title: null, url: null, gmail_message_id: null })]);
    await user.click(row("bare").getByRole("button", { name: "Show details for bare" }));
    const details = within(await screen.findByRole("dialog"));
    expect(details.getByText("No links were captured for this job.")).toBeInTheDocument();
    expect(details.queryByRole("link")).not.toBeInTheDocument();
    expect(details.getByRole("button", { name: "Mark applied" })).toBeEnabled();
  });

  it("closes with the close button and with Escape", async () => {
    const user = setupUser();
    renderDashboard();
    await user.click(row("java").getByRole("button", { name: /Show details/ }));
    expect(within(screen.getByRole("dialog")).queryByText("Digest email")).not.toBeInTheDocument(); // no gmail id
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await user.click(row("java").getByRole("button", { name: /Show details/ }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("refresh", () => {
  it("reloads jobs and the store banner from the API", async () => {
    const user = setupUser();
    const firestore: StoreInfo = { backend: "firestore", description: "Firestore project 'p'", emulator: false, envFile: null };
    fetchMock.mockResolvedValueOnce(jsonResponse({ store: firestore, jobs: [makeJob({ id: "fresh", title: "Fresh Job" })] }));
    renderDashboard();

    await user.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("Fresh Job")).toBeInTheDocument();
    expect(screen.queryByTestId("job-row-react")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Firestore project 'p'");
  });

  it("keeps the selected remote status listed after a refresh removes its last job", async () => {
    const user = setupUser();
    fetchMock.mockResolvedValueOnce(jsonResponse({ store, jobs: [react] }));
    renderDashboard();
    const trigger = screen.getByRole("combobox", { name: "Remote" });
    await choose(user, trigger, "Remote not stated");
    expect(rowIds()).toEqual(["job-row-java"]);

    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("No jobs match the current filters.")).toBeInTheDocument();

    await user.click(trigger);
    const options = (await screen.findAllByRole("option")).map((option) => option.textContent);
    expect(options).toEqual(["Any", "Remote", "Remote not stated"]);
    await user.click(screen.getByRole("option", { name: "Any" }));
    expect(rowIds()).toEqual(["job-row-react"]);
  });

  it("reports refresh failures", async () => {
    const user = setupUser();
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "boom" }, 500));
    renderDashboard();
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not refresh: boom");
    expect(screen.getByTestId("job-row-react")).toBeInTheDocument();
  });
});
