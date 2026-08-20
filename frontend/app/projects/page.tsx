"use client";

import { useState } from "react";
import Link from "next/link";
import { useProjectsList } from "@/hooks/useProjects";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { SkeletonLines } from "@/components/Skeleton";
import { Pagination } from "@/components/Pagination";
import { formatTimestamp } from "@/lib/format";

const LIMIT = 15;

export default function ProjectsPage() {
  const [offset, setOffset] = useState(0);
  const projects = useProjectsList({ limit: LIMIT, offset });

  return (
    <div className="mx-auto max-w-6xl px-6 py-14 sm:px-8">
      <PageHeader
        eyebrow="Workspace"
        title="Projects"
        description="Every codebase LocoPilot has run an execution against."
      />

      <Panel>
        {projects.isLoading ? (
          <SkeletonLines count={5} />
        ) : projects.isError ? (
          <ErrorState error={projects.error} onRetry={() => projects.refetch()} />
        ) : projects.data && projects.data.items.length > 0 ? (
          <ul className="flex flex-col divide-y divide-line">
            {projects.data.items.map((project) => (
              <li key={project.id}>
                <Link
                  href={`/projects/${project.id}`}
                  className="flex flex-col gap-3 py-4 transition-colors first:pt-0 last:pb-0 hover:bg-white/[0.015] sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <p className="truncate text-base text-ivory">{project.name}</p>
                    <p className="mt-1 text-sm text-ivory-faint">
                      {project.workspace_path ?? project.repo_url ?? "No workspace path recorded"} · created{" "}
                      {formatTimestamp(project.created_at)}
                    </p>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-sm text-ivory-faint">
                      {Object.values(project.execution_counts).reduce((a, b) => a + b, 0)} execution(s)
                    </span>
                    {project.last_execution_status ? (
                      <StatusBadge status={project.last_execution_status} />
                    ) : (
                      <span className="text-sm text-ivory-faint">No runs</span>
                    )}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No projects yet"
            description="Projects are created automatically the first time an execution runs against a workspace."
          />
        )}
      </Panel>

      {projects.data && projects.data.total > LIMIT ? (
        <div className="mt-4 rounded-lg border border-line">
          <Pagination total={projects.data.total} limit={LIMIT} offset={offset} onOffsetChange={setOffset} />
        </div>
      ) : null}
    </div>
  );
}
