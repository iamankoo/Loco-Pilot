from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.artifact import Artifact


async def create_artifact(
    db: AsyncSession,
    *,
    execution_id: uuid.UUID,
    artifact_type: str,
    path: str,
    metadata: dict | None = None,
) -> Artifact:
    artifact = Artifact(
        execution_id=execution_id,
        artifact_type=artifact_type,
        path=path,
        artifact_metadata=metadata,
    )
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    return artifact
