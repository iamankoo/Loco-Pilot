"""Detects and records build artifacts produced by an execution.

The workspace is the durable location for Phase 1 (Developer's edits and
any Docker-run build/test command share the same live bind-mounted
directory — see Phase 1.4's sandbox architecture), so a matched artifact
is recorded by its workspace-relative path rather than copied elsewhere.
`execution.docker.sandbox.Sandbox.copy_out` remains available (and
tested) for a future scenario where a build produces output outside the
mounted workspace; nothing in this workflow needs it today, so it isn't
forced in just to exercise it.

Path safety: `glob_pattern` originates from `Plan.expected_artifact_glob`
— LLM-produced, so treated as untrusted input, not a trusted config
value. `Path.glob()` supports `..` segments and WILL walk outside its
base directory if the pattern contains them, so the pattern is rejected
outright if it looks like an escape attempt before globbing ever runs,
and every match is independently re-validated to be inside
`workspace.root` before being recorded — two checks, neither trusting the
other alone.
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath, PureWindowsPath

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.db.models.artifact import Artifact
from backend.app.db.repositories.artifacts import create_artifact
from tools.workspace import Workspace

logger = get_logger(component="artifact_service")

_MAX_ARTIFACTS_PER_EXECUTION = 10

_EXTENSION_TYPES = {
    ".whl": "python-wheel",
    ".tar.gz": "archive",
    ".zip": "archive",
    ".jar": "jar",
    ".apk": "android-package",
}


class ArtifactGlobRejectedError(Exception):
    pass


def _artifact_type_for(path: str) -> str:
    lowered = path.lower()
    for suffix, artifact_type in _EXTENSION_TYPES.items():
        if lowered.endswith(suffix):
            return artifact_type
    return "file"


def _validate_glob_pattern(pattern: str) -> None:
    if not pattern or ".." in pattern:
        raise ArtifactGlobRejectedError(f"Artifact glob pattern rejected: {pattern!r}")
    if PurePosixPath(pattern).is_absolute() or PureWindowsPath(pattern).is_absolute():
        raise ArtifactGlobRejectedError(f"Artifact glob pattern must be relative: {pattern!r}")


async def collect_artifacts(
    workspace: Workspace,
    glob_pattern: str,
    execution_id: uuid.UUID,
    db: AsyncSession,
) -> list[Artifact]:
    try:
        _validate_glob_pattern(glob_pattern)
    except ArtifactGlobRejectedError as exc:
        logger.warning("artifact_glob_rejected", pattern=glob_pattern, error=str(exc))
        return []

    matches = sorted(workspace.root.glob(glob_pattern))[:_MAX_ARTIFACTS_PER_EXECUTION]

    records: list[Artifact] = []
    for match in matches:
        if not match.is_file():
            continue
        resolved = match.resolve()
        try:
            resolved.relative_to(workspace.root)
        except ValueError:
            logger.warning("artifact_path_escaped_workspace", path=str(match))
            continue

        relative_path = workspace.relative(resolved)
        artifact = await create_artifact(
            db,
            execution_id=execution_id,
            artifact_type=_artifact_type_for(relative_path),
            path=relative_path,
            metadata={"size_bytes": resolved.stat().st_size},
        )
        records.append(artifact)

    logger.info("artifacts_collected", execution_id=str(execution_id), glob=glob_pattern, count=len(records))
    return records
