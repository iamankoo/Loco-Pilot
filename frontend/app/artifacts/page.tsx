"use client";

import Link from "next/link";
import { useRecentArtifacts } from "@/hooks/useArtifacts";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { SkeletonLines } from "@/components/Skeleton";
import { formatTimestamp, truncate } from "@/lib/format";

export default function ArtifactsPage() {
  const artifacts = useRecentArtifacts();

  return (
    <div className="mx-auto max-w-6xl px-6 py-14 sm:px-8">
      <PageHeader
        eyebrow="Outputs"
        title="Artifacts"
        description="Build outputs and generated files from recent executions."
      />

      <Panel>
        {artifacts.isLoading ? (
          <SkeletonLines count={5} />
        ) : artifacts.isError ? (
          <ErrorState error={artifacts.error} onRetry={() => artifacts.refetch()} />
        ) : artifacts.data && artifacts.data.length > 0 ? (
          <ul className="flex flex-col divide-y divide-line">
            {artifacts.data.map((artifact) => (
              <li key={artifact.id}>
                <Link
                  href={`/executions/${artifact.execution_id}`}
                  className="flex flex-col gap-2 py-3.5 transition-colors first:pt-0 last:pb-0 hover:bg-white/[0.015] sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <p className="truncate font-mono text-sm text-ivory">{artifact.path}</p>
                    <p className="mt-1 text-sm text-ivory-faint">
                      {artifact.artifact_type} · {truncate(artifact.execution_task, 60)}
                      {artifact.project_name ? ` · ${artifact.project_name}` : ""}
                    </p>
                  </div>
                  <span className="flex-shrink-0 text-sm text-ivory-faint">{formatTimestamp(artifact.created_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No artifacts yet"
            description="Artifacts produced by an execution — build outputs, packaged files — will appear here."
          />
        )}
      </Panel>
    </div>
  );
}
