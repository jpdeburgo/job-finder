import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_FILTERS } from "@/lib/jobs";
import type { Job, StoreInfo } from "@/lib/types";
import { makeFinishedRun, makeJob, makeRun } from "@/test/factories";
import { setupUser } from "@/test/user";
import { JobsDashboard } from "./JobsDashboard";

// Job calls go to fetchMock (tests queue its responses); the search panel's
// /api/runs calls go to runsApiMock, and Refresh's reassessment
// (/api/jobs/reassess) to reassessMock, so they never consume a queued response.
const fetchMock = vi.fn();
const runsApiMock = vi.fn();
const reassessMock = vi.fn();
vi.stubGlobal("fetch", (...args: [string, RequestInit?]) => {
  const url = String(args[0]);
  if (url.startsWith("/api/runs")) return runsApiMock(...args);
  if (url === "/api/jobs/reassess") return reassessMock(...args);
  return fetchMock(...args);
});

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
  runsApiMock.mockReset();
  runsApiMock.mockImplementation(async () => jsonResponse({ run: null })); // no search run yet
  reassessMock.mockReset();
  reassessMock.mockImplementation(async () => jsonResponse(summary()));
});

const summary = (overrides = {}) => ({
  total_jobs: 3,
  reassessed: 3,
  changed: 1,
  no_longer_match: 0,
  fetched: 0,
  unavailable: 0,
  skills_source: "saved",
  ...overrides,
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
    expect(screen.getByText("3 tracked · 3 match")).toBeInTheDocument();
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

  it("filters by one or several companies, listing each company once", async () => {
    const user = setupUser();
    renderDashboard([...jobs, makeJob({ id: "nvidia", company: "NVIDIA", title: "CUDA Engineer" })]);
    const trigger = screen.getByRole("button", { name: "Company" });
    expect(trigger).toHaveTextContent("All companies");

    await user.click(trigger);
    const options = await screen.findAllByRole("menuitemcheckbox");
    // Alphabetical, with how many jobs each has; no any/all choice (a job has one company).
    expect(options.map((option) => option.getAttribute("aria-label"))).toEqual([
      "Accenture, 1 job", "Insight Global, 2 jobs", "NVIDIA, 1 job",
    ]);
    expect(screen.queryByRole("menuitemradio")).not.toBeInTheDocument();

    await user.click(screen.getByRole("menuitemcheckbox", { name: "Accenture, 1 job" }));
    expect(rowIds()).toEqual(["job-row-java"]);
    expect(trigger).toHaveTextContent("Accenture");

    // The menu stays open: pick another.
    await user.click(screen.getByRole("menuitemcheckbox", { name: "NVIDIA, 1 job" }));
    expect(rowIds()).toEqual(["job-row-nvidia", "job-row-java"]); // newest first
    expect(trigger).toHaveTextContent("Accenture or NVIDIA");

    await user.click(screen.getByRole("menuitemcheckbox", { name: "Accenture, 1 job" }));
    expect(rowIds()).toEqual(["job-row-nvidia"]);

    await user.click(screen.getByRole("menuitem", { name: "Clear companies" }));
    expect(rowIds()).toHaveLength(4);
    expect(trigger).toHaveTextContent("All companies");
  });

  it("finds a company by typing in the company filter", async () => {
    const user = setupUser();
    renderDashboard([
      ...jobs,
      makeJob({ id: "nvidia", company: "NVIDIA", title: "CUDA Engineer" }),
      makeJob({ id: "doordash", company: "Doordashusa", title: "Backend Engineer" }),
      makeJob({ id: "databricks", company: "Databricks", title: "Platform Engineer" }),
    ]);
    const trigger = screen.getByRole("button", { name: "Company" });

    await user.click(trigger);
    const search = screen.getByRole("searchbox", { name: "Search companies" });
    await waitFor(() => expect(search).toHaveFocus());

    await user.keyboard("door");
    expect(screen.getAllByRole("menuitemcheckbox").map((option) => option.getAttribute("aria-label"))).toEqual([
      "Doordashusa, 1 job",
    ]);
    await user.keyboard("{Enter}");
    expect(rowIds()).toEqual(["job-row-doordash"]);
    expect(trigger).toHaveTextContent("Doordashusa");

    // Straight on to the next one (a later word in the name counts too).
    await user.keyboard("glob{Enter}");
    expect(trigger).toHaveTextContent("Doordashusa or Insight Global");
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
    await user.click(screen.getByRole("button", { name: "Company" }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Insight Global, 2 jobs" }));
    await user.keyboard("{Escape}");
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

  it("filters by several skills: any of them, or all", async () => {
    const user = setupUser();
    renderDashboard();
    const trigger = screen.getByRole("button", { name: "Skills" });
    expect(trigger).toHaveTextContent("Any skill");

    await user.click(trigger);
    const options = await screen.findAllByRole("menuitemcheckbox");
    // Every matched skill once, A–Z, with how many jobs have it.
    expect(options.map((option) => option.getAttribute("aria-label"))).toEqual([
      "AWS, 1 job", "Java, 1 job", "Python, 1 job", "React, 1 job", "TypeScript, 1 job",
    ]);

    // The menu stays open while you pick.
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Python, 1 job" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Java, 1 job" }));
    expect(screen.getByRole("menuitemcheckbox", { name: "Python, 1 job" })).toHaveAttribute("aria-checked", "true");
    expect(rowIds()).toEqual(["job-row-python", "job-row-java"]);
    expect(trigger).toHaveTextContent("Python or Java");

    await user.click(screen.getByRole("menuitemradio", { name: "All of the selected skills" }));
    expect(screen.getByText("No jobs match the current filters.")).toBeInTheDocument();
    expect(trigger).toHaveTextContent("Python and Java");

    await user.click(screen.getByRole("menuitemcheckbox", { name: "Java, 1 job" }));
    expect(rowIds()).toEqual(["job-row-python"]);

    await user.click(screen.getByRole("menuitem", { name: "Clear skills" }));
    expect(rowIds()).toEqual(["job-row-react", "job-row-python", "job-row-java"]);
    expect(trigger).toHaveTextContent("Any skill");
  });

  it("sorts by title", async () => {
    const user = setupUser();
    renderDashboard();
    await choose(user, screen.getByRole("combobox", { name: "Sort" }), "Title (A–Z)");
    expect(rowIds()).toEqual(["job-row-java", "job-row-react", "job-row-python"]);
  });

  it("sorts by best fit, unscored jobs last", async () => {
    const user = setupUser();
    renderDashboard([
      makeJob({ id: "unscored", title: "Old", fit_score: null, last_seen_at: "2026-11-06T13:00:00+00:00" }),
      makeJob({ id: "weak", title: "Weak", fit_score: 30, last_seen_at: "2026-11-05T13:00:00+00:00" }),
      makeJob({ id: "strong", title: "Strong", fit_score: 88, last_seen_at: "2026-11-01T13:00:00+00:00" }),
    ]);

    await choose(user, screen.getByRole("combobox", { name: "Sort" }), "Best fit");

    expect(rowIds()).toEqual(["job-row-strong", "job-row-weak", "job-row-unscored"]);
  });

  const salaryJobs = () => [
    makeJob({ id: "unlisted", title: "Unlisted", salary_low: 0, salary_high: 0, salary_period: null, last_seen_at: "2026-11-06T13:00:00+00:00" }),
    makeJob({ id: "from", title: "From only", salary_low: 140000, salary_high: 0, salary_period: "year", last_seen_at: "2026-11-01T13:00:00+00:00" }),
    // $55 - $65/hr: $114,400 - $135,200 a year.
    makeJob({ id: "range", title: "Range", salary_low: 55, salary_high: 65, salary_period: "hour", last_seen_at: "2026-11-02T13:00:00+00:00" }),
    makeJob({ id: "monthly", title: "Monthly", salary_low: 1200, salary_high: 3000, salary_period: "month", last_seen_at: "2026-11-03T13:00:00+00:00" }),
  ];

  it("sorts by salary with \"Not listed\" jobs at the bottom", async () => {
    const user = setupUser();
    renderDashboard(salaryJobs());
    expect(rowIds()[0]).toBe("job-row-unlisted"); // newest first by default

    await choose(user, screen.getByRole("combobox", { name: "Sort" }), "Salary (highest)");

    expect(rowIds()).toEqual(["job-row-from", "job-row-range", "job-row-monthly", "job-row-unlisted"]);
    expect(row("unlisted").getByText("Not listed")).toBeInTheDocument();
  });

  it("sorts by lowest salary, per year, with \"Not listed\" jobs still at the bottom", async () => {
    const user = setupUser();
    renderDashboard(salaryJobs());

    await choose(user, screen.getByRole("combobox", { name: "Sort" }), "Salary (lowest)");

    expect(rowIds()).toEqual(["job-row-monthly", "job-row-range", "job-row-from", "job-row-unlisted"]);
    expect(row("monthly").getByText("$1,200 - $3,000/mo")).toBeInTheDocument();
  });

  const tiedJobs = () => {
    const job = (id: string, score: number, salary: number) =>
      makeJob({ id, title: id, score, salary_low: salary, salary_high: 0, salary_period: salary ? "year" : null });
    return [job("two-low", 2, 80000), job("three-low", 3, 70000), job("two-high", 2, 150000), job("three-high", 3, 120000)];
  };

  it("sorts by skill matches, then by salary among jobs with the same number", async () => {
    const user = setupUser();
    renderDashboard(tiedJobs());
    const thenBy = screen.getByRole("combobox", { name: "Then by" });
    expect(thenBy).toHaveTextContent("Nothing else");

    await choose(user, screen.getByRole("combobox", { name: "Sort" }), "Skill matches (most)");
    await choose(user, thenBy, "Salary (highest)");
    expect(rowIds()).toEqual(["job-row-three-high", "job-row-three-low", "job-row-two-high", "job-row-two-low"]);

    await choose(user, thenBy, "Salary (lowest)");
    expect(rowIds()).toEqual(["job-row-three-low", "job-row-three-high", "job-row-two-low", "job-row-two-high"]);
  });

  it("keeps \"Then by\" when the first sort changes, unless it's now the same sort", async () => {
    const user = setupUser();
    renderDashboard(tiedJobs());
    const sort = screen.getByRole("combobox", { name: "Sort" });
    const thenBy = screen.getByRole("combobox", { name: "Then by" });
    await choose(user, thenBy, "Salary (lowest)");

    await choose(user, sort, "Best fit");
    expect(thenBy).toHaveTextContent("Salary (lowest)");

    // The same sort in the other direction makes no sense as a tie-breaker.
    await choose(user, sort, "Salary (highest)");
    expect(thenBy).toHaveTextContent("Nothing else");
    await user.click(thenBy);
    expect(screen.queryByRole("option", { name: "Salary (lowest)" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Last seen (newest)" })).not.toBeInTheDocument(); // ties end newest first anyway
  });

  it("filters to jobs with a salary listed, or only the \"Not listed\" ones", async () => {
    const user = setupUser();
    renderDashboard(salaryJobs());
    const trigger = screen.getByRole("combobox", { name: "Salary" });
    expect(trigger).toHaveTextContent("Any");

    await choose(user, trigger, "Listed");
    expect(rowIds()).toEqual(["job-row-monthly", "job-row-range", "job-row-from"]);

    await choose(user, trigger, "Not listed");
    expect(rowIds()).toEqual(["job-row-unlisted"]);

    // Together with the lowest-first sort: the lowest paid jobs, no "Not listed" in the way.
    await choose(user, trigger, "Listed");
    await choose(user, screen.getByRole("combobox", { name: "Sort" }), "Salary (lowest)");
    expect(rowIds()).toEqual(["job-row-monthly", "job-row-range", "job-row-from"]);

    await choose(user, trigger, "Any");
    expect(rowIds()).toHaveLength(4);
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

  it("marks a job on-site from the details drawer, and back to what the site says", async () => {
    const user = setupUser();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ job: { ...react, work_arrangement: "on_site", is_remote: false, site_is_remote: true } }),
    );
    renderDashboard();
    expect(row("react").getByText("Remote")).toBeInTheDocument();

    await user.click(row("react").getByRole("button", { name: /Show details/ }));
    const drawer = () => within(screen.getByRole("dialog"));
    const select = () => drawer().getByRole("combobox", { name: "Work arrangement for job react" });
    expect(select()).toHaveTextContent("As the site says (Remote)");
    await choose(user, select(), "On-site");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/jobs/react",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ work_arrangement: "on_site" }) }),
    );
    await waitFor(() => expect(row("react").getByText("On-site (you)")).toBeInTheDocument());
    expect(select()).toHaveTextContent("On-site");

    fetchMock.mockResolvedValueOnce(jsonResponse({ job: react }));
    await choose(user, select(), "As the site says (Remote)");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/jobs/react",
      expect.objectContaining({ body: JSON.stringify({ work_arrangement: null }) }),
    );
    await waitFor(() => expect(row("react").getByText("Remote")).toBeInTheDocument());
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

  it("explains the fit score", async () => {
    const user = setupUser();
    renderDashboard([
      makeJob({
        id: "fit",
        title: "Full Stack Engineer",
        fit_score: 66,
        fit_breakdown: { skills: 48, role: 30, experience: -8, remote: 0, stack: -4 },
        fit_reasons: ["Skills: Python, React (2 core)", "Asks for 6+ yrs; you have 5 (1 short)"],
      }),
    ]);
    expect(row("fit").getByLabelText("Fit 66 of 100, Good")).toHaveTextContent("66 · Good");

    await user.click(row("fit").getByRole("button", { name: /Show details/ }));
    const fit = within(within(await screen.findByRole("dialog")).getByTestId("fit-details"));

    expect(fit.getByText("66 · Good")).toBeInTheDocument();
    expect(fit.getByText("+48")).toBeInTheDocument();
    expect(fit.getByText("+30")).toBeInTheDocument();
    expect(fit.getByText("−8")).toBeInTheDocument();
    expect(fit.getByText("−4")).toBeInTheDocument();
    expect(fit.getByText("Asks for 6+ yrs; you have 5 (1 short)")).toBeInTheDocument();
  });

  it("says why a job no longer matches your skills, with a link to change them", async () => {
    const user = setupUser();
    renderDashboard([
      makeJob({ id: "stale", matches_skills: false, skills_mismatch_reason: "it mentions only SQL; a match needs 2 of your skills" }),
      makeJob({ id: "fine", title: "Fine Job", matches_skills: true }),
    ]);
    expect(row("fine").queryByText("No longer matches your skills")).not.toBeInTheDocument();

    await user.click(row("stale").getByRole("button", { name: /Show details/ }));
    const details = within(await screen.findByRole("dialog"));
    expect(details.getByTestId("skills-mismatch")).toHaveTextContent(
      "No longer matches your skills: it mentions only SQL; a match needs 2 of your skills. Change them on the Skills page.",
    );
    expect(details.getByRole("link", { name: "Skills page" })).toHaveAttribute("href", "/skills");
  });

  it("says why a job listed as remote was marked not remote", async () => {
    const user = setupUser();
    renderDashboard([
      makeJob({ id: "onsite", is_remote: false, not_remote_reason: 'its description: "must be onsite in Plano"' }),
      makeJob({ id: "remote", is_remote: true }),
    ]);

    await user.click(row("onsite").getByRole("button", { name: /Show details/ }));
    const details = within(await screen.findByRole("dialog"));
    expect(details.getByText("Not remote")).toBeInTheDocument();
    expect(details.getByTestId("not-remote-reason")).toHaveTextContent(
      'Listed as remote, but its description: "must be onsite in Plano".',
    );
  });

  it("shows a dash, and no fit section, for jobs saved before the fit score existed", async () => {
    const user = setupUser();
    renderDashboard([makeJob({ id: "old", fit_score: null, fit_breakdown: {}, fit_reasons: [] })]);
    expect(row("old").getByTitle(/Not scored/)).toHaveTextContent("—");

    await user.click(row("old").getByRole("button", { name: /Show details/ }));
    expect(within(await screen.findByRole("dialog")).queryByTestId("fit-details")).not.toBeInTheDocument();
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
    expect(screen.getAllByRole("status")[0]).toHaveTextContent("Firestore project 'p'");
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

  it("re-scores the saved jobs against your skills first, then reloads them", async () => {
    const user = setupUser();
    let finishReassess: (response: Response) => void = () => {};
    reassessMock.mockImplementation(() => new Promise<Response>((resolve) => (finishReassess = resolve)));
    const rescored = makeJob({
      id: "react",
      title: "React Developer",
      matches_skills: false,
      skills_mismatch_reason: "it doesn't mention any of your skills",
    });
    fetchMock.mockResolvedValueOnce(jsonResponse({ store, jobs: [rescored] }));
    renderDashboard();

    await user.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByRole("button", { name: "Reassessing…" })).toBeDisabled();
    expect(screen.getByText(/Re-scoring your saved jobs against your skills/)).toBeInTheDocument();
    expect(reassessMock).toHaveBeenCalledWith("/api/jobs/reassess", { method: "POST" });
    expect(fetchMock).not.toHaveBeenCalled(); // reassess first, then reload

    finishReassess(jsonResponse(summary({ changed: 2, no_longer_match: 1, fetched: 3, unavailable: 1 })));

    const notice = await screen.findByTestId("reassess-notice");
    expect(notice).toHaveTextContent("Reassessed 3 jobs against your skills");
    expect(notice).toHaveTextContent("2 jobs changed; 1 no longer matches (marked in the list).");
    expect(notice).toHaveTextContent("Loaded 3 job descriptions from the job sites");
    expect(notice).toHaveTextContent("1 job couldn't be reassessed");
    const badge = await row("react").findByText("No longer matches your skills");
    expect(badge).toHaveAttribute("title", "No longer matches your skills: it doesn't mention any of your skills");
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();

    await user.click(within(notice).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByTestId("reassess-notice")).not.toBeInTheDocument();
  });

  it("still reloads when the search API isn't running, and says so", async () => {
    const user = setupUser();
    reassessMock.mockImplementation(async () =>
      jsonResponse({ error: "The search API isn't reachable at http://127.0.0.1:8000. Start it with ..." }, 503),
    );
    fetchMock.mockResolvedValueOnce(jsonResponse({ store, jobs: [makeJob({ id: "fresh", title: "Fresh Job" })] }));
    renderDashboard();

    await user.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("Fresh Job")).toBeInTheDocument();
    const notice = screen.getByTestId("reassess-notice");
    expect(notice).toHaveAttribute("role", "alert");
    expect(notice).toHaveTextContent("Jobs reloaded, but not reassessed against your skills");
    expect(notice).toHaveTextContent("Re-scoring needs the search API. The search API isn't reachable");
  });

  it("doesn't reassess again after a search, which already did", async () => {
    const running = makeRun();
    runsApiMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/runs" && init?.method === "POST") return jsonResponse({ run: running }, 202);
      if (url === "/api/runs/abc123") return jsonResponse({ run: makeFinishedRun() });
      return jsonResponse({ run: null });
    });
    fetchMock.mockResolvedValueOnce(jsonResponse({ store, jobs: [makeJob({ id: "fresh", title: "Fresh Job" })] }));
    const user = setupUser();
    renderDashboard();

    await user.click(await screen.findByRole("button", { name: "Run search" }));

    expect(await screen.findByText("Fresh Job", {}, { timeout: 5000 })).toBeInTheDocument();
    expect(reassessMock).not.toHaveBeenCalled();
  }, 10_000);
});

describe("running a search", () => {
  it("starts a search and reloads the jobs when it finishes", async () => {
    const user = setupUser();
    const running = makeRun();
    const done = makeFinishedRun();
    runsApiMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/runs" && init?.method === "POST") return jsonResponse({ run: running }, 202);
      if (url === "/api/runs/abc123") return jsonResponse({ run: done });
      return jsonResponse({ run: null });
    });
    fetchMock.mockResolvedValueOnce(jsonResponse({ store, jobs: [makeJob({ id: "fresh", title: "Fresh Job" })] }));
    renderDashboard();

    await user.click(await screen.findByRole("button", { name: "Run search" }));
    expect(screen.getByRole("button", { name: "Searching…" })).toBeDisabled();

    // The panel checks on the run every 2s; once it's done, the table reloads.
    expect(await screen.findByText("Fresh Job", {}, { timeout: 5000 })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/jobs", { cache: "no-store" });
    expect(screen.getByText(/4 matches, 1 new\. Emailed 1 job\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run search" })).toBeEnabled();
  }, 10_000);
});

describe("status in the address bar", () => {
  beforeEach(() => window.history.replaceState(null, "", "/jobs"));

  it("starts filtered when opened from a home-screen link (/jobs?status=applied)", () => {
    window.history.replaceState(null, "", "/jobs?status=applied");
    render(<JobsDashboard initialJobs={jobs} initialStore={store} initialFilters={{ ...DEFAULT_FILTERS, status: "applied" }} />);
    expect(rowIds()).toEqual(["job-row-python"]);
    expect(screen.getByRole("combobox", { name: "Status" })).toHaveTextContent("Applied");
    expect(window.location.search).toBe("?status=applied");
  });

  it("keeps ?status= in step with the status filter", async () => {
    const user = setupUser();
    renderDashboard();
    expect(window.location.search).toBe("");

    await user.click(chips().getByRole("radio", { name: /Skipped 1/ }));
    expect(window.location.pathname + window.location.search).toBe("/jobs?status=skipped");

    await choose(user, screen.getByRole("combobox", { name: "Status" }), "All statuses");
    expect(window.location.pathname + window.location.search).toBe("/jobs");
  });

  it("leaves other query parameters alone", async () => {
    window.history.replaceState(null, "", "/jobs?utm=digest");
    const user = setupUser();
    renderDashboard();
    await user.click(chips().getByRole("radio", { name: /Applied 1/ }));
    expect(new URLSearchParams(window.location.search).get("utm")).toBe("digest");
    expect(new URLSearchParams(window.location.search).get("status")).toBe("applied");
  });
});


// Paging mounts a fresh page of rows (each with its own dropdowns) per step,
// which is slow in jsdom, though instant in a browser.
describe("pagination", { timeout: 20_000 }, () => {
  // 60 jobs, newest first: job-01 is the most recently seen.
  const many = Array.from({ length: 60 }, (_, index) => {
    const n = String(index + 1).padStart(2, "0");
    const minute = String(59 - index).padStart(2, "0");
    return makeJob({ id: `job-${n}`, title: `Job ${n}`, last_seen_at: `2026-11-01T10:${minute}:00+00:00` });
  });
  const pager = () => within(screen.getByRole("navigation", { name: "Pagination" }));

  beforeEach(() => {
    window.history.replaceState(null, "", "/jobs");
  });

  it("shows 25 jobs a page and moves between pages", async () => {
    const user = setupUser();
    renderDashboard(many);

    expect(rowIds()).toHaveLength(25);
    expect(rowIds()[0]).toBe("job-row-job-01");
    expect(screen.getByText("Showing 1–25 of 60 jobs")).toBeInTheDocument();
    expect(pager().getByRole("button", { name: "Page 1" })).toHaveAttribute("aria-current", "page");
    expect(pager().getByRole("button", { name: "Previous page" })).toBeDisabled();

    await user.click(pager().getByRole("button", { name: "Next page" }));
    expect(rowIds()[0]).toBe("job-row-job-26");
    expect(screen.getByText("Showing 26–50 of 60 jobs")).toBeInTheDocument();
    expect(window.location.search).toBe("?page=2");

    await user.click(pager().getByRole("button", { name: "Last page" }));
    expect(rowIds()).toHaveLength(10);
    expect(screen.getByText("Showing 51–60 of 60 jobs")).toBeInTheDocument();
    expect(pager().getByRole("button", { name: "Next page" })).toBeDisabled();

    await user.click(pager().getByRole("button", { name: "Page 1" }));
    expect(rowIds()[0]).toBe("job-row-job-01");
    expect(window.location.search).toBe("");
  });

  it("changes the page size and starts again at page 1", async () => {
    const user = setupUser();
    renderDashboard(many);
    await user.click(pager().getByRole("button", { name: "Page 2" }));

    await choose(user, screen.getByRole("combobox", { name: "Rows per page" }), "50");

    expect(rowIds()).toHaveLength(50);
    expect(rowIds()[0]).toBe("job-row-job-01");
    expect(screen.getByText("Showing 1–50 of 60 jobs")).toBeInTheDocument();
    expect(window.location.search).toBe("?per_page=50");
  });

  it("goes back to page 1 when the filters or sort change", async () => {
    const user = setupUser();
    renderDashboard(many);
    await user.click(pager().getByRole("button", { name: "Page 3" }));

    await user.type(screen.getByRole("searchbox", { name: "Search" }), "Job 3");

    // "Job 30" to "Job 39", from the top: page 3 would be past the end.
    expect(rowIds()).toEqual(Array.from({ length: 10 }, (_, index) => `job-row-job-${30 + index}`));
    expect(screen.getByText("Showing 1–10 of 10 jobs")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Pagination" })).not.toBeInTheDocument(); // one page

    // Sorting starts over too.
    await user.clear(screen.getByRole("searchbox", { name: "Search" }));
    await user.click(pager().getByRole("button", { name: "Page 2" }));
    await choose(user, screen.getByRole("combobox", { name: "Sort" }), "Title (A–Z)");
    expect(screen.getByText("Showing 1–25 of 60 jobs")).toBeInTheDocument();
  });

  it("opens on the page in the address", () => {
    render(<JobsDashboard initialJobs={many} initialStore={store} initialPage={2} initialPageSize={50} />);

    expect(rowIds()).toHaveLength(10);
    expect(screen.getByText("Showing 51–60 of 60 jobs")).toBeInTheDocument();
  });

  it("shows the last page that has jobs when the page empties", async () => {
    const user = setupUser();
    // 26 "emailed" jobs: page 2 holds one. Skipping it moves it out of the filter.
    const emailed = many.slice(0, 26).map((job) => ({ ...job, status: "emailed" }));
    render(
      <JobsDashboard
        initialJobs={[...emailed, ...many.slice(26).map((job) => ({ ...job, status: "applied" }))]}
        initialStore={store}
        initialFilters={{ ...DEFAULT_FILTERS, status: "emailed" }}
        initialPage={2}
      />,
    );
    expect(rowIds()).toEqual(["job-row-job-26"]);
    fetchMock.mockResolvedValueOnce(jsonResponse({ job: { ...emailed[25], status: "skipped" } }));

    await choose(user, row("job-26").getByRole("combobox", { name: "Status for job job-26" }), "Skipped");

    await waitFor(() => expect(rowIds()).toHaveLength(25));
    expect(screen.getByText("Showing 1–25 of 25 jobs")).toBeInTheDocument();
  });
});
