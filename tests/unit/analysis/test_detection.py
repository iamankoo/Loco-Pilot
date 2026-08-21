from __future__ import annotations

from pathlib import Path

from analysis.detection import detect_project_type
from analysis.manifests import parse_dependency_manifests
from analysis.scanner import scan_repository
from tools.workspace import Workspace


def _analyze(tmp_path: Path):
    workspace = Workspace.at(tmp_path)
    structure = scan_repository(workspace)
    dependencies = parse_dependency_manifests(workspace, structure.dependency_manifests)
    return detect_project_type(structure, dependencies)


def test_detects_existing_python_fastapi_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = [\n    "fastapi>=0.115",\n    "pytest>=8.3",\n]\n'
    )
    (tmp_path / "app.py").write_text("app = 1\n")

    detection = _analyze(tmp_path)

    assert "Python" in detection.languages
    assert "FastAPI" in detection.frameworks
    assert "pytest" in detection.test_frameworks
    assert "pyproject.toml" in detection.evidence


def test_detects_existing_nextjs_project(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"next": "14.0.0", "react": "18.0.0"}, "devDependencies": {"jest": "29.0.0"}}'
    )
    (tmp_path / "tsconfig.json").write_text("{}")

    detection = _analyze(tmp_path)

    assert "JavaScript/TypeScript" in detection.languages
    assert "Next.js" in detection.frameworks
    # Next.js already implies React; it should not be double-reported.
    assert detection.frameworks.count("React") == 0
    assert "Jest" in detection.test_frameworks


def test_detects_existing_cpp_project(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.10)\nenable_testing()\n")
    (tmp_path / "main.cpp").write_text("int main() { return 0; }\n")

    detection = _analyze(tmp_path)

    assert "C/C++" in detection.languages
    assert "CTest" in detection.test_frameworks


def test_detects_existing_flutter_project(tmp_path: Path) -> None:
    (tmp_path / "pubspec.yaml").write_text(
        "name: demo\ndependencies:\n  flutter:\n    sdk: flutter\ndev_dependencies:\n  flutter_test:\n    sdk: flutter\n"
    )
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "widget_test.dart").write_text("void main() {}\n")

    detection = _analyze(tmp_path)

    assert "Dart/Flutter" in detection.languages
    assert "Flutter" in detection.frameworks
    assert "flutter test" in detection.test_frameworks


def test_no_manifest_falls_back_to_extension_evidence(tmp_path: Path) -> None:
    (tmp_path / "main.go").write_text("package main\n")

    detection = _analyze(tmp_path)

    assert "Go" in detection.languages
    assert any("extension" in e for e in detection.evidence)


def test_weak_filename_alone_does_not_claim_a_framework(tmp_path: Path) -> None:
    """A file named `app.py` existing is not, by itself, evidence of any
    framework — only real dependency evidence should ever claim one."""
    (tmp_path / "app.py").write_text("print('hi')\n")

    detection = _analyze(tmp_path)

    assert detection.frameworks == []
