"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useProjectDetail } from "@/hooks/useProjects";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { SkeletonLines, Skeleton } from "@/components/Skeleton";
import { formatRelativeTime, formatTimestamp, truncate } from "@/lib/format";

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const project = useProjectDetail(params.id);

  if (project.isLoading) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-14 sm:px-8">
        <Skeleton className="mb-4 h-4 w-32" />
        <Skeleton className="mb-10 h-10 w-96" />
        <SkeletonLines count={4} />
      </div>
    );
  }

  if (project.isError) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-14 sm:px-8">
        <ErrorState error={project.error} onRetry={() => project.refetch()} />
      </div>
    );
  }

  const data = project.data;
  if (!data) return null;

  const totalExecutions = Object.values(data.execution_counts).reduce((a, b) => a + b, 0);

  return (
    <div className="mx-auto max-w-6xl px-6 py-14 sm:px-8">
      <p className="mb-3 text-xs uppercase tracking-widest2 text-gold/80">Project</p>
      <h1 className="font-display text-4xl tracking-tightest text-ivory sm:text-5xl">{data.name}</h1>
      <p className="mt-3 text-base text-ivory-faint">
        {data.workspace_path ?? data.repo_url ?? "No workspace path recorded"} · created{" "}
        {formatTimestamp(data.created_at)}
      </p>

      <div className="my-10 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line sm:grid-cols-4">
        <div className="bg-ground-raised/30 px-6 py-6">
          <p className="text-xs uppercase tracking-widest2 text-ivory-faint">Total Runs</p>
          <p className="mt-2 font-display text-4xl text-ivory">{totalExecutions}</p>
        </div>
        {Object.entries(data.execution_counts).map(([status, count]) => (
          <div key={status} className="bg-ground-raised/30 px-6 py-6">
            <p className="text-xs uppercase tracking-widest2 text-ivory-faint">{status.replace("_", " ")}</p>
            <p className="mt-2 font-display text-4xl text-ivory">{count}</p>
          </div>
        ))}
      </div>

      <Panel title="Recent Executions">
        {data.recent_executions.length > 0 ? (
          <ul className="flex flex-col divide-y divide-line">
            {data.recent_executions.map((execution) => (
              <li key={execution.id}>
                <Link
                  href={`/executions/${execution.id}`}
                  className="flex items-center justify-between gap-4 py-3.5 transition-colors first:pt-0 last:pb-0 hover:bg-white/[0.015]"
                >
                  <div className="min-w-0">
                    <p className="truncate text-base text-ivory">{truncate(execution.task, 72)}</p>
                    <p className="mt-1 text-sm text-ivory-faint">{formatRelativeTime(execution.created_at)}</p>
                  </div>
                  <StatusBadge status={execution.status} />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No executions yet for this project" />
        )}
      </Panel>
    </div>
  );
}
