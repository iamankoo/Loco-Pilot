import { ApiError } from "@/lib/api";

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError ? error.message : "Something went wrong reaching the backend.";
  const status = error instanceof ApiError ? error.status : null;

  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-status-error/25 bg-status-error/[0.04] py-16 text-center">
      <p className="font-display text-xl text-ivory">
        {status ? `Request failed (${status})` : "Request failed"}
      </p>
      <p className="max-w-md text-base leading-relaxed text-ivory-faint">{message}</p>
      {onRetry ? (
        <button
          onClick={onRetry}
          className="mt-1 rounded-full border border-line-strong px-4 py-1.5 text-sm text-ivory-dim transition-colors hover:border-gold/40 hover:text-ivory"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}
