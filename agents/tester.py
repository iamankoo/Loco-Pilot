"""Tester: determines whether the change works — for real, honestly.

Reuses Phase 2.2's `ProjectContext` (already built once by the
Orchestrator) for framework/test-directory detection instead of
re-scanning the workspace itself, falling back to the original marker-file
`list_directory` check only when no `ProjectContext` is available (e.g. a
`TesterAgent` exercised directly, outside the graph). Prefers a targeted
test selection (Phase 2.6's `analysis.test_selection`) over the whole
suite when the changed files/task point at specific tests.

Status is ALWAYS derived deterministically from the real exit code/
timeout of the actual command that ran — never from an LLM's reading of
the output. An LLM is not needed for this agent's core correctness at
all; passed/failed/skipped counts and failing test names are parsed from
the real stdout/stderr via lightweight, best-effort patterns common
across pytest/Jest/Mocha/cargo test, not invented.

Phase 2.7: whenever this turn follows a Debugger attempt, the most recent
`debug_attempts` entry's `status` is patched here to "fixed"/"unresolved"
based on the real, just-computed `TestResult` — the outcome of a debug
attempt is only knowable once the fix is actually re-tested, which always
happens on Tester's next turn, never on Debugger's own.
"""

from __future__ import annotations

import re

from agents.base import BaseAgent
from agents.schemas import TestResult
from agents.state import ExecutionState
from analysis.test_selection import select_test_targets

_TEST_EXECUTION_TOOL_NAMES = ("run_tests", "execute_terminal_command")

# Fallback marker-file detection, used only when no `ProjectContext` is
# available at all (e.g. TesterAgent exercised directly in a unit test).
_PROJECT_TEST_COMMANDS: tuple[tuple[str, str, list[str]], ...] = (
    ("pyproject.toml", "pytest", ["python", "-m", "pytest"]),
    ("pytest.ini", "pytest", ["python", "-m", "pytest"]),
    ("setup.py", "pytest", ["python", "-m", "pytest"]),
    ("package.json", "npm test", ["npm", "test"]),
    ("build.gradle", "gradle", ["./gradlew", "test"]),
    ("build.gradle.kts", "gradle", ["./gradlew", "test"]),
)

# Base invocation per detected framework. `JUnit` has no single universal
# command — it depends on the build tool (Maven vs Gradle), resolved from
# `ProjectContext.package_managers` instead of hardcoded here.
_FRAMEWORK_COMMANDS: dict[str, list[str]] = {
    "pytest": ["python", "-m", "pytest"],
    "unittest": ["python", "-m", "unittest", "discover"],
    "Jest": ["npx", "jest"],
    "Vitest": ["npx", "vitest", "run"],
    "Mocha": ["npx", "mocha"],
    "Playwright": ["npx", "playwright", "test"],
    "Cypress": ["npx", "cypress", "run"],
    "go test": ["go", "test", "./..."],
    "cargo test": ["cargo", "test"],
    "CTest": ["ctest"],
    "flutter test": ["flutter", "test"],
}

# Frameworks whose CLI accepts specific file/directory paths as extra
# positional arguments to narrow what runs — go test/cargo test/CTest/
# JUnit's build-tool invocations don't follow this convention closely
# enough to target safely without a real toolchain to validate against.
_PATH_TARGETABLE_FRAMEWORKS = {"pytest", "Jest", "Vitest", "Mocha", "Playwright", "flutter test"}

# Preferred order when a project shows evidence of more than one
# framework — general unit-test runners before E2E-flavored ones.
_FRAMEWORK_PRIORITY = [
    "pytest", "unittest", "Jest", "Vitest", "Mocha", "Playwright", "Cypress",
    "go test", "cargo test", "CTest", "flutter test", "JUnit",
]

_DEFAULT_TIMEOUT_SECONDS = 120
_DEFAULT_MAX_OUTPUT_BYTES = 200_000

