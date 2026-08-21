"use client";

import Link from "next/link";
import { useExecutionsList, useExecutionStatusCounts } from "@/hooks/useExecutions";
import { useProjectsList } from "@/hooks/useProjects";
import { Breadcrumb } from "@/components/Breadcrumb";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";
import { CommandCenter } from "@/features/dashboard/CommandCenter";
import { formatRelativeTime, truncate } from "@/lib/format";

export default function DashboardPage() {
  const executions = useExecutionsList({ limit: 6, offset: 0 });
  const projects = useProjectsList({ limit: 5, offset: 0 });
  const counts = useExecutionStatusCounts();

  return (
    <div className="mx-auto max-w-6xl px-6 py-14 sm:px-8">
      <Breadcrumb items={[{ label: "Home", href: "/" }, { label: "Dashboard" }]} />
      <PageHeader
        eyebrow="Overview"
        title="Dashboard"
        description="Give LocoPilot a task, and watch it plan, build, test, and review the work."
      />

      <div className="mb-10">
        <CommandCenter />
      </div>

      <Panel title="Recent Executions" className="mb-10">
        {executions.isLoading ? (
          <div className="flex flex-col gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : executions.isError ? (
          <ErrorState error={executions.error} onRetry={() => executions.refetch()} />
        ) : executions.data && executions.data.items.length > 0 ? (
          <ul className="flex flex-col divide-y divide-line">
            {executions.data.items.map((execution) => (
              <li key={execution.id}>
                <Link
                  href={`/executions/${execution.id}`}
                  className="flex items-center justify-between gap-4 py-3.5 transition-colors first:pt-0 last:pb-0 hover:bg-white/[0.015]"
                >
                  <div className="min-w-0">
                    <p className="truncate text-base text-ivory">{truncate(execution.task, 64)}</p>
                    <p className="mt-1 text-sm text-ivory-faint">
                      {execution.project_name ?? "Unknown project"} · {formatRelativeTime(execution.created_at)}
                    </p>
                  </div>
                  <StatusBadge status={execution.status} />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No executions yet"
            description="Use the command center above to give LocoPilot its first task."
          />
        )}
      </Panel>

      <div className="mb-10 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line sm:grid-cols-4">
        <StatCell label="Projects" value={projects.data?.total} loading={projects.isLoading} />
        <StatCell label="Running" value={counts.data?.running} loading={counts.isLoading} accent />
        <StatCell label="Passed" value={counts.data?.passed} loading={counts.isLoading} />
        <StatCell label="Failed" value={counts.data?.failed} loading={counts.isLoading} />
      </div>

      <Panel title="Projects">
        {projects.isLoading ? (
          <div className="flex flex-col gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : projects.isError ? (
          <ErrorState error={projects.error} onRetry={() => projects.refetch()} />
        ) : projects.data && projects.data.items.length > 0 ? (
          <ul className="flex flex-col divide-y divide-line">
            {projects.data.items.map((project) => (
              <li key={project.id}>
                <Link
                  href={`/projects/${project.id}`}
                  className="flex items-center justify-between gap-4 py-3.5 transition-colors first:pt-0 last:pb-0 hover:bg-white/[0.015]"
                >
                  <p className="truncate text-base text-ivory">{project.name}</p>
                  {project.last_execution_status ? (
                    <StatusBadge status={project.last_execution_status} />
                  ) : (
                    <span className="text-sm text-ivory-faint">No runs</span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No projects yet" />
        )}
      </Panel>
    </div>
  );
}

function StatCell({ label, value, loading, accent }: { label: string; value?: number; loading: boolean; accent?: boolean }) {
  return (
    <div className="bg-ground-raised/30 px-6 py-6">
      <p className="text-xs uppercase tracking-widest2 text-ivory-faint">{label}</p>
      {loading ? (
        <Skeleton className="mt-3 h-10 w-14" />
      ) : (
        <p className={`mt-2 font-display text-5xl ${accent ? "text-gold" : "text-ivory"}`}>{value ?? 0}</p>
      )}
    </div>
  );
}
