import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "@/components/common/ErrorBoundary";

function Broken(): never {
  throw new Error("the clock looped");
}

describe("ErrorBoundary (Tim, 2026-11-08)", () => {
  it("shows the words, the error and a way out in place of a white page", () => {
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("the clock looped")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    quiet.mockRestore();
  });
});
