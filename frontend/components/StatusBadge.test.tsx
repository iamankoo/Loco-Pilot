import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders the human-readable label for a known status", () => {
    render(<StatusBadge status="needs_review" />);
    expect(screen.getByText("Needs Review")).toBeInTheDocument();
  });

  it("falls back to the raw status string for unknown values", () => {
    render(<StatusBadge status="some_new_status" />);
    expect(screen.getByText("some_new_status")).toBeInTheDocument();
  });
});
