export function Pagination({
  total,
  limit,
  offset,
  onOffsetChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onOffsetChange: (offset: number) => void;
}) {
  if (total <= limit) return null;

  const page = Math.floor(offset / limit) + 1;
  const pageCount = Math.ceil(total / limit);

  return (
    <div className="flex items-center justify-between px-5 py-3.5">
      <p className="text-sm text-ivory-faint">
        Page {page} of {pageCount} · {total} total
      </p>
      <div className="flex gap-2">
        <button
          disabled={offset === 0}
          onClick={() => onOffsetChange(Math.max(0, offset - limit))}
          className="rounded-full border border-line-strong px-3.5 py-1 text-sm text-ivory-dim transition-colors hover:border-gold/40 hover:text-ivory disabled:cursor-not-allowed disabled:opacity-30"
        >
          Previous
        </button>
        <button
          disabled={offset + limit >= total}
          onClick={() => onOffsetChange(offset + limit)}
          className="rounded-full border border-line-strong px-3.5 py-1 text-sm text-ivory-dim transition-colors hover:border-gold/40 hover:text-ivory disabled:cursor-not-allowed disabled:opacity-30"
        >
          Next
        </button>
      </div>
    </div>
  );
}
