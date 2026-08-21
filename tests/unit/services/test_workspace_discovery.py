from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from backend.app.core.config import get_settings
from backend.app.db.repositories.projects import create_project
from backend.app.services.workspace_discovery import (
    discover_or_provision_workspace,
    extract_project_name_hint,
    task_indicates_creation,
)


@pytest.fixture
def workspace_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCOPILOT_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_extracts_project_name_hint_from_task_text() -> None:
    assert extract_project_name_hint("Fix authentication bug in DeepLens") == "DeepLens"
    assert extract_project_name_hint("Check config.py in Document Saathi") == "Document Saathi"
    assert extract_project_name_hint("Create a C++ calculator") is None


def test_task_indicates_creation() -> None:
    assert task_indicates_creation("Create a C++ calculator") is True
    assert task_indicates_creation("Build a new REST API") is True
    assert task_indicates_creation("Fix authentication bug in DeepLens") is False
    assert task_indicates_creation("Check config.py in Document Saathi") is False


async def test_existing_project_found_by_explicit_project_id(db_session, workspace_root: Path) -> None:
    project = await create_project(db_session, name="DeepLens", workspace_path=str(workspace_root))

    result = await discover_or_provision_workspace(
        db_session, task="fix login", project_id=project.id, workspace_path=None, project_name=None
    )

    assert result.outcome == "existing"
    assert result.project_id == project.id


async def test_unknown_explicit_project_id_is_not_found(db_session, workspace_root: Path) -> None:
    result = await discover_or_provision_workspace(
        db_session, task="fix login", project_id=uuid.uuid4(), workspace_path=None, project_name=None
    )

    assert result.outcome == "not_found"


async def test_existing_project_found_by_name_hint_in_task(db_session, workspace_root: Path) -> None:
    # A unique-per-run name (matching the pattern the rest of this test
    # suite uses elsewhere) so a leftover row from a prior run against the
    # same shared Postgres instance can never be matched instead of this
    # test's own project.
    unique_name = f"DeepLens-{uuid.uuid4().hex[:8]}"
    project_dir = workspace_root / "deeplens"
    project_dir.mkdir()
    await create_project(db_session, name=unique_name, workspace_path=str(project_dir))

    result = await discover_or_provision_workspace(
        db_session,
        task=f"Fix authentication bug in {unique_name}",
        project_id=None,
        workspace_path=None,
        project_name=None,
    )

    assert result.outcome == "existing"
    assert result.project_name == unique_name
    assert result.workspace_path == str(project_dir)


async def test_missing_named_project_is_reported_not_created(db_session, workspace_root: Path) -> None:
    """'Check config.py in Document Saathi': no such project exists and the
    task does not ask to create one — must be an honest not-found, never a
    silently-created empty directory."""
    result = await discover_or_provision_workspace(
        db_session, task="Check config.py in Document Saathi", project_id=None, workspace_path=None, project_name=None
    )

    assert result.outcome == "not_found"
    assert "Document Saathi" in result.reason
    assert not (workspace_root / "projects" / "document-saathi").exists()


async def test_new_project_created_when_task_explicitly_requests_it(db_session, workspace_root: Path) -> None:
    result = await discover_or_provision_workspace(
        db_session, task="Create a C++ calculator", project_id=None, workspace_path=None, project_name=None
    )

    assert result.outcome == "created"
    assert result.workspace_path is not None
    assert Path(result.workspace_path).is_dir()
    assert str(workspace_root) in result.workspace_path


async def test_no_reference_at_all_preserves_default_provisioning_behavior(db_session, workspace_root: Path) -> None:
    """No project_id/workspace_path/project_name at all: unchanged Phase
    1.7 behavior — provision a fresh default workspace rather than reject
    the request."""
    result = await discover_or_provision_workspace(
        db_session, task="do something", project_id=None, workspace_path=None, project_name=None
    )

    assert result.outcome == "created"
    assert result.workspace_path is not None


async def test_invalid_explicit_workspace_path_is_reported_as_invalid_not_missing(db_session, workspace_root: Path) -> None:
    result = await discover_or_provision_workspace(
        db_session,
        task="do something",
        project_id=None,
        workspace_path=str(workspace_root / "does-not-exist"),
        project_name=None,
    )

    assert result.outcome == "invalid"
