"""Builds the LangGraph state machine wiring Orchestrator -> Planner ->
Developer -> Tester -> (Debugger loop | Reviewer) -> finalize.

Each agent node is a thin persistence wrapper (`make_agent_node`) around a
`BaseAgent` subclass: it creates an `AgentStep` row, builds a
permission-scoped `BoundToolRunner` for that agent, runs it, and records
success/failure — the actual reasoning lives in `agents.<role>`, not here.
This file owns every SQLAlchemy-touching concern in the agent pipeline;
individual agents never see a DB session (see `agents.base`). It also owns
the bounded-autonomy machinery Phase 1.5 adds: per-agent and
execution-wide tool-call budgets, cancellation checks between node
transitions, stage-specific RAG re-retrieval, and incremental
re-indexing of files Developer actually changed.
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
from backend.app.security.secret_scrubber import scrub_secrets
from backend.app.services.artifact_service import collect_artifacts
from backend.app.services.cancellation import is_cancelled
from backend.app.services.tool_execution import BoundToolRunner
from rag.embeddings.base import EmbeddingProvider
from rag.ingestion.indexer import RepositoryIndexer
from rag.retrieval.context_builder import build_context
from rag.retrieval.retriever import Retriever
from tools.base import Permission, ToolContext
from tools.registry import ToolRegistry
from tools.workspace import Workspace

logger = get_logger(component="graph")

# Debugger is granted WRITE at the permission-table level (see
# agents/permissions.py) but this implementation only ever investigates —
# its tool-calling loop is scoped to these read-only tool names.
_DEBUGGER_TOOL_NAMES = {"read_file", "search_files", "list_directory", "git_status", "git_diff"}

# Which agent roles benefit from a stage-specific RAG re-retrieval beyond
# the Orchestrator's initial task-based retrieval (Planner already
# consumes that one).
_TOOL_LOOP_AGENTS = {"developer", "debugger"}


@dataclass
class GraphDependencies:
    registry: ToolRegistry
    llm_client: StructuredLLMClient | None
    embedding_provider: EmbeddingProvider
    db: AsyncSession | None = None
    max_debug_retries: int = 2
    retrieval_top_k: int = 8
    max_tool_calls_per_agent: int = 12
    max_total_tool_calls: int = 60
    max_context_chars: int = 12_000
    # LangGraph's own `recursion_limit` — passed by the caller (see
    # `backend.app.services.execution_service.run_execution`) to
    # `graph.ainvoke(..., config={"recursion_limit": deps.max_agent_turns})`.
    # Not read by anything in this module; kept alongside the other bounded-
    # autonomy settings so one `GraphDependencies` instance fully describes
    # an execution's limits.
    max_agent_turns: int = 50


def _summarize(value: object) -> object:
    if isinstance(value, PydanticBaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_summarize(v) for v in value[:20]]
    if isinstance(value, str):
        return value[:2000]
    return value


def _build_tool_runner(
    state: ExecutionState,
    deps: GraphDependencies,
    permissions: set[Permission],
    agent_step_id: str | None,
    *,
    allowed_tool_names: set[str] | None = None,
) -> BoundToolRunner:
    workspace = Workspace.at(state.workspace_root)
    context = ToolContext(workspace=workspace, execution_id=state.execution_id, agent_step_id=agent_step_id)
    return BoundToolRunner(
        registry=deps.registry,
        context=context,
        permissions=permissions,
        db=deps.db,
        allowed_tool_names=allowed_tool_names,
    )


def _retrieval_query_for(agent_name: str, state: ExecutionState) -> str | None:
    """Query construction changes per agent stage: Developer retrieves
    against the task + plan steps it's about to implement; Debugger
    retrieves against the task + the actual failure it needs to diagnose.
    Planner already receives the Orchestrator's initial task-based
    retrieval, so it isn't repeated here."""
    if agent_name == "developer" and state.plan is not None:
        return f"{state.user_task}\n" + "\n".join(state.plan.steps)
    if agent_name == "debugger" and state.test_results is not None:
        return f"{state.user_task}\n{state.test_results.summary}\n" + "\n".join(state.test_results.errors)
    return None


async def _retrieve_stage_context(agent_name: str, state: ExecutionState, deps: GraphDependencies):
    query = _retrieval_query_for(agent_name, state)
    if query is None or deps.db is None:
        return None
    try:
        retriever = Retriever(deps.embedding_provider)
        chunks = await retriever.retrieve(
            query, project_id=uuid.UUID(state.project_id), db=deps.db, top_k=deps.retrieval_top_k
        )
        return build_context(chunks, max_chars=deps.max_context_chars)
    except Exception as exc:  # noqa: BLE001 - retrieval failure must not abort the agent turn
        logger.warning("stage_retrieval_failed", agent=agent_name, error=str(exc))
        return None


async def _reindex_changed_files(state: ExecutionState, update: dict, deps: GraphDependencies) -> None:
    if deps.db is None:
        return
    files_changed = update.get("files_changed") or []
    changed_paths = [f.path for f in files_changed if f.change_type in ("created", "modified")]
    if not changed_paths:
        return
    try:
        workspace = Workspace.at(state.workspace_root)
        indexer = RepositoryIndexer(deps.embedding_provider)
        for path in changed_paths:
            await indexer.index_file(workspace, uuid.UUID(state.project_id), path, deps.db)
        logger.info("incremental_reindex_completed", files=len(changed_paths))
    except Exception as exc:  # noqa: BLE001 - a reindex failure must not fail the agent turn that just succeeded
        logger.warning("incremental_reindex_failed", error=str(exc))


