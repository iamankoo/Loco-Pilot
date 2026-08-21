"""Assembles everything `analysis/*` deterministically discovers about a
workspace into one bounded, serializable `ProjectContext` — the structured
understanding the Planner reads instead of "just knowing" the repository.

Every stage is independently wrapped: a failure in one (a malformed
manifest, a git command failing, an oversized repository) is recorded as a
warning and the rest of the context is still built, rather than aborting
workspace intelligence altogether — a partial, honestly-labeled
understanding is more useful to the Planner than none at all.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from analysis.detection import ProjectTypeDetection, detect_project_type
from analysis.git_info import GitInfo, inspect_git
from analysis.manifests import DependencySummary, parse_dependency_manifests
from analysis.relevant_files import MAX_RELEVANT_FILES, RelevantFile, find_relevant_files
from analysis.scanner import RepositoryStructure, ScanLimits, scan_repository
from backend.app.core.logging import get_logger
from tools.workspace import Workspace

logger = get_logger(component="workspace_intelligence")

MAX_IMPORTANT_FILES_PER_CATEGORY = 10

_IMPORTANT_FILE_PATTERNS: dict[str, tuple[str, ...]] = {
    "entrypoints": ("main.", "app.", "manage.py", "wsgi.py", "asgi.py", "server.", "index.js", "index.ts"),
    "routes": ("route", "controller", "endpoint", "views.py", "urls.py"),
    "services": ("service",),
    "models": ("model",),
    "schemas": ("schema",),
    "docker": ("dockerfile", "docker-compose"),
}


class ImportantFiles(BaseModel):
    readme: list[str] = Field(default_factory=list)
    entrypoints: list[str] = Field(default_factory=list)
    routes: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    schemas: list[str] = Field(default_factory=list)
    docker: list[str] = Field(default_factory=list)
    ci: list[str] = Field(default_factory=list)
    dependency_manifests: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)


def _identify_important_files(structure: RepositoryStructure) -> ImportantFiles:
    important = ImportantFiles(
        readme=[f for f in structure.documentation_files if f.lower().rsplit("/", 1)[-1].startswith("readme")][
            :MAX_IMPORTANT_FILES_PER_CATEGORY
        ],
        dependency_manifests=structure.dependency_manifests[:MAX_IMPORTANT_FILES_PER_CATEGORY],
        ci=structure.ci_files[:MAX_IMPORTANT_FILES_PER_CATEGORY],
        test_files=[f for f in structure.files if any(f.startswith(d + "/") for d in structure.test_directories)][
            :MAX_IMPORTANT_FILES_PER_CATEGORY
        ],
    )

    buckets: dict[str, list[str]] = {key: [] for key in _IMPORTANT_FILE_PATTERNS}
    for path in structure.files:
        filename = path.rsplit("/", 1)[-1].lower()
        for category, patterns in _IMPORTANT_FILE_PATTERNS.items():
            if len(buckets[category]) >= MAX_IMPORTANT_FILES_PER_CATEGORY:
                continue
            if any(filename.startswith(p) or p in filename for p in patterns):
                buckets[category].append(path)

    important.entrypoints = buckets["entrypoints"]
    important.routes = buckets["routes"]
    important.services = buckets["services"]
    important.models = buckets["models"]
    important.schemas = buckets["schemas"]
    important.docker = buckets["docker"]
    return important


class ProjectContext(BaseModel):
    workspace_root: str
    project_path: str | None = None
    project_name: str | None = None

    git: GitInfo = Field(default_factory=GitInfo)

    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    test_frameworks: list[str] = Field(default_factory=list)
    package_managers: list[str] = Field(default_factory=list)
    detection_evidence: list[str] = Field(default_factory=list)

    dependencies: DependencySummary = Field(default_factory=DependencySummary)

    structure: RepositoryStructure | None = None
    important_files: ImportantFiles = Field(default_factory=ImportantFiles)
    test_directories: list[str] = Field(default_factory=list)

    relevant_files: list[RelevantFile] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)
    incomplete: bool = False


async def build_project_context(
    workspace: Workspace,
    task: str,
    *,
    project_name: str | None = None,
    scan_limits: ScanLimits | None = None,
    retrieved_chunk_paths: list[tuple[str, float]] | None = None,
) -> ProjectContext:
    warnings: list[str] = []
    incomplete = False

    logger.info("repository_scan_started", workspace=str(workspace.root))
    try:
        structure = scan_repository(workspace, scan_limits)
        warnings.extend(structure.warnings)
        if structure.truncated:
            incomplete = True
            logger.warning(
                "repository_scan_limited",
                file_count=structure.file_count,
                directory_count=structure.directory_count,
                warnings=structure.warnings,
            )
        logger.info(
            "repository_scan_completed",
            file_count=structure.file_count,
            directory_count=structure.directory_count,
            truncated=structure.truncated,
        )
    except Exception as exc:  # noqa: BLE001 - a scan failure must not abort context assembly
        logger.warning("repository_scan_failed", error=str(exc))
        warnings.append(f"Repository structure scan failed: {exc}")
        structure = None
        incomplete = True

    dependencies = DependencySummary()
    if structure is not None:
        try:
            dependencies = parse_dependency_manifests(workspace, structure.dependency_manifests)
            warnings.extend(dependencies.warnings)
        except Exception as exc:  # noqa: BLE001 - dependency parsing must not abort context assembly
            logger.warning("dependency_parsing_failed", error=str(exc))
            warnings.append(f"Dependency manifest parsing failed: {exc}")
            incomplete = True

    detection = ProjectTypeDetection()
    if structure is not None:
        try:
            detection = detect_project_type(structure, dependencies)
            logger.info(
                "project_type_detected",
                languages=detection.languages,
                frameworks=detection.frameworks,
                package_managers=detection.package_managers,
            )
            logger.info("test_framework_detected", test_frameworks=detection.test_frameworks)
        except Exception as exc:  # noqa: BLE001 - detection must not abort context assembly
            logger.warning("project_type_detection_failed", error=str(exc))
            warnings.append(f"Project type detection failed: {exc}")
            incomplete = True

    important_files = ImportantFiles()
    if structure is not None:
        try:
            important_files = _identify_important_files(structure)
        except Exception as exc:  # noqa: BLE001 - must not abort context assembly
            logger.warning("important_file_detection_failed", error=str(exc))
            warnings.append(f"Important file detection failed: {exc}")
            incomplete = True

    relevant_files: list[RelevantFile] = []
    if structure is not None:
        try:
            relevant_files = find_relevant_files(
                structure, task, retrieved_chunk_paths=retrieved_chunk_paths, max_results=MAX_RELEVANT_FILES
            )
            logger.info("relevant_files_identified", count=len(relevant_files))
        except Exception as exc:  # noqa: BLE001 - must not abort context assembly
            logger.warning("relevant_file_discovery_failed", error=str(exc))
            warnings.append(f"Relevant file discovery failed: {exc}")
            incomplete = True

    try:
        git = await inspect_git(workspace)
        warnings.extend(git.warnings)
    except Exception as exc:  # noqa: BLE001 - git awareness must not abort context assembly
        logger.warning("git_inspection_failed", error=str(exc))
        warnings.append(f"Git inspection failed: {exc}")
        git = GitInfo()
        incomplete = True

    logger.info(
        "workspace_context_built",
        file_count=structure.file_count if structure else 0,
        languages=detection.languages,
        frameworks=detection.frameworks,
        relevant_file_count=len(relevant_files),
        incomplete=incomplete,
    )

    return ProjectContext(
        workspace_root=str(workspace.root),
        project_path=str(workspace.root),
        project_name=project_name,
        git=git,
        languages=detection.languages,
        frameworks=detection.frameworks,
        test_frameworks=detection.test_frameworks,
        package_managers=detection.package_managers,
        detection_evidence=detection.evidence,
        dependencies=dependencies,
        structure=structure,
        important_files=important_files,
        test_directories=structure.test_directories if structure else [],
        relevant_files=relevant_files,
        warnings=warnings,
        incomplete=incomplete,
    )
