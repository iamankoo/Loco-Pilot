"""The boundary between FastAPI and LangGraph.

Architecture: API -> Execution Service -> LangGraph -> Agents -> RAG/Tools.
FastAPI routes never instantiate agents or build the graph themselves —
they call into this module, which owns the full lifecycle of one
execution: creating the DB record, building graph dependencies, running
the graph to completion (bounded by `MAX_EXECUTION_SECONDS`), and
persisting the final status.
"""

from __future__ import annotations

import asyncio
import uuid

from langgraph.errors import GraphRecursionError

from agents.graph import GraphDependencies, build_graph
from agents.llm_client import LangChainStructuredLLMClient, StructuredLLMClient, UnavailableLLMClient
from agents.state import ExecutionState, compute_honest_status
from backend.app.core.config import get_settings
from backend.app.core.llm.factory import get_llm_provider
from backend.app.core.logging import bind_execution_context, clear_execution_context, get_logger
from backend.app.db.models.execution import Execution, ExecutionStatus
from backend.app.db.models.project import Project
from backend.app.db.repositories.executions import create_execution, get_execution, update_execution_status
from backend.app.db.repositories.projects import get_project
from backend.app.db.session import get_session_factory
from backend.app.services.cancellation import clear_cancellation, request_cancellation
from backend.app.services.execution_locks import get_project_execution_lock
from backend.app.services.execution_workspace import (
    create_execution_workspace,
    mark_execution_workspace_status,
)
from rag.embeddings.factory import get_embedding_provider
from tools.registry import build_default_registry
from tools.workspace import Workspace, WorkspaceError

logger = get_logger(component="execution_service")


class ExecutionServiceError(Exception):
    pass


def _build_llm_client(model: str | None = None) -> StructuredLLMClient:
    """Never fails: a broken/misconfigured provider must not prevent
    creating the execution record. Instead of collapsing every failure
    into a generic "no client configured" message, the real reason
    (missing key, wrong model, provider/account not authorized, ...) is
    captured and surfaced verbatim the first time an agent actually
    tries to use the LLM. `model` overrides only the model name for
    role-based routing (PLANNER_MODEL/DEVELOPER_MODEL/DEBUGGER_MODEL/
    REVIEWER_MODEL) — the provider/base_url/api_key stay whatever LLM_*
    already configures."""
    try:
        provider = get_llm_provider(model=model)
        return LangChainStructuredLLMClient(provider.chat_model())
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_provider_unavailable", model=model, error=str(exc))
        return UnavailableLLMClient(str(exc))


async def create_and_run_execution(db, *, project_id: uuid.UUID, task: str) -> Execution:
    """Creates the Execution record. Does not run the graph itself — the
    caller (the API route) schedules `run_execution` as a background task
    so the HTTP request returns immediately with the created record."""
    project = await get_project(db, project_id)
    if project is None:
        raise ExecutionServiceError(f"Project not found: {project_id}")
    if not project.workspace_path:
        raise ExecutionServiceError(f"Project {project_id} has no workspace_path configured.")

    try:
        Workspace.at(project.workspace_path)
    except WorkspaceError as exc:
        raise ExecutionServiceError(f"Invalid workspace_path for project {project_id}: {exc}") from exc

    return await create_execution(db, project_id=project_id, task=task)


def cancel_execution(execution_id: uuid.UUID) -> None:
    """Requests cancellation of a running execution — checked between graph
    node transitions (see `agents.graph.make_agent_node`), not mid-tool-call."""
    request_cancellation(execution_id)


_HONEST_STATUS_TO_DB_STATUS: dict[str, ExecutionStatus] = {
    "cancelled": ExecutionStatus.CANCELLED,
    "timed_out": ExecutionStatus.TIMED_OUT,
    "error": ExecutionStatus.ERROR,
    "failed": ExecutionStatus.ERROR,
    "passed": ExecutionStatus.PASSED,
    "needs_review": ExecutionStatus.NEEDS_REVIEW,
}


def _map_final_status(state: ExecutionState) -> ExecutionStatus:
    """Delegates to `agents.state.compute_honest_status` — the same
    function the graph's own finalize node uses — so the graph-level and
    DB-persisted final status can never disagree with each other."""
    return _HONEST_STATUS_TO_DB_STATUS.get(compute_honest_status(state), ExecutionStatus.NEEDS_REVIEW)


