"""The base agent contract.

Deliberately has no SQLAlchemy import anywhere in this module or any
concrete agent: persistence and DB session lifecycle live in the graph
node wrapper (`agents.graph`), which constructs a `ToolRunner` bound to a
DB session and passes it in here. Agents only ever see the two protocols
below, which keeps every agent trivially unit-testable in isolation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from agents.llm_client import StructuredLLMClient
from agents.state import ExecutionState
from tools.execution_result import ToolExecutionResult

DEFAULT_MAX_TOOL_CALLS = 12


class ToolRunner(Protocol):
    async def call(self, tool_name: str, tool_input: dict) -> ToolExecutionResult: ...

    def available_tools(self) -> set[str]:
        """Names of tools this agent is actually permitted to call — lets an
        agent honestly detect whether a capability (e.g. test execution)
        exists yet, instead of assuming or fabricating."""
        ...

    def tool_schemas(self) -> list[dict]:
        """OpenAI-function-calling-format schemas for this agent's actually
        permitted tools — what `generate_with_tools` binds to the model.
        Never includes a tool outside the agent's granted permission set."""
        ...


class BaseAgent(ABC):
    name: str

    def __init__(
        self,
        *,
        llm_client: StructuredLLMClient | None,
        tools: ToolRunner,
        max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    ) -> None:
        self.llm_client = llm_client
        self.tools = tools
        self.max_tool_calls = max_tool_calls

    @abstractmethod
    async def run(self, state: ExecutionState) -> dict:
        """Execute this agent's turn and return a partial state update."""
        raise NotImplementedError
