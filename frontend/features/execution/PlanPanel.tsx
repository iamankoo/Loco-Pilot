import type { PlanSummary } from "@/lib/types";
import { EmptyState } from "@/components/EmptyState";

export function PlanPanel({ plan }: { plan: PlanSummary | null }) {
  if (!plan) {
    return <EmptyState title="No plan yet" description="The Planner agent's plan will appear here once produced." />;
  }

  return (
    <div className="flex flex-col gap-4">
      {plan.objective ? <p className="text-base leading-relaxed text-ivory">{plan.objective}</p> : null}

      {plan.steps.length > 0 ? (
        <ol className="flex flex-col gap-2">
          {plan.steps.map((step, i) => (
            <li key={i} className="flex gap-2.5 text-base leading-relaxed text-ivory-dim">
              <span className="text-gold/70">{i + 1}.</span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      ) : null}

      {plan.files_likely_involved.length > 0 ? (
        <div>
          <p className="mb-1.5 text-xs uppercase tracking-widest2 text-ivory-faint">Files likely involved</p>
          <div className="flex flex-wrap gap-1.5">
            {plan.files_likely_involved.map((path) => (
              <code key={path} className="rounded bg-white/[0.04] px-2 py-1 font-mono text-sm text-ivory-dim">
                {path}
              </code>
            ))}
          </div>
        </div>
      ) : null}

      {plan.testing_strategy ? (
        <div>
          <p className="mb-1 text-xs uppercase tracking-widest2 text-ivory-faint">Testing strategy</p>
          <p className="text-base leading-relaxed text-ivory-dim">{plan.testing_strategy}</p>
        </div>
      ) : null}

      {plan.risks.length > 0 ? (
        <div>
          <p className="mb-1.5 text-xs uppercase tracking-widest2 text-ivory-faint">Risks</p>
          <ul className="flex flex-col gap-1">
            {plan.risks.map((risk, i) => (
              <li key={i} className="text-base leading-relaxed text-ivory-dim">
                {risk}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
