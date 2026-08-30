"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { isActiveExecution } from "@/lib/format";

/** Executions in a non-terminal state poll faster; the list overall polls
 * at a modest interval so a history table doesn't need to be watched. */
const LIST_POLL_MS = 8_000;
const DETAIL_POLL_MS = 2_500;

export function useExecutionsList(params: {
  projectId?: string;
  status?: string;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ["executions", params],
    queryFn: () => api.listExecutions(params),
    refetchInterval: LIST_POLL_MS,
  });
}

export function useExecutionDetail(executionId: string | undefined) {
  return useQuery({
    queryKey: ["execution", executionId],
    queryFn: () => api.getExecution(executionId as string),
    enabled: Boolean(executionId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status) return DETAIL_POLL_MS;
      return isActiveExecution(status) ? DETAIL_POLL_MS : false;
    },
  });
}

export function useExecutionSteps(executionId: string | undefined, active: boolean) {
  return useQuery({
    queryKey: ["execution-steps", executionId],
    queryFn: () => api.listExecutionSteps(executionId as string),
    enabled: Boolean(executionId),
    refetchInterval: active ? DETAIL_POLL_MS : false,
  });
}

export function useExecutionToolCalls(executionId: string | undefined, active: boolean) {
  return useQuery({
    queryKey: ["execution-tool-calls", executionId],
    queryFn: () => api.listExecutionToolCalls(executionId as string, { limit: 100 }),
    enabled: Boolean(executionId),
    refetchInterval: active ? DETAIL_POLL_MS : false,
  });
}

export function useExecutionArtifacts(executionId: string | undefined, active: boolean) {
  return useQuery({
    queryKey: ["execution-artifacts", executionId],
    queryFn: () => api.listExecutionArtifacts(executionId as string),
    enabled: Boolean(executionId),
    refetchInterval: active ? DETAIL_POLL_MS : false,
  });
}

/** Live runtime status (see backend runtime_service) — distinct from the
 * historical `test_results.runtime_*` snapshot: a runtime deliberately
 * outlives its own execution, so this keeps polling (slowly) even once the
 * execution itself is terminal, until the runtime is reported stopped. */
export function useExecutionRuntime(executionId: string | undefined, hasRuntime: boolean) {
  return useQuery({
    queryKey: ["execution-runtime", executionId],
    queryFn: () => api.getExecutionRuntime(executionId as string),
    enabled: Boolean(executionId) && hasRuntime,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "running" || status === "starting" ? DETAIL_POLL_MS : 15_000;
    },
  });
}

const OVERVIEW_STATUSES = ["running", "pending", "passed", "failed"] as const;

/** Global status counts derived from real `total` fields returned by the
 * existing list endpoint (one lightweight `limit=1` request per status) —
 * no dedicated aggregate endpoint exists, and none is added for this. */
export function useExecutionStatusCounts() {
  return useQuery({
    queryKey: ["execution-status-counts"],
    queryFn: async () => {
      const results = await Promise.all(
        OVERVIEW_STATUSES.map((status) => api.listExecutions({ status, limit: 1 }))
      );
      const counts: Record<string, number> = {};
      OVERVIEW_STATUSES.forEach((status, i) => {
        counts[status] = results[i]?.total ?? 0;
      });
      return counts;
    },
    refetchInterval: LIST_POLL_MS,
  });
}
