import { EmptyState } from "@/components/EmptyState";

export function DebugRetryPanel({ retryCount, stepErrors }: { retryCount: number; stepErrors: string[] }) {
  if (retryCount === 0 && stepErrors.length === 0) {
    return <EmptyState title="No retries" description="This execution has not needed a debug/retry loop." />;
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="text-xs uppercase tracking-widest2 text-ivory-faint">Debug retries</p>
        <p className="mt-1 font-display text-3xl text-ivory">{retryCount}</p>
      </div>

      {stepErrors.length > 0 ? (
        <ul className="flex flex-col gap-1.5">
          {stepErrors.map((error, i) => (
            <li
              key={i}
              className="whitespace-pre-wrap rounded bg-status-error/[0.06] px-2.5 py-1.5 font-mono text-sm leading-relaxed text-status-error"
            >
              {error}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
