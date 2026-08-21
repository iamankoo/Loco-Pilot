import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/lib/api";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const useProjectsList = vi.fn();
vi.mock("@/hooks/useProjects", () => ({
  useProjectsList: (...args: unknown[]) => useProjectsList(...args),
}));

const mutateAsync = vi.fn();
const useCreateExecution = vi.fn();
vi.mock("@/hooks/useExecutionMutations", () => ({
  useCreateExecution: (...args: unknown[]) => useCreateExecution(...args),
}));

import { CommandCenter } from "./CommandCenter";

const NO_PROJECTS = { data: { items: [], total: 0, limit: 100, offset: 0 }, isLoading: false, isError: false };
const ONE_PROJECT = {
  data: { items: [{ id: "proj-1", name: "sample-calculator" }], total: 1, limit: 100, offset: 0 },
  isLoading: false,
  isError: false,
};

function mockCreateExecution(overrides: Partial<ReturnType<typeof useCreateExecution>> = {}) {
  useCreateExecution.mockReturnValue({
    mutateAsync,
    isPending: false,
    isError: false,
    error: null,
    ...overrides,
  });
}

describe("CommandCenter", () => {
  beforeEach(() => {
    push.mockClear();
    mutateAsync.mockClear();
    useProjectsList.mockReset();
    useCreateExecution.mockReset();
  });

  it("disables submission until a task is entered", () => {
    useProjectsList.mockReturnValue(NO_PROJECTS);
    mockCreateExecution();
    render(<CommandCenter />);
    expect(screen.getByRole("button", { name: /run locopilot/i })).toBeDisabled();
  });

  it("shows a guidance message when there are no projects yet", () => {
    useProjectsList.mockReturnValue(NO_PROJECTS);
    mockCreateExecution();
    render(<CommandCenter />);
    expect(screen.getByText(/no projects yet/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/workspace path/i)).toBeInTheDocument();
  });

  it("submits on Enter (without Shift) and navigates to the new execution", async () => {
    useProjectsList.mockReturnValue(ONE_PROJECT);
    mutateAsync.mockResolvedValue({ id: "exec-123" });
    mockCreateExecution();
    render(<CommandCenter />);

    const textarea = screen.getByLabelText(/task description/i);
    await userEvent.type(textarea, "Add a power(a, b) function to calculator.py with tests.");
    await userEvent.type(textarea, "{Enter}");

    expect(mutateAsync).toHaveBeenCalledWith({ task: "Add a power(a, b) function to calculator.py with tests.", project_id: "proj-1" });
    expect(push).toHaveBeenCalledWith("/executions/exec-123");
  });

  it("does not submit on Shift+Enter", async () => {
    useProjectsList.mockReturnValue(ONE_PROJECT);
    mockCreateExecution();
    render(<CommandCenter />);

    const textarea = screen.getByLabelText(/task description/i);
    await userEvent.type(textarea, "line one");
    await userEvent.type(textarea, "{Shift>}{Enter}{/Shift}");

    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("shows the backend error message when execution creation fails", () => {
    useProjectsList.mockReturnValue(ONE_PROJECT);
    mockCreateExecution({ isError: true, error: new ApiError(422, "Invalid workspace_path.") });
    render(<CommandCenter />);
    expect(screen.getByText("Invalid workspace_path.")).toBeInTheDocument();
  });

  it("shows a starting label while the request is pending", () => {
    useProjectsList.mockReturnValue(ONE_PROJECT);
    mockCreateExecution({ isPending: true });
    render(<CommandCenter />);
    expect(screen.getByRole("button", { name: /starting locopilot/i })).toBeInTheDocument();
  });
});
