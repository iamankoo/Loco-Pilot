"""Bounded, best-effort parsing of dependency manifests the scanner found.

Deliberately not a full build-tool implementation: each parser extracts
just package names (Java/Maven coordinates as `group:artifact`) from the
manifest formats listed in the Phase 2.2 spec, using the stdlib only
(`json`, `xml.etree`, and small regexes for the TOML/YAML-like formats
Python 3.10 has no builtin parser for). Dependencies are never installed;
manifest content is never handed to the LLM verbatim, only this capped
summary.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from pydantic import BaseModel, Field

from tools.workspace import Workspace, WorkspaceError

MAX_DEPENDENCIES_PER_KIND = 40
MAX_MANIFEST_READ_BYTES = 200_000


class DependencySummary(BaseModel):
    package_managers: list[str] = Field(default_factory=list)
    direct_dependencies: list[str] = Field(default_factory=list)
    dev_dependencies: list[str] = Field(default_factory=list)
    manifests_parsed: list[str] = Field(default_factory=list)
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


def _read_bounded(workspace: Workspace, relative_path: str) -> str | None:
    """Never lets one bad manifest path (a symlink escaping the workspace,
    an unreadable file) fail parsing for every other manifest — `resolve`
    raising `WorkspaceError` is treated exactly like a missing/unreadable
    file, not a reason to abort."""
    try:
        path = workspace.resolve(relative_path)
        if not path.is_file() or path.stat().st_size > MAX_MANIFEST_READ_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, WorkspaceError):
        return None


def _cap(names: list[str]) -> tuple[list[str], bool]:
    if len(names) > MAX_DEPENDENCIES_PER_KIND:
        return names[:MAX_DEPENDENCIES_PER_KIND], True
    return names, False


def parse_dependency_manifests(workspace: Workspace, manifest_paths: list[str]) -> DependencySummary:
    package_managers: set[str] = set()
    direct: list[str] = []
    dev: list[str] = []
    parsed: list[str] = []
    warnings: list[str] = []

    for rel_path in manifest_paths:
        name = Path(rel_path).name
        text = _read_bounded(workspace, rel_path)
        if text is None:
            continue

        try:
            if name in ("requirements.txt",):
                direct += _parse_requirements_txt(text)
                package_managers.add("pip")
            elif name == "requirements-dev.txt":
                dev += _parse_requirements_txt(text)
                package_managers.add("pip")
            elif name == "pyproject.toml":
                d, dv, mgr = _parse_pyproject_toml(text)
                direct += d
                dev += dv
                package_managers.add(mgr)
            elif name == "package.json":
                d, dv = _parse_package_json(text)
                direct += d
                dev += dv
                package_managers.add("npm")
            elif name == "pnpm-lock.yaml":
                package_managers.add("pnpm")
            elif name == "yarn.lock":
                package_managers.add("yarn")
            elif name == "package-lock.json":
                package_managers.add("npm")
            elif name == "pom.xml":
                direct += _parse_pom_xml(text)
                package_managers.add("maven")
            elif name in ("build.gradle", "build.gradle.kts"):
                direct += _parse_gradle(text)
                package_managers.add("gradle")
            elif name == "go.mod":
                direct += _parse_go_mod(text)
                package_managers.add("go modules")
            elif name == "Cargo.toml":
                d, dv = _parse_cargo_toml(text)
                direct += d
                dev += dv
                package_managers.add("cargo")
            elif name == "pubspec.yaml":
                d, dv = _parse_pubspec_yaml(text)
                direct += d
                dev += dv
                package_managers.add("pub")
            else:
                continue
            parsed.append(rel_path)
        except Exception as exc:  # noqa: BLE001 - a malformed manifest must not abort the whole analysis
            warnings.append(f"Could not parse {rel_path}: {exc}")

    direct = sorted(dict.fromkeys(direct))
    dev = sorted(dict.fromkeys(n for n in dev if n not in direct))
    direct, direct_truncated = _cap(direct)
    dev, dev_truncated = _cap(dev)

    return DependencySummary(
        package_managers=sorted(package_managers),
        direct_dependencies=direct,
        dev_dependencies=dev,
        manifests_parsed=parsed,
        truncated=direct_truncated or dev_truncated,
        warnings=warnings,
    )


_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")


def _parse_requirements_txt(text: str) -> list[str]:
    names = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = _REQ_LINE.match(line)
        if match:
            names.append(match.group(1))
    return names


_PYPROJECT_MAIN_DEPS = re.compile(r"^\s*dependencies\s*=\s*\[(.*?)\]", re.DOTALL | re.MULTILINE)
_TOML_STRING = re.compile(r'"([^"]+)"|\'([^\']+)\'')
_POETRY_DEP_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*=", re.MULTILINE)
_TOML_SECTION = re.compile(r"^\[([^\]]+)\]\s*\n(.*?)(?=^\[|\Z)", re.DOTALL | re.MULTILINE)


def _extract_dep_names_from_array_block(block: str) -> list[str]:
    names = []
    for match in _TOML_STRING.finditer(block):
        raw = match.group(1) or match.group(2)
        name = re.split(r"[<>=!~\[; ]", raw, maxsplit=1)[0].strip()
        if name:
            names.append(name)
    return names


def _parse_pyproject_toml(text: str) -> tuple[list[str], list[str], str]:
    direct: list[str] = []
    dev: list[str] = []
    package_manager = "pip"

    main_match = _PYPROJECT_MAIN_DEPS.search(text)
    if main_match:
        direct = _extract_dep_names_from_array_block(main_match.group(1))

    for section_name, body in _TOML_SECTION.findall(text):
        if section_name in ("project.optional-dependencies",) or section_name.startswith("dependency-groups"):
            for arr_match in re.finditer(r"=\s*\[(.*?)\]", body, re.DOTALL):
                dev += _extract_dep_names_from_array_block(arr_match.group(1))
        elif section_name == "tool.poetry.dependencies" and not direct:
            package_manager = "poetry"
            for line in body.splitlines():
                match = _POETRY_DEP_LINE.match(line)
                if match and match.group(1).lower() != "python":
                    direct.append(match.group(1))
        elif section_name in ("tool.poetry.group.dev.dependencies", "tool.poetry.dev-dependencies"):
            for line in body.splitlines():
                match = _POETRY_DEP_LINE.match(line)
                if match:
                    dev.append(match.group(1))

    return direct, dev, package_manager


def _parse_package_json(text: str) -> tuple[list[str], list[str]]:
    data = json.loads(text)
    direct = list((data.get("dependencies") or {}).keys())
    dev = list((data.get("devDependencies") or {}).keys())
    return direct, dev


def _parse_pom_xml(text: str) -> list[str]:
    names = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return names
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    for dep in root.iter(f"{ns}dependency"):
        group = dep.find(f"{ns}groupId")
        artifact = dep.find(f"{ns}artifactId")
        if artifact is not None and artifact.text:
            names.append(f"{group.text}:{artifact.text}" if group is not None and group.text else artifact.text)
    return names


_GRADLE_DEP = re.compile(
    r"""(?:implementation|api|testImplementation|compileOnly|runtimeOnly)\s*[(\s]['"]([^'"]+)['"]"""
)


def _parse_gradle(text: str) -> list[str]:
    return [match.group(1) for match in _GRADLE_DEP.finditer(text)]


def _parse_go_mod(text: str) -> list[str]:
    names = []
    block_match = re.search(r"require\s*\((.*?)\)", text, re.DOTALL)
    if block_match:
        for line in block_match.group(1).splitlines():
            line = line.strip()
            if line and not line.startswith("//"):
                names.append(line.split()[0])
    for match in re.finditer(r"^require\s+(\S+)\s+v[0-9]", text, re.MULTILINE):
        names.append(match.group(1))
    return names


def _parse_cargo_toml(text: str) -> tuple[list[str], list[str]]:
    def section_names(section: str) -> list[str]:
        match = re.search(rf"^\[{re.escape(section)}\]\s*\n(.*?)(?=^\[|\Z)", text, re.DOTALL | re.MULTILINE)
        if not match:
            return []
        return [
            line.split("=")[0].strip()
            for line in match.group(1).splitlines()
            if "=" in line and not line.strip().startswith("#")
        ]

    return section_names("dependencies"), section_names("dev-dependencies")


def _parse_pubspec_yaml(text: str) -> tuple[list[str], list[str]]:
    """A narrow, indentation-based reader for the common
    `dependencies:` / `dev_dependencies:` shape of a Flutter `pubspec.yaml`
    — not a general YAML parser. Only keys indented exactly one level under
    the section header are taken as dependency names."""

    def section_names(header: str) -> list[str]:
        match = re.search(rf"^{header}:[ \t]*\n((?:[ \t]+.*\n?)*)", text, re.MULTILINE)
        if not match:
            return []
        names = []
        for line in match.group(1).splitlines():
            if not line.strip() or line.strip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" \t"))
            if 0 < indent <= 2:
                key = line.strip().split(":", 1)[0].strip()
                if key and key != "sdk":
                    names.append(key)
        return names

    return section_names("dependencies"), section_names("dev_dependencies")
