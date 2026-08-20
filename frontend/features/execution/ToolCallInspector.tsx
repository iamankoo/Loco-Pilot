"use client";

import { useState } from "react";
import type { ToolCallSummary } from "@/lib/types";
import { formatDurationMs, formatTimestamp } from "@/lib/format";
import { EmptyState } from "@/components/EmptyState";
import { cn } from "@/lib/cn";

export function ToolCallInspector({ toolCalls }: { toolCalls: ToolCallSummary[] }) {
  if (toolCalls.length === 0) {
    return <EmptyState title="No tool calls yet" description="Filesystem, terminal, and git actions will appear here." />;
  }

  return (
    <ul className="flex flex-col divide-y divide-line">
      {toolCalls.map((call) => (
        <ToolCallRow key={call.id} call={call} />
      ))}
    </ul>
  );
}

function ToolCallRow({ call }: { call: ToolCallSummary }) {
  const [open, setOpen] = useState(false);
  const failed = call.status !== "success";

  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <div className="flex min-w-0 items-center gap-3">
          <span
            className={cn(
              "h-1.5 w-1.5 flex-shrink-0 rounded-full",
              failed ? "bg-status-error" : "bg-status-success"
            )}
          />
          <span className="truncate font-mono text-sm text-ivory">{call.tool_name}</span>
        </div>
        <div className="flex flex-shrink-0 items-center gap-3 text-sm text-ivory-faint">
          <span>{formatDurationMs(call.duration_ms)}</span>
          <span>{formatTimestamp(call.created_at)}</span>
          <ChevronIcon open={open} />
        </div>
      </button>

      {open ? (
        <div className="mt-3 flex flex-col gap-3 rounded-md border border-line bg-white/[0.015] p-3.5">
          {call.error_message ? (
            <p className="text-base text-status-error">{call.error_message}</p>
          ) : null}
          <ToolCallJsonBlock label="Input" value={call.input} />
          <ToolCallJsonBlock label="Output" value={call.output} />
        </div>
      ) : null}
    </li>
  );
}

function ToolCallJsonBlock({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined) return null;
  return (
    <div>
      <p className="mb-1.5 text-xs uppercase tracking-widest2 text-ivory-faint">{label}</p>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-black/30 p-3 font-mono text-xs leading-relaxed text-ivory-dim">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 12 12"
      fill="none"
      className={cn("transition-transform duration-200", open && "rotate-180")}
    >
      <path d="M2.5 4.5L6 8L9.5 4.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
