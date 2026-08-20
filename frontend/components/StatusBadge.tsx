import { cn } from "@/lib/cn";
import { statusLabel, statusTone } from "@/lib/format";

const TONE_STYLES: Record<string, string> = {
  success: "text-status-success border-status-success/30 bg-status-success/10",
  error: "text-status-error border-status-error/30 bg-status-error/10",
  running: "text-gold border-gold/30 bg-gold/10",
  pending: "text-ivory-dim border-line-strong bg-white/[0.02]",
  cancelled: "text-ivory-faint border-line-strong bg-white/[0.02]",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const tone = statusTone(status);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium uppercase tracking-widest2",
        TONE_STYLES[tone],
        className
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          tone === "success" && "bg-status-success",
          tone === "error" && "bg-status-error",
          tone === "running" && "bg-gold animate-pulse-soft",
          (tone === "pending" || tone === "cancelled") && "bg-ivory-faint"
        )}
      />
      {statusLabel(status)}
    </span>
  );
}
