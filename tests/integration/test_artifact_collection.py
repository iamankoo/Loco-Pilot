from __future__ import annotations

import uuid

from backend.app.db.repositories.executions import create_execution
from backend.app.db.repositories.projects import create_project
from backend.app.services.artifact_service import collect_artifacts
from tools.workspace import Workspace


async def _real_execution_id(db_session, tmp_workspace: Workspace) -> uuid.UUID:
    project = await create_project(
        db_session, name=f"proj-{uuid.uuid4()}", workspace_path=str(tmp_workspace.root)
    )
    execution = await create_execution(db_session, project_id=project.id, task="build")
    return execution.id


async def test_collect_artifacts_records_matching_files(db_session, tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "dist").mkdir()
    (tmp_workspace.root / "dist" / "app.whl").write_bytes(b"fake wheel contents")
    (tmp_workspace.root / "dist" / "notes.txt").write_text("not an artifact")

    execution_id = await _real_execution_id(db_session, tmp_workspace)
    artifacts = await collect_artifacts(tmp_workspace, "dist/*.whl", execution_id, db_session)

    assert len(artifacts) == 1
    assert artifacts[0].path == "dist/app.whl"
    assert artifacts[0].artifact_type == "python-wheel"


async def test_collect_artifacts_no_match_completes_normally(db_session, tmp_workspace: Workspace) -> None:
    artifacts = await collect_artifacts(tmp_workspace, "dist/*.whl", uuid.uuid4(), db_session)
    assert artifacts == []


async def test_collect_artifacts_rejects_parent_traversal_glob(db_session, tmp_workspace: Workspace) -> None:
    outside_marker = tmp_workspace.root.parent / "should-not-be-found.whl"
    outside_marker.write_bytes(b"outside")
    try:
        artifacts = await collect_artifacts(tmp_workspace, "../*.whl", uuid.uuid4(), db_session)
        assert artifacts == []
    finally:
        outside_marker.unlink(missing_ok=True)


async def test_collect_artifacts_rejects_absolute_glob(db_session, tmp_workspace: Workspace) -> None:
    artifacts = await collect_artifacts(tmp_workspace, "/etc/*.whl", uuid.uuid4(), db_session)
    assert artifacts == []


async def test_collect_artifacts_infers_type_from_extension(db_session, tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "app.jar").write_bytes(b"fake jar")
    (tmp_workspace.root / "app.apk").write_bytes(b"fake apk")

    execution_id = await _real_execution_id(db_session, tmp_workspace)
    jar_artifacts = await collect_artifacts(tmp_workspace, "*.jar", execution_id, db_session)
    apk_artifacts = await collect_artifacts(tmp_workspace, "*.apk", execution_id, db_session)

    assert jar_artifacts[0].artifact_type == "jar"
    assert apk_artifacts[0].artifact_type == "android-package"
