"""Phase 2.9: structured commit-summary generation — deterministic, from
real execution state only. Never executes a commit itself: `git_commit`
remains unregistered as an agent-callable tool (a deliberate Phase 1.2
decision preserved here), so committing stays a separate, explicit action
outside LocoPilot's own autonomous loop. GitHub publishing is never
performed by LocoPilot at all.
"""

from __future__ import annotations

from agents.state import ExecutionState


def generate_commit_summary(state: ExecutionState) -> str:
    """A conventional-commit-style message built entirely from real,
    already-persisted state (task, actual file changes, actual test
    outcome) — never from an LLM's own claim of what it did."""
    changed = [f for f in state.files_changed if f.change_type != "failed"]
    created = sorted(f.path for f in changed if f.change_type == "created")
    modified = sorted(f.path for f in changed if f.change_type == "modified")
    deleted = sorted(f.path for f in changed if f.change_type == "deleted")
    renamed = sorted(f.path for f in changed if f.change_type == "renamed")

    subject = state.user_task.strip().splitlines()[0][:72] if state.user_task.strip() else "update"

    lines = [subject, ""]
    if created:
        lines.append("Created: " + ", ".join(created))
    if modified:
        lines.append("Modified: " + ", ".join(modified))
    if deleted:
        lines.append("Deleted: " + ", ".join(deleted))
    if renamed:
        lines.append("Renamed: " + ", ".join(renamed))

    if state.test_results is not None:
        lines.append(f"Tests: {state.test_results.status} ({state.test_results.passed} passed, {state.test_results.failed} failed)")
    if state.review_result is not None:
        lines.append(f"Review: {state.review_result.verdict}")

    return "\n".join(lines).strip()
