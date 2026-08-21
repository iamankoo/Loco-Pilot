"""Targeted test selection: given the files Developer actually changed
and the task's own wording, rank candidate test files so Tester can run a
focused subset first rather than the entire suite after every change.

Deterministic and filesystem-only — no test file's content is read, no
code executes during selection (execution happens later, only through the
sandbox). Reuses `analysis.relevant_files`'s keyword/path scoring rather
than inventing a second ranking approach.
"""

from __future__ import annotations

from analysis.relevant_files import extract_keywords, score_path
from analysis.scanner import RepositoryStructure, is_test_path

MAX_TEST_TARGETS = 5


def _stem(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def select_test_targets(
    structure: RepositoryStructure | None,
    *,
    changed_files: list[str] | None = None,
    task: str = "",
    max_targets: int = MAX_TEST_TARGETS,
) -> list[str]:
    """Ranks test files by relevance to `changed_files`/`task`, returning
    only ones with a real positive match — never "every test file just in
    case". A test suite is commonly organized either by exact per-file
    name (jwt.py -> test_jwt.py) or by feature/directory (auth/jwt.py ->
    test_auth.py), so both the changed file's own stem AND its containing
    directory name become extra matching signals alongside the task's own
    keywords."""
    if structure is None:
        return []
    test_files = [f for f in structure.files if is_test_path(f)]
    if not test_files:
        return []

    keywords = extract_keywords(task)
    for changed in changed_files or []:
        normalized = changed.replace("\\", "/")
        parts = normalized.split("/")
        for directory in parts[:-1]:
            if directory:
                keywords.add(directory.lower())
        keywords.add(_stem(normalized).lower())

    scored: list[tuple[float, str]] = []
    for test_file in test_files:
        score, _ = score_path(test_file, keywords)
        if score > 0:
            scored.append((score, test_file))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [path for _, path in scored[:max_targets]]
