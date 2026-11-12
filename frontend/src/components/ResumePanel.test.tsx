import fs from "node:fs";
import path from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MAX_RESUME_BYTES, resumeFromDocument, type Resume } from "@/lib/resume";
import { DEFAULT_SEARCH_SKILLS, type SkillSettings } from "@/lib/skills";
import type { StoreInfo } from "@/lib/types";
import { setupUser } from "@/test/user";
import { ResumePanel } from "./ResumePanel";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);
const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** settings/resume as backend/resume.py writes it: a parsed reading (10.5 years) and an AI one (8.8). */
const DOCUMENT = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "test", "fixtures", "resume.json"), "utf-8"));
const withReadings = (...methods: string[]) =>
  ({
    ...DOCUMENT,
    analyses: Object.fromEntries(methods.map((method) => [method, DOCUMENT.analyses[method]])),
  }) as Record<string, unknown>;
const resume = (...methods: string[]): Resume => resumeFromDocument(withReadings(...methods))!;

const store: StoreInfo = { backend: "local", description: "local Firestore stand-in at /repo/backend/local_firestore.json", emulator: false, envFile: null };
const defaults = {
  skills: [...DEFAULT_SEARCH_SKILLS.skills],
  core_skills: [...DEFAULT_SEARCH_SKILLS.core_skills],
  proficiency: { ...DEFAULT_SEARCH_SKILLS.proficiency },
};
const skills: SkillSettings = {
  skills: ["Python", "ReactJS", "SQL"],
  core_skills: ["Python", "ReactJS"],
  proficiency: { Python: 5, ReactJS: 4, SQL: 2 },
  source: "saved",
  updated_at: "2026-11-08T22:00:00+00:00",
  defaults,
};
const REASSESSED = { total_jobs: 12, reassessed: 12, changed: 4, no_longer_match: 0, fetched: 0, unavailable: 0, skills_source: "saved" };

/** Answer the dashboard's API routes the way the server would. */
function serveApi(overrides: { analyze?: () => Response } = {}) {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === "/api/resume" && init?.method === "POST") return jsonResponse({ resume: withReadings("parse") });
    if (url === "/api/resume" && init?.method === "DELETE") return jsonResponse({ resume: null });
    if (url === "/api/resume/analyze") {
      return overrides.analyze?.() ?? jsonResponse({ resume: withReadings("parse", JSON.parse(String(init?.body)).method) });
    }
    if (url === "/api/skills" && init?.method === "PUT") {
      return jsonResponse({ ...skills, ...JSON.parse(String(init.body)), updated_at: "2026-11-11T10:00:00+00:00" });
    }
    if (url === "/api/jobs/reassess") return jsonResponse(REASSESSED);
    throw new Error(`unexpected fetch ${init?.method ?? "GET"} ${url}`);
  });
}

const renderPanel = (initialResume: Resume | null) =>
  render(<ResumePanel initialResume={initialResume} initialSkills={skills} store={store} />);
const pickList = ({ skills, core_skills, proficiency }: SkillSettings) => ({ skills, core_skills, proficiency });
const stat = (label: string) => screen.getByText(label).parentElement!;
const skillRow = (name: string) => screen.getByRole("table", { name: "Skills found" }).querySelector(`tr[data-skill="${name}"]`) as HTMLElement;
const calls = (url: string) => fetchMock.mock.calls.filter(([called]) => called === url);

beforeEach(() => {
  fetchMock.mockReset();
  serveApi();
});

