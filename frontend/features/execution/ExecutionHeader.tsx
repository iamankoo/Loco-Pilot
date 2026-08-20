"use client";

import { useState } from "react";
import Link from "next/link";
import type { ExecutionDetail } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";
import { useCancelExecution } from "@/hooks/useExecutionMutations";
import { formatDuration, formatTimestamp, isActiveExecution } from "@/lib/format";

export function ExecutionHeader({ execution }: { execution: ExecutionDetail }) {
  const cancelMutation = useCancelExecution(execution.id);
  const [confirming, setConfirming] = useState(false);
  const cancellable = isActiveExecution(execution.status);

  return (
    <div className="mb-10">
      <div className="mb-4 flex items-center gap-2 text-sm text-ivory-faint">
        <Link href="/executions" className="hover:text-ivory-dim">
          Executions
        </Link>
        <span>/</span>
        {execution.project_id ? (
          <Link href={`/projects/${execution.project_id}`} className="hover:text-ivory-dim">
            {execution.project_name ?? "Project"}
          </Link>
        ) : null}
      </div>

      <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="font-display text-balance text-3xl leading-[1.15] tracking-tightest text-ivory sm:text-4xl lg:text-[2.75rem]">
            {execution.task}
          </h1>
          <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-ivory-faint">
            <StatusBadge status={execution.status} />
            <span>Created {formatTimestamp(execution.created_at)}</span>
            {execution.started_at ? <span>Started {formatTimestamp(execution.started_at)}</span> : null}
            <span>Elapsed {formatDuration(execution.elapsed_seconds)}</span>
            {execution.retry_count > 0 ? <span className="text-gold/80">{execution.retry_count} retry(s)</span> : null}
          </div>
        </div>

        {cancellable ? (
          <div className="flex flex-shrink-0 items-center gap-2">
            {confirming ? (
              <>
                <button
                  onClick={() => cancelMutation.mutate(undefined, { onSettled: () => setConfirming(false) })}
                  disabled={cancelMutation.isPending}
                  className="rounded-full border border-status-error/40 bg-status-error/10 px-4 py-1.5 text-sm text-status-error transition-colors hover:bg-status-error/20 disabled:opacity-50"
                >
                  {cancelMutation.isPending ? "Cancelling…" : "Confirm cancel"}
                </button>
                <button
                  onClick={() => setConfirming(false)}
                  className="rounded-full border border-line-strong px-3.5 py-1.5 text-sm text-ivory-faint hover:text-ivory-dim"
                >
                  Back
                </button>
              </>
            ) : (
              <button
                onClick={() => setConfirming(true)}
                className="rounded-full border border-line-strong px-4 py-1.5 text-sm text-ivory-dim transition-colors hover:border-status-error/40 hover:text-status-error"
              >
                Cancel execution
              </button>
            )}
          </div>
        ) : null}
      </div>

      {cancelMutation.isError ? (
        <p className="mt-3 text-sm text-status-error">Failed to cancel — it may have already finished.</p>
      ) : null}

      {execution.error_message ? (
        <p className="mt-4 whitespace-pre-wrap rounded-md border border-status-error/25 bg-status-error/[0.05] px-4 py-3 text-base leading-relaxed text-status-error">
          {execution.error_message}
        </p>
      ) : null}
    </div>
  );
}
