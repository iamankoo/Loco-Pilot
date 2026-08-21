"""The tool contract every controlled tool implements.

Architecture: Agent -> Tool Call -> Tool Registry -> Validation ->
Permission Boundary -> Tool Implementation -> Result. Agents never touch
the OS directly; they only ever hold a `Tool` reference obtained from the
registry, scoped to a `ToolContext` bound to one workspace.

Input/output are Pydantic models, which is exactly what LangChain's
`StructuredTool` expects — later phases can wrap a `Tool` into a LangChain
tool without changing this contract.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Generic, TypeVar

from pydantic import BaseModel

from tools.workspace import Workspace

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class Permission(str, enum.Enum):
    READ = "read"
    WRITE = "write"
    GIT_WRITE = "git_write"
    EXECUTE = "execute"


class ToolError(Exception):
    """A well-formed tool failure (bad input, permission boundary, OS error).

    Distinct from an unhandled exception: callers treat this as an
    expected, loggable/persistable failure with a clear message, not a bug.

    `code` is an optional, coarse machine-checkable classification (e.g.
    "FILE_NOT_FOUND", "PATH_OUTSIDE_WORKSPACE", "DESTINATION_EXISTS") for
    callers/tests that want to branch on failure kind rather than parse the
    message text — purely additive: every existing `raise ToolError("...")`
    call site is unaffected and `str(exc)` still yields just the message.
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class ToolPermissionError(ToolError):
    """Raised when a caller (an agent) requests a tool outside its granted
    permission set. Structural, not advisory — callers must check this
    before invoking a tool, not rely on the LLM not asking."""


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool execution is scoped to: the workspace it may touch,
    and the execution/agent-step it should be correlated with for logging
    and persistence (both optional — tools are independently testable
    without a live execution)."""

    workspace: Workspace
    execution_id: str | None = None
    agent_step_id: str | None = None


class Tool(ABC, Generic[InputT, OutputT]):
    name: ClassVar[str]
    description: ClassVar[str]
    permission: ClassVar[Permission]
    input_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]

    @abstractmethod
    async def run(self, tool_input: InputT, context: ToolContext) -> OutputT:
        """Execute the tool. Must raise `ToolError` for expected failures."""
        raise NotImplementedError

    @classmethod
    def input_schema(cls) -> dict:
        return cls.input_model.model_json_schema()

    @classmethod
    def output_schema(cls) -> dict:
        return cls.output_model.model_json_schema()
