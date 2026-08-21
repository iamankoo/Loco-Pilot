"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useSystemStatus() {
  return useQuery({
    queryKey: ["system-status"],
    queryFn: async () => {
      const [health, readiness, llm] = await Promise.allSettled([
        api.getHealth(),
        api.getReadiness(),
        api.getLlmHealth(),
      ]);
      return {
        health: health.status === "fulfilled" ? health.value : null,
        readiness: readiness.status === "fulfilled" ? readiness.value : null,
        llm: llm.status === "fulfilled" ? llm.value : null,
        reachable: health.status === "fulfilled",
      };
    },
    refetchInterval: 10_000,
    retry: 0,
  });
}
