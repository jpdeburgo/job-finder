import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_SEARCH_SKILLS, type SkillSettings } from "@/lib/skills";
import type { StoreInfo } from "@/lib/types";
import { setupUser } from "@/test/user";
import { SkillsEditor } from "./SkillsEditor";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);
const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const store: StoreInfo = { backend: "local", description: "local Firestore stand-in at /repo/backend/local_firestore.json", emulator: false, envFile: null };
const defaults = {
  skills: [...DEFAULT_SEARCH_SKILLS.skills],
  core_skills: [...DEFAULT_SEARCH_SKILLS.core_skills],
  proficiency: { ...DEFAULT_SEARCH_SKILLS.proficiency },
};

function settings(overrides: Partial<SkillSettings> = {}): SkillSettings {
  return {
    skills: ["Python", "React", "SQL", "AWS"],
    core_skills: ["Python", "React"],
    proficiency: { Python: 5, React: 3, SQL: 2, AWS: 3 },
    source: "saved",
    updated_at: "2026-11-08T22:00:00+00:00",
    defaults,
    ...overrides,
  };
}

const REASSESSED = { total_jobs: 12, reassessed: 12, changed: 4, no_longer_match: 1, fetched: 0, unavailable: 0, skills_source: "saved" };

/**
 * Answer PUT with what was sent (as the server would save it), DELETE with
 * the defaults, and the re-scoring that follows with `reassess`.
 */
function serveApi(reassess: () => Response | Promise<Response> = () => jsonResponse(REASSESSED)) {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === "/api/skills" && init?.method === "PUT") {
      const body = JSON.parse(String(init.body));
      return jsonResponse(settings({ ...body, updated_at: "2026-11-09T10:00:00+00:00" }));
    }
    if (url === "/api/skills" && init?.method === "DELETE") {
      return jsonResponse({ ...defaults, source: "default", updated_at: null, defaults });
    }
    if (url === "/api/jobs/reassess" && init?.method === "POST") return reassess();
    throw new Error(`unexpected fetch ${url}`);
  });
}

const group = (name: "Core skills" | "Other skills") => within(screen.getByRole("list", { name }));
const chips = (name: "Core skills" | "Other skills") =>
  group(name)
    .getAllByRole("listitem")
    .map((item) => item.dataset.skill);
const stars = (skill: string) => within(screen.getByRole("radiogroup", { name: `How well you know ${skill}` }));
const rating = (skill: string) =>
  stars(skill)
    .getAllByRole("radio")
    .findIndex((radio) => radio.getAttribute("aria-checked") === "true") + 1;
const saveButton = () => screen.getByRole("button", { name: "Save skills" });
const status = () => screen.getByTestId("save-status");

beforeEach(() => {
  fetchMock.mockReset();
  serveApi();
});

describe("showing the list", () => {
  it("splits your saved skills into core and other", () => {
    render(<SkillsEditor initialSettings={settings()} store={store} />);
    expect(chips("Core skills")).toEqual(["Python", "React"]);
    expect(chips("Other skills")).toEqual(["SQL", "AWS"]);
    expect(screen.getByText(/What the search looks for/)).toHaveTextContent(
      "What the search looks for in each posting, and how well you know it. Your list, saved on 2026-11-08 in the local file.",
    );
    expect(screen.getByText("Your list")).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
  });

  it("says when the defaults are in use, with no reset button", () => {
    render(<SkillsEditor initialSettings={{ ...defaults, source: "default", updated_at: null, defaults }} store={store} />);
    expect(screen.getByText(/These are the defaults from/)).toBeInTheDocument();
    expect(chips("Core skills")).toHaveLength(DEFAULT_SEARCH_SKILLS.core_skills.length);
    expect(screen.queryByRole("button", { name: /Reset to defaults/ })).not.toBeInTheDocument();
  });
});

