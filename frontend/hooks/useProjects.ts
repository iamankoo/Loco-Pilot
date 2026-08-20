"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

const LIST_POLL_MS = 15_000;

export function useProjectsList(params: { limit?: number; offset?: number } = {}) {
  return useQuery({
    queryKey: ["projects", params],
    queryFn: () => api.listProjects(params),
    refetchInterval: LIST_POLL_MS,
  });
}

export function useProjectDetail(projectId: string | undefined) {
  return useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId as string),
    enabled: Boolean(projectId),
    refetchInterval: LIST_POLL_MS,
  });
}
