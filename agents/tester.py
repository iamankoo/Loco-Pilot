"""Tester: determines whether the change works — for real, honestly.

Detects an appropriate test command from real project marker files (never
guesses/fabricates one), requests execution through the tool layer
(`execute_terminal_command`, backed by the Phase 1.4 Docker sandbox), and
interprets the actual exit code/stdout/stderr into a structured
`TestResult`. If no execute-capable tool is available (checked against
this agent's own actual permissions, not assumed) or no recognized
project marker is found, it reports `status="unavailable"` honestly
rather than fabricating a result — there is nothing to interpret when no
command was actually run.
"""

from __future__ import annotations

from agents.base import BaseAgent
from agents.schemas import TestResult
from agents.state import ExecutionState

_TEST_EXECUTION_TOOL_NAMES = ("run_tests", "execute_terminal_command")

_PROJECT_TEST_COMMANDS: tuple[tuple[str, list[str]], ...] = (
    ("pyproject.toml", ["python", "-m", "pytest"]),
    ("pytest.ini", ["python", "-m", "pytest"]),
    ("setup.py", ["python", "-m", "pytest"]),
    ("package.json", ["npm", "test"]),
    ("build.gradle", ["./gradlew", "test"]),
    ("build.gradle.kts", ["./gradlew", "test"]),
)

_DEFAULT_TIMEOUT_SECONDS = 120
_DEFAULT_MAX_OUTPUT_BYTES = 200_000

_TEST_INTERPRETATION_PROMPT = """You are the Tester for LocoPilot, an autonomous software engineering agent.
You are given the actual exit code, stdout, and stderr of a real test command execution.
Summarize it into a structured TestResult. Do not invent results beyond what this output shows."""


class TesterAgent(BaseAgent):
    name = "tester"

    async def run(self, state: ExecutionState) -> dict:
        available = self.tools.available_tools()
        execution_tool = next((name for name in _TEST_EXECUTION_TOOL_NAMES if name in available), None)

        if execution_tool is None:
            return self._unavailable(
                "Test execution is not available: no sandboxed, execute-capable tool is "
                "registered for this agent."
            )

        command = await self._detect_test_command()
        if command is None:
            return self._unavailable(
                "Could not determine an appropriate test command: no recognized project "
                "marker file (pyproject.toml, package.json, ...) was found in the workspace."
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
                commands=[command_str],
                errors=[result.error or "execution tool failed"],
                summary=f"Failed to execute test command: {result.error or 'unknown error'}",
            )
        else:
            exit_code = result.output.get("exit_code")
            timed_out = bool(result.output.get("timed_out", False))
            stdout = result.output.get("stdout", "")
            stderr = result.output.get("stderr", "")

            if self.llm_client is not None:
                test_result = await self.llm_client.generate(
                    system=_TEST_INTERPRETATION_PROMPT,
                    user=(
                        f"Command: {command_str}\nExit code: {exit_code}\nTimed out: {timed_out}\n\n"
                        f"Stdout:\n{stdout}\n\nStderr:\n{stderr}"
                    ),
                    output_model=TestResult,
                )
            elif timed_out:
                test_result = TestResult(
                    status="error",
                    commands=[command_str],
                    errors=["Command timed out before completing."],
                    summary="Test command timed out.",
                )
            else:
                passed = exit_code == 0
                tail = (stderr or stdout)[-2000:]
                test_result = TestResult(
                    status="passed" if passed else "failed",
                    commands=[command_str],
                    errors=[] if passed else [tail or f"exit code {exit_code}"],
                    summary=f"Command exited {exit_code} (no LLM configured to interpret output further).",
                )

        return {
            "test_results": test_result,
            "current_agent": self.name,
            "execution_status": "reviewing",
            "messages": [f"Tester: {test_result.summary}"],
        }

    async def _detect_test_command(self) -> list[str] | None:
        listing = await self.tools.call("list_directory", {"path": "."})
        if listing.status != "success" or not listing.output:
            return None
        names = {entry["name"] for entry in listing.output.get("entries", [])}
        for marker, command in _PROJECT_TEST_COMMANDS:
            if marker in names:
                return command
        return None

    def _unavailable(self, summary: str) -> dict:
        test_result = TestResult(status="unavailable", commands=[], passed=0, failed=0, errors=[], summary=summary)
        return {
            "test_results": test_result,
            "current_agent": self.name,
            "execution_status": "reviewing",
            "messages": [f"Tester: {summary}"],
        }