describe("sorting", () => {
  // Not in A–Z or star order as listed.
  const unsorted = () =>
    settings({
      skills: ["TypeScript", "Python", "React", "SQL", "AWS", "Docker"],
      core_skills: ["TypeScript", "Python", "React"],
      proficiency: { TypeScript: 4, Python: 5, React: 2, SQL: 2, AWS: 3, Docker: 5 },
    });
  const sortBy = (name: string) => screen.getByRole("radio", { name });

  it("shows your list in its own order until you choose another", () => {
    render(<SkillsEditor initialSettings={unsorted()} store={store} />);
    expect(sortBy("List order")).toHaveAttribute("aria-checked", "true");
    expect(chips("Core skills")).toEqual(["TypeScript", "Python", "React"]);
    expect(chips("Other skills")).toEqual(["SQL", "AWS", "Docker"]);
  });

  it("sorts both groups A–Z or by stars, without changing the list", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={unsorted()} store={store} />);

    await user.click(sortBy("A–Z"));
    expect(chips("Core skills")).toEqual(["Python", "React", "TypeScript"]);
    expect(chips("Other skills")).toEqual(["AWS", "Docker", "SQL"]);

    await user.click(sortBy("Proficiency"));
    expect(chips("Core skills")).toEqual(["Python", "TypeScript", "React"]);
    expect(chips("Other skills")).toEqual(["Docker", "AWS", "SQL"]);

    // Only the view changed: nothing to save.
    expect(saveButton()).toBeDisabled();
    expect(status()).toBeEmptyDOMElement();
  });

  it("keeps a skill in place while you rate it, and re-sorts when you save", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={unsorted()} store={store} />);
    await user.click(sortBy("Proficiency"));

    await user.click(stars("React").getByRole("radio", { name: /^5 stars/ }));

    expect(rating("React")).toBe(5);
    expect(chips("Core skills")).toEqual(["Python", "TypeScript", "React"]); // not moved yet
    expect(screen.getByText("Sorted by your saved stars; saving re-sorts.")).toBeInTheDocument();

    await user.click(saveButton());
    await waitFor(() => expect(chips("Core skills")).toEqual(["Python", "React", "TypeScript"])); // 5, 5 (A–Z), 4
    expect(screen.queryByText("Sorted by your saved stars; saving re-sorts.")).not.toBeInTheDocument();
  });

  it("puts a new skill in its sorted place", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={unsorted()} store={store} />);
    await user.click(sortBy("A–Z"));
    await user.type(screen.getByRole("textbox", { name: "Add another skill" }), "Bash{Enter}");
    expect(chips("Other skills")).toEqual(["AWS", "Bash", "Docker", "SQL"]);
  });

  it("remembers your choice next time", async () => {
    const user = setupUser();
    const { unmount } = render(<SkillsEditor initialSettings={unsorted()} store={store} />);
    await user.click(sortBy("A–Z"));
    unmount();

    render(<SkillsEditor initialSettings={unsorted()} store={store} />);
    expect(sortBy("A–Z")).toHaveAttribute("aria-checked", "true");
    expect(chips("Core skills")).toEqual(["Python", "React", "TypeScript"]);
  });
});

