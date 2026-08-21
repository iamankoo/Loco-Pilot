import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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

const createProject = vi.fn();
const uploadProjectFiles = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      createProject: (...args: unknown[]) => createProject(...args),
      uploadProjectFiles: (...args: unknown[]) => uploadProjectFiles(...args),
    },
  };
});

import { CommandCenter } from "./CommandCenter";
import { ApiError } from "@/lib/api";

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
    mutateAsync.mockReset();
    createProject.mockReset();
    uploadProjectFiles.mockReset();
    useProjectsList.mockReset();
    useCreateExecution.mockReset();
  });

  it("disables submission until a task is entered", () => {
    useProjectsList.mockReturnValue(NO_PROJECTS);
    mockCreateExecution();
    render(<CommandCenter />);
    expect(screen.getByRole("button", { name: /run locopilot/i })).toBeDisabled();
  });

  it("defaults the workspace selector to LocoPilot Storage", () => {
    useProjectsList.mockReturnValue(NO_PROJECTS);
    mockCreateExecution();
    render(<CommandCenter />);
    expect(screen.getByLabelText(/workspace/i)).toHaveValue("__default_storage__");
  });

  it("submits with no project_id/workspace_path when using the default storage workspace", async () => {
    useProjectsList.mockReturnValue(NO_PROJECTS);
    mutateAsync.mockResolvedValue({ id: "exec-1" });
    mockCreateExecution();
    render(<CommandCenter />);

    await userEvent.type(screen.getByLabelText(/task description/i), "Build a calculator{Enter}");

    expect(mutateAsync).toHaveBeenCalledWith({ task: "Build a calculator" });
    expect(push).toHaveBeenCalledWith("/executions/exec-1");
  });

  it("submits with the selected existing project's id", async () => {
    useProjectsList.mockReturnValue(ONE_PROJECT);
    mutateAsync.mockResolvedValue({ id: "exec-2" });
    mockCreateExecution();
    render(<CommandCenter />);

    await userEvent.selectOptions(screen.getByLabelText(/workspace/i), "proj-1");
    await userEvent.type(screen.getByLabelText(/task description/i), "Fix the failing test{Enter}");

    expect(mutateAsync).toHaveBeenCalledWith({ task: "Fix the failing test", project_id: "proj-1" });
  });

  it("reveals a path input when Local folder is selected and requires it before submitting", async () => {
    useProjectsList.mockReturnValue(NO_PROJECTS);
    mockCreateExecution();
    render(<CommandCenter />);

    await userEvent.selectOptions(screen.getByLabelText(/workspace/i), "__local_folder__");
    await userEvent.type(screen.getByLabelText(/task description/i), "Check config.py");
    expect(screen.getByRole("button", { name: /run locopilot/i })).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/local folder path/i), "D:/Projects/DeepLens");
    expect(screen.getByRole("button", { name: /run locopilot/i })).not.toBeDisabled();
  });

  it("submits workspace_path and project_name for a local folder", async () => {
    useProjectsList.mockReturnValue(NO_PROJECTS);
    mutateAsync.mockResolvedValue({ id: "exec-3" });
    mockCreateExecution();
    render(<CommandCenter />);

    await userEvent.selectOptions(screen.getByLabelText(/workspace/i), "__local_folder__");
    await userEvent.type(screen.getByLabelText(/local folder path/i), "D:/Projects/DeepLens");
    await userEvent.type(screen.getByLabelText(/project name/i), "deeplens");
    await userEvent.type(screen.getByLabelText(/task description/i), "Check config.py{Enter}");

    expect(mutateAsync).toHaveBeenCalledWith({
      task: "Check config.py",
      workspace_path: "D:/Projects/DeepLens",
      project_name: "deeplens",
    });
  });

  it("does not submit on Shift+Enter", async () => {
    useProjectsList.mockReturnValue(NO_PROJECTS);
    mockCreateExecution();
    render(<CommandCenter />);

    const textarea = screen.getByLabelText(/task description/i);
    await userEvent.type(textarea, "line one");
    await userEvent.type(textarea, "{Shift>}{Enter}{/Shift}");

    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("shows the backend error message when execution creation fails", async () => {
    useProjectsList.mockReturnValue(NO_PROJECTS);
    mutateAsync.mockRejectedValue(new ApiError(422, "Invalid workspace_path."));
    mockCreateExecution();
    render(<CommandCenter />);

    await userEvent.type(screen.getByLabelText(/task description/i), "Build a calculator{Enter}");
    expect(await screen.findByText("Invalid workspace_path.")).toBeInTheDocument();
  });

  it("shows a starting label while the request is in flight", async () => {
    useProjectsList.mockReturnValue(NO_PROJECTS);
    mutateAsync.mockReturnValue(new Promise(() => {})); // never resolves
    mockCreateExecution();
    render(<CommandCenter />);

    await userEvent.type(screen.getByLabelText(/task description/i), "Build a calculator{Enter}");
    expect(await screen.findByRole("button", { name: /starting locopilot/i })).toBeInTheDocument();
  });

  it("creates a project and uploads attachments before running when files are attached", async () => {
    useProjectsList.mockReturnValue(NO_PROJECTS);
    createProject.mockResolvedValue({ id: "proj-new" });
    uploadProjectFiles.mockResolvedValue({ files: [] });
    mutateAsync.mockResolvedValue({ id: "exec-4" });
    mockCreateExecution();
    render(<CommandCenter />);

    const file = new File(["print(1)"], "hello.py", { type: "text/x-python" });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(fileInput, file);
    expect(screen.getByText("hello.py")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/task description/i), "Review hello.py{Enter}");

    expect(createProject).toHaveBeenCalled();
    expect(uploadProjectFiles).toHaveBeenCalledWith("proj-new", [file]);
    expect(mutateAsync).toHaveBeenCalledWith({ task: "Review hello.py", project_id: "proj-new" });
  });

  it("removes an attachment when its remove button is clicked", async () => {
    useProjectsList.mockReturnValue(NO_PROJECTS);
    mockCreateExecution();
    render(<CommandCenter />);

    const file = new File(["x"], "notes.md");
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(fileInput, file);
    expect(screen.getByText("notes.md")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /remove notes.md/i }));
    expect(screen.queryByText("notes.md")).not.toBeInTheDocument();
  });

  it("disables voice input with an explanatory title when unsupported", () => {
    useProjectsList.mockReturnValue(NO_PROJECTS);
    mockCreateExecution();
    render(<CommandCenter />);

    const micButton = screen.getByRole("button", { name: /voice input/i });
    expect(micButton).toBeDisabled();
    expect(micButton).toHaveAttribute("title", "Voice input isn't supported in this browser");
  });
});
