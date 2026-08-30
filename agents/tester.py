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
from analysis.browser_verification import verify_in_browser
from analysis.document_artifact import verify_document_artifacts
from analysis.static_site import verify_static_site
from analysis.test_selection import select_test_targets
from backend.app.services import runtime_service
from tools.workspace import Workspace, WorkspaceError

# Where a real Playwright screenshot of a verified runtime is saved, inside
# the workspace so it travels with the project and can be recorded as a
# genuine execution artifact — a dot-prefixed platform directory, clearly
# distinct from anything the Developer/Planner would name.
_SCREENSHOT_RELATIVE_PATH = ".locopilot/verification-screenshot.png"

_TEST_EXECUTION_TOOL_NAMES = ("run_tests", "execute_terminal_command")

# A static site with no build step has exactly one sane, always-safe way to
# serve it — this is deliberately NOT left to Planner's own judgment call:
# an LLM-proposed run_command/run_port is used when both are present (a
# non-trivial app may genuinely need something else, e.g. `npm start`), but
# a plain static site whose plan omitted them still gets a real runtime
# started and verified whenever the task actually asked for one, rather
# than silently skipping verification because of an LLM reliability gap.
# The port here is only ever the CONTAINER-internal port — arbitrary and
# safe, since the actual host-exposed port is always freshly allocated by
# runtime_service, never this number (see backend.app.services.runtime_service).
_DEFAULT_STATIC_SITE_RUN_COMMAND = ["python3", "-m", "http.server", "8000"]
_DEFAULT_STATIC_SITE_RUN_PORT = 8000
_RUN_INTENT_RE = re.compile(
    r"\brun\b.{0,20}\b(local\s*host|localhost)\b|\b(local\s*host|localhost)\b.{0,20}\brun\b|"
    r"\bserve\b|\bstart\b.{0,20}\bserver\b",
    re.IGNORECASE,
)