def make_agent_node(
    agent_cls: type[BaseAgent], permissions: set[Permission], deps: GraphDependencies
) -> Callable[[ExecutionState], "object"]:
    allowed_tool_names = _DEBUGGER_TOOL_NAMES if agent_cls.name == "debugger" else None

    async def node(state: ExecutionState) -> dict:
        bind_execution_context(execution_id=state.execution_id, agent=agent_cls.name)
        logger.info(
            "agent_turn_started",
            previous_agent=state.current_agent,
            next_agent=agent_cls.name,
            retry_count=state.retry_count,
        )

        if is_cancelled(uuid.UUID(state.execution_id)):
            logger.info("agent_turn_skipped", next_agent=agent_cls.name, reason="cancellation_requested")
            return {
                "current_agent": agent_cls.name,
                "execution_status": "cancelled",
                "messages": ["Execution cancelled before " + agent_cls.name + " started."],
            }

        step = None
        if deps.db is not None:
            step = await create_agent_step(
                deps.db,
                execution_id=uuid.UUID(state.execution_id),
                agent_name=agent_cls.name,
                input_metadata={"execution_status": state.execution_status, "retry_count": state.retry_count},
            )

        run_state = state
        if agent_cls.name in _TOOL_LOOP_AGENTS:
            fresh_context = await _retrieve_stage_context(agent_cls.name, state, deps)
            if fresh_context is not None:
                run_state = state.model_copy(update={"repository_context": fresh_context})

        tools = _build_tool_runner(
            state, deps, permissions, str(step.id) if step else None, allowed_tool_names=allowed_tool_names
        )

        remaining_total = max(0, deps.max_total_tool_calls - len(state.tool_calls))
        max_tool_calls = min(deps.max_tool_calls_per_agent, remaining_total)
        agent = agent_cls(llm_client=deps.llm_client, tools=tools, max_tool_calls=max_tool_calls)

        try:
            update = await agent.run(run_state)
        except Exception as exc:  # noqa: BLE001 - agent failures become structured state, never crash the graph
            logger.exception("agent_turn_failed", next_agent=agent_cls.name, retry_count=state.retry_count)
            if step is not None:
                await complete_agent_step(
                    deps.db, step.id, status=AgentStepStatus.FAILED, error_message=scrub_secrets(str(exc))
                )
            return {
                "current_agent": agent_cls.name,
                "execution_status": "error",
                "errors": [f"{agent_cls.name}: {exc}"],
                "messages": [f"{agent_cls.name}: failed — {exc}"],
            }

        if agent_cls.name == "developer":
            await _reindex_changed_files(state, update, deps)

        if run_state is not state and "repository_context" not in update:
            update["repository_context"] = run_state.repository_context

        if step is not None:
            output_summary = scrub_secrets({k: _summarize(v) for k, v in update.items()})
            await complete_agent_step(deps.db, step.id, status=AgentStepStatus.SUCCEEDED, output_metadata=output_summary)

        logger.info(
            "agent_turn_completed",
            next_agent=agent_cls.name,
            retry_count=update.get("retry_count", state.retry_count),
            status=update.get("execution_status", state.execution_status),
        )
        return update

    return node


def make_orchestrator_node(deps: GraphDependencies) -> Callable[[ExecutionState], "object"]:
    async def node(state: ExecutionState) -> dict:
        bind_execution_context(execution_id=state.execution_id, agent="orchestrator")

        if is_cancelled(uuid.UUID(state.execution_id)):
            logger.info("agent_turn_skipped", next_agent="orchestrator", reason="cancellation_requested")
            return {
                "current_agent": "orchestrator",
                "execution_status": "cancelled",
                "messages": ["Execution cancelled before orchestrator started."],
            }

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
                repository_context = build_context(chunks, max_chars=deps.max_context_chars)
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
        if final_status not in ("passed", "failed", "error", "cancelled", "timed_out"):
            final_status = "failed"

        artifact_count = 0
        if (
            deps.db is not None
            and state.plan is not None
            and state.plan.expected_artifact_glob
            and final_status == "passed"
        ):
            try:
                workspace = Workspace.at(state.workspace_root)
                artifacts = await collect_artifacts(
                    workspace, state.plan.expected_artifact_glob, uuid.UUID(state.execution_id), deps.db
                )
                artifact_count = len(artifacts)
            except Exception as exc:  # noqa: BLE001 - artifact collection must not fail a finished execution
                logger.warning("artifact_collection_failed", error=str(exc))

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
            "tool_call_count": len(state.tool_calls),
            "artifact_count": artifact_count,
        }

        return {"final_result": final_result, "current_agent": "orchestrator", "execution_status": final_status}

    return node


def route_after_planner(state: ExecutionState) -> str:
    return "finalize" if state.execution_status in ("error", "cancelled") else "developer"


def route_after_developer(state: ExecutionState) -> str:
    return "finalize" if state.execution_status in ("error", "cancelled") else "tester"


def route_after_tester(state: ExecutionState, max_retries: int) -> str:
    if state.execution_status in ("error", "cancelled"):
        return "finalize"
    if (
        state.test_results is not None
        and state.test_results.status in ("failed", "error")
        and state.retry_count < max_retries
    ):
        return "debugger"
    return "reviewer"


def route_after_debugger(state: ExecutionState) -> str:
    return "finalize" if state.execution_status in ("error", "cancelled") else "developer"


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