describe("editing", () => {
  it("adds several skills at once, as core or other", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.type(screen.getByRole("textbox", { name: "Add a core skill" }), "Go, Kotlin{Enter}");
    await user.type(screen.getByRole("textbox", { name: "Add another skill" }), "Kubernetes");
    await user.click(within(screen.getByRole("textbox", { name: "Add another skill" }).closest("form")!).getByRole("button", { name: "Add" }));

    expect(chips("Core skills")).toEqual(["Python", "React", "Go", "Kotlin"]);
    expect(chips("Other skills")).toEqual(["SQL", "AWS", "Kubernetes"]);
    expect(screen.getByRole("textbox", { name: "Add a core skill" })).toHaveValue("");
    expect(status()).toHaveTextContent("Unsaved changes");
    expect(saveButton()).toBeEnabled();
  });

  it("won't add a skill twice, and says why", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);
    const box = screen.getByRole("textbox", { name: "Add another skill" });

    await user.type(box, "aws{Enter}");

    expect(chips("Other skills")).toEqual(["SQL", "AWS"]);
    expect(screen.getByText('"AWS" is already in your list.')).toBeInTheDocument();
    expect(box).toHaveValue("aws"); // kept, so you can fix it
    expect(box).toHaveAttribute("aria-invalid", "true");
  });

  it("moves skills between core and other, and removes them", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.click(screen.getByRole("button", { name: "Make SQL a core skill" }));
    await user.click(screen.getByRole("button", { name: "Move React to other skills" }));
    await user.click(screen.getByRole("button", { name: "Remove AWS" }));

    expect(chips("Core skills")).toEqual(["Python", "SQL"]);
    expect(chips("Other skills")).toEqual(["React"]);
  });

  it("can't save without a core skill", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.click(screen.getByRole("button", { name: "Move Python to other skills" }));
    await user.click(screen.getByRole("button", { name: "Move React to other skills" }));

    expect(screen.queryByRole("list", { name: "Core skills" })).not.toBeInTheDocument();
    expect(screen.getByText(/No core skills yet/)).toBeInTheDocument();
    expect(status()).toHaveTextContent("Mark at least one skill as core");
    expect(saveButton()).toBeDisabled();
  });

  it("discards changes", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.click(screen.getByRole("button", { name: "Remove SQL" }));
    await user.click(screen.getByRole("button", { name: "Discard changes" }));

    expect(chips("Other skills")).toEqual(["SQL", "AWS"]);
    expect(saveButton()).toBeDisabled();
  });
});

describe("saving", () => {
  it("sends the list and shows it's saved", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.type(screen.getByRole("textbox", { name: "Add a core skill" }), "Go{Enter}");
    await user.click(saveButton());

    await waitFor(() => expect(status()).toHaveTextContent("Saved. The next search will use these skills."));
    expect(fetchMock).toHaveBeenCalledWith("/api/skills", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        skills: ["Python", "React", "SQL", "AWS", "Go"],
        core_skills: ["Python", "React", "Go"],
        proficiency: { Python: 5, React: 3, SQL: 2, AWS: 3, Go: 3 },
      }),
    });
    expect(screen.getByText(/saved on 2026-11-09/)).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
  });

  it("clears an Add box's message once the list is saved", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.type(screen.getByRole("textbox", { name: "Add another skill" }), "AWS, Docker{Enter}");
    expect(screen.getByText('"AWS" is already in your list.')).toBeInTheDocument();
    await user.click(saveButton());

    await waitFor(() => expect(status()).toHaveTextContent("Saved."));
    expect(screen.queryByText(/already in your list/)).not.toBeInTheDocument();
  });

  it("shows the server's error and keeps your changes", async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ error: "disk full" }, 500));
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.click(screen.getByRole("button", { name: "Remove SQL" }));
    await user.click(saveButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save your skillsdisk full");
    expect(chips("Other skills")).toEqual(["AWS"]);
    expect(status()).toHaveTextContent("Unsaved changes");
  });
});

describe("reset to defaults", () => {
  it("asks first, then goes back to the defaults", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.click(screen.getByRole("button", { name: "Reset to defaults" }));
    expect(screen.getByText("Forget your list and use the defaults?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(fetchMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Reset to defaults" }));
    await user.click(screen.getByRole("button", { name: "Reset" }));

    await waitFor(() => expect(status()).toHaveTextContent("Back to the defaults"));
    expect(fetchMock).toHaveBeenCalledWith("/api/skills", { method: "DELETE" });
    expect(chips("Core skills")).toEqual(DEFAULT_SEARCH_SKILLS.core_skills);
    expect(screen.getByText(/These are the defaults from/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reset to defaults/ })).not.toBeInTheDocument();
  });
});


