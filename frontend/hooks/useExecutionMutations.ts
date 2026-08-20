"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { CreateExecutionRequest } from "@/lib/types";

export function useCancelExecution(executionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelExecution(executionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["execution", executionId] });
      queryClient.invalidateQueries({ queryKey: ["execution-steps", executionId] });
    },
  });
}

export function useCreateExecution() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateExecutionRequest) => api.createExecution(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["executions"] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}