# Best-effort, cross-framework count patterns — pytest/Jest/cargo all use
# "N passed"/"N failed" somewhere in their default summary; Mocha uses
# "passing"/"failing"/"pending". Not a claim of parsing every framework's
# output format correctly.
_COUNT_PATTERNS = {
    "passed": re.compile(r"(\d+)\s+(?:passed|passing)\b", re.IGNORECASE),
    "failed": re.compile(r"(\d+)\s+(?:failed|failing)\b", re.IGNORECASE),
    "skipped": re.compile(r"(\d+)\s+(?:skipped|pending)\b", re.IGNORECASE),
}
_PYTEST_FAILING_TEST = re.compile(r"^FAILED\s+(\S+)", re.MULTILINE)
_GO_FAILING_TEST = re.compile(r"^---\s+FAIL:\s+(\S+)", re.MULTILINE)
_MAX_FAILING_TESTS = 20


def _parse_counts(output: str) -> tuple[int, int, int]:
    def _last(pattern: re.Pattern) -> int:
        matches = pattern.findall(output)
        return int(matches[-1]) if matches else 0

    return _last(_COUNT_PATTERNS["passed"]), _last(_COUNT_PATTERNS["failed"]), _last(_COUNT_PATTERNS["skipped"])


def _parse_failing_tests(output: str) -> list[str]:
    names = list(dict.fromkeys(_PYTEST_FAILING_TEST.findall(output) + _GO_FAILING_TEST.findall(output)))
    return names[:_MAX_FAILING_TESTS]


_PYTEST_MARKER_FILES = {"pyproject.toml", "pytest.ini", "setup.py"}


_RESOLVED_DEBUG_STATUSES = ("fixed", "unresolved")


def _patch_last_debug_attempt(state: ExecutionState, test_result: TestResult) -> list | None:
    """Returns an updated `debug_attempts` list with the most recent entry's
    `status` set to "fixed" (real test passed) or "unresolved" (anything
    else) — regardless of whether Debugger's own turn called it
    "diagnosed", "blocked", or "no_fix_needed": whatever it concluded, the
    real outcome is still whether the very next test run actually passed.
    Returns `None` when there is no pending attempt to patch (no debug
    history yet, or it was already resolved by an earlier Tester turn)."""
    if not state.debug_attempts:
        return None
    last = state.debug_attempts[-1]
    if last.status in _RESOLVED_DEBUG_STATUSES:
        return None
    outcome = "fixed" if test_result.status == "passed" else "unresolved"
    return state.debug_attempts[:-1] + [last.model_copy(update={"status": outcome})]


def _pick_framework(test_frameworks: list[str], config_files: list[str]) -> str | None:
    # `analysis.detection` falls back to declaring "unittest" whenever
    # Python test files exist but no framework dependency is declared
    # (e.g. no pyproject.toml `dependencies` list at all) — a real but
    # weak signal. A pytest config marker file's mere presence, even with
    # no explicit "pytest" dependency, is itself much stronger evidence
    # that pytest (a strict superset of unittest's own test discovery) is
    # the actually-intended runner, so it takes priority over that guess.
    if "unittest" in test_frameworks and "pytest" not in test_frameworks and any(
        f in _PYTEST_MARKER_FILES for f in config_files
    ):
        return "pytest"
    for framework in _FRAMEWORK_PRIORITY:
        if framework in test_frameworks:
            return framework
    return test_frameworks[0] if test_frameworks else None


