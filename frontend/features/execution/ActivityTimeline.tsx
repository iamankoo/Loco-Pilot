import type { AgentStepSummary } from "@/lib/types";
import { formatDurationMs, formatTimestamp } from "@/lib/format";
import { EmptyState } from "@/components/EmptyState";
import { cn } from "@/lib/cn";

const AGENT_LABELS: Record<string, string> = {
  planner: "Planner",
  developer: "Developer",
  tester: "Tester",
  debugger: "Debugger",
  reviewer: "Reviewer",
};

export function ActivityTimeline({ steps }: { steps: AgentStepSummary[] }) {
  if (steps.length === 0) {
    return <EmptyState title="No activity yet" description="Steps will appear here as agents begin working." />;
  }

  return (
    <ol className="flex flex-col">
      {steps.map((step, i) => (
        <li key={step.id} className="relative flex gap-4 pb-6 last:pb-0">
          {i < steps.length - 1 ? (
            <span className="absolute left-[7px] top-4 h-full w-px bg-line" aria-hidden />
          ) : null}
          <span
            className={cn(
              "relative z-10 mt-1.5 h-3.5 w-3.5 flex-shrink-0 rounded-full border-2",
              step.status === "succeeded" && "border-status-success bg-status-success/20",
              step.status === "failed" && "border-status-error bg-status-error/20",
              step.status === "running" && "animate-pulse-soft border-gold bg-gold/20",
              step.status === "pending" && "border-line-strong bg-ground"
            )}
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <p className="text-base text-ivory">{AGENT_LABELS[step.agent_name] ?? step.agent_name}</p>
              <p className="text-sm text-ivory-faint">
                {formatTimestamp(step.started_at)}
                {step.duration_ms !== null ? ` · ${formatDurationMs(step.duration_ms)}` : ""}
              </p>
            </div>
            {step.messages.length > 0 ? (
              <ul className="mt-2 flex flex-col gap-1.5">
                {step.messages.map((message, mi) => (
                  <li key={mi} className="text-base leading-relaxed text-ivory-dim">
                    {message}
                  </li>
                ))}
              </ul>
            ) : null}
            {step.error_message ? (
              <p className="mt-2 text-base leading-relaxed text-status-error">{step.error_message}</p>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
