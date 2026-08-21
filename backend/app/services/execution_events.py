"""Phase 2.12: a deterministic, ordered event stream + execution metrics
for one execution — reconstructed entirely from already-persisted
`AgentStep`/`ToolCall`/`Execution` rows, the same durable data
`execution_detail.py`/`execution_report.py` already read. Not a second
logging/telemetry system: `backend/app/core/logging.py`'s structlog
events remain the live, in-flight log stream; this is the queryable,
per-execution reconstruction of what already happened, for
`GET /api/v1/executions/{id}/events`.

Every event carries only bounded fields already present on its source row
(tool name, duration_ms, a truncated error_message) — never a full
tool-call input/output blob or prompt/response text, so this stays cheap
to compute and safe to expose regardless of execution size.
"""

from __future__ import annotations

from datetime import datetime

from backend.app.core.error_classification import classify_error
from backend.app.db.models.agent_step import AgentStep
from backend.app.db.models.execution import Execution
from backend.app.db.models.tool_call import ToolCall

_TERMINAL_EVENT_BY_STATUS = {
    "passed": "execution_completed",
    "needs_review": "execution_completed",
    "failed": "execution_failed",
    "error": "execution_failed",
    "timed_out": "execution_failed",
    "cancelled": "execution_cancelled",
}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def build_execution_events(
    *, execution: Execution, steps: list[AgentStep], tool_calls: list[ToolCall]
) -> dict:
    events: list[dict] = []
    seq = 0

    def add(event_type: str, timestamp: datetime | None, **data: object) -> None:
        nonlocal seq
        events.append({"seq": seq, "event": event_type, "timestamp": _iso(timestamp), **data})
        seq += 1

    if execution.started_at:
        add("execution_started", execution.started_at, execution_id=str(execution.id))

    tool_calls_by_step: dict = {}
    for tc in tool_calls:
        tool_calls_by_step.setdefault(tc.agent_step_id, []).append(tc)

    for step in steps:
        input_metadata = step.input_metadata or {}
        retry_count = int(input_metadata.get("retry_count") or 0)
        if retry_count > 0:
            add("retry_started", step.started_at, agent=step.agent_name, retry_count=retry_count)

        add(f"{step.agent_name}_started", step.started_at, agent=step.agent_name)

        for tc in sorted(tool_calls_by_step.get(step.id, []), key=lambda t: t.created_at):
            event_type = "tool_call_completed" if tc.status == "success" else "tool_call_failed"
            add(
                event_type,
                tc.created_at,
                agent=step.agent_name,
                tool=tc.tool_name,
                duration_ms=tc.duration_ms,
                error=tc.error_message if tc.status != "success" else None,
            )

        metadata = step.output_metadata or {}
        if step.agent_name == "tester" and (metadata.get("test_results") or {}).get("status") == "failed":
            add("test_failed", step.completed_at or step.started_at, agent=step.agent_name)
        if step.agent_name == "reviewer" and (metadata.get("review_result") or {}).get("verdict") == "changes_required":
            add("review_changes_requested", step.completed_at or step.started_at, agent=step.agent_name)

        if step.status == "failed":
            add(
                f"{step.agent_name}_failed",
                step.completed_at or step.started_at,
                agent=step.agent_name,
                error=step.error_message,
                error_class=classify_error(step.error_message),
            )
        elif step.completed_at is not None:
            add(f"{step.agent_name}_completed", step.completed_at, agent=step.agent_name)

    if execution.completed_at:
        terminal_event = _TERMINAL_EVENT_BY_STATUS.get(execution.status, "execution_completed")
        add(
            terminal_event,
            execution.completed_at,
            execution_id=str(execution.id),
            status=execution.status,
            error_class=classify_error(execution.error_message) if execution.error_message else None,
        )

    events.sort(key=lambda e: (e["timestamp"] or "", e["seq"]))
    # seq is re-assigned after sort so it's a stable, gap-free, deterministic
    # ordinal regardless of the original construction order above.
    for i, event in enumerate(events):
        event["seq"] = i

    return {"events": events, "metrics": _compute_metrics(execution, steps, tool_calls)}


def _compute_metrics(execution: Execution, steps: list[AgentStep], tool_calls: list[ToolCall]) -> dict:
    per_agent_ms: dict[str, int] = {}
    for step in steps:
        if step.started_at and step.completed_at:
            duration_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)
            per_agent_ms[step.agent_name] = per_agent_ms.get(step.agent_name, 0) + duration_ms

    total_duration_seconds = None
    if execution.started_at and execution.completed_at:
        total_duration_seconds = (execution.completed_at - execution.started_at).total_seconds()

    debug_attempt_count = 0
    review_attempt_count = 0
    for step in steps:
        metadata = step.output_metadata or {}
        if step.agent_name == "debugger" and "debug_attempts" in metadata:
            debug_attempt_count = len(metadata["debug_attempts"])
        if step.agent_name == "reviewer" and "review_attempts" in metadata:
            review_attempt_count = len(metadata["review_attempts"])

    return {
        "total_duration_seconds": total_duration_seconds,
        "per_agent_duration_ms": per_agent_ms,
        "tool_call_count": len(tool_calls),
        "tool_call_failures": sum(1 for tc in tool_calls if tc.status != "success"),
        "test_run_count": sum(1 for s in steps if s.agent_name == "tester"),
        "debug_attempt_count": debug_attempt_count,
        "review_attempt_count": review_attempt_count,
    }
