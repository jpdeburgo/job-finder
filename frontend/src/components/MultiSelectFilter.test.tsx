import { render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { setupUser } from "@/test/user";
import { MultiSelectFilter, multiSelectLabel, searchOptions } from "./MultiSelectFilter";

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

  it("says when there's nothing to pick, with no search box", async () => {
    const user = setupUser();
    render(<MultiSelectFilter options={[]} selected={[]} onChange={vi.fn()} {...labels} />);
    await user.click(screen.getByRole("button"));
    expect(screen.getByText("No companies yet.")).toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  });
});

describe("searchOptions", () => {
  const options = ["Databricks", "Accenture", "Insight Global", "Adobe", "Doordashusa", "Remote OK", "Airbnb"].map(
    (value) => ({ value, count: 1 }),
  );
  const values = (query: string) => searchOptions(options, query).map((option) => option.value);

  it("returns every choice, in order, for an empty search", () => {
    expect(values("")).toEqual(options.map((option) => option.value));
    expect(values("   ")).toHaveLength(options.length);
  });

  it("puts names that start with the search first, then word starts, then the rest", () => {
    // Accenture, Adobe, Airbnb start with "a"; Databricks and Insight Global have one inside.
    expect(values("a")).toEqual(["Accenture", "Adobe", "Airbnb", "Databricks", "Insight Global", "Doordashusa"]);
    expect(values("global")).toEqual(["Insight Global"]); // a later word
    expect(values("OK")).toEqual(["Remote OK"]);
    expect(values("bricks")).toEqual(["Databricks"]);
  });

  it("ignores case, spaces, and punctuation", () => {
    expect(values("ACCENT")).toEqual(["Accenture"]);
    expect(values("insightglobal")).toEqual(["Insight Global"]);
    expect(values("remoteok")).toEqual(["Remote OK"]);
    expect(values("doordash")).toEqual(["Doordashusa"]);
    expect(values("zzz")).toEqual([]);
  });

  it("says where the search matched, to highlight it", () => {
    expect(searchOptions(options, "glo").find((o) => o.value === "Insight Global")?.match).toEqual([8, 11]);
    // Only matches once spaces are ignored: nothing to highlight.
    expect(searchOptions(options, "insightglobal")[0].match).toBeNull();
  });
});

describe("MultiSelectFilter search", () => {
  const companies = ["Accenture", "Adobe", "Airbnb", "Databricks", "Insight Global", "Nvidia"].map((value, index) => ({
    value,
    count: index + 1,
  }));

  /** The filter with its own state, like FilterBar keeps it. */
  function Harness({ onChange = vi.fn() }: { onChange?: (selected: string[]) => void }) {
    const [selected, setSelected] = useState<string[]>([]);
    return (
      <MultiSelectFilter
        options={companies}
        selected={selected}
        onChange={(next) => {
          setSelected(next);
          onChange(next);
        }}
        searchLabel="Search companies"
        {...labels}
      />
    );
  }

  const choices = () => screen.queryAllByRole("menuitemcheckbox").map((item) => item.textContent?.replace(/\d+$/, ""));

  async function openMenu(user: ReturnType<typeof setupUser>) {
    await user.click(screen.getByRole("button", { name: /All companies|or|\w/ }));
    const search = screen.getByRole("searchbox", { name: "Search companies" });
    await waitFor(() => expect(search).toHaveFocus());
    return search;
  }

  it("opens with the search box focused, so typing narrows the list right away", async () => {
    const user = setupUser();
    render(<Harness />);
    await openMenu(user);
    expect(choices()).toHaveLength(6);

    await user.keyboard("a");
    // Names starting with "a" first, then the ones with an "a" inside.
    expect(choices()).toEqual(["Accenture", "Adobe", "Airbnb", "Databricks", "Insight Global", "Nvidia"]);
    await user.keyboard("d");
    expect(choices()).toEqual(["Adobe"]);
    // The matched part is in bold.
    expect(screen.getByText("Ad")).toHaveClass("font-semibold");
  });

  it("says when nothing matches", async () => {
    const user = setupUser();
    render(<Harness />);
    await openMenu(user);
    await user.keyboard("zzz");
    expect(choices()).toEqual([]);
    expect(screen.getByRole("status")).toHaveTextContent("No matches for “zzz”.");
  });

  it("picks the best match with Enter and clears the search for the next one", async () => {
    const user = setupUser();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const search = await openMenu(user);

    await user.keyboard("nvi{Enter}");
    expect(onChange).toHaveBeenLastCalledWith(["Nvidia"]);
    expect(search).toHaveValue("");
    expect(search).toHaveFocus();

    await user.keyboard("global{Enter}");
    expect(onChange).toHaveBeenLastCalledWith(["Nvidia", "Insight Global"]);
    // The menu stays open, and Enter on an already-picked match doesn't unpick it.
    await user.keyboard("nvi{Enter}");
    expect(onChange).toHaveBeenLastCalledWith(["Nvidia", "Insight Global"]);
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("picks with the mouse from the narrowed list, keeping the search", async () => {
    const user = setupUser();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const search = await openMenu(user);
    await user.keyboard("a");
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Airbnb, 3 jobs" }));
    expect(onChange).toHaveBeenLastCalledWith(["Airbnb"]);
    expect(search).toHaveValue("a");
    expect(screen.getByRole("menuitemcheckbox", { name: "Airbnb, 3 jobs" })).toHaveAttribute("aria-checked", "true");
  });

  it("moves between the search box and the list with the arrow keys; typing on a choice goes to the search", async () => {
    const user = setupUser();
    render(<Harness />);
    const search = await openMenu(user);
    await user.keyboard("a");

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitemcheckbox", { name: "Accenture, 1 job" })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitemcheckbox", { name: "Adobe, 2 jobs" })).toHaveFocus();

    // Typing on a choice keeps searching (instead of jumping to a letter).
    await user.keyboard("i");
    expect(search).toHaveFocus();
    expect(search).toHaveValue("ai");
    expect(choices()).toEqual(["Airbnb"]);

    await user.keyboard("{ArrowDown}{ArrowUp}");
    expect(search).toHaveFocus();
  });

  it("clears the search with the first Escape and closes with the second; reopening starts fresh", async () => {
    const user = setupUser();
    render(<Harness />);
    const search = await openMenu(user);
    await user.keyboard("ado");

    await user.keyboard("{Escape}");
    expect(search).toHaveValue("");
    expect(choices()).toHaveLength(6);
    expect(screen.getByRole("menu")).toBeInTheDocument();

    await user.keyboard("ado{Escape}{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    const reopened = await openMenu(user);
    expect(reopened).toHaveValue("");
    expect(choices()).toHaveLength(6);
  });
});
