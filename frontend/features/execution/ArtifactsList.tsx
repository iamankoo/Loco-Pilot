import type { ArtifactSummary } from "@/lib/types";
import { EmptyState } from "@/components/EmptyState";
import { formatTimestamp } from "@/lib/format";
import { ApiError, api } from "@/lib/api";
import { useState } from "react";

async function openArtifact(executionId: string, artifactId: string, onError: (message: string) => void) {
  // Open the tab synchronously (inside the click) so popup blockers allow
  // it, then point it at the authenticated blob once it arrives.
  const tab = window.open("", "_blank");
  try {
    const blob = await api.fetchArtifactBlob(executionId, artifactId);
    const url = URL.createObjectURL(blob);
    if (tab) tab.location.href = url;
    else window.location.href = url;
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (error) {
    tab?.close();
    onError(error instanceof ApiError ? error.message : "Could not open the artifact.");
  }
}

export function ArtifactsList({
  executionId,
  artifacts,
}: {
  executionId: string;
  artifacts: ArtifactSummary[];
}) {
  const [error, setError] = useState<string | null>(null);

  if (artifacts.length === 0) {
    return <EmptyState title="No artifacts" description="Build outputs and generated files will appear here." />;
  }

  return (
    <>
    {error ? <p className="mb-3 text-sm text-status-error">{error}</p> : null}
    <ul className="flex flex-col divide-y divide-line">
      {artifacts.map((artifact) => (
        <li key={artifact.id} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
          <div className="min-w-0">
            <p className="truncate font-mono text-sm text-ivory">{artifact.path}</p>
            <p className="mt-1 text-sm text-ivory-faint">
              {artifact.artifact_type} · {formatTimestamp(artifact.created_at)}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void openArtifact(executionId, artifact.id, setError)}
            className="shrink-0 text-sm text-gold hover:underline"
          >
            View
          </button>
        </li>
      ))}
    </ul>
    </>
  );
}
