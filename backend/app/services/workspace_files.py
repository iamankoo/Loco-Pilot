"""Safe, workspace-bounded file browsing and upload.

Every path operation here goes through `Workspace.resolve()` — the same
boundary every agent tool already uses — so browsing/uploading can never
escape the project's authorized workspace_path via `../`, an absolute
path, or a symlink.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from tools.filesystem.schemas import DEFAULT_EXCLUDED_DIRS
from tools.workspace import Workspace, WorkspaceError

MAX_UPLOAD_BYTES = 5_000_000

# A generous allowlist of ordinary source/text/config file extensions.
# Deliberately excludes executables/binaries/archives — uploaded files are
# never auto-executed, but there is no reason to accept them either.
ALLOWED_UPLOAD_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".json", ".md", ".mdx", ".txt", ".rst",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env.example",
    ".csv", ".tsv",
    ".java", ".kt", ".scala",
    ".c", ".h", ".cpp", ".cc", ".hpp", ".cxx",
    ".go", ".rs", ".rb", ".php", ".swift", ".m",
    ".sql", ".sh", ".bash", ".ps1",
    ".html", ".css", ".scss", ".less",
    ".xml", ".proto", ".gradle", ".dockerfile",
}


class WorkspaceFileError(Exception):
    """Raised for any rejected browse/upload request (traversal, size, type)."""


@dataclass
class WorkspaceEntry:
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None


@dataclass
class UploadedFile:
    filename: str
    relative_path: str
    size_bytes: int
    content_type: str | None


def _workspace_for(workspace_path: str | None) -> Workspace:
    if not workspace_path:
        raise WorkspaceFileError("Project has no workspace_path configured.")
    try:
        return Workspace.at(workspace_path)
    except WorkspaceError as exc:
        raise WorkspaceFileError(str(exc)) from exc


def list_workspace_entries(workspace_path: str | None, relative_path: str) -> list[WorkspaceEntry]:
    """Lists the immediate contents of `relative_path` within the
    workspace. Raises WorkspaceFileError for any traversal/escape attempt,
    a missing directory, or a path that isn't a directory."""
    workspace = _workspace_for(workspace_path)
    try:
        target = workspace.resolve(relative_path) if relative_path else workspace.root
    except WorkspaceError as exc:
        raise WorkspaceFileError(str(exc)) from exc

    if not target.exists():
        raise WorkspaceFileError(f"Path not found: {relative_path!r}")
    if not target.is_dir():
        raise WorkspaceFileError(f"Not a directory: {relative_path!r}")

    entries: list[WorkspaceEntry] = []
    try:
        children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        raise WorkspaceFileError(f"Could not read directory: {exc}") from exc

    for child in children:
        if child.name in DEFAULT_EXCLUDED_DIRS or child.name.startswith("."):
            continue
        entries.append(
            WorkspaceEntry(
                name=child.name,
                path=workspace.relative(child),
                is_dir=child.is_dir(),
                size_bytes=child.stat().st_size if child.is_file() else None,
            )
        )
    return entries


def _safe_filename(original: str) -> str:
    name = os.path.basename(original).strip()
    if not name or name in (".", ".."):
        raise WorkspaceFileError("Invalid filename.")
    return name


def _unique_destination(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = Path(filename).stem, Path(filename).suffix
    for n in range(1, 1000):
        alt = directory / f"{stem}-{n}{suffix}"
        if not alt.exists():
            return alt
    raise WorkspaceFileError("Could not allocate a unique filename.")


async def save_uploaded_files(workspace_path: str | None, files: list[UploadFile]) -> list[UploadedFile]:
    """Saves each upload into `<workspace>/uploads/`, enforcing an
    extension allowlist and a per-file size cap. Filenames are reduced to
    their basename and de-duplicated — never taken as a path."""
    workspace = _workspace_for(workspace_path)
    uploads_dir = workspace.resolve("uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)

    saved: list[UploadedFile] = []
    for upload in files:
        filename = _safe_filename(upload.filename or "")
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_UPLOAD_EXTENSIONS:
            raise WorkspaceFileError(f"File type not allowed: {filename!r} ({extension or 'no extension'}).")

        destination = _unique_destination(uploads_dir, filename)
        size = 0
        with destination.open("wb") as out:
            while chunk := await upload.read(1_000_000):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    out.close()
                    destination.unlink(missing_ok=True)
                    raise WorkspaceFileError(f"File too large: {filename!r} (max {MAX_UPLOAD_BYTES} bytes).")
                out.write(chunk)

        saved.append(
            UploadedFile(
                filename=filename,
                relative_path=workspace.relative(destination),
                size_bytes=size,
                content_type=upload.content_type,
            )
        )
    return saved
