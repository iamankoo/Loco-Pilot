import type { ReviewResultSummary } from "@/lib/types";
import { EmptyState } from "@/components/EmptyState";
import { cn } from "@/lib/cn";

export function ReviewPanel({ review }: { review: ReviewResultSummary | null }) {
  if (!review) {
    return <EmptyState title="Not reviewed yet" description="A review verdict appears once the Reviewer agent completes." />;
  }

  const approved = review.verdict === "approved";

  return (
    <div className="flex flex-col gap-4">
      <span
        className={cn(
          "inline-flex w-fit items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs uppercase tracking-widest2",
          approved
            ? "border-status-success/30 bg-status-success/10 text-status-success"
            : "border-status-error/30 bg-status-error/10 text-status-error"
        )}
      >
        {review.verdict.replace(/_/g, " ")}
      </span>

      {review.summary ? <p className="text-base leading-relaxed text-ivory-dim">{review.summary}</p> : null}

      {review.issues.length > 0 ? (
        <div>
          <p className="mb-1.5 text-xs uppercase tracking-widest2 text-ivory-faint">Issues</p>
          <ul className="flex flex-col gap-1">
            {review.issues.map((issue, i) => (
              <li key={i} className="text-base leading-relaxed text-ivory-dim">
                {issue}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {review.regressions_observed.length > 0 ? (
        <div>
          <p className="mb-1.5 text-xs uppercase tracking-widest2 text-status-error/80">Regressions observed</p>
          <ul className="flex flex-col gap-1">
            {review.regressions_observed.map((regression, i) => (
              <li key={i} className="text-base leading-relaxed text-status-error">
                {regression}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