describe("ResumePanel", () => {
  it("starts with an upload, and shows what parsing found once a file is uploaded", async () => {
    const user = setupUser();
    renderPanel(null);
    expect(screen.getByText("Upload your resume")).toBeInTheDocument();
    expect(screen.queryByText("What your resume shows")).not.toBeInTheDocument();

    const file = new File(["%PDF-1.4"], "jane-doe.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Resume file"), file);

    await screen.findByText("What your resume shows");
    const [[, init]] = calls("/api/resume");
    expect((init.body as FormData).get("file")).toBe(file);
    expect(within(stat("Years of experience")).getByText("10.5 years")).toBeInTheDocument();
    expect(screen.getByText("Added up from the dates of 4 jobs, overlaps counted once")).toBeInTheDocument();
    expect(screen.getByText(/Parsed with rules \(no AI\)/)).toBeInTheDocument();
    expect(within(stat("Jobs in your work history")).getByText("4")).toBeInTheDocument();
    expect(screen.getByText("Senior Software Engineer · Acme Corp · Austin, TX")).toBeInTheDocument();
    expect(screen.getByText("The resume mentions 8 years of experience; the dates in its work history add up to 10.5.")).toBeInTheDocument();
    expect(screen.getByText("Your resume")).toBeInTheDocument();
  });

  it("shows each skill's level, years, and which are on your list already (in any spelling)", () => {
    renderPanel(resume("parse"));
    const react = skillRow("React");
    expect(within(react).getByText("On your list (ReactJS)")).toBeInTheDocument();
    expect(within(react).getByRole("img", { name: "5 of 5 stars: Expert" })).toBeInTheDocument();
    expect(within(react).getByText("7.9 years across 2 jobs; still using it")).toBeInTheDocument();
    expect(within(react).getByText("7.9 years")).toBeInTheDocument();
    // On your list at 4 stars: it can be updated to the resume's 5.
    expect(within(react).getByText("You rated it 4★")).toBeInTheDocument();
    expect(within(react).getByRole("checkbox", { name: "Update ReactJS to 5 stars" })).not.toBeChecked();
    // On your list with the same stars: nothing to do.
    expect(within(skillRow("Python")).queryByRole("checkbox")).not.toBeInTheDocument();

    const go = skillRow("Go");
    expect(within(go).getByText("Listed")).toBeInTheDocument(); // only in the skills section
    expect(within(go).getByRole("img", { name: "2 of 5 stars: Familiar" })).toBeInTheDocument();
    expect(within(go).getByRole("checkbox", { name: "Add Go to your skills" })).not.toBeChecked();
    expect(within(skillRow("Java")).getByText("Feb 2018")).toBeInTheDocument(); // last used
  });

  it("opens on the AI reading when there is one, and switches between readings", async () => {
    const user = setupUser();
    renderPanel(resume("parse", "ai"));
    expect(screen.getByText(/Read by Claude \(claude-test\)/)).toBeInTheDocument();
    expect(within(stat("Years of experience")).getByText("8.8 years")).toBeInTheDocument();
    expect(within(skillRow("Code review")).getByText("Inferred")).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Parsed" }));
    expect(within(stat("Years of experience")).getByText("10.5 years")).toBeInTheDocument();
  });

  it("reads it with AI on request", async () => {
    const user = setupUser();
    renderPanel(resume("parse"));
    await user.click(screen.getByRole("radio", { name: "AI" }));
    expect(screen.getByText(/Not read with AI yet/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Read with AI" }));

    await screen.findByText(/Read by Claude/);
    expect(JSON.parse(String(calls("/api/resume/analyze")[0][1].body))).toEqual({ method: "ai" });
    expect(within(stat("Years of experience")).getByText("8.8 years")).toBeInTheDocument();
  });

  it("says why AI didn't work, and keeps the parsed reading", async () => {
    const user = setupUser();
    serveApi({ analyze: () => jsonResponse({ error: "AI isn't set up: add ANTHROPIC_API_KEY or OPENAI_API_KEY to backend/.env" }, 503) });
    renderPanel(resume("parse"));
    await user.click(screen.getByRole("radio", { name: "AI" }));
    await user.click(screen.getByRole("button", { name: "Read with AI" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Couldn't read it with AI")).toBeInTheDocument();
    expect(within(alert).getByText(/add ANTHROPIC_API_KEY/)).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Parsed" }));
    expect(within(stat("Years of experience")).getByText("10.5 years")).toBeInTheDocument();
  });

  it("parses again on request", async () => {
    const user = setupUser();
    renderPanel(resume("parse"));
    await user.click(screen.getByRole("button", { name: "Read again" }));
    await waitFor(() => expect(calls("/api/resume/analyze")).toHaveLength(1));
    expect(JSON.parse(String(calls("/api/resume/analyze")[0][1].body))).toEqual({ method: "parse" });
  });

  it("adds the skills you pick to your list, then re-scores your jobs", async () => {
    const user = setupUser();
    renderPanel(resume("parse"));
    await user.click(within(skillRow("Go")).getByRole("checkbox"));
    await user.click(within(skillRow("Kubernetes")).getByRole("checkbox"));

    await user.click(screen.getByRole("button", { name: "Add 2 skills" }));

    const added = await screen.findByTestId("skills-added");
    // In the table's order (best known first), as core skills, at the resume's stars.
    expect(within(added).getByText("Added 2 skills to your list")).toBeInTheDocument();
    expect(within(added).getByText("Added as core skills: Kubernetes, Go.")).toBeInTheDocument();
    const [[, put]] = calls("/api/skills");
    expect(JSON.parse(String(put.body))).toEqual({
      skills: ["Python", "ReactJS", "SQL", "Kubernetes", "Go"],
      core_skills: ["Python", "ReactJS", "Kubernetes", "Go"],
      proficiency: { Python: 5, ReactJS: 4, SQL: 2, Kubernetes: 4, Go: 2 },
    });
    expect(await screen.findByText("Reassessed 12 jobs against your skills")).toBeInTheDocument();
    // Now they're on your list.
    expect(within(skillRow("Go")).getByText("On your list")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to your list" })).toBeDisabled();
  });

  it("updates the stars of a skill on your list only when you tick it", async () => {
    const user = setupUser();
    renderPanel(resume("parse"));
    await user.click(screen.getByRole("checkbox", { name: "Update ReactJS to 5 stars" }));
    await user.click(screen.getByRole("button", { name: "Update 1 rating" }));

    const notice = await screen.findByTestId("skills-added");
    expect(within(notice).getByText("Updated the stars for 1 skill")).toBeInTheDocument();
    expect(within(notice).getByText("New stars: ReactJS 4★ → 5★.")).toBeInTheDocument();
    const [[, put]] = calls("/api/skills");
    // Only ReactJS's stars change: SQL (also rated differently) wasn't ticked, and core stays as it was.
    expect(JSON.parse(String(put.body))).toEqual({ ...pickList(skills), proficiency: { Python: 5, ReactJS: 5, SQL: 2 } });
    expect(within(skillRow("React")).queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("selects everything it can apply at once", async () => {
    const user = setupUser();
    renderPanel(resume("parse"));
    const total = resume("parse").analyses.parse!.skills.length;
    // New skills: all but Python, SQL, and React (as ReactJS); ratings: ReactJS 4 -> 5 and SQL 2 -> 3.
    await user.click(screen.getByRole("button", { name: `Select all ${total - 3 + 2}` }));
    expect(screen.getByRole("button", { name: `Add ${total - 3} skills, update 2 ratings` })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByRole("button", { name: "Add to your list" })).toBeDisabled();
  });

  it("uploads pasted text", async () => {
    const user = setupUser();
    renderPanel(null);
    await user.click(screen.getByRole("button", { name: "Paste text" }));
    await user.type(screen.getByLabelText("Resume text"), "Jane Doe, Python developer");
    await user.click(screen.getByRole("button", { name: "Use this text" }));

    await screen.findByText("What your resume shows");
    expect(JSON.parse(String(calls("/api/resume")[0][1].body))).toEqual({ text: "Jane Doe, Python developer" });
  });

  it("refuses a file that's too big without uploading it", async () => {
    const user = setupUser();
    renderPanel(null);
    await user.upload(screen.getByLabelText("Resume file"), new File([new Uint8Array(MAX_RESUME_BYTES + 1)], "huge.pdf", { type: "application/pdf" }));
    expect(await screen.findByText(/a resume can be at most 5 MB/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("removes the resume after you confirm", async () => {
    const user = setupUser();
    renderPanel(resume("parse", "ai"));
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.getByText("Remove your resume? Your skills stay as they are.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove" }));

    await screen.findByText("Upload your resume");
    expect(calls("/api/resume")[0][1].method).toBe("DELETE");
    expect(screen.queryByText("What your resume shows")).not.toBeInTheDocument();
  });

  it("shows the text it read, to check the file came through", async () => {
    const user = setupUser();
    renderPanel(resume("parse"));
    await user.click(screen.getByText("Text read from jane-doe.pdf"));
    expect(screen.getByText(/Cypress, TX \| jane@example\.com/)).toBeVisible();
  });
});
