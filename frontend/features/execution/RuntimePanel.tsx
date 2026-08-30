"use client";

import { useState } from "react";
import type { RuntimeStatus, TestResultSummary } from "@/lib/types";
import { EmptyState } from "@/components/EmptyState";
import { ExternalLinkIcon } from "@/components/icons";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";
import { useExecutionRuntime } from "@/hooks/useExecutions";

const STATUS_LABEL: Record<string, string> = {
  starting: "Starting",
  running: "Running",
  verification_failed: "Verification failed",
  start_failed: "Failed to start",
  stopped: "Stopped",
  no_runtime: "No runtime",
};

const STATUS_DOT: Record<string, string> = {
  starting: "bg-status-running animate-pulse-soft",
  running: "bg-status-success",
  verification_failed: "bg-status-error",
  start_failed: "bg-status-error",
  stopped: "bg-ivory-faint",
  no_runtime: "bg-ivory-faint",
};

export function RuntimePanel({
  executionId,
  testResults,
}: {
  executionId: string;
  testResults: TestResultSummary | null;
}) {
  const hasRuntime = Boolean(testResults?.runtime_status);
  const live = useExecutionRuntime(executionId, hasRuntime);
  const [stopping, setStopping] = useState(false);

  if (!hasRuntime) {
    return (
      <EmptyState
        title="No runtime available"
        description="This task didn't produce a running application — a runtime only starts when the plan specifies a run command."
      />
    );
  }

  const data: RuntimeStatus | undefined = live.data;
  const status = data?.status ?? testResults?.runtime_status ?? "no_runtime";
  const url = data?.url ?? testResults?.runtime_url ?? null;
  const canOpen = status === "running" && Boolean(url);

  async function handleStop() {
    setStopping(true);
    try {
      await api.stopExecutionRuntime(executionId);
      await live.refetch();
    } finally {
      setStopping(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2.5">
        <span className={cn("h-2 w-2 rounded-full", STATUS_DOT[status] ?? "bg-ivory-faint")} />
        <p className="text-xs uppercase tracking-widest2 text-ivory-faint">
          {STATUS_LABEL[status] ?? status}
        </p>
      </div>

      {url ? (
        <code className="rounded bg-black/30 px-3 py-2 font-mono text-sm text-ivory-dim break-all">{url}</code>
      ) : null}

      {data?.detail ? <p className="text-sm leading-relaxed text-ivory-faint">{data.detail}</p> : null}

      <div className="flex flex-wrap gap-2">
        {canOpen ? (
          <a
            href={url ?? undefined}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 rounded-full bg-gold px-4 py-2 text-sm font-medium text-ground transition-transform duration-200 hover:scale-[1.02]"
          >
            Open in Browser
            <ExternalLinkIcon />
          </a>
        ) : null}
        {status === "running" || status === "starting" ? (
          <button
            type="button"
            onClick={handleStop}
            disabled={stopping}
            className="rounded-full border border-line-strong px-4 py-2 text-sm text-ivory-dim transition-colors hover:border-gold/40 hover:text-ivory disabled:opacity-50"
          >
            {stopping ? "Stopping…" : "Stop"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
