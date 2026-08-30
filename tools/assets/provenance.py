"""asset-manifest.json — a real, persistent record of where every non-
Developer-authored visual asset in a generated project actually came from.

Written into the workspace root (an ordinary project file, not hidden
execution-only metadata) so it travels with the project and is inspectable
like any other generated artifact, while also being real evidence
Reviewer/Tester can read back deterministically — see
`agents.reviewer`/`analysis.document_artifact` for the "read real files,
don't trust a claim" pattern this follows.

Only assets acquired through `tools.assets.tools`/`tools.image` get an
entry — a plain `write_file` for HTML/CSS/JS is not an "asset" in this
sense and is not recorded here, keeping the manifest meaningfully scoped
to provenance-worthy content (downloaded, generated, or otherwise sourced
media) rather than every file in the project.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from tools.workspace import Workspace

MANIFEST_FILENAME = "asset-manifest.json"


class AssetManifestEntry(BaseModel):
    local_path: str
    asset_type: str  # "image" | "icon" | "font" | ...
    # "web_download" | "image_generation" | "local_creation" (e.g. an
    # inline SVG the Developer wrote directly via write_file — recorded
    # only when the caller explicitly wants provenance for a hand-authored
    # asset too; not automatic for every write_file call).
    acquisition_method: str
    source_provider: str  # "wikimedia_commons" | an IMAGE_PROVIDER name | "local" | ...
    source_url: str | None = None
    license: str | None = None
    attribution: str | None = None
    acquired_at: str


def _manifest_path(workspace: Workspace) -> Path:
    return workspace.root / MANIFEST_FILENAME


def read_manifest(workspace: Workspace) -> list[AssetManifestEntry]:
    path = _manifest_path(workspace)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = []
    for item in raw if isinstance(raw, list) else []:
        try:
            entries.append(AssetManifestEntry.model_validate(item))
        except Exception:  # noqa: BLE001 - a malformed manifest entry is skipped, not fatal
            continue
    return entries


def record_asset(workspace: Workspace, entry: AssetManifestEntry) -> None:
    """Appends `entry` to asset-manifest.json, replacing any existing entry
    for the same `local_path` (a re-download/regeneration updates
    provenance in place rather than accumulating stale duplicates)."""
    entries = [e for e in read_manifest(workspace) if e.local_path != entry.local_path]
    entries.append(entry)
    payload = [e.model_dump(mode="json") for e in entries]
    _manifest_path(workspace).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def new_entry(
    *,
    local_path: str,
    asset_type: str,
    acquisition_method: str,
    source_provider: str,
    source_url: str | None = None,
    license: str | None = None,  # noqa: A002 - matches the manifest's own field name
    attribution: str | None = None,
) -> AssetManifestEntry:
    return AssetManifestEntry(
        local_path=local_path,
        asset_type=asset_type,
        acquisition_method=acquisition_method,
        source_provider=source_provider,
        source_url=source_url,
        license=license,
        attribution=attribution,
        acquired_at=datetime.now(timezone.utc).isoformat(),
    )
