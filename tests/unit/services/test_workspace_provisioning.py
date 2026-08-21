from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.core.config import get_settings
from backend.app.services.workspace_provisioning import provision_default_workspace, slugify


def test_slugify_produces_url_safe_lowercase_slug() -> None:
    assert slugify("Write a Calculator in C++!") == "write-a-calculator-in-c"


def test_slugify_falls_back_when_nothing_remains() -> None:
    assert slugify("!!!") == "project"


def test_provision_default_workspace_creates_directory_under_workspace_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCOPILOT_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        name, path = provision_default_workspace(seed_text="Build a calculator", project_name=None)
        created = Path(path)
        assert created.exists() and created.is_dir()
        assert created.parent == tmp_path / "projects"
        assert created.name.startswith("build-a-calculator-")
        assert name == "build-a-calculator"
    finally:
        get_settings.cache_clear()


def test_provision_default_workspace_uses_explicit_project_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCOPILOT_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        name, path = provision_default_workspace(seed_text="irrelevant task text", project_name="my-project")
        assert name == "my-project"
        assert Path(path).name.startswith("my-project-")
    finally:
        get_settings.cache_clear()
