"""Reconstructs a rich execution summary from already-persisted data —
no new columns, no migration.

Every agent turn already writes its return dict (scrubbed) into
`AgentStep.output_metadata` (see `agents.graph.make_agent_node`), which
includes exactly the same `messages`/`plan`/`files_changed`/
`test_results`/`review_result` fields the LangGraph state carries. This
module is the read-side counterpart: it walks the persisted steps for one
execution and derives the same picture the graph had at the end of the
run, entirely from durable data.

`current_agent` is deliberately computed here rather than read from
`Execution.current_agent` — that column exists but nothing in the
execution pipeline populates it (a pre-existing gap, not something this
module should silently paper over by writing to it); a step with no
`completed_at` is the live "what's running right now" signal, and steps
are ordered so the last one is always what a completed run finished on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from backend.app.db.models.agent_step import AgentStep


@dataclass
class ExecutionSynthesis:
    current_agent: str | None = None
    retry_count: int = 0
    plan: dict | None = None
    files_changed: list[dict] = field(default_factory=list)
    test_results: dict | None = None
    review_result: dict | None = None
    step_errors: list[str] = field(default_factory=list)


def synthesize_execution_detail(steps: list[AgentStep]) -> ExecutionSynthesis:
    synthesis = ExecutionSynthesis()
    if not steps:
        return synthesis

    for step in steps:
        metadata = step.output_metadata or {}

        if step.agent_name == "planner" and "plan" in metadata:
            synthesis.plan = metadata["plan"]
        if step.agent_name == "developer" and metadata.get("files_changed"):
            synthesis.files_changed.extend(metadata["files_changed"])
        if step.agent_name == "tester" and "test_results" in metadata:
            synthesis.test_results = metadata["test_results"]
        if step.agent_name == "reviewer" and "review_result" in metadata:
            synthesis.review_result = metadata["review_result"]
        if step.status == "failed" and step.error_message:
            synthesis.step_errors.append(f"{step.agent_name}: {step.error_message}")

    in_progress = next((s for s in steps if s.completed_at is None), None)
    synthesis.current_agent = in_progress.agent_name if in_progress else steps[-1].agent_name

    last_input = steps[-1].input_metadata or {}
    synthesis.retry_count = int(last_input.get("retry_count") or 0)

    return synthesis


def elapsed_seconds(started_at: datetime | None, completed_at: datetime | None) -> float | None:
    if started_at is None:
        return None
    end = completed_at or datetime.now(started_at.tzinfo)
    return max(0.0, (end - started_at).total_seconds())
