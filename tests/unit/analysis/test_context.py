from __future__ import annotations

from pathlib import Path

import pytest

from analysis import context as context_module
from analysis.context import build_project_context
from analysis.scanner import ScanLimits
from tools.workspace import Workspace


async def test_build_project_context_for_existing_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\ndependencies = ["fastapi>=0.115"]\n')
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "auth_service.py").write_text("def login(): pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auth.py").write_text("def test_login(): pass\n")

    ctx = await build_project_context(Workspace.at(tmp_path), "Fix authentication bug")

    assert ctx.languages == ["Python"]
    assert "FastAPI" in ctx.frameworks
    assert ctx.structure is not None and ctx.structure.file_count > 0
    assert any("auth" in r.path for r in ctx.relevant_files)
    assert ctx.incomplete is False
    assert ctx.warnings == []
    # Must be JSON-serializable — this is what gets stored in ExecutionState.
    assert ctx.model_dump_json()


async def test_context_is_marked_incomplete_when_scan_is_truncated(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"file_{i}.txt").write_text("x")

    ctx = await build_project_context(Workspace.at(tmp_path), "do something", scan_limits=ScanLimits(max_files=2))

    assert ctx.incomplete is True
    assert ctx.structure.truncated is True
    assert any("file count" in w.lower() for w in ctx.warnings)


async def test_context_assembly_survives_a_stage_failure_honestly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure in one analysis stage (simulated here) must not prevent
    the rest of the context from being built, and must be recorded as a
    warning rather than silently dropped — "fabricate nothing" applies to
    workspace intelligence exactly as it does to test results."""
    (tmp_path / "app.py").write_text("x = 1\n")

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated detection failure")

    monkeypatch.setattr(context_module, "detect_project_type", _boom)

    ctx = await build_project_context(Workspace.at(tmp_path), "do something")

    assert ctx.incomplete is True
    assert any("detection failed" in w.lower() for w in ctx.warnings)
    # The scan itself still succeeded and is still present.
    assert ctx.structure is not None
    assert ctx.structure.file_count > 0
