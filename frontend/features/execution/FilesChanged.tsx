"use client";

import { useState } from "react";
import type { FileChangeSummary, ToolCallSummary } from "@/lib/types";
import { EmptyState } from "@/components/EmptyState";
import { cn } from "@/lib/cn";

/** Reconstructs a lightweight diff view per file purely from already-persisted
 * `edit_file`/`write_file` tool-call input/output — there is no separate
 * diff/patch storage, so this is the real record of what each tool call did,
 * not a fabricated diff. */
function editsForPath(toolCalls: ToolCallSummary[], path: string) {
  return toolCalls.filter(
    (call) =>
      (call.tool_name === "edit_file" || call.tool_name === "write_file") &&
      call.status === "success" &&
      (call.input as { path?: string } | null)?.path === path
  );
}

export function FilesChanged({ files, toolCalls }: { files: FileChangeSummary[]; toolCalls: ToolCallSummary[] }) {
  if (files.length === 0) {
    return <EmptyState title="No files changed yet" description="File edits will appear here as the Developer agent works." />;
  }

  return (
    <ul className="flex flex-col divide-y divide-line">
      {files.map((file, i) => (
        <FileRow key={`${file.path}-${i}`} file={file} edits={editsForPath(toolCalls, file.path)} />
      ))}
    </ul>
  );
}

function FileRow({ file, edits }: { file: FileChangeSummary; edits: ToolCallSummary[] }) {
  const [open, setOpen] = useState(false);
  const hasDiff = edits.length > 0;

  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <button
        onClick={() => hasDiff && setOpen((v) => !v)}
        className={cn("flex w-full items-center justify-between gap-3 text-left", !hasDiff && "cursor-default")}
      >
        <div className="flex min-w-0 items-center gap-3">
          <ChangeTypeTag type={file.change_type} />
          <span className="truncate font-mono text-sm text-ivory">{file.path}</span>
        </div>
        {file.detail ? <span className="flex-shrink-0 text-sm text-ivory-faint">{file.detail}</span> : null}
      </button>

      {open && hasDiff ? (
        <div className="mt-3 flex flex-col gap-3">
          {edits.map((edit) => (
            <DiffBlock key={edit.id} call={edit} />
          ))}
        </div>
      ) : null}
    </li>
  );
}

function ChangeTypeTag({ type }: { type: string }) {
  return (
    <span className="flex-shrink-0 rounded border border-line-strong px-1.5 py-0.5 text-xs uppercase tracking-wide text-ivory-faint">
      {type}
    </span>
  );
}

function DiffBlock({ call }: { call: ToolCallSummary }) {
  const input = call.input as { old_string?: string; new_string?: string; content?: string } | null;
  if (!input) return null;

  if (call.tool_name === "write_file" && typeof input.content === "string") {
    return (
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded border border-status-success/20 bg-status-success/[0.04] p-3 font-mono text-sm leading-relaxed">
        {input.content
          .split("\n")
          .map((line, i) => (
            <div key={i} className="text-status-success">
              + {line}
            </div>
          ))}
      </pre>
    );
  }

  return (
    <div className="overflow-hidden rounded border border-line">
      {typeof input.old_string === "string" ? (
        <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words border-b border-line bg-status-error/[0.04] p-3 font-mono text-sm leading-relaxed">
          {input.old_string.split("\n").map((line, i) => (
            <div key={i} className="text-status-error">
              − {line}
            </div>
          ))}
        </pre>
      ) : null}
      {typeof input.new_string === "string" ? (
        <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words bg-status-success/[0.04] p-3 font-mono text-sm leading-relaxed">
          {input.new_string.split("\n").map((line, i) => (
            <div key={i} className="text-status-success">
              + {line}
            </div>
          ))}
        </pre>
      ) : null}
    </div>
  );
}
