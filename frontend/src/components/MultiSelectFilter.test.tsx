import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { setupUser } from "@/test/user";
import { MultiSelectFilter, multiSelectLabel } from "./MultiSelectFilter";

describe("multiSelectLabel", () => {
  it.each([
    [[], "any", "Any skill"],
    [["Python"], "all", "Python"],
    [["Python", "React"], "any", "Python or React"],
    [["Python", "React"], "all", "Python and React"],
    [["Python", "React", "SQL"], "any", "Python or 2 more"],
    [["Python", "React", "SQL"], "all", "Python + 2 more"],
  ] as const)("%j (%s) reads %j", (selected, match, label) => {
    expect(multiSelectLabel([...selected], "Any skill", match)).toBe(label);
  });

  it("reads 'or' without a match mode (one company per job)", () => {
    expect(multiSelectLabel(["Accenture", "NVIDIA"], "All companies")).toBe("Accenture or NVIDIA");
  });
});

const labels = { noneLabel: "All companies", emptyLabel: "No companies yet.", clearLabel: "Clear companies" };

describe("MultiSelectFilter", () => {
  it("keeps a picked choice listed after its last job is gone, and compares in any case", async () => {
    const user = setupUser();
    const onChange = vi.fn();
    render(
      <MultiSelectFilter options={[{ value: "Accenture", count: 4 }]} selected={["accenture", "Gone Co"]} onChange={onChange} {...labels} />,
    );

    await user.click(screen.getByRole("button"));

    expect(screen.getByRole("menuitemcheckbox", { name: "Accenture, 4 jobs" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("menuitemcheckbox", { name: "Gone Co, 0 jobs" })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Accenture, 4 jobs" }));
    expect(onChange).toHaveBeenLastCalledWith(["Gone Co"]);
  });

  it("has no any/all choice unless it's given one", async () => {
    const user = setupUser();
    render(<MultiSelectFilter options={[{ value: "Accenture", count: 1 }]} selected={[]} onChange={vi.fn()} {...labels} />);
    await user.click(screen.getByRole("button"));
    expect(screen.queryByRole("menuitemradio")).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Clear companies" })).not.toBeInTheDocument(); // nothing picked
  });

  it("offers any or all when given a match mode", async () => {
    const user = setupUser();
    const onMatch = vi.fn();
    render(
      <MultiSelectFilter
        options={[{ value: "Python", count: 2 }]}
        selected={["Python"]}
        onChange={vi.fn()}
        match={{ value: "any", onChange: onMatch, plural: "skills" }}
        {...labels}
      />,
    );
    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("menuitemradio", { name: "All of the selected skills" }));
    expect(onMatch).toHaveBeenCalledWith("all");
  });

  it("says when there's nothing to pick", async () => {
    const user = setupUser();
    render(<MultiSelectFilter options={[]} selected={[]} onChange={vi.fn()} {...labels} />);
    await user.click(screen.getByRole("button"));
    expect(screen.getByText("No companies yet.")).toBeInTheDocument();
  });
});
