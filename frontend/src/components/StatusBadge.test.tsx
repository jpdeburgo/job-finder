import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { setupUser } from "@/test/user";
import { ExternalLink } from "./ExternalLink";
import { StatusBadge, statusClasses, statusLabel } from "./StatusBadge";
import { StatusSelect } from "./StatusSelect";
import { StoreBanner } from "./StoreBanner";

describe("StatusBadge", () => {
  it("renders the friendly label with a hint for known statuses", () => {
    render(<StatusBadge status="unemailed" />);
    const badge = screen.getByText("Unemailed");
    expect(badge).toHaveAttribute("title", expect.stringContaining("digest email"));
    expect(badge.className).toContain(statusClasses("unemailed"));
  });

  it("falls back to the raw value and a neutral style for unknown statuses", () => {
    render(<StatusBadge status="weird" />);
    expect(screen.getByText("weird")).not.toHaveAttribute("title");
    expect(statusLabel("weird")).toBe("weird");
    expect(statusLabel("offer")).toBe("Offer");
    expect(statusClasses("weird")).toBe(statusClasses("also-unknown"));
    expect(statusClasses("weird")).not.toBe(statusClasses("offer"));
  });
});

describe("StatusSelect", () => {
  it("shows the current label and lists every status", async () => {
    const user = setupUser();
    const onChange = vi.fn();
    render(<StatusSelect jobId="x" value="emailed" onChange={onChange} />);
    const trigger = screen.getByRole("combobox", { name: "Status for job x" });
    expect(trigger).toHaveTextContent("Emailed");

    await user.click(trigger);
    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "Unemailed",
      "Emailed",
      "Applied",
      "Skipped",
      "Interviewing",
      "Rejected",
      "Offer",
    ]);
    await user.click(screen.getByRole("option", { name: "Offer" }));
    expect(onChange).toHaveBeenCalledWith("offer");
  });

  it("shows an unknown status as a placeholder and can be disabled", () => {
    render(<StatusSelect jobId="x" value="weird" disabled onChange={() => {}} />);
    const trigger = screen.getByRole("combobox", { name: "Status for job x" });
    expect(trigger).toHaveTextContent("weird");
    expect(trigger).toBeDisabled();
  });
});

describe("StoreBanner", () => {
  it("labels local, Firestore, and emulator stores differently", () => {
    const { rerender } = render(
      <StoreBanner store={{ backend: "local", description: "local stand-in", emulator: false, envFile: "/repo/.env" }} />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Local file");
    expect(screen.getByRole("status")).toHaveTextContent("GOOGLE_APPLICATION_CREDENTIALS");

    rerender(<StoreBanner store={{ backend: "firestore", description: "Firestore project 'p'", emulator: false, envFile: null }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Firestore");
    expect(screen.getByRole("status")).not.toHaveTextContent("GOOGLE_APPLICATION_CREDENTIALS");

    rerender(
      <StoreBanner
        store={{ backend: "firestore", description: "Firestore project 'p' (emulator at x)", emulator: true, envFile: null }}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Emulator");
  });

  it("tells you which .env it read when falling back to the local file", () => {
    const { rerender } = render(
      <StoreBanner store={{ backend: "local", description: "local stand-in", emulator: false, envFile: "/repo/.env" }} />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("No Firebase settings found in frontend/.env.local or /repo/.env");

    rerender(<StoreBanner store={{ backend: "local", description: "local stand-in", emulator: false, envFile: null }} />);
    expect(screen.getByRole("status")).toHaveTextContent("no .env exists in backend/ or a parent directory");
  });
});

describe("ExternalLink", () => {
  it("always opens in a new tab with noopener noreferrer and shows an icon", () => {
    render(<ExternalLink href="https://example.com">Example</ExternalLink>);
    const link = screen.getByRole("link", { name: /Example/ });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link.querySelector("svg")).not.toBeNull();
  });

  it("can hide the icon", () => {
    render(
      <ExternalLink href="https://example.com" plain>
        Plain
      </ExternalLink>,
    );
    expect(screen.getByRole("link").querySelector("svg")).toBeNull();
  });
});
