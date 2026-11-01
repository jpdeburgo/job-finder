import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { setupUser } from "@/test/user";
import { ThemeToggle } from "./ThemeToggle";

const setTheme = vi.fn();
vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "system", setTheme }),
}));

describe("ThemeToggle", () => {
  it("offers light, dark, and system and applies the choice", async () => {
    const user = setupUser();
    render(<ThemeToggle />);
    await user.click(screen.getByRole("button", { name: "Change theme" }));
    const items = await screen.findAllByRole("menuitemradio");
    expect(items.map((item) => item.textContent)).toEqual(["Light", "Dark", "System"]);
    expect(screen.getByRole("menuitemradio", { name: "System" })).toHaveAttribute("aria-checked", "true");

    await user.click(screen.getByRole("menuitemradio", { name: "Dark" }));
    expect(setTheme).toHaveBeenCalledWith("dark");
  });
});
