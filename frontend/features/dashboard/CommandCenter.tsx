"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useRouter } from "next/navigation";
import { useProjectsList } from "@/hooks/useProjects";
import { useCreateExecution } from "@/hooks/useExecutionMutations";
import { ApiError } from "@/lib/api";

const NEW_WORKSPACE = "__new_workspace__";

export function CommandCenter() {
  const router = useRouter();
  const projects = useProjectsList({ limit: 100 });
  const createExecution = useCreateExecution();

  const [task, setTask] = useState("");
  const [projectId, setProjectId] = useState<string>(NEW_WORKSPACE);
  const [workspacePath, setWorkspacePath] = useState("");
  const [projectName, setProjectName] = useState("");
  const autoSelectedRef = useRef(false);

  useEffect(() => {
    if (!autoSelectedRef.current && projects.data && projects.data.items.length > 0) {
      autoSelectedRef.current = true;
      setProjectId(projects.data.items[0]!.id);
    }
  }, [projects.data]);

  const hasProjects = (projects.data?.items.length ?? 0) > 0;
  const usingNewWorkspace = projectId === NEW_WORKSPACE;
  const canSubmit =
    task.trim().length > 0 &&
    !createExecution.isPending &&
    (usingNewWorkspace ? workspacePath.trim().length > 0 : true);

  async function submit() {
    if (!canSubmit) return;
    const payload = usingNewWorkspace
      ? {
          task: task.trim(),
          workspace_path: workspacePath.trim(),
          project_name: projectName.trim() || undefined,
        }
      : { task: task.trim(), project_id: projectId };

    try {
      const execution = await createExecution.mutateAsync(payload);
      router.push(`/executions/${execution.id}`);
    } catch {
      // surfaced via createExecution.isError below
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void submit();
    } else if (e.key === "Escape") {
      e.currentTarget.blur();
    }
  }

  return (
    <section className="rounded-lg border border-gold/25 bg-gradient-to-b from-gold/[0.05] to-transparent p-6 sm:p-8">
      <p className="text-xs uppercase tracking-widest2 text-gold/80">Command</p>
      <h2 className="mt-2 font-display text-2xl text-ivory sm:text-3xl">What should LocoPilot build?</h2>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="mt-6"
      >
        <label htmlFor="command-task" className="sr-only">
          Task description
        </label>
        <textarea
          id="command-task"
          value={task}
          onChange={(e) => setTask(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="e.g. Add a power(a, b) function to calculator.py that raises a to the power of b, with a test."
          rows={4}
          disabled={createExecution.isPending}
          className="w-full resize-none rounded-md border border-line-strong bg-black/20 p-4 text-base leading-relaxed text-ivory placeholder:text-ivory-faint focus-visible:outline-none focus-visible:border-gold/50 focus-visible:ring-2 focus-visible:ring-gold/30 disabled:opacity-60"
        />

        <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex-1">
            <label htmlFor="command-project" className="mb-1.5 block text-xs uppercase tracking-widest2 text-ivory-faint">
              Project
            </label>
            {projects.isError ? (
              <p className="text-sm text-status-error">
                Could not load projects — you can still start a new workspace below.
              </p>
            ) : (
              <select
                id="command-project"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                disabled={createExecution.isPending || projects.isLoading}
                className="w-full rounded-md border border-line-strong bg-black/20 px-3 py-2.5 text-sm text-ivory focus-visible:outline-none focus-visible:border-gold/50 focus-visible:ring-2 focus-visible:ring-gold/30 disabled:opacity-60"
              >
                {projects.data?.items.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
                <option value={NEW_WORKSPACE}>+ New workspace…</option>
              </select>
            )}
          </div>

          <button
            type="submit"
            disabled={!canSubmit}
            className="flex-shrink-0 rounded-full bg-gold px-6 py-2.5 text-sm font-medium tracking-wide text-ground transition-transform duration-200 hover:scale-[1.02] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold/50 focus-visible:ring-offset-2 focus-visible:ring-offset-ground disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:scale-100"
          >
            {createExecution.isPending ? "Starting LocoPilot…" : "Run LocoPilot →"}
          </button>
        </div>

        {usingNewWorkspace ? (
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="command-workspace" className="mb-1.5 block text-xs uppercase tracking-widest2 text-ivory-faint">
                Workspace path
              </label>
              <input
                id="command-workspace"
                value={workspacePath}
                onChange={(e) => setWorkspacePath(e.target.value)}
                placeholder="/path/to/repository"
                disabled={createExecution.isPending}
                className="w-full rounded-md border border-line-strong bg-black/20 px-3 py-2.5 font-mono text-sm text-ivory placeholder:text-ivory-faint focus-visible:outline-none focus-visible:border-gold/50 focus-visible:ring-2 focus-visible:ring-gold/30 disabled:opacity-60"
              />
            </div>
            <div>
              <label
                htmlFor="command-project-name"
                className="mb-1.5 block text-xs uppercase tracking-widest2 text-ivory-faint"
              >
                Project name (optional)
              </label>
              <input
                id="command-project-name"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="my-project"
                disabled={createExecution.isPending}
                className="w-full rounded-md border border-line-strong bg-black/20 px-3 py-2.5 text-sm text-ivory placeholder:text-ivory-faint focus-visible:outline-none focus-visible:border-gold/50 focus-visible:ring-2 focus-visible:ring-gold/30 disabled:opacity-60"
              />
            </div>
          </div>
        ) : null}

        {createExecution.isError ? (
          <p className="mt-4 text-sm text-status-error">
            {createExecution.error instanceof ApiError
              ? createExecution.error.message
              : "Failed to start the execution — the backend may be unreachable."}
          </p>
        ) : null}

        {!hasProjects && !projects.isLoading && !projects.isError ? (
          <p className="mt-4 text-sm text-ivory-faint">
            No projects yet — provide a workspace path above and LocoPilot will create one automatically.
          </p>
        ) : null}
      </form>
    </section>
  );
}
