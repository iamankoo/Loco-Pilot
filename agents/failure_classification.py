"""Deterministic, regex-based test-failure classification.

The actual `TestResult` (real exit code, real parsed output) is the
authoritative evidence — this module never asks an LLM to decide the
class, and `agents.debugger.DebuggerAgent` always overrides whatever
class an LLM's structured output might otherwise propose with this
function's result. A best-effort pattern match across common failure
shapes, not a claim of perfectly classifying every possible failure —
falls back to a broad, honest bucket ("test_failure"/"environment_error"/
"unknown") rather than a confident-sounding wrong guess.
"""

from __future__ import annotations

import re

from agents.schemas import TestResult

FailureClass = str

_PATTERNS: tuple[tuple[FailureClass, re.Pattern], ...] = (
    ("syntax_error", re.compile(r"SyntaxError|IndentationError|Parse error", re.IGNORECASE)),
    (
        "import_error",
        re.compile(r"ImportError|ModuleNotFoundError|cannot find module|Cannot find module", re.IGNORECASE),
    ),
    (
        "dependency_error",
        re.compile(
            r"No matching distribution|ERESOLVE|npm ERR!.*(missing|404|E404)|"
            r"package .* (not found|could not be resolved)|Could not find a version",
            re.IGNORECASE,
        ),
    ),
    ("type_error", re.compile(r"\bTypeError\b")),
    ("assertion_failure", re.compile(r"AssertionError|assert(ion)? (failed|error)", re.IGNORECASE)),
    (
        "build_failure",
        re.compile(r"CMake Error|error: .*\.(cpp|c|h)|make(?:\[\d+\])?: \*\*\*|compilation terminated", re.IGNORECASE),
    ),
    (
        "configuration_error",
        re.compile(r"MissingConfiguration|EnvironmentError.*config|KeyError.*(config|settings)", re.IGNORECASE),
    ),
    (
        "environment_error",
        re.compile(
            r"docker executable not found|permission denied|No such file or directory: ['\"]?docker",
            re.IGNORECASE,
        ),
    ),
)


def classify_failure(test_result: TestResult | None) -> FailureClass:
    if test_result is None:
        return "unknown"
    if test_result.status == "timed_out":
        return "timeout"
    if test_result.status not in ("failed", "error"):
        return "unknown"

    text = "\n".join(test_result.errors) + "\n" + test_result.summary
    for failure_class, pattern in _PATTERNS:
        if pattern.search(text):
            return failure_class

    return "test_failure" if test_result.status == "failed" else "environment_error"
