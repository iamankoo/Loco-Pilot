"""Deterministic, bounded repository structure scanning.

Answers "what does this project look like" without reading any file's
content and without unbounded recursion. Reuses the same excluded-directory
set the repository indexer and `search_files` tool already use
(`rag.exclusions`), so "what LocoPilot considers noise" is defined in one
place, not duplicated here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from rag.exclusions import EXCLUDED_DIRS
from tools.workspace import Workspace

DEFAULT_MAX_FILES = 2000
DEFAULT_MAX_DEPTH = 8

DEPENDENCY_MANIFEST_NAMES = {
    "pyproject.toml", "requirements.txt", "requirements-dev.txt", "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "go.mod", "go.sum",
    "Cargo.toml", "Cargo.lock",
    "pubspec.yaml", "pubspec.lock",
    "CMakeLists.txt", "Makefile",
}

_CONFIG_FILE_NAMES = {
    "pyproject.toml", "setup.cfg", "pytest.ini", "tox.ini", ".flake8",
    "tsconfig.json", ".eslintrc.json", ".eslintrc.js", "next.config.js", "next.config.ts",
    "vite.config.ts", "vite.config.js", "jest.config.js", "jest.config.ts", "vitest.config.ts",
    "playwright.config.ts", "cypress.config.ts", "docker-compose.yml", "docker-compose.yaml",
    "Dockerfile", ".env.example", "alembic.ini", "CMakeLists.txt", "Makefile",
}

_DOC_FILE_PREFIXES = ("readme", "changelog", "contributing", "license")
_TEST_DIR_NAMES = {"tests", "test", "__tests__", "spec", "specs"}
_CI_DIR_NAMES = {".github", ".gitlab-ci", ".circleci"}
_SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".cc", ".dart", ".kt",
}


class RepositoryStructure(BaseModel):
    root: str
    directories: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    source_directories: list[str] = Field(default_factory=list)
    test_directories: list[str] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    documentation_files: list[str] = Field(default_factory=list)
    dependency_manifests: list[str] = Field(default_factory=list)
    ci_files: list[str] = Field(default_factory=list)
    has_git: bool = False
    file_count: int = 0
    directory_count: int = 0
    ignored_directories: list[str] = Field(default_factory=list)
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ScanLimits:
    max_files: int = DEFAULT_MAX_FILES
    max_depth: int = DEFAULT_MAX_DEPTH


def is_test_path(relative_path: str) -> bool:
    """True if any path segment looks like a test file/directory — the
    same naming convention `scan_repository` uses to classify
    `test_directories`, exposed here so other modules (e.g. the RAG hybrid
    retriever's test-awareness boost) don't need their own copy of it."""
    for segment in relative_path.replace("\\", "/").split("/"):
        lower = segment.lower()
        stem = lower.rsplit(".", 1)[0] if "." in lower else lower
        if lower in _TEST_DIR_NAMES or stem.startswith("test_") or stem.endswith("_test"):
            return True
    return False


def _is_source_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in _SOURCE_EXTENSIONS


def scan_repository(workspace: Workspace, limits: ScanLimits | None = None) -> RepositoryStructure:
    """Bounded, deterministically-ordered directory walk. Stops descending
    once `max_depth` is reached and stops entirely once `max_files` files
    have been recorded — `truncated=True` then means `file_count` is a
    lower bound, not the project's real total."""
    limits = limits or ScanLimits()
    root = workspace.root

    directories: list[str] = []
    files: list[str] = []
    source_directories: set[str] = set()
    test_directories: set[str] = set()
    config_files: set[str] = set()
    documentation_files: set[str] = set()
    dependency_manifests: set[str] = set()
    ci_files: set[str] = set()
    ignored_directories: set[str] = set()
    warnings: list[str] = []
    truncated = False
    depth_limit_warned = False

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        depth = len(current.relative_to(root).parts)

        kept = []
        for name in sorted(dirnames):
            if name in EXCLUDED_DIRS:
                ignored_directories.add(name)
            else:
                kept.append(name)
        if depth >= limits.max_depth:
            if kept and not depth_limit_warned:
                warnings.append(f"Maximum scan depth ({limits.max_depth}) reached; some subdirectories were not explored.")
                depth_limit_warned = True
            kept = []
        dirnames[:] = kept

        if current != root:
            rel_dir = workspace.relative(current)
            directories.append(rel_dir)
            base_name = current.name.lower()
            if base_name in _TEST_DIR_NAMES or base_name.startswith("test_") or base_name.endswith("_test"):
                test_directories.add(rel_dir)
            elif base_name in _CI_DIR_NAMES:
                ci_files.add(rel_dir)

        if truncated:
            continue

        for filename in sorted(filenames):
            if len(files) >= limits.max_files:
                truncated = True
                warnings.append(f"Maximum file count ({limits.max_files}) reached; scan stopped early.")
                break

            file_path = current / filename
            rel_file = workspace.relative(file_path)
            files.append(rel_file)

            if filename in DEPENDENCY_MANIFEST_NAMES:
                dependency_manifests.add(rel_file)
            if filename in _CONFIG_FILE_NAMES:
                config_files.add(rel_file)
            lower = filename.lower()
            if lower.startswith(_DOC_FILE_PREFIXES) or lower.endswith(".md"):
                documentation_files.add(rel_file)
            if depth <= 2 and _is_source_file(filename):
                container = workspace.relative(current) if current != root else "."
                source_directories.add(container)

        if truncated:
            break

    return RepositoryStructure(
        root=str(root),
        directories=sorted(directories),
        files=files,
        source_directories=sorted(d for d in source_directories if d not in test_directories),
        test_directories=sorted(test_directories),
        config_files=sorted(config_files),
        documentation_files=sorted(documentation_files),
        dependency_manifests=sorted(dependency_manifests),
        ci_files=sorted(ci_files),
        has_git=(root / ".git").exists(),
        file_count=len(files),
        directory_count=len(directories),
        ignored_directories=sorted(ignored_directories),
        truncated=truncated,
        warnings=warnings,
    )
