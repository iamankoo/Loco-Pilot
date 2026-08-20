"""The failure modes a sandbox can raise, distinct enough that callers
(the `execute_terminal_command` tool) can convert each into a clear,
structured `ToolError` instead of an opaque crash."""

from __future__ import annotations


class SandboxError(Exception):
    """Base class for all sandbox failures."""


class DockerUnavailableError(SandboxError):
    """The `docker` CLI is not installed/reachable/daemon not running."""


class ImageUnavailableError(SandboxError):
    """The requested sandbox image does not exist locally and could not be pulled/built."""


class ContainerCreationError(SandboxError):
    """`docker create` failed."""


class ContainerStartError(SandboxError):
    """`docker start` failed."""


class WorkspaceTransferError(SandboxError):
    """A `copy_in` operation failed or targeted a path outside the allowed boundary."""


class ArtifactTransferError(SandboxError):
    """A `copy_out` operation failed or targeted a path outside the allowed boundary."""
