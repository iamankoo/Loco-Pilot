"use client";

import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";
import { useRouter } from "next/navigation";
import { useProjectsList } from "@/hooks/useProjects";
import { useCreateExecution } from "@/hooks/useExecutionMutations";
import { useSpeechToText } from "@/hooks/useSpeechToText";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { MicIcon, PaperclipIcon } from "@/components/icons";

const DEFAULT_STORAGE = "__default_storage__";
const LOCAL_FOLDER = "__local_folder__";

// Kept in sync with backend ALLOWED_UPLOAD_EXTENSIONS
// (backend/app/services/workspace_files.py) — ordinary source/text/config
// files are accepted; executables/binaries/archives are not.
const ACCEPTED_ATTACHMENT_EXTENSIONS =
  ".py,.js,.jsx,.ts,.tsx,.mjs,.cjs,.json,.md,.mdx,.txt,.rst,.yaml,.yml,.toml,.ini,.cfg," +
  ".csv,.tsv,.java,.kt,.scala,.c,.h,.cpp,.cc,.hpp,.cxx,.go,.rs,.rb,.php,.swift,.m,.sql," +
  ".sh,.bash,.ps1,.html,.css,.scss,.less,.xml,.proto,.gradle";

export function CommandCenter({
  eyebrow = "Command",
  heading = "What should LocoPilot build?",
  placeholder = "e.g. Add a power(a, b) function to calculator.py that raises a to the power of b, with a test.",
}: {
  eyebrow?: string;
  heading?: string;
  placeholder?: string;
}) {
  const router = useRouter();
  const projects = useProjectsList({ limit: 100 });
  const createExecution = useCreateExecution();

  const [task, setTask] = useState("");
  const [workspaceMode, setWorkspaceMode] = useState<string>(DEFAULT_STORAGE);
  const [workspacePath, setWorkspacePath] = useState("");
  const [projectName, setProjectName] = useState("");
  const [attachments, setAttachments] = useState<File[]>([]);
  const [stage, setStage] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const speech = useSpeechToText((transcript) => {
    setTask((prev) => (prev.trim() ? `${prev.trim()} ${transcript}` : transcript));
  });

  const usingLocalFolder = workspaceMode === LOCAL_FOLDER;
  const usingDefaultStorage = workspaceMode === DEFAULT_STORAGE;
  const isBusy = createExecution.isPending || stage !== null;
  const canSubmit = task.trim().length > 0 && !isBusy && (usingLocalFolder ? workspacePath.trim().length > 0 : true);

  function addAttachments(fileList: FileList | null) {
    if (!fileList) return;
    setAttachments((prev) => [...prev, ...Array.from(fileList)]);
  }

  function removeAttachment(index: number) {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }

  async function submit() {
    if (!canSubmit) return;
    setSubmitError(null);

    try {
      let projectId: string | undefined;
      if (!usingDefaultStorage && !usingLocalFolder) {
        projectId = workspaceMode;
      }

      if (attachments.length > 0) {
        // Uploads require a project/workspace to exist first — resolve or
        // provision one before running the execution, then attach files.
        if (!projectId) {
          setStage("Preparing workspace…");
          const project = await api.createProject({
            name: projectName.trim() || undefined,
            workspace_path: usingLocalFolder ? workspacePath.trim() : undefined,
          });
          projectId = project.id;
        }
        setStage("Uploading attachments…");
        await api.uploadProjectFiles(projectId, attachments);
      }

      setStage("Starting LocoPilot…");
      const payload = projectId
        ? { task: task.trim(), project_id: projectId }
        : usingLocalFolder
          ? { task: task.trim(), workspace_path: workspacePath.trim(), project_name: projectName.trim() || undefined }
          : { task: task.trim() };

      const execution = await createExecution.mutateAsync(payload);
      router.push(`/executions/${execution.id}`);
    } catch (error) {
      setSubmitError(error instanceof ApiError ? error.message : "Failed to start the execution.");
      setStage(null);
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
    <section className="rounded-xl border border-gold/25 bg-gradient-to-b from-gold/[0.06] to-transparent p-6 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.5)] sm:p-8">
      {eyebrow ? <p className="text-xs uppercase tracking-widest2 text-gold/80">{eyebrow}</p> : null}
      {heading ? <h2 className={cn("font-display text-2xl text-ivory sm:text-3xl", eyebrow && "mt-2")}>{heading}</h2> : null}

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
          placeholder={placeholder}
          rows={6}
          disabled={isBusy}
          className="w-full resize-none rounded-lg border border-line-strong bg-black/20 p-5 text-base leading-relaxed text-ivory placeholder:text-ivory-faint focus-visible:outline-none focus-visible:border-gold/50 focus-visible:ring-2 focus-visible:ring-gold/30 disabled:opacity-60"
        />

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_ATTACHMENT_EXTENSIONS}
            className="hidden"
            onChange={(e: ChangeEvent<HTMLInputElement>) => {
              addAttachments(e.target.files);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isBusy}
            title="Attach files"
            aria-label="Attach files"
            className="flex h-8 w-8 items-center justify-center rounded-full border border-line-strong text-ivory-faint transition-colors hover:border-gold/40 hover:text-ivory focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold/30 disabled:opacity-50"
          >
            <PaperclipIcon />
          </button>

          <button
            type="button"
            onClick={speech.toggle}
            disabled={isBusy || !speech.supported}
            title={speech.supported ? (speech.isListening ? "Stop listening" : "Voice input") : "Voice input isn't supported in this browser"}
            aria-label="Voice input"
            aria-pressed={speech.isListening}
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold/30 disabled:opacity-40",
              speech.isListening
                ? "border-status-error/40 bg-status-error/10 text-status-error animate-pulse-soft"
                : "border-line-strong text-ivory-faint hover:border-gold/40 hover:text-ivory"
            )}
          >
            <MicIcon />
          </button>

          {speech.isListening ? (
            <span className="text-xs uppercase tracking-widest2 text-status-error">● Listening…</span>
          ) : null}

          {attachments.map((file, i) => (
            <span
              key={`${file.name}-${i}`}
              className="flex items-center gap-1.5 rounded-full border border-line-strong bg-white/[0.03] px-3 py-1 text-xs text-ivory-dim"
            >
              <span className="max-w-[10rem] truncate font-mono">{file.name}</span>
              <button
                type="button"
                onClick={() => removeAttachment(i)}
                aria-label={`Remove ${file.name}`}
                className="text-ivory-faint hover:text-status-error"
              >
                ×
              </button>
            </span>
          ))}
        </div>

        <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex-1">
            <label htmlFor="command-workspace" className="mb-1.5 block text-xs uppercase tracking-widest2 text-ivory-faint">
              Workspace
            </label>
            {projects.isError ? (
              <p className="text-sm text-status-error">Could not load projects — LocoPilot Storage is still available below.</p>
            ) : (
              <select
                id="command-workspace"
                value={workspaceMode}
                onChange={(e) => setWorkspaceMode(e.target.value)}
                disabled={isBusy || projects.isLoading}
                className="w-full rounded-md border border-line-strong bg-black/20 px-3 py-2.5 text-sm text-ivory focus-visible:outline-none focus-visible:border-gold/50 focus-visible:ring-2 focus-visible:ring-gold/30 disabled:opacity-60"
              >
                <option value={DEFAULT_STORAGE}>LocoPilot Storage (default)</option>
                {projects.data?.items.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
                <option value={LOCAL_FOLDER}>Local folder…</option>
              </select>
            )}
          </div>

          <button
            type="submit"
            disabled={!canSubmit}
            className="flex-shrink-0 rounded-full bg-gold px-6 py-2.5 text-sm font-medium tracking-wide text-ground transition-transform duration-200 hover:scale-[1.02] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold/50 focus-visible:ring-offset-2 focus-visible:ring-offset-ground disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:scale-100"
          >
            {stage ?? (createExecution.isPending ? "Starting LocoPilot…" : "Run LocoPilot →")}
          </button>
        </div>

        {usingLocalFolder ? (
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="command-workspace-path" className="mb-1.5 block text-xs uppercase tracking-widest2 text-ivory-faint">
                Local folder path
              </label>
              <input
                id="command-workspace-path"
                value={workspacePath}
                onChange={(e) => setWorkspacePath(e.target.value)}
                placeholder="/path/to/repository"
                disabled={isBusy}
                className="w-full rounded-md border border-line-strong bg-black/20 px-3 py-2.5 font-mono text-sm text-ivory placeholder:text-ivory-faint focus-visible:outline-none focus-visible:border-gold/50 focus-visible:ring-2 focus-visible:ring-gold/30 disabled:opacity-60"
              />
            </div>
            <div>
              <label htmlFor="command-project-name" className="mb-1.5 block text-xs uppercase tracking-widest2 text-ivory-faint">
                Project name (optional)
              </label>
              <input
                id="command-project-name"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="my-project"
                disabled={isBusy}
                className="w-full rounded-md border border-line-strong bg-black/20 px-3 py-2.5 text-sm text-ivory placeholder:text-ivory-faint focus-visible:outline-none focus-visible:border-gold/50 focus-visible:ring-2 focus-visible:ring-gold/30 disabled:opacity-60"
              />
            </div>
          </div>
        ) : null}

        {submitError ? <p className="mt-4 text-sm text-status-error">{submitError}</p> : null}
      </form>
    </section>
  );
}
