"use client";

import { useParams } from "next/navigation";
import {
  useExecutionArtifacts,
  useExecutionDetail,
  useExecutionSteps,
  useExecutionToolCalls,
} from "@/hooks/useExecutions";
import { Panel } from "@/components/Panel";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton, SkeletonLines } from "@/components/Skeleton";
import { isActiveExecution } from "@/lib/format";
import { ExecutionHeader } from "@/features/execution/ExecutionHeader";
import { AgentPipeline } from "@/features/execution/AgentPipeline";
import { ActivityTimeline } from "@/features/execution/ActivityTimeline";
import { ToolCallInspector } from "@/features/execution/ToolCallInspector";
import { FilesChanged } from "@/features/execution/FilesChanged";
import { TestResultsPanel } from "@/features/execution/TestResultsPanel";
import { PlanPanel } from "@/features/execution/PlanPanel";
import { ReviewPanel } from "@/features/execution/ReviewPanel";
import { DebugRetryPanel } from "@/features/execution/DebugRetryPanel";
import { ArtifactsList } from "@/features/execution/ArtifactsList";

export default function ExecutionDetailPage() {
  const params = useParams<{ id: string }>();
  const executionId = params.id;

  const execution = useExecutionDetail(executionId);
  const active = execution.data ? isActiveExecution(execution.data.status) : false;

  const steps = useExecutionSteps(executionId, active);
  const toolCalls = useExecutionToolCalls(executionId, active);
  const artifacts = useExecutionArtifacts(executionId, active);

  if (execution.isLoading) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-14 sm:px-8">
        <Skeleton className="mb-3 h-4 w-40" />
        <Skeleton className="mb-6 h-10 w-full max-w-2xl" />
        <Skeleton className="mb-10 h-16 w-full" />
        <SkeletonLines count={6} />
      </div>
    );
  }

  if (execution.isError) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-14 sm:px-8">
        <ErrorState error={execution.error} onRetry={() => execution.refetch()} />
      </div>
    );
  }

  const data = execution.data;
  if (!data) return null;

  return (
    <div className="mx-auto max-w-6xl px-6 py-14 sm:px-8">
      <ExecutionHeader execution={data} />

      <Panel title="Pipeline" className="mb-6">
        <AgentPipeline execution={data} steps={steps.data ?? []} />
      </Panel>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <div className="flex flex-col gap-6 lg:col-span-3">
          <Panel title="Activity">
            {steps.isLoading ? <SkeletonLines count={4} /> : <ActivityTimeline steps={steps.data ?? []} />}
          </Panel>

          <Panel title={`Files Changed${data.files_changed.length > 0 ? ` (${data.files_changed.length})` : ""}`}>
            <FilesChanged files={data.files_changed} toolCalls={toolCalls.data?.items ?? []} />
          </Panel>

          <Panel title={`Tool Calls${data.tool_call_count > 0 ? ` (${data.tool_call_count})` : ""}`}>
            {toolCalls.isLoading ? <SkeletonLines count={4} /> : <ToolCallInspector toolCalls={toolCalls.data?.items ?? []} />}
          </Panel>
        </div>

        <div className="flex flex-col gap-6 lg:col-span-2">
          <Panel title="Plan">
            <PlanPanel plan={data.plan} />
          </Panel>

          <Panel title="Test Results">
            <TestResultsPanel results={data.test_results} />
          </Panel>

          <Panel title="Review">
            <ReviewPanel review={data.review_result} />
          </Panel>

          <Panel title="Debug & Retries">
            <DebugRetryPanel retryCount={data.retry_count} stepErrors={data.step_errors} />
          </Panel>

          <Panel title={`Artifacts${data.artifact_count > 0 ? ` (${data.artifact_count})` : ""}`}>
            {artifacts.isLoading ? <SkeletonLines count={2} /> : <ArtifactsList artifacts={artifacts.data ?? []} />}
          </Panel>
        </div>
      </div>
    </div>
  );
}