describe("proficiency stars", () => {
  it("shows each skill's stars and label", () => {
    render(<SkillsEditor initialSettings={settings()} store={store} />);
    expect(rating("Python")).toBe(5);
    expect(rating("SQL")).toBe(2);
    expect(stars("SQL").getByRole("radio", { name: "2 stars: Familiar" })).toHaveAttribute("aria-checked", "true");
    expect(group("Core skills").getByText("Expert")).toBeInTheDocument();
  });

  it("rates a skill with a click", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.click(stars("SQL").getByRole("radio", { name: "4 stars: Advanced" }));

    expect(rating("SQL")).toBe(4);
    expect(status()).toHaveTextContent("Unsaved changes");
    expect(saveButton()).toBeEnabled();
  });

  it("rates a skill from the keyboard, with one tab stop per skill", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);
    const chosen = stars("React").getByRole("radio", { name: "3 stars: Proficient" });
    expect(stars("React").getAllByRole("radio").map((radio) => radio.tabIndex)).toEqual([-1, -1, 0, -1, -1]);

    chosen.focus();
    await user.keyboard("{ArrowRight}");
    expect(rating("React")).toBe(4);
    expect(stars("React").getByRole("radio", { name: "4 stars: Advanced" })).toHaveFocus();
    await user.keyboard("{Home}");
    expect(rating("React")).toBe(1);
    await user.keyboard("{ArrowLeft}"); // already at 1
    expect(rating("React")).toBe(1);
    await user.keyboard("{End}");
    expect(rating("React")).toBe(5);
  });

  it("starts new skills at 3 stars and keeps stars when a skill moves", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.type(screen.getByRole("textbox", { name: "Add another skill" }), "Docker{Enter}");
    await user.click(screen.getByRole("button", { name: "Make SQL a core skill" }));

    expect(rating("Docker")).toBe(3);
    expect(chips("Core skills")).toContain("SQL");
    expect(rating("SQL")).toBe(2);
  });

  it("treats putting a star back as no change", async () => {
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.click(stars("SQL").getByRole("radio", { name: "5 stars: Expert" }));
    await user.click(stars("SQL").getByRole("radio", { name: "2 stars: Familiar" }));

    expect(saveButton()).toBeDisabled();
  });
});

describe("re-scoring saved jobs after saving", () => {
  it("re-scores the saved jobs and says what changed", async () => {
    let finish: (response: Response) => void = () => {};
    serveApi(() => new Promise<Response>((resolve) => (finish = resolve)));
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.click(stars("AWS").getByRole("radio", { name: "5 stars: Expert" }));
    await user.click(saveButton());

    expect(await screen.findByText(/Re-scoring your saved jobs against these skills/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/jobs/reassess", { method: "POST" });
    await user.click(stars("AWS").getByRole("radio", { name: "4 stars: Advanced" }));
    expect(saveButton()).toBeDisabled(); // not while the last save is still being applied

    finish(jsonResponse(REASSESSED));

    const notice = await screen.findByTestId("reassess-notice");
    expect(notice).toHaveTextContent("Reassessed 12 jobs against your skills");
    expect(notice).toHaveTextContent("4 jobs changed; 1 no longer matches (marked in the list).");
    expect(within(notice).getByRole("link", { name: "See your jobs" })).toHaveAttribute("href", "/jobs");
    expect(saveButton()).toBeEnabled();
  });

  it("still saves when the search API isn't running, and says how to re-score later", async () => {
    serveApi(() => jsonResponse({ error: "The search API isn't reachable at http://127.0.0.1:8000." }, 503));
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.click(stars("AWS").getByRole("radio", { name: "1 star: Beginner" }));
    await user.click(saveButton());

    const notice = await screen.findByTestId("reassess-notice");
    expect(notice).toHaveAttribute("role", "alert");
    expect(notice).toHaveTextContent("Skills saved, but your saved jobs weren't re-scored");
    expect(notice).toHaveTextContent("Once it's running, click Refresh on the Jobs page.");
    expect(within(notice).queryByRole("link", { name: "See your jobs" })).not.toBeInTheDocument();
    expect(status()).toHaveTextContent("Saved. The next search will use these skills.");
  });

  it("doesn't re-score when the save fails", async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ error: "disk full" }, 500));
    const user = setupUser();
    render(<SkillsEditor initialSettings={settings()} store={store} />);

    await user.click(screen.getByRole("button", { name: "Remove SQL" }));
    await user.click(saveButton());

    await screen.findByText("disk full");
    expect(fetchMock).not.toHaveBeenCalledWith("/api/jobs/reassess", expect.anything());
  });
});
