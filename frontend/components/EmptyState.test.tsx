import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { ApiError } from "@/lib/api";

describe("EmptyState", () => {
  it("renders the title and optional description", () => {
    render(<EmptyState title="No executions yet" description="Kick one off to see it here." />);
    expect(screen.getByText("No executions yet")).toBeInTheDocument();
    expect(screen.getByText("Kick one off to see it here.")).toBeInTheDocument();
  });

  it("omits the description when none is given", () => {
    render(<EmptyState title="No projects yet" />);
    expect(screen.getByText("No projects yet")).toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("shows the API error status and message", () => {
    render(<ErrorState error={new ApiError(404, "Execution not found.")} />);
    expect(screen.getByText("Request failed (404)")).toBeInTheDocument();
    expect(screen.getByText("Execution not found.")).toBeInTheDocument();
  });

  it("shows a generic message for non-API errors", () => {
    render(<ErrorState error={new Error("network down")} />);
    expect(screen.getByText("Request failed")).toBeInTheDocument();
    expect(screen.getByText("Something went wrong reaching the backend.")).toBeInTheDocument();
  });

  it("invokes onRetry when the retry button is clicked", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    let retried = false;
    render(<ErrorState error={new ApiError(500, "boom")} onRetry={() => (retried = true)} />);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retried).toBe(true);
  });
});
