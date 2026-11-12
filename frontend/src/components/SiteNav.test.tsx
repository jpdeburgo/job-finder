import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SiteNav } from "./SiteNav";

const pathname = vi.fn();
vi.mock("next/navigation", () => ({ usePathname: () => pathname() }));

beforeEach(() => pathname.mockReset());

const link = (name: string) => screen.getByRole("link", { name });

describe("SiteNav", () => {
  it("links to home, the tracker, the skills page, and the resume page", () => {
    pathname.mockReturnValue("/");
    render(<SiteNav />);
    expect(link("Home")).toHaveAttribute("href", "/");
    expect(link("Jobs")).toHaveAttribute("href", "/jobs");
    expect(link("Skills")).toHaveAttribute("href", "/skills");
    expect(link("Resume")).toHaveAttribute("href", "/resume");
  });

  it.each([
    ["/", "Home"],
    ["/jobs", "Jobs"],
    ["/jobs/anything", "Jobs"],
    ["/skills", "Skills"],
    ["/resume", "Resume"],
  ])("marks %s as the %s page", (path, current) => {
    pathname.mockReturnValue(path);
    render(<SiteNav />);
    for (const name of ["Home", "Jobs", "Skills", "Resume"]) {
      if (name === current) expect(link(name)).toHaveAttribute("aria-current", "page");
      else expect(link(name)).not.toHaveAttribute("aria-current");
    }
  });
});