async def run_execution(execution_id: uuid.UUID) -> None:
    """Runs one execution's full graph to completion.

    Opens its own DB session (this typically runs as a FastAPI background
    task, after the request's own session has already closed) and
    persists status transitions as the run progresses.
    """
    bind_execution_context(execution_id=str(execution_id))
    session_factory = get_session_factory()

    try:
        async with session_factory() as db:
            execution = await get_execution(db, execution_id)
            if execution is None:
                logger.error("execution_not_found")
                return

            project: Project | None = await get_project(db, execution.project_id)
            if project is None or not project.workspace_path:
                await update_execution_status(
                    db,
                    execution_id,
                    status=ExecutionStatus.ERROR,
                    error_message="Project or workspace_path missing.",
                    mark_completed=True,
                )
                return

            try:
                workspace = Workspace.at(project.workspace_path)
            except WorkspaceError as exc:
                await update_execution_status(
                    db, execution_id, status=ExecutionStatus.ERROR, error_message=str(exc), mark_completed=True
                )
                return

            # Phase 2.10: a per-execution, traceable workspace directory
            # (independent of the project's own shared files — see
            # execution_workspace.py) plus a per-project lock, so a second
            # execution against this same project can never race this
            # one's tool calls on the shared workspace. Two different
            # projects are never serialized against each other.
            create_execution_workspace(str(execution_id), project_id=str(project.id))
            async with get_project_execution_lock(project.id):
                mark_execution_workspace_status(str(execution_id), "active")
                await update_execution_status(db, execution_id, status=ExecutionStatus.RUNNING, mark_started=True)

                settings = get_settings()
                deps = GraphDependencies(
                    registry=build_default_registry(),
                    llm_client=_build_llm_client(),
                    embedding_provider=get_embedding_provider(),
                    db=db,
                    planner_llm_client=_build_llm_client(settings.planner_model) if settings.planner_model else None,
                    developer_llm_client=_build_llm_client(settings.developer_model) if settings.developer_model else None,
                    debugger_llm_client=_build_llm_client(settings.debugger_model) if settings.debugger_model else None,
                    reviewer_llm_client=_build_llm_client(settings.reviewer_model) if settings.reviewer_model else None,
                    max_debug_retries=settings.max_debug_retries,
                    max_review_retries=settings.max_review_retries,
                    max_tool_calls_per_agent=settings.max_tool_calls_per_agent,
                    max_total_tool_calls=settings.max_total_tool_calls,
                    max_context_chars=settings.max_context_chars,
                    max_agent_turns=settings.max_agent_turns,
                    workspace_scan_max_files=settings.workspace_scan_max_files,
                    workspace_scan_max_depth=settings.workspace_scan_max_depth,
                )
                graph = build_graph(deps)

                initial_state = ExecutionState(
                    execution_id=str(execution_id),
                    project_id=str(project.id),
                    user_task=execution.task,
                    workspace_root=str(workspace.root),
                )

                try:
                    final_state_dict = await asyncio.wait_for(
                        graph.ainvoke(initial_state, config={"recursion_limit": settings.max_agent_turns}),
                        timeout=settings.max_execution_seconds,
                    )
                    final_state = ExecutionState.model_validate(final_state_dict)
                except asyncio.TimeoutError:
                    logger.warning("execution_timed_out", timeout_seconds=settings.max_execution_seconds)
                    mark_execution_workspace_status(str(execution_id), "failed")
                    await update_execution_status(
                        db,
                        execution_id,
                        status=ExecutionStatus.TIMED_OUT,
                        error_message=f"Execution exceeded the {settings.max_execution_seconds}s time limit.",
                        mark_completed=True,
                    )
                    return
                except GraphRecursionError:
                    # The outer safety net beneath MAX_DEBUG_RETRIES: should not
                    # normally trigger (retry-budget routing already terminates
                    # the debug loop deterministically), but a routing bug or an
                    # unexpected state must still end in an honest, bounded
                    # failure rather than genuinely running away.
                    logger.warning("execution_exceeded_max_agent_turns", max_agent_turns=settings.max_agent_turns)
                    mark_execution_workspace_status(str(execution_id), "failed")
                    await update_execution_status(
                        db,
                        execution_id,
                        status=ExecutionStatus.ERROR,
                        error_message=f"Execution exceeded the maximum of {settings.max_agent_turns} agent turns.",
                        mark_completed=True,
                    )
                    return
                except Exception as exc:  # noqa: BLE001 - a hard graph failure must still leave a clean execution record
                    logger.exception("graph_execution_failed")
                    mark_execution_workspace_status(str(execution_id), "failed")
                    await update_execution_status(
                        db, execution_id, status=ExecutionStatus.ERROR, error_message=str(exc), mark_completed=True
                    )
                    return

                status = _map_final_status(final_state)
                error_message = final_state.errors[-1] if status == ExecutionStatus.ERROR and final_state.errors else None
                mark_execution_workspace_status(
                    str(execution_id),
                    "cancelled" if status == ExecutionStatus.CANCELLED else
                    "failed" if status in (ExecutionStatus.ERROR, ExecutionStatus.TIMED_OUT) else
                    "completed",
                )
                await update_execution_status(
                    db, execution_id, status=status, error_message=error_message, mark_completed=True
                )
    finally:
        clear_cancellation(execution_id)
        clear_execution_context()
