import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ApiError } from "@/lib/api";
import type { ExecutionDetail } from "@/lib/types";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "exec-1" }),
}));

const useExecutionDetail = vi.fn();
const useExecutionSteps = vi.fn();
const useExecutionToolCalls = vi.fn();
const useExecutionArtifacts = vi.fn();

vi.mock("@/hooks/useExecutions", () => ({
  useExecutionDetail: (...args: unknown[]) => useExecutionDetail(...args),
  useExecutionSteps: (...args: unknown[]) => useExecutionSteps(...args),
  useExecutionToolCalls: (...args: unknown[]) => useExecutionToolCalls(...args),
  useExecutionArtifacts: (...args: unknown[]) => useExecutionArtifacts(...args),
}));

vi.mock("@/hooks/useExecutionMutations", () => ({
  useCancelExecution: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
}));

const emptyListQuery = { data: undefined, isLoading: false, isError: false, error: null };

import ExecutionDetailPage from "./page";

const BASE_EXECUTION: ExecutionDetail = {
  id: "exec-1",
  project_id: "proj-1",
  project_name: "demo-project",
  task: "Fix the failing test",
  status: "passed",
  current_agent: "reviewer",
  retry_count: 0,
  error_message: null,
  created_at: "2026-01-01T00:00:00Z",
  started_at: "2026-01-01T00:00:01Z",
  completed_at: "2026-01-01T00:01:00Z",
  elapsed_seconds: 59,
  plan: null,
  files_changed: [],
  test_results: null,
  review_result: null,
  tool_call_count: 0,
  artifact_count: 0,
  step_errors: [],
};

describe("ExecutionDetailPage", () => {
  it("renders a loading skeleton while the execution query is pending", () => {
    useExecutionDetail.mockReturnValue({ isLoading: true, isError: false, data: undefined, refetch: vi.fn() });
    useExecutionSteps.mockReturnValue(emptyListQuery);
    useExecutionToolCalls.mockReturnValue(emptyListQuery);
    useExecutionArtifacts.mockReturnValue(emptyListQuery);

    const { container } = render(<ExecutionDetailPage />);
    expect(container.querySelectorAll(".animate-pulse-soft").length).toBeGreaterThan(0);
  });

  it("renders an error state when the execution fails to load", () => {
    useExecutionDetail.mockReturnValue({
      isLoading: false,
      isError: true,
      error: new ApiError(404, "Execution not found."),
      data: undefined,
      refetch: vi.fn(),
    });
    useExecutionSteps.mockReturnValue(emptyListQuery);
    useExecutionToolCalls.mockReturnValue(emptyListQuery);
    useExecutionArtifacts.mockReturnValue(emptyListQuery);

    render(<ExecutionDetailPage />);
    expect(screen.getByText("Request failed (404)")).toBeInTheDocument();
    expect(screen.getByText("Execution not found.")).toBeInTheDocument();
  });

  it("renders the full execution workspace once data loads successfully", () => {
    useExecutionDetail.mockReturnValue({ isLoading: false, isError: false, data: BASE_EXECUTION, refetch: vi.fn() });
    useExecutionSteps.mockReturnValue(emptyListQuery);
    useExecutionToolCalls.mockReturnValue(emptyListQuery);
    useExecutionArtifacts.mockReturnValue(emptyListQuery);

    render(<ExecutionDetailPage />);
    expect(screen.getByText("Fix the failing test")).toBeInTheDocument();
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("Pipeline")).toBeInTheDocument();
    expect(screen.getByText("Activity")).toBeInTheDocument();
    expect(screen.getByText("No plan yet")).toBeInTheDocument();
  });

  it("does not show a cancel control for a terminal execution", () => {
    useExecutionDetail.mockReturnValue({ isLoading: false, isError: false, data: BASE_EXECUTION, refetch: vi.fn() });
    useExecutionSteps.mockReturnValue(emptyListQuery);
    useExecutionToolCalls.mockReturnValue(emptyListQuery);
    useExecutionArtifacts.mockReturnValue(emptyListQuery);

    render(<ExecutionDetailPage />);
    expect(screen.queryByRole("button", { name: "Cancel execution" })).not.toBeInTheDocument();
  });

  it("shows a cancel control for an active execution", () => {
    useExecutionDetail.mockReturnValue({
      isLoading: false,
      isError: false,
      data: { ...BASE_EXECUTION, status: "running", completed_at: null },
      refetch: vi.fn(),
    });
    useExecutionSteps.mockReturnValue(emptyListQuery);
    useExecutionToolCalls.mockReturnValue(emptyListQuery);
    useExecutionArtifacts.mockReturnValue(emptyListQuery);

    render(<ExecutionDetailPage />);
    expect(screen.getByRole("button", { name: "Cancel execution" })).toBeInTheDocument();
  });

  it("renders the raw error message as literal text, never as HTML", () => {
    const maliciousTask = "<img src=x onerror=alert(1)> XSS check";
    useExecutionDetail.mockReturnValue({
      isLoading: false,
      isError: false,
      data: { ...BASE_EXECUTION, task: maliciousTask },
      refetch: vi.fn(),
    });
    useExecutionSteps.mockReturnValue(emptyListQuery);
    useExecutionToolCalls.mockReturnValue(emptyListQuery);
    useExecutionArtifacts.mockReturnValue(emptyListQuery);

    const { container } = render(<ExecutionDetailPage />);
    expect(screen.getByText(maliciousTask)).toBeInTheDocument();
    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(container.querySelector("script")).not.toBeInTheDocument();
  });
});
