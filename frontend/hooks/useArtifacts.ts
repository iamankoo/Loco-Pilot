"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ArtifactSummary } from "@/lib/types";

export interface ArtifactWithExecution extends ArtifactSummary {
  execution_id: string;
  execution_task: string;
  project_name: string | null;
}

const RECENT_EXECUTIONS_SCANNED = 25;

/** No global "list all artifacts" endpoint exists — artifacts are scoped
 * per-execution by design (see `/api/v1/executions/{id}/artifacts`). This
 * fans out over the most recently created executions and combines their
 * real, already-persisted artifacts rather than adding a new backend
 * aggregate endpoint for a secondary page. */
export function useRecentArtifacts() {
  return useQuery({
    queryKey: ["recent-artifacts"],
    queryFn: async (): Promise<ArtifactWithExecution[]> => {
      const executions = await api.listExecutions({ limit: RECENT_EXECUTIONS_SCANNED, offset: 0 });
      const perExecution = await Promise.all(
        executions.items.map(async (execution) => {
          const artifacts = await api.listExecutionArtifacts(execution.id);
          return artifacts.map((artifact) => ({
            ...artifact,
            execution_id: execution.id,
            execution_task: execution.task,
            project_name: execution.project_name,
          }));
        })
      );
      return perExecution.flat().sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    },
    refetchInterval: 20_000,
  });
}
