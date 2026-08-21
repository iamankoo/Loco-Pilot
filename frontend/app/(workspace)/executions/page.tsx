"use client";

import { useState } from "react";
import Link from "next/link";
import { useExecutionsList } from "@/hooks/useExecutions";
import { Breadcrumb } from "@/components/Breadcrumb";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { SkeletonLines } from "@/components/Skeleton";
import { Pagination } from "@/components/Pagination";
import { cn } from "@/lib/cn";
import { formatDuration, formatTimestamp, statusLabel, truncate } from "@/lib/format";

const LIMIT = 20;

const STATUS_FILTERS = [
  { value: undefined, label: "All" },
  { value: "running", label: statusLabel("running") },
  { value: "pending", label: statusLabel("pending") },
  { value: "passed", label: statusLabel("passed") },
  { value: "failed", label: statusLabel("failed") },
  { value: "needs_review", label: statusLabel("needs_review") },
  { value: "error", label: statusLabel("error") },
  { value: "cancelled", label: statusLabel("cancelled") },
  { value: "timed_out", label: statusLabel("timed_out") },
] as const;

export default function ExecutionsPage() {
  const [status, setStatus] = useState<string | undefined>(undefined);
  const [offset, setOffset] = useState(0);
  const executions = useExecutionsList({ status, limit: LIMIT, offset });

  return (
    <div className="mx-auto max-w-6xl px-6 py-14 sm:px-8">
      <Breadcrumb items={[{ label: "Home", href: "/" }, { label: "Executions" }]} />
      <PageHeader eyebrow="History" title="Executions" description="Every run LocoPilot has attempted, in order." />

      <div className="mb-6 flex flex-wrap gap-2">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.label}
            onClick={() => {
              setStatus(filter.value);
              setOffset(0);
            }}
            className={cn(
              "rounded-full border px-3.5 py-1.5 text-sm tracking-wide transition-colors",
              status === filter.value
                ? "border-gold/40 bg-gold/10 text-gold"
                : "border-line-strong text-ivory-faint hover:text-ivory-dim"
            )}
          >
            {filter.label}
          </button>
        ))}
      </div>

      <Panel>
        {executions.isLoading ? (
          <SkeletonLines count={6} />
        ) : executions.isError ? (
          <ErrorState error={executions.error} onRetry={() => executions.refetch()} />
        ) : executions.data && executions.data.items.length > 0 ? (
          <ul className="flex flex-col divide-y divide-line">
            {executions.data.items.map((execution) => (
              <li key={execution.id}>
                <Link
                  href={`/executions/${execution.id}`}
                  className="flex flex-col gap-2 py-4 transition-colors first:pt-0 last:pb-0 hover:bg-white/[0.015] sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <p className="truncate text-base text-ivory">{truncate(execution.task, 80)}</p>
                    <p className="mt-1 text-sm text-ivory-faint">
                      {execution.project_name ?? "Unknown project"} · {formatTimestamp(execution.created_at)} ·{" "}
                      {formatDuration(execution.elapsed_seconds)}
                    </p>
                  </div>
                  <StatusBadge status={execution.status} />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No executions found"
            description={status ? `No executions with status "${statusLabel(status)}".` : "No executions have run yet."}
          />
        )}
      </Panel>

      {executions.data && executions.data.total > LIMIT ? (
        <div className="mt-4 rounded-lg border border-line">
          <Pagination total={executions.data.total} limit={LIMIT} offset={offset} onOffsetChange={setOffset} />
        </div>
      ) : null}
    </div>
  );
}
