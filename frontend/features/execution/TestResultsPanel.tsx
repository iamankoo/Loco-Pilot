import type { TestResultSummary } from "@/lib/types";
import { EmptyState } from "@/components/EmptyState";
import { cn } from "@/lib/cn";

export function TestResultsPanel({ results }: { results: TestResultSummary | null }) {
  if (!results) {
    return <EmptyState title="No test results yet" description="Results will appear here once the Tester agent runs." />;
  }

  const passed = results.status === "passed";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-6">
        <div>
          <p className="text-xs uppercase tracking-widest2 text-ivory-faint">Passed</p>
          <p className={cn("mt-1 font-display text-3xl", passed ? "text-status-success" : "text-ivory")}>
            {results.passed}
          </p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-widest2 text-ivory-faint">Failed</p>
          <p className={cn("mt-1 font-display text-3xl", results.failed > 0 ? "text-status-error" : "text-ivory")}>
            {results.failed}
          </p>
        </div>
      </div>

      {results.summary ? <p className="text-base leading-relaxed text-ivory-dim">{results.summary}</p> : null}

      {results.commands.length > 0 ? (
        <div>
          <p className="mb-1.5 text-xs uppercase tracking-widest2 text-ivory-faint">Commands</p>
          <div className="flex flex-col gap-1">
            {results.commands.map((command, i) => (
              <code key={i} className="rounded bg-black/30 px-2.5 py-1.5 font-mono text-sm text-ivory-dim">
                {command}
              </code>
            ))}
          </div>
        </div>
      ) : null}

      {results.errors.length > 0 ? (
        <div>
          <p className="mb-1.5 text-xs uppercase tracking-widest2 text-status-error/80">Errors</p>
          <ul className="flex flex-col gap-1.5">
            {results.errors.map((error, i) => (
              <li key={i} className="whitespace-pre-wrap rounded bg-status-error/[0.06] px-2.5 py-1.5 font-mono text-sm leading-relaxed text-status-error">
                {error}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
