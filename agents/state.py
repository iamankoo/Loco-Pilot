"""The LangGraph state schema.

A typed Pydantic model, not a bare dict — every node reads/writes named,
validated fields. List fields use `Annotated[..., operator.add]` so nodes
append their own new items (a tool call, an error, a trace message) and
LangGraph concatenates them across the run, rather than every node needing
the full accumulated history just to add one entry.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from agents.schemas import DebugResult, FileChange, Plan, ReviewResult, TestResult
from rag.retrieval.context_builder import RepositoryContext

ExecutionStatusLiteral = Literal[
    "pending",
    "planning",
    "developing",
    "testing",
    "debugging",
    "reviewing",
    "passed",
    "failed",
    "error",
    "cancelled",
    "timed_out",
]


class ToolCallRecord(BaseModel):
    tool_name: str
    status: Literal["success", "error"]
    duration_ms: int
    summary: str | None = None


class ExecutionState(BaseModel):
    execution_id: str
    project_id: str
    user_task: str
    workspace_root: str

    repository_context: RepositoryContext | None = None
    plan: Plan | None = None
    current_agent: str | None = None

    messages: Annotated[list[str], operator.add] = Field(default_factory=list)
    tool_calls: Annotated[list[ToolCallRecord], operator.add] = Field(default_factory=list)
    files_changed: Annotated[list[FileChange], operator.add] = Field(default_factory=list)
    errors: Annotated[list[str], operator.add] = Field(default_factory=list)

    test_results: TestResult | None = None
    retry_count: int = 0
    review_result: ReviewResult | None = None
    final_result: dict | None = None
    execution_status: ExecutionStatusLiteral = "pending"
