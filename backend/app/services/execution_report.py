"""Phase 2.11: an evidence-based engineering report for one execution.

Everything here is reconstructed from already-persisted data — the same
`AgentStep.output_metadata` `execution_detail.py` already reads (no new
table, no migration) — plus the `Execution`/`Artifact` rows and, when the
project's workspace still exists, a live, read-only Git status snapshot.
Nothing here is generated from an LLM's own claim of what happened; a field
is only ever set to a value that has real persisted (or live, deterministic)
evidence behind it, and is left `None`/empty rather than guessed otherwise.

Deliberately not a live `git diff`: by the time a report is requested, the
shared project workspace (see `execution_workspace.py`'s docstring on why
it isn't duplicated per execution) may already have moved on past this
execution's own changes — a "historical diff" reconstructed after the fact
could misattribute someone else's later edit to this run. `files_changed`
(from Developer's own real tool-call results, Phase 2.9's authoritative
record) is what this report treats as the true account of what changed;
a live, current diff remains available separately via the `git_diff` tool/
`GitStatusTool`, scoped to whatever the workspace looks like *right now*.
"""

from __future__ import annotations

from backend.app.db.models.agent_step import AgentStep
from backend.app.db.models.artifact import Artifact
from backend.app.db.models.execution import Execution
from backend.app.db.models.project import Project
from backend.app.services.execution_detail import elapsed_seconds, synthesize_execution_detail
from tools.workspace import Workspace, WorkspaceError


def _last_metadata_for_agent(steps: list[AgentStep], agent_name: str, key: str) -> list | None:
    """The last step for `agent_name` already carries the FULL accumulated
    history for `key` (state fields like `debug_attempts`/`review_attempts`
    are appended-to, never replaced) — so only the last one is read, never
    concatenated across steps, which would double-count history a later
    step already includes in full."""
    for step in reversed(steps):
        if step.agent_name == agent_name:
            metadata = step.output_metadata or {}
            if key in metadata:
                return metadata[key]
    return None


def _changes_summary(files_changed: list[dict]) -> dict:
    by_type: dict[str, list[str]] = {"created": [], "modified": [], "deleted": [], "renamed": [], "failed": []}
    for change in files_changed:
        change_type = change.get("change_type")
        if change_type in by_type:
            by_type[change_type].append(change.get("path", ""))
    return {
        "created": sorted(set(by_type["created"])),
        "modified": sorted(set(by_type["modified"])),
        "deleted": sorted(set(by_type["deleted"])),
        "renamed": sorted(set(by_type["renamed"])),
        "rejected_attempts": sorted(set(by_type["failed"])),
        "total_real_changes": len({c.get("path") for c in files_changed if c.get("change_type") != "failed"}),
    }


def _debugging_summary(debug_attempts: list[dict] | None) -> dict:
    if not debug_attempts:
        return {"attempt_count": 0, "attempts": [], "final_status": "not_needed"}
    return {
        "attempt_count": len(debug_attempts),
        "attempts": debug_attempts,
        "final_status": debug_attempts[-1].get("status", "unknown"),
    }


def _review_summary(review_result: dict | None, review_attempts: list[dict] | None) -> dict:
    if review_result is None:
        return {"verdict": None, "attempt_count": len(review_attempts or [])}
    return {
        "verdict": review_result.get("verdict"),
        "risk": review_result.get("risk"),
        "summary": review_result.get("summary"),
        "issues": review_result.get("issues", []),
        "security_issues": review_result.get("security_issues", []),
        "recommendations": review_result.get("recommendations", []),
        "files_reviewed": review_result.get("files_reviewed"),
        "tests_evaluated": review_result.get("tests_evaluated"),
        "attempt_count": len(review_attempts or []),
    }


def _recommended_next_action(status: str, test_results: dict | None, debugging: dict, review: dict) -> str:
    if status == "passed":
        return "None — execution completed successfully with passing tests and an approved review."
    if status in ("error", "timed_out"):
        return "Inspect step_errors and error_message; the execution did not reach a testable state."
    if status == "cancelled":
        return "No action needed — cancelled by request; re-run the task if it should still be done."
    if test_results and test_results.get("status") == "failed" and debugging["attempt_count"] == 0:
        return "Tests failed and no debugging was attempted — investigate the failing tests listed above."
    if debugging["final_status"] == "unresolved":
        return "Debugging did not resolve the failure — manual investigation is likely needed."
    if review.get("verdict") == "changes_required":
        return "Reviewer requested changes — address the listed issues and re-run."
    return "Review the plan, changes, and test/review results above to decide the next step."


def _final_reason(status: str, error_message: str | None, test_results: dict | None, review: dict) -> str:
    if status == "passed":
        return "A real test run passed and the review was approved."
    if error_message:
        return error_message
    if test_results and test_results.get("status") == "failed":
        return f"Tests failed: {test_results.get('summary', '(no summary)')}"
    if review.get("verdict") == "changes_required":
        return "Reviewer requested changes that were not subsequently approved."
    return "Execution did not reach an honest passing state."


async def build_execution_report(
    *,
    execution: Execution,
    project: Project | None,
    steps: list[AgentStep],
    artifacts: list[Artifact],
) -> dict:
    synthesis = synthesize_execution_detail(steps)

    debug_attempts = _last_metadata_for_agent(steps, "debugger", "debug_attempts")
    review_attempts = _last_metadata_for_agent(steps, "reviewer", "review_attempts")

    debugging = _debugging_summary(debug_attempts)
    review = _review_summary(synthesis.review_result, review_attempts)

    step_errors = list(synthesis.step_errors)
    if execution.error_message and execution.error_message not in step_errors:
        step_errors.append(execution.error_message)

    git_info: dict = {"is_git_repository": False}
    if project is not None and project.workspace_path:
        try:
            workspace = Workspace.at(project.workspace_path)
            from analysis.git_info import inspect_git

            info = await inspect_git(workspace)
            git_info = info.model_dump()
        except WorkspaceError:
            git_info = {"is_git_repository": False, "warnings": ["workspace_path is no longer valid"]}

    return {
        "execution": {
            "id": str(execution.id),
            "project_id": str(execution.project_id),
            "project_name": project.name if project else None,
            "task": execution.task,
            "status": execution.status,
            "current_agent": synthesis.current_agent,
            "retry_count": synthesis.retry_count,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
            "duration_seconds": elapsed_seconds(execution.started_at, execution.completed_at),
        },
        "workspace": {
            "project_path": project.workspace_path if project else None,
            "git": git_info,
        },
        "plan": synthesis.plan,
        "changes": _changes_summary(synthesis.files_changed),
        "tests": synthesis.test_results,
        "debugging": debugging,
        "review": review,
        "artifacts": [
            {"id": str(a.id), "artifact_type": a.artifact_type, "path": a.path} for a in artifacts
        ],
        "final": {
            "status": execution.status,
            "reason": _final_reason(execution.status, execution.error_message, synthesis.test_results, review),
            "step_errors": step_errors,
            "recommended_next_action": _recommended_next_action(
                execution.status, synthesis.test_results, debugging, review
            ),
        },
    }
