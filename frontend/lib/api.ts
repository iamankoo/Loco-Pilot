import type {
  ArtifactSummary,
  AgentStepSummary,
  CreateExecutionRequest,
  ExecutionDetail,
  ExecutionListResponse,
  ExecutionRecord,
  ProjectDetail,
  ProjectListResponse,
  ToolCallListResponse,
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // response body wasn't JSON — fall back to statusText
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function toQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export interface HealthCheck {
  status: string;
  detail?: string;
}

export interface ReadinessResponse {
  status: string;
  checks: { database: HealthCheck; redis: HealthCheck };
}

export const api = {
  getHealth: () => request<{ status: string; service: string; version: string }>(`/health`),

  getReadiness: async (): Promise<ReadinessResponse> => {
    const response = await fetch(`${API_BASE_URL}/health/ready`, { cache: "no-store" });
    return (await response.json()) as ReadinessResponse;
  },

  listProjects: (params: { limit?: number; offset?: number } = {}) =>
    request<ProjectListResponse>(`/api/v1/projects${toQuery(params)}`),

  getProject: (projectId: string) => request<ProjectDetail>(`/api/v1/projects/${projectId}`),

  listExecutions: (params: { projectId?: string; status?: string; limit?: number; offset?: number } = {}) =>
    request<ExecutionListResponse>(
      `/api/v1/executions${toQuery({
        project_id: params.projectId,
        status: params.status,
        limit: params.limit,
        offset: params.offset,
      })}`
    ),

  getExecution: (executionId: string) => request<ExecutionDetail>(`/api/v1/executions/${executionId}`),

  listExecutionSteps: (executionId: string) =>
    request<AgentStepSummary[]>(`/api/v1/executions/${executionId}/steps`),

  listExecutionToolCalls: (executionId: string, params: { limit?: number; offset?: number } = {}) =>
    request<ToolCallListResponse>(`/api/v1/executions/${executionId}/tool-calls${toQuery(params)}`),

  listExecutionArtifacts: (executionId: string) =>
    request<ArtifactSummary[]>(`/api/v1/executions/${executionId}/artifacts`),

  createExecution: (payload: CreateExecutionRequest) =>
    request<ExecutionRecord>(`/api/v1/executions`, { method: "POST", body: JSON.stringify(payload) }),

  cancelExecution: (executionId: string) =>
    request<ExecutionRecord>(`/api/v1/executions/${executionId}/cancel`, { method: "POST" }),
};
