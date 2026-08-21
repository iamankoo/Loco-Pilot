"""Bounded, per-stage retrieval-query construction.

Each agent stage needs a different (small, deliberate) slice of
`ExecutionState` to retrieve well against — never the entire accumulated
state dumped into one query string. This is the single place that
decides what goes into a retrieval query, so `agents/graph.py` doesn't
duplicate that judgement per call site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_QUERY_CHARS = 2_000
MAX_EXPLICIT_HINTS = 5

# A conservative, common set of source-file extensions — used only to
# recognize an explicitly-named file in free-text task/error strings, not
# to validate or resolve a path.
_FILENAME_PATTERN = re.compile(
    r"\b[\w\-./\\]+\.(?:py|js|jsx|ts|tsx|java|go|rs|rb|php|c|h|cpp|hpp|cc|cs|dart|kt|swift|"
    r"json|yaml|yml|toml|cfg|ini|md|sql|sh)\b",
    re.IGNORECASE,
)
# `File "path/to/file.py", line 42` — the standard Python traceback shape.
_TRACEBACK_FILE_PATTERN = re.compile(r'File "([^"]+)"')


def _extract_filename_hints(*texts: str) -> list[str]:
    hints: list[str] = []
    for text in texts:
        if not text:
            continue
        for match in _TRACEBACK_FILE_PATTERN.finditer(text):
            name = match.group(1).replace("\\", "/").rsplit("/", 1)[-1]
            if name not in hints:
                hints.append(name)
        for match in _FILENAME_PATTERN.finditer(text):
            name = match.group(0).replace("\\", "/").rsplit("/", 1)[-1]
            if name not in hints:
                hints.append(name)
    return hints[:MAX_EXPLICIT_HINTS]


@dataclass
class RetrievalQuery:
    text: str
    explicit_file_hints: list[str] = field(default_factory=list)


def _bounded(text: str) -> str:
    return text[:MAX_QUERY_CHARS]


def build_retrieval_query(agent_name: str, state) -> RetrievalQuery | None:  # noqa: ANN001 - agents.state.ExecutionState (avoids a state<->query_builder import cycle)
    """Returns `None` when this stage has nothing new worth retrieving
    against (e.g. Tester, or Planner whose stage is covered by the
    Orchestrator's initial retrieval)."""
    project_files = []
    if state.project_context is not None:
        project_files = [r.path for r in state.project_context.relevant_files]

    if agent_name == "orchestrator":
        hints = list(dict.fromkeys(_extract_filename_hints(state.user_task) + project_files))
        return RetrievalQuery(text=_bounded(state.user_task), explicit_file_hints=hints[:MAX_EXPLICIT_HINTS])

    if agent_name == "developer" and state.plan is not None:
        parts = [state.user_task, state.plan.objective, *state.plan.steps]
        hints = list(dict.fromkeys(state.plan.files_likely_involved + _extract_filename_hints(state.user_task)))
        if state.debug_result is not None:
            parts.append(state.debug_result.root_cause)
            parts.append(state.debug_result.proposed_fix)
            hints = list(dict.fromkeys(hints + state.debug_result.files_to_change))
        return RetrievalQuery(text=_bounded("\n".join(parts)), explicit_file_hints=hints[:MAX_EXPLICIT_HINTS])

    if agent_name == "debugger" and state.test_results is not None:
        failure_text = "\n".join([state.test_results.summary, *state.test_results.errors])
        parts = [state.user_task, failure_text]
        hints = _extract_filename_hints(failure_text)
        # The code Developer just changed is exactly what a failing test
        # is most likely to be exercising.
        hints = list(dict.fromkeys(hints + [f.path for f in state.files_changed]))
        return RetrievalQuery(text=_bounded("\n".join(parts)), explicit_file_hints=hints[:MAX_EXPLICIT_HINTS])

    if agent_name == "reviewer":
        parts = [state.user_task]
        if state.plan is not None:
            parts.append(state.plan.objective)
        changed_paths = [f.path for f in state.files_changed if f.change_type != "failed"]
        hints = list(dict.fromkeys(changed_paths))
        return RetrievalQuery(text=_bounded("\n".join(parts)), explicit_file_hints=hints[:MAX_EXPLICIT_HINTS])

    return None
