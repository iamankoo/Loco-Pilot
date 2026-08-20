"""The terminal execution contract.

Phase 1.2 defines this contract and a restricted local executor for
internal dev/test use only — it is NOT registered in the tool registry and
NOT reachable by an agent. Phase 1.3 implements this same contract with a
Docker sandbox:

    Agent -> Terminal Tool -> Execution Policy -> Docker Sandbox -> Command

`command` is always argv (a list of strings), never a shell string, so
there is no shell to inject into.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExecutionPolicy(BaseModel):
    """Constraints a terminal executor must enforce, regardless of backend."""

    allow_network: bool = False
    max_timeout_seconds: int = 60
    max_output_bytes: int = 500_000


class TerminalCommandRequest(BaseModel):
    command: list[str] = Field(min_length=1)
    working_directory: str = "."
    timeout_seconds: int = Field(default=30, gt=0)
    max_output_bytes: int = Field(default=200_000, gt=0)


class TerminalCommandResult(BaseModel):
    command: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int
    timed_out: bool
