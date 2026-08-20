import { AGENT_PIPELINE } from "@/lib/types";
import type { AgentStepSummary, ExecutionDetail } from "@/lib/types";
import { cn } from "@/lib/cn";

type StageStatus = "not_started" | "running" | "succeeded" | "failed";

function orchestratorStatus(execution: ExecutionDetail): StageStatus {
  switch (execution.status) {
    case "pending":
    case "running":
      return "running";
    case "passed":
    case "needs_review":
      return "succeeded";
    case "cancelled":
      return "failed";
    default:
      return "failed";
  }
}

function agentStageStatus(agentName: string, steps: AgentStepSummary[]): { status: StageStatus; occurrences: number } {
  const occurrences = steps.filter((s) => s.agent_name === agentName);
  const last = occurrences.at(-1);
  if (!last) return { status: "not_started", occurrences: 0 };
  if (last.status === "succeeded") return { status: "succeeded", occurrences: occurrences.length };
  if (last.status === "failed") return { status: "failed", occurrences: occurrences.length };
  return { status: "running", occurrences: occurrences.length };
}

const STAGE_LABELS: Record<string, string> = {
  orchestrator: "Orchestrator",
  planner: "Planner",
  developer: "Developer",
  tester: "Tester",
  debugger: "Debugger",
  reviewer: "Reviewer",
};

export function AgentPipeline({ execution, steps }: { execution: ExecutionDetail; steps: AgentStepSummary[] }) {
  return (
    <div className="flex items-start overflow-x-auto pb-2">
      {AGENT_PIPELINE.map((agent, i) => {
        const { status, occurrences } =
          agent === "orchestrator" ? { status: orchestratorStatus(execution), occurrences: 1 } : agentStageStatus(agent, steps);
        const isLast = i === AGENT_PIPELINE.length - 1;

        return (
          <div key={agent} className="flex flex-shrink-0 items-start">
            <div className="flex w-28 flex-col items-center gap-3 text-center sm:w-32">
              <StageDot status={status} />
              <div>
                <p className={cn("text-sm", status === "not_started" ? "text-ivory-faint" : "text-ivory")}>
                  {STAGE_LABELS[agent]}
                </p>
                {occurrences > 1 ? (
                  <p className="mt-0.5 text-xs uppercase tracking-wide text-gold/70">×{occurrences}</p>
                ) : null}
              </div>
            </div>
            {!isLast ? (
              <div
                className={cn(
                  "mt-[15px] h-px w-6 flex-shrink-0 sm:w-10",
                  status === "succeeded" || status === "failed" ? "bg-line-strong" : "bg-line"
                )}
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function StageDot({ status }: { status: StageStatus }) {
  if (status === "running") {
    return (
      <span className="relative flex h-7 w-7 items-center justify-center">
        <span className="absolute h-7 w-7 animate-pulse-soft rounded-full bg-gold/20" />
        <span className="h-3 w-3 rounded-full bg-gold" />
      </span>
    );
  }
  if (status === "succeeded") {
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-full border border-status-success/40 bg-status-success/10 text-status-success">
        <CheckIcon />
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-full border border-status-error/40 bg-status-error/10 text-status-error">
        <CrossIcon />
      </span>
    );
  }
  return <span className="h-7 w-7 rounded-full border border-line-strong" />;
}

function CheckIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 12 12" fill="none">
      <path d="M2.5 6.2L4.8 8.5L9.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CrossIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <path d="M3 3L9 9M9 3L3 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
