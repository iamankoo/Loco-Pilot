import type { ArtifactSummary } from "@/lib/types";
import { EmptyState } from "@/components/EmptyState";
import { formatTimestamp } from "@/lib/format";

export function ArtifactsList({ artifacts }: { artifacts: ArtifactSummary[] }) {
  if (artifacts.length === 0) {
    return <EmptyState title="No artifacts" description="Build outputs and generated files will appear here." />;
  }

  return (
    <ul className="flex flex-col divide-y divide-line">
      {artifacts.map((artifact) => (
        <li key={artifact.id} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
          <div className="min-w-0">
            <p className="truncate font-mono text-sm text-ivory">{artifact.path}</p>
            <p className="mt-1 text-sm text-ivory-faint">
              {artifact.artifact_type} · {formatTimestamp(artifact.created_at)}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}