class TesterAgent(BaseAgent):
    name = "tester"

    async def run(self, state: ExecutionState) -> dict:
        available = self.tools.available_tools()
        execution_tool = next((name for name in _TEST_EXECUTION_TOOL_NAMES if name in available), None)

        if execution_tool is None:
            return self._unavailable(
                state,
                "Test execution is not available: no sandboxed, execute-capable tool is "
                "registered for this agent.",
            )

        framework, command = await self._determine_command(state)
        if framework is None or command is None:
            return self._unavailable(
                state,
                "Could not determine an appropriate test command: no recognized test framework "
                "or project marker file was found in the workspace."
            )

        result = await self.tools.call(
            execution_tool,
            {
                "command": command,
                "working_directory": ".",
                "timeout_seconds": _DEFAULT_TIMEOUT_SECONDS,
                "max_output_bytes": _DEFAULT_MAX_OUTPUT_BYTES,
            },
        )

        command_str = " ".join(command)

        if result.status != "success" or result.output is None:
            test_result = TestResult(
                status="error",
                framework=framework,
                commands=[command_str],
                errors=[result.error or "execution tool failed"],
                summary=f"Failed to execute test command: {result.error or 'unknown error'}",
            )
        else:
            test_result = self._interpret(framework, command_str, result.output)

        update = {
            "test_results": test_result,
            "current_agent": self.name,
            "execution_status": "reviewing",
            "messages": [f"Tester: {test_result.summary}"],
        }
        debug_attempts = _patch_last_debug_attempt(state, test_result)
        if debug_attempts is not None:
            update["debug_attempts"] = debug_attempts
        return update

    def _interpret(self, framework: str, command_str: str, output: dict) -> TestResult:
        """Status is always derived from the real exit code/timeout —
        never from a model's reading of the output. Counts and failing
        test names are parsed from the same real output deterministically."""
        exit_code = output.get("exit_code")
        timed_out = bool(output.get("timed_out", False))
        stdout = output.get("stdout", "")
        stderr = output.get("stderr", "")
        duration_ms = output.get("duration_ms")
        combined = f"{stdout}\n{stderr}"

        if timed_out:
            return TestResult(
                status="timed_out",
                framework=framework,
                commands=[command_str],
                duration_ms=duration_ms,
                errors=["Command timed out before completing."],
                summary=f"{framework} timed out before completing.",
            )

        passed, failed, skipped = _parse_counts(combined)
        failing_tests = _parse_failing_tests(combined)
        status = "passed" if exit_code == 0 else "failed"

        if passed or failed or skipped:
            summary = f"{framework}: {passed} passed, {failed} failed, {skipped} skipped (exit code {exit_code})"
        else:
            summary = f"{framework} exited {exit_code}"

        tail = (stderr or stdout)[-2000:]
        return TestResult(
            status=status,
            framework=framework,
            commands=[command_str],
            passed=passed,
            failed=failed,
            skipped=skipped,
            failing_tests=failing_tests,
            duration_ms=duration_ms,
            errors=[] if status == "passed" else [tail or f"exit code {exit_code}"],
            summary=summary,
        )

    async def _determine_command(self, state: ExecutionState) -> tuple[str | None, list[str] | None]:
        project_context = state.project_context
        if project_context is None or not project_context.test_frameworks:
            return await self._detect_command_from_markers()

        config_files = project_context.structure.config_files if project_context.structure else []
        framework = _pick_framework(project_context.test_frameworks, config_files)
        if framework is None:
            return None, None

        base_command = self._base_command_for(framework, project_context.package_managers)
        if base_command is None:
            return framework, None

        if framework not in _PATH_TARGETABLE_FRAMEWORKS:
            return framework, base_command

        changed_paths = [f.path for f in state.files_changed if f.change_type != "failed"]
        targets = select_test_targets(project_context.structure, changed_files=changed_paths, task=state.user_task)
        if targets:
            return framework, base_command + targets

        if project_context.test_directories:
            return framework, base_command + [project_context.test_directories[0]]

        return framework, base_command

    def _base_command_for(self, framework: str, package_managers: list[str]) -> list[str] | None:
        if framework == "JUnit":
            if "maven" in package_managers:
                return ["mvn", "test"]
            if "gradle" in package_managers:
                return ["./gradlew", "test"]
            return None
        return _FRAMEWORK_COMMANDS.get(framework)

    async def _detect_command_from_markers(self) -> tuple[str | None, list[str] | None]:
        listing = await self.tools.call("list_directory", {"path": "."})
        if listing.status != "success" or not listing.output:
            return None, None
        names = {entry["name"] for entry in listing.output.get("entries", [])}
        for marker, framework, command in _PROJECT_TEST_COMMANDS:
            if marker in names:
                return framework, command
        return None, None

    def _unavailable(self, state: ExecutionState, summary: str) -> dict:
        test_result = TestResult(status="unavailable", commands=[], passed=0, failed=0, errors=[], summary=summary)
        update = {
            "test_results": test_result,
            "current_agent": self.name,
            "execution_status": "reviewing",
            "messages": [f"Tester: {summary}"],
        }
        debug_attempts = _patch_last_debug_attempt(state, test_result)
        if debug_attempts is not None:
            update["debug_attempts"] = debug_attempts
        return update