def _task_implies_local_run(task: str) -> bool:
    return bool(_RUN_INTENT_RE.search(task))

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
            return await self._run_project_type_fallback_check(state)

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

    async def _run_project_type_fallback_check(self, state: ExecutionState) -> dict:
        """Dispatches to whichever deterministic, no-conventional-test-
        framework verification actually applies — a static website
        (`_run_static_site_check`) or a generated document/spreadsheet
        deliverable (`_run_document_artifact_check`) — before finally
        falling back to the original "unavailable" outcome when neither
        applies (a non-web, non-document project with no test framework) or
        the workspace itself can't be opened (e.g. this agent exercised
        directly in a unit test, with no real workspace on disk)."""
        try:
            workspace = Workspace.at(state.workspace_root)
        except WorkspaceError:
            return self._unavailable(
                state,
                "Could not determine an appropriate test command: no recognized test framework "
                "or project marker file was found in the workspace.",
            )

        static_site_result = await self._run_static_site_check(state, workspace)
        if static_site_result is not None:
            return static_site_result

        document_result = self._run_document_artifact_check(state, workspace)
        if document_result is not None:
            return document_result

        return self._unavailable(
            state,
            "Could not determine an appropriate test command: no recognized test framework, no HTML "
            "entry point, and no generated document/spreadsheet artifact was found in the workspace.",
        )

    def _run_document_artifact_check(self, state: ExecutionState, workspace: Workspace) -> dict | None:
        """Verifies a generated document/spreadsheet deliverable (PDF/DOCX/
        XLSX/CSV, via tools/documents/tools.py) actually exists and is a
        genuinely valid file of its claimed type — without this, a task
        like "create a PDF report" could never honestly reach "passed"
        (agents.state.compute_honest_status requires a real passing
        TestResult), permanently capping even a correctly-completed
        document task at "needs_review". Returns None (not a TestResult) if
        no document tool was ever used this execution, so the caller can
        fall through to the final "unavailable" outcome."""
        verification = verify_document_artifacts(workspace, state.files_changed)
        if not verification.found_any:
            return None

        errors = [f"Generated artifact not found: {path}" for path in verification.missing_paths]
        errors += [f"Generated artifact is not valid: {path} ({reason})" for path, reason in verification.invalid_paths]
        status = "passed" if verification.ok else "failed"

        summary = f"Document artifact check: {len(verification.checked_paths)} generated file(s) verified"
        summary += "." if status == "passed" else " — see errors."

        test_result = TestResult(
            status=status,
            framework="document-artifact",
            commands=[],
            errors=errors,
            summary=summary,
            verification_kind="static_site",  # reuses the same "not a conventional test suite" evidence lane
        )
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

    async def _run_static_site_check(self, state: ExecutionState, workspace: Workspace) -> dict | None:
        """Deterministically confirms the real entry HTML exists, every
        local CSS/JS/image reference it makes actually resolves to a real
        file, and — for an image — that file's content is genuinely the
        binary format its extension claims (closes the exact bug class
        where a model writes base64 TEXT to a `.png` path via a text-only
        write). If the plan specifies `run_command`/`run_port`, or the task
        text itself implies "run it on localhost" even when the plan
        omitted them (see `_task_implies_local_run` — Planner's own
        structured-output reliability for these two fields is not trusted
        as the sole gate for whether verification happens at all), starts
        a real, localhost-only runtime on a freshly allocated host port
        (never the LocoPilot backend's own port) and confirms it actually
        answers HTTP requests before ever calling this "passed" — never
        from an agent's own claim. Returns None (not a TestResult) if no
        HTML entry point exists at all, so the caller can try the next
        project-type check."""
        hint_paths = list(state.plan.files_likely_involved) if state.plan else []
        verification = verify_static_site(workspace, hint_paths=hint_paths)

        if verification.entry_path is None:
            return None

        errors: list[str] = [f"Referenced local asset not found: {path}" for path in verification.missing_assets]
        errors += [f"Referenced local asset is not valid: {path} ({reason})" for path, reason in verification.invalid_assets]

        runtime_url: str | None = None
        runtime_status: str | None = None
        run_command = state.plan.run_command if state.plan else None
        run_port = state.plan.run_port if state.plan else None
        if not (run_command and run_port) and _task_implies_local_run(state.user_task):
            # Planner didn't (or couldn't reliably) fill run_command/run_port
            # — the task still explicitly asked for a running local site, so
            # fall back to the one deterministic, always-safe way to serve a
            # plain static site rather than silently skipping verification.
            run_command = _DEFAULT_STATIC_SITE_RUN_COMMAND
            run_port = _DEFAULT_STATIC_SITE_RUN_PORT
        if run_command and run_port:
            record = await runtime_service.start_runtime(
                state.execution_id, workspace, command=run_command, container_port=run_port
            )
            runtime_status = record.status
            if record.status == "running":
                runtime_url = record.runtime.url
            else:
                errors.append(f"Runtime server failed to start or never became reachable: {record.detail}")

        assets_ok = not verification.missing_assets and not verification.invalid_assets

        visual_verification_kind: str = "none"
        visual_ok: bool | None = None
        visual_reason = ""
        console_errors: list[str] = []
        screenshot_path: str | None = None
        if runtime_status == "running" and runtime_url:
            browser_result = await verify_in_browser(
                runtime_url, screenshot_file=workspace.root / _SCREENSHOT_RELATIVE_PATH
            )
            if browser_result.available:
                visual_verification_kind = "browser"
                visual_ok = browser_result.ok
                visual_reason = browser_result.reason
                console_errors = browser_result.console_errors
                if browser_result.screenshot_path:
                    screenshot_path = _SCREENSHOT_RELATIVE_PATH
                if not browser_result.ok:
                    errors.append(f"Browser verification: {browser_result.reason}")
            else:
                visual_verification_kind = "unavailable"
                visual_reason = browser_result.reason

        runtime_ok = runtime_status in (None, "running")
        visual_gate_ok = visual_verification_kind != "browser" or visual_ok is True
        status = "passed" if assets_ok and runtime_ok and visual_gate_ok else "failed"

        summary = (
            f"Static site check: entry point {verification.entry_path}, "
            f"{len(verification.checked_assets)} local asset reference(s) checked"
        )
        if runtime_status == "running":
            summary += f", runtime verified reachable at {runtime_url}"
        elif runtime_status is not None:
            summary += f", runtime {runtime_status}"
        if visual_verification_kind == "browser":
            summary += f", browser verification {'passed' if visual_ok else 'failed'} ({visual_reason})"
        elif visual_verification_kind == "unavailable":
            summary += f", browser verification unavailable ({visual_reason})"
        summary += "." if status == "passed" else " — see errors."

        test_result = TestResult(
            status=status,
            framework="static-site",
            commands=[" ".join(run_command)] if run_command else [],
            errors=errors,
            summary=summary,
            verification_kind="static_site",
            runtime_url=runtime_url,
            runtime_status=runtime_status,
            visual_verification_kind=visual_verification_kind,
            visual_ok=visual_ok,
            visual_reason=visual_reason,
            console_errors=console_errors,
            screenshot_path=screenshot_path,
        )
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
