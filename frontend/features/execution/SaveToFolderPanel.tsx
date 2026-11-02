"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useLocalFolder } from "@/hooks/useLocalFolder";
import { saveProjectToFolder, type SyncResult } from "@/lib/local-folder";

const SYNCED_KEY_PREFIX = "locopilot.synced.";

function wasSynced(executionId: string): boolean {
  try {
    return window.localStorage.getItem(SYNCED_KEY_PREFIX + executionId) !== null;
  } catch {
    return false;
  }
}

function markSynced(executionId: string): void {
  try {
    window.localStorage.setItem(SYNCED_KEY_PREFIX + executionId, new Date().toISOString());
  } catch {
    // best effort — worst case the project is offered for saving again
  }
}

/** Copies the finished project from the server onto the folder the user
 * picked on their own machine. Runs automatically ONCE per execution when it
 * finishes (if permission is still granted); after that, only on request —
 * re-syncing would overwrite edits the user made locally in the meantime. */
export function SaveToFolderPanel({
  executionId,
  projectId,
  projectName,
  finished,
}: {
  executionId: string;
  projectId: string;
  projectName: string | null;
  finished: boolean;
}) {
  const folder = useLocalFolder();
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [result, setResult] = useState<SyncResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const autoTried = useRef(false);

  const sync = useCallback(async () => {
    if (!folder.handle) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const tree = await api.listProjectFileTree(projectId);
      const synced = await saveProjectToFolder(
        folder.handle,
        projectName ?? `project-${projectId.slice(0, 8)}`,
        tree.files,
        (path) => api.fetchProjectFile(projectId, path),
        (done, total) => setProgress({ done, total })
      );
      markSynced(executionId);
      setResult(
        tree.truncated
          ? { ...synced, skipped: [...synced.skipped, "(project has more files than the 2,000-file save limit)"] }
          : synced
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Saving failed.");
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }, [executionId, folder.handle, projectId, projectName]);

  // One automatic save when the run finishes, only if permission is intact.
  useEffect(() => {
    if (!finished || !folder.ready || !folder.handle || !folder.granted) return;
    if (autoTried.current || wasSynced(executionId)) return;
    autoTried.current = true;
    void sync();
  }, [executionId, finished, folder.ready, folder.handle, folder.granted, sync]);

  if (!folder.ready) return null;

  if (!folder.supported) {
    return (
      <p className="text-sm leading-relaxed text-ivory-dim">
        Your browser can&apos;t save directly to a folder on your computer. Open LocoPilot in Chrome or Edge to have the
        finished files written to a folder you choose.
      </p>
    );
  }

  if (!folder.handle) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm leading-relaxed text-ivory-dim">
          No save folder is selected, so the files only exist on the server. Choose a folder to copy them to your
          computer.
        </p>
        <button
          type="button"
          onClick={() => void folder.choose()}
          className="self-start rounded-full bg-gold px-5 py-2 text-sm font-medium text-ground"
        >
          Choose folder
        </button>
      </div>
    );
  }

  const target = `${folder.handle.name}/…`;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm leading-relaxed text-ivory-dim">
        Save location: <span className="font-mono text-ivory">{target}</span>
        {projectName ? <> (in a <span className="font-mono text-ivory">{projectName}</span> subfolder)</> : null}
      </p>

      {busy ? (
        <p className="text-sm text-ivory-dim">
          Saving files{progress ? ` — ${progress.done} of ${progress.total}` : "…"}
        </p>
      ) : null}

      {result ? (
        <p className="text-sm text-status-success">
          Saved {result.written} file{result.written === 1 ? "" : "s"} to{" "}
          <span className="font-mono">{result.folder}</span>. Open that folder in VS Code to run them.
        </p>
      ) : null}
      {result && result.skipped.length > 0 ? (
        <p className="text-xs text-ivory-faint">Skipped: {result.skipped.join(", ")}</p>
      ) : null}
      {error ? <p className="text-sm text-status-error">{error}</p> : null}

      <div className="flex flex-wrap gap-2">
        {!folder.granted ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => void folder.regrant()}
            className="rounded-full bg-gold px-5 py-2 text-sm font-medium text-ground disabled:opacity-40"
          >
            Allow access to this folder
          </button>
        ) : (
          <button
            type="button"
            disabled={busy || !finished}
            onClick={() => void sync()}
            className="rounded-full bg-gold px-5 py-2 text-sm font-medium text-ground disabled:cursor-not-allowed disabled:opacity-40"
          >
            {finished ? "Save to my computer" : "Waiting for the run to finish…"}
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => void folder.choose()}
          className="rounded-full border border-line-strong px-5 py-2 text-sm text-ivory-dim hover:text-ivory disabled:opacity-40"
        >
          Change folder
        </button>
      </div>
      {finished && result === null && !busy ? (
        <p className="text-xs text-ivory-faint">
          Saving again overwrites files with the same name in that folder, including any edits you made there.
        </p>
      ) : null}
    </div>
  );
}
