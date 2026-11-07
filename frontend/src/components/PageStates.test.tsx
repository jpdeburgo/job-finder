import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PageLoading, StoreProblem } from "./PageStates";

describe("PageLoading", () => {
  it("is a labelled loading placeholder", () => {
    render(<PageLoading label="Loading overview" />);
    expect(screen.getByRole("status", { name: "Loading overview" })).toBeInTheDocument();
  });
});

describe("StoreProblem", () => {
  it("shows the error and where to fix it", () => {
    render(<StoreProblem message="No Firebase credentials found." />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Could not open the job store");
    expect(alert).toHaveTextContent("No Firebase credentials found.");
    expect(alert).toHaveTextContent("IG_STATE_BACKEND");
  });
});
