from __future__ import annotations

from pathlib import Path

import pytest

from analysis.manifests import MAX_MANIFEST_READ_BYTES, parse_dependency_manifests
from tools.workspace import Workspace


def _workspace(tmp_path: Path) -> Workspace:
    return Workspace.at(tmp_path)


def test_parses_python_pyproject_dependencies(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = [\n    "fastapi>=0.115",\n    "pydantic>=2.9",\n]\n'
        '[project.optional-dependencies]\ndev = [\n    "pytest>=8.3",\n]\n'
    )

    summary = parse_dependency_manifests(_workspace(tmp_path), ["pyproject.toml"])

    assert "fastapi" in summary.direct_dependencies
    assert "pydantic" in summary.direct_dependencies
    assert "pytest" in summary.dev_dependencies
    assert "pip" in summary.package_managers


def test_parses_requirements_txt(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("flask==3.0.0\n# a comment\nrequests>=2.0\n\n-e .\n")

    summary = parse_dependency_manifests(_workspace(tmp_path), ["requirements.txt"])

    assert "flask" in summary.direct_dependencies
    assert "requests" in summary.direct_dependencies
    assert "pip" in summary.package_managers


def test_parses_node_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"next": "14.0.0", "react": "18.0.0"}, "devDependencies": {"jest": "29.0.0"}}'
    )

    summary = parse_dependency_manifests(_workspace(tmp_path), ["package.json"])

    assert "next" in summary.direct_dependencies
    assert "react" in summary.direct_dependencies
    assert "jest" in summary.dev_dependencies
    assert "npm" in summary.package_managers


def test_parses_go_mod(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text(
        "module example.com/demo\n\ngo 1.21\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n)\n"
    )

    summary = parse_dependency_manifests(_workspace(tmp_path), ["go.mod"])

    assert "github.com/gin-gonic/gin" in summary.direct_dependencies
    assert "go modules" in summary.package_managers


def test_parses_cargo_toml(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "demo"\n\n[dependencies]\nserde = "1.0"\ntokio = { version = "1", features = ["full"] }\n'
    )

    summary = parse_dependency_manifests(_workspace(tmp_path), ["Cargo.toml"])

    assert "serde" in summary.direct_dependencies
    assert "tokio" in summary.direct_dependencies
    assert "cargo" in summary.package_managers


def test_parses_pubspec_yaml(tmp_path: Path) -> None:
    (tmp_path / "pubspec.yaml").write_text(
        "name: demo\nenvironment:\n  sdk: '>=2.12.0 <3.0.0'\n"
        "dependencies:\n  flutter:\n    sdk: flutter\n  http: ^0.13.0\n"
        "dev_dependencies:\n  flutter_test:\n    sdk: flutter\n"
    )

    summary = parse_dependency_manifests(_workspace(tmp_path), ["pubspec.yaml"])

    assert "http" in summary.direct_dependencies
    assert "flutter_test" in summary.dev_dependencies
    assert "pub" in summary.package_managers


def test_parses_pom_xml(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text(
        "<project><dependencies>"
        "<dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency>"
        "</dependencies></project>"
    )

    summary = parse_dependency_manifests(_workspace(tmp_path), ["pom.xml"])

    assert "org.springframework.boot:spring-boot-starter-web" in summary.direct_dependencies
    assert "maven" in summary.package_managers


def test_dependency_list_is_capped(tmp_path: Path) -> None:
    deps = "\n".join(f"package-{i}==1.0" for i in range(100))
    (tmp_path / "requirements.txt").write_text(deps)

    summary = parse_dependency_manifests(_workspace(tmp_path), ["requirements.txt"])

    assert len(summary.direct_dependencies) <= 40
    assert summary.truncated is True


def test_oversized_manifest_is_skipped_not_parsed(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("x" * (MAX_MANIFEST_READ_BYTES + 1))

    summary = parse_dependency_manifests(_workspace(tmp_path), ["requirements.txt"])

    assert summary.manifests_parsed == []
    assert summary.direct_dependencies == []


def test_manifest_symlink_escaping_workspace_is_skipped_not_fatal(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"outside-manifest-{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "secret_requirements.txt").write_text("super-secret-package==1.0\n")

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    link = workspace_root / "requirements.txt"
    try:
        link.symlink_to(outside / "secret_requirements.txt")
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not permitted in this environment.")

    (workspace_root / "package.json").write_text('{"dependencies": {"left-pad": "1.0.0"}}')

    summary = parse_dependency_manifests(_workspace(workspace_root), ["requirements.txt", "package.json"])

    assert "super-secret-package" not in summary.direct_dependencies
    # The symlink escape must not prevent the OTHER, legitimate manifest
    # from still being parsed.
    assert "left-pad" in summary.direct_dependencies
