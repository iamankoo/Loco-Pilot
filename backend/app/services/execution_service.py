"""The boundary between FastAPI and LangGraph.

Architecture: API -> Execution Service -> LangGraph -> Agents -> RAG/Tools.
FastAPI routes never instantiate agents or build the graph themselves —
they call into this module, which owns the full lifecycle of one
execution: creating the DB record, building graph dependencies, running
the graph to completion, and persisting the final status.
"""

from __future__ import annotations

import uuid

from agents.graph import GraphDependencies, build_graph
from agents.llm_client import LangChainStructuredLLMClient, StructuredLLMClient
from agents.state import ExecutionState
from backend.app.core.config import get_settings
from backend.app.core.llm.factory import get_llm_provider
from backend.app.core.logging import bind_execution_context, clear_execution_context, get_logger
from backend.app.db.models.execution import Execution, ExecutionStatus
from backend.app.db.models.project import Project
from backend.app.db.repositories.executions import create_execution, get_execution, update_execution_status
from backend.app.db.repositories.projects import get_project
from backend.app.db.session import get_session_factory
from rag.embeddings.factory import get_embedding_provider
from tools.registry import build_default_registry
from tools.workspace import Workspace, WorkspaceError

logger = get_logger(component="execution_service")


class ExecutionServiceError(Exception):
    pass


def _build_llm_client() -> StructuredLLMClient | None:
    try:
        provider = get_llm_provider()
        return LangChainStructuredLLMClient(provider.chat_model())
    except Exception as exc:  # noqa: BLE001 - LLM misconfiguration must not prevent creating the execution record
        logger.warning("llm_provider_unavailable", error=str(exc))
        return None


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


def _map_final_status(state: ExecutionState) -> ExecutionStatus:
    if state.execution_status == "error":
        return ExecutionStatus.ERROR
    if state.review_result is None:
        return ExecutionStatus.NEEDS_REVIEW
    if state.review_result.verdict == "approved":
        return ExecutionStatus.PASSED
    return ExecutionStatus.NEEDS_REVIEW


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

            await update_execution_status(db, execution_id, status=ExecutionStatus.RUNNING, mark_started=True)

            settings = get_settings()
            deps = GraphDependencies(
                registry=build_default_registry(),
                llm_client=_build_llm_client(),
                embedding_provider=get_embedding_provider(),
                db=db,
                max_debug_retries=settings.max_debug_retries,
            )
            graph = build_graph(deps)

            initial_state = ExecutionState(
                execution_id=str(execution_id),
                project_id=str(project.id),
                user_task=execution.task,
                workspace_root=str(workspace.root),
            )

            try:
                final_state_dict = await graph.ainvoke(initial_state, config={"recursion_limit": 50})
                final_state = ExecutionState.model_validate(final_state_dict)
            except Exception as exc:  # noqa: BLE001 - a hard graph failure must still leave a clean execution record
                logger.exception("graph_execution_failed")
                await update_execution_status(
                    db, execution_id, status=ExecutionStatus.ERROR, error_message=str(exc), mark_completed=True
                )
                return

            status = _map_final_status(final_state)
            error_message = final_state.errors[-1] if status == ExecutionStatus.ERROR and final_state.errors else None
            await update_execution_status(
                db, execution_id, status=status, error_message=error_message, mark_completed=True
            )
    finally:
        clear_execution_context()
