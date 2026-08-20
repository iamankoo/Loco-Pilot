"""Builds the LangGraph state machine wiring Orchestrator -> Planner ->
Developer -> Tester -> (Debugger loop | Reviewer) -> finalize.

Each agent node is a thin persistence wrapper (`make_agent_node`) around a
`BaseAgent` subclass: it creates an `AgentStep` row, builds a
permission-scoped `BoundToolRunner` for that agent, runs it, and records
success/failure — the actual reasoning lives in `agents.<role>`, not here.
This file owns every SQLAlchemy-touching concern in the agent pipeline;
individual agents never see a DB session (see `agents.base`).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base import BaseAgent
from agents.debugger import DebuggerAgent
from agents.developer import DeveloperAgent
from agents.llm_client import StructuredLLMClient
from agents.permissions import (
    DEBUGGER_PERMISSIONS,
    DEVELOPER_PERMISSIONS,
    PLANNER_PERMISSIONS,
    REVIEWER_PERMISSIONS,
    TESTER_PERMISSIONS,
)
from agents.planner import PlannerAgent
from agents.reviewer import ReviewerAgent
from agents.state import ExecutionState
from agents.tester import TesterAgent
from backend.app.core.logging import bind_execution_context, get_logger
from backend.app.db.models.agent_step import AgentStepStatus
from backend.app.db.repositories.agent_steps import complete_agent_step, create_agent_step
from backend.app.services.tool_execution import BoundToolRunner
from rag.embeddings.base import EmbeddingProvider
from rag.retrieval.context_builder import build_context
from rag.retrieval.retriever import Retriever
from tools.base import Permission, ToolContext
from tools.registry import ToolRegistry
from tools.workspace import Workspace

logger = get_logger(component="graph")


@dataclass
class GraphDependencies:
    registry: ToolRegistry
    llm_client: StructuredLLMClient | None
    embedding_provider: EmbeddingProvider
    db: AsyncSession | None = None
    max_debug_retries: int = 2
    retrieval_top_k: int = 8


def _summarize(value: object) -> object:
    if isinstance(value, PydanticBaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_summarize(v) for v in value[:20]]
    if isinstance(value, str):
        return value[:2000]
    return value


def _build_tool_runner(
    state: ExecutionState, deps: GraphDependencies, permissions: set[Permission], agent_step_id: str | None
) -> BoundToolRunner:
    workspace = Workspace.at(state.workspace_root)
    context = ToolContext(workspace=workspace, execution_id=state.execution_id, agent_step_id=agent_step_id)
    return BoundToolRunner(registry=deps.registry, context=context, permissions=permissions, db=deps.db)


def make_agent_node(
    agent_cls: type[BaseAgent], permissions: set[Permission], deps: GraphDependencies
) -> Callable[[ExecutionState], "object"]:
    async def node(state: ExecutionState) -> dict:
        bind_execution_context(execution_id=state.execution_id, agent=agent_cls.name)

        step = None
        if deps.db is not None:
            step = await create_agent_step(
                deps.db,
                execution_id=uuid.UUID(state.execution_id),
                agent_name=agent_cls.name,
                input_metadata={"execution_status": state.execution_status, "retry_count": state.retry_count},
            )

        tools = _build_tool_runner(state, deps, permissions, str(step.id) if step else None)
        agent = agent_cls(llm_client=deps.llm_client, tools=tools)

        try:
            update = await agent.run(state)
        except Exception as exc:  # noqa: BLE001 - agent failures become structured state, never crash the graph
            logger.exception("agent_failed", agent=agent_cls.name)
            if step is not None:
                await complete_agent_step(deps.db, step.id, status=AgentStepStatus.FAILED, error_message=str(exc))
            return {
                "current_agent": agent_cls.name,
                "execution_status": "error",
                "errors": [f"{agent_cls.name}: {exc}"],
                "messages": [f"{agent_cls.name}: failed — {exc}"],
            }

        if step is not None:
            output_summary = {k: _summarize(v) for k, v in update.items()}
            await complete_agent_step(deps.db, step.id, status=AgentStepStatus.SUCCEEDED, output_metadata=output_summary)

        return update

    return node


def make_orchestrator_node(deps: GraphDependencies) -> Callable[[ExecutionState], "object"]:
    async def node(state: ExecutionState) -> dict:
        bind_execution_context(execution_id=state.execution_id, agent="orchestrator")

        repository_context = None
        if deps.db is not None:
            try:
                retriever = Retriever(deps.embedding_provider)
                chunks = await retriever.retrieve(
                    state.user_task,
                    project_id=uuid.UUID(state.project_id),
                    db=deps.db,
                    top_k=deps.retrieval_top_k,
                )
                repository_context = build_context(chunks)
            except Exception as exc:  # noqa: BLE001 - retrieval failure must not abort the whole execution
                logger.warning("retrieval_failed", error=str(exc))

        trace = "Orchestrator: execution initialized"
        trace += (
            f", retrieved {len(repository_context.chunks)} context chunk(s)."
            if repository_context is not None
            else "; no repository context retrieved."
        )

        return {
            "repository_context": repository_context,
            "current_agent": "orchestrator",
            "execution_status": "planning",
            "messages": [trace],
        }

    return node


def make_finalize_node(deps: GraphDependencies) -> Callable[[ExecutionState], "object"]:
    async def node(state: ExecutionState) -> dict:
        final_status = state.execution_status
        if final_status not in ("passed", "failed", "error"):
            final_status = "failed"

        final_result = {
            "status": final_status,
            "summary": (
                state.review_result.summary
                if state.review_result
                else (state.errors[-1] if state.errors else "Execution ended without a completed review.")
            ),
            "files_changed": [f.model_dump(mode="json") for f in state.files_changed],
            "test_status": state.test_results.status if state.test_results else "unavailable",
            "retry_count": state.retry_count,
        }

        return {"final_result": final_result, "current_agent": "orchestrator", "execution_status": final_status}

    return node


def route_after_planner(state: ExecutionState) -> str:
    return "finalize" if state.execution_status == "error" else "developer"


def route_after_developer(state: ExecutionState) -> str:
    return "finalize" if state.execution_status == "error" else "tester"


def route_after_tester(state: ExecutionState, max_retries: int) -> str:
    if state.execution_status == "error":
        return "finalize"
    if (
        state.test_results is not None
        and state.test_results.status in ("failed", "error")
        and state.retry_count < max_retries
    ):
        return "debugger"
    return "reviewer"


def route_after_debugger(state: ExecutionState) -> str:
    return "finalize" if state.execution_status == "error" else "developer"


def build_graph(deps: GraphDependencies):
    graph = StateGraph(ExecutionState)

    graph.add_node("orchestrator", make_orchestrator_node(deps))
    graph.add_node("planner", make_agent_node(PlannerAgent, PLANNER_PERMISSIONS, deps))
    graph.add_node("developer", make_agent_node(DeveloperAgent, DEVELOPER_PERMISSIONS, deps))
    graph.add_node("tester", make_agent_node(TesterAgent, TESTER_PERMISSIONS, deps))
    graph.add_node("debugger", make_agent_node(DebuggerAgent, DEBUGGER_PERMISSIONS, deps))
    graph.add_node("reviewer", make_agent_node(ReviewerAgent, REVIEWER_PERMISSIONS, deps))
    graph.add_node("finalize", make_finalize_node(deps))

    graph.add_edge(START, "orchestrator")
    graph.add_edge("orchestrator", "planner")
    graph.add_conditional_edges("planner", route_after_planner, {"developer": "developer", "finalize": "finalize"})
    graph.add_conditional_edges("developer", route_after_developer, {"tester": "tester", "finalize": "finalize"})
    graph.add_conditional_edges(
        "tester",
        lambda state: route_after_tester(state, deps.max_debug_retries),
        {"debugger": "debugger", "reviewer": "reviewer", "finalize": "finalize"},
    )
    graph.add_conditional_edges("debugger", route_after_debugger, {"developer": "developer", "finalize": "finalize"})
    graph.add_edge("reviewer", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()
