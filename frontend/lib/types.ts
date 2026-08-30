/**
 * Mirrors `backend/app/api/v1/dashboard_schemas.py`. Kept as plain
 * structural types (not generated) since the backend is the single
 * source of truth for shape; update both sides together when the API
 * contract changes.
 */

export type ExecutionStatus =
  | "pending"
  | "running"
  | "passed"
  | "failed"
  | "needs_review"
  | "error"
  | "cancelled"
  | "timed_out";

export const AGENT_PIPELINE = ["orchestrator", "planner", "developer", "tester", "debugger", "reviewer"] as const;
export type AgentName = (typeof AGENT_PIPELINE)[number];

export interface PlanSummary {
  objective: string | null;
  assumptions: string[];
  files_likely_involved: string[];
  steps: string[];
  testing_strategy: string | null;
  risks: string[];
  expected_artifact_glob: string | null;
}

export interface FileChangeSummary {
  path: string;
  change_type: string;
  detail: string | null;
}

export interface TestResultSummary {
  status: string;
  commands: string[];
  passed: number;
  failed: number;
  errors: string[];
  summary: string | null;
  verification_kind: "automated_tests" | "static_site" | "none";
  runtime_url: string | null;
  runtime_status: "starting" | "running" | "verification_failed" | "start_failed" | "stopped" | null;
}

export interface RuntimeStatus {
  status: "starting" | "running" | "verification_failed" | "start_failed" | "stopped" | "no_runtime";
  url: string | null;
  detail: string | null;
}

export interface ReviewResultSummary {
  verdict: string;
  summary: string | null;
  issues: string[];
  regressions_observed: string[];
}

export interface ExecutionSummary {
  id: string;
  project_id: string;
  project_name: string | null;
  task: string;
  status: ExecutionStatus;
  current_agent: string | null;
  retry_count: number;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  elapsed_seconds: number | null;
}

export interface ExecutionListResponse {
  items: ExecutionSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ExecutionDetail extends ExecutionSummary {
  plan: PlanSummary | null;
  files_changed: FileChangeSummary[];
  test_results: TestResultSummary | null;
  review_result: ReviewResultSummary | null;
  tool_call_count: number;
  artifact_count: number;
  step_errors: string[];
}

export interface AgentStepSummary {
  id: string;
  agent_name: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  messages: string[];
}

export interface ToolCallSummary {
  id: string;
  agent_step_id: string | null;
  tool_name: string;
  status: string;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error_message: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface ToolCallListResponse {
  items: ToolCallSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ArtifactSummary {
  id: string;
  artifact_type: string;
  path: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
  repo_url: string | null;
  workspace_path: string | null;
  created_at: string;
  updated_at: string;
  last_execution_status: string | null;
  last_execution_at: string | null;
  execution_counts: Record<string, number>;
}

export interface ProjectListResponse {
  items: ProjectSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ProjectDetail extends ProjectSummary {
  recent_executions: ExecutionSummary[];
}

export interface CreateExecutionRequest {
  task: string;
  project_id?: string | null;
  workspace_path?: string | null;
  project_name?: string | null;
}

export interface ExecutionRecord {
  id: string;
  project_id: string;
  task: string;
  status: ExecutionStatus;
  current_agent: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export const TERMINAL_STATUSES: ExecutionStatus[] = ["passed", "failed", "error", "cancelled", "timed_out"];

export function isTerminalStatus(status: string): boolean {
  return TERMINAL_STATUSES.includes(status as ExecutionStatus);
}

export interface CreateProjectRequest {
  name?: string | null;
  workspace_path?: string | null;
}

export interface WorkspaceEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size_bytes: number | null;
}

export interface WorkspaceListResponse {
  path: string;
  entries: WorkspaceEntry[];
}

export interface UploadedFile {
  filename: string;
  relative_path: string;
  size_bytes: number;
  content_type: string | null;
}

export interface UploadResponse {
  files: UploadedFile[];
}

export type LlmStatus = "ok" | "not_configured" | "auth_failed" | "model_access_denied" | "error";

export interface LlmHealth {
  status: LlmStatus;
  provider: string;
  model: string;
  detail: string | null;
}
