"use client";

import { useSystemStatus } from "@/hooks/useSystemStatus";
import { Breadcrumb } from "@/components/Breadcrumb";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";
import { cn } from "@/lib/cn";

export default function SettingsPage() {
  const status = useSystemStatus();
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  return (
    <div className="mx-auto max-w-6xl px-6 py-14 sm:px-8">
      <Breadcrumb items={[{ label: "Home", href: "/" }, { label: "Settings" }]} />
      <PageHeader eyebrow="System" title="Settings" description="Live status of the LocoPilot backend and its dependencies." />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel title="Backend">
          {status.isLoading ? (
            <Skeleton className="h-16 w-full" />
          ) : (
            <div className="flex flex-col gap-3">
              <StatusRow label="API" ok={status.data?.reachable ?? false} baseUrl={apiBaseUrl} />
              <StatusRow
                label="Database"
                ok={status.data?.readiness?.checks.database.status === "ok"}
                detail={status.data?.readiness?.checks.database.detail}
              />
              <StatusRow
                label="Redis"
                ok={status.data?.readiness?.checks.redis.status === "ok"}
                detail={status.data?.readiness?.checks.redis.detail}
              />
              {status.data?.health ? (
                <p className="mt-1 text-sm text-ivory-faint">
                  {status.data.health.service} · v{status.data.health.version}
                </p>
              ) : null}
            </div>
          )}
        </Panel>

        <Panel title="LLM">
          {status.isLoading ? (
            <Skeleton className="h-16 w-full" />
          ) : (
            <LlmStatusRow llm={status.data?.llm ?? null} />
          )}
        </Panel>

        <Panel title="Access" className="lg:col-span-2">
          <p className="text-base leading-relaxed text-ivory-dim">
            This dashboard talks directly to the LocoPilot API — there is no login or account system in this
            phase. Access control is expected to be handled at the network layer (VPN, reverse proxy, or a
            future authenticated deployment) rather than inside the application.
          </p>
        </Panel>
      </div>
    </div>
  );
}

const LLM_STATUS_LABEL: Record<string, string> = {
  ok: "Connected",
  not_configured: "Not configured",
  auth_failed: "Authentication failed",
  model_access_denied: "Model access denied",
  error: "Error",
};

function LlmStatusRow({ llm }: { llm: { status: string; provider: string; model: string; detail: string | null } | null }) {
  if (!llm) {
    return <StatusRow label="Qwen Coder" ok={false} detail="Could not reach the backend to check LLM status." />;
  }

  const tone = llm.status === "ok" ? "success" : llm.status === "model_access_denied" ? "warning" : "error";

  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <p className="text-base text-ivory">Qwen Coder</p>
        <p className="mt-0.5 font-mono text-sm text-ivory-faint">
          {llm.provider} · {llm.model}
        </p>
        {llm.detail ? <p className="mt-1.5 max-w-sm text-sm text-status-error">{llm.detail}</p> : null}
      </div>
      <span
        className={cn(
          "flex flex-shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs uppercase tracking-widest2",
          tone === "success" && "border-status-success/30 bg-status-success/10 text-status-success",
          tone === "warning" && "border-gold/30 bg-gold/10 text-gold",
          tone === "error" && "border-status-error/30 bg-status-error/10 text-status-error"
        )}
      >
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            tone === "success" && "bg-status-success",
            tone === "warning" && "bg-gold",
            tone === "error" && "bg-status-error"
          )}
        />
        {LLM_STATUS_LABEL[llm.status] ?? llm.status}
      </span>
    </div>
  );
}

function StatusRow({ label, ok, detail, baseUrl }: { label: string; ok: boolean; detail?: string; baseUrl?: string }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line pb-3 last:border-0 last:pb-0">
      <div>
        <p className="text-base text-ivory">{label}</p>
        {baseUrl ? <p className="mt-0.5 font-mono text-sm text-ivory-faint">{baseUrl}</p> : null}
        {detail ? <p className="mt-0.5 max-w-sm text-sm text-status-error">{detail}</p> : null}
      </div>
      <span
        className={cn(
          "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs uppercase tracking-widest2",
          ok
            ? "border-status-success/30 bg-status-success/10 text-status-success"
            : "border-status-error/30 bg-status-error/10 text-status-error"
        )}
      >
        <span className={cn("h-1.5 w-1.5 rounded-full", ok ? "bg-status-success" : "bg-status-error")} />
        {ok ? "Online" : "Unreachable"}
      </span>
    </div>
  );
}
