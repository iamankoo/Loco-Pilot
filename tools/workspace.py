"""Workspace: the sandboxed root directory a tool call is allowed to touch.

Every filesystem/git/terminal tool resolves paths through
`Workspace.resolve()`, which is the single security boundary preventing
path traversal, absolute-path escapes, and symlink escapes. No tool should
ever build a filesystem path by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


class WorkspaceError(Exception):
    """Raised when a requested path/workspace violates the sandbox boundary."""


def _looks_absolute(path_str: str) -> bool:
    # Check both path styles regardless of host OS: a malicious input could
    # use either style, and we want to reject both defensively.
    return PurePosixPath(path_str).is_absolute() or PureWindowsPath(path_str).is_absolute()


@dataclass(frozen=True)
class Workspace:
    """A resolved, existing directory that tool calls are confined to."""

    root: Path

    @classmethod
    def at(cls, root: str | Path) -> Workspace:
        resolved = Path(root).resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise WorkspaceError(f"Workspace root does not exist or is not a directory: {resolved}")
        return cls(root=resolved)

    def resolve(self, relative_path: str) -> Path:
        """Resolve a workspace-relative path, rejecting any escape attempt.

        Absolute paths are rejected outright. Relative paths (including
        ones containing `..`) are resolved against the workspace root and
        then checked to still be inside it — `Path.resolve()` also follows
        symlinks to their real target, so a symlink pointing outside the
        workspace is caught by the same check.
        """
        if relative_path is None or relative_path.strip() == "":
            raise WorkspaceError("Path must not be empty.")
        if _looks_absolute(relative_path):
            raise WorkspaceError(f"Absolute paths are not allowed: {relative_path!r}")

        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError(f"Path escapes workspace root: {relative_path!r}") from exc
        return candidate

    def relative(self, absolute_path: Path) -> str:
        """Render an absolute path (already known to be inside the workspace) as a workspace-relative string."""
        return absolute_path.relative_to(self.root).as_posix()
