import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { setupUser } from "@/test/user";
import { SkillsFilter, skillsFilterLabel } from "./SkillsFilter";

describe("skillsFilterLabel", () => {
  it.each([
    [[], "any", "Any skill"],
    [["Python"], "all", "Python"],
    [["Python", "React"], "any", "Python or React"],
    [["Python", "React"], "all", "Python and React"],
    [["Python", "React", "SQL"], "any", "Python or 2 more"],
    [["Python", "React", "SQL"], "all", "Python + 2 more"],
  ] as const)("%j (%s) reads %j", (selected, match, label) => {
    expect(skillsFilterLabel([...selected], match)).toBe(label);
  });
});

describe("SkillsFilter", () => {
  it("keeps a picked skill listed after its last job is gone, and picks in any case", async () => {
    const user = setupUser();
    const onChange = vi.fn();
    render(<SkillsFilter options={[{ skill: "Python", count: 4 }]} selected={["python", "Go"]} match="any" onChange={onChange} />);

    await user.click(screen.getByRole("button"));

    expect(screen.getByRole("menuitemcheckbox", { name: "Python, 4 jobs" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("menuitemcheckbox", { name: "Go, 0 jobs" })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Python, 4 jobs" }));
    expect(onChange).toHaveBeenLastCalledWith(["Go"], "any");
  });

  it("says when no skills have matched yet", async () => {
    const user = setupUser();
    render(<SkillsFilter options={[]} selected={[]} match="any" onChange={vi.fn()} />);
    await user.click(screen.getByRole("button"));
    expect(screen.getByText("No skills matched yet.")).toBeInTheDocument();
  });
});
