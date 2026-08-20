"""Tester: determines whether the change works — honestly.

No execute-capable tool is registered anywhere in Phase 1.2/1.3's tool
registry (that's Phase 1.4's Docker sandbox). Tester detects this by
checking its own actually-permitted tool names, not by assuming, and
reports `status="unavailable"` with no LLM call — there is nothing for an
LLM to interpret when no test ever ran, and asking one invites exactly the
kind of fabricated "tests passed" result this system must never produce.

The `status="passed"/"failed"` path below is real code, ready for the day
an execute-capable tool exists — it is exercised in tests via a fake
execution tool, not currently reachable in production.
"""

from __future__ import annotations

from agents.base import BaseAgent
from agents.schemas import TestResult
from agents.state import ExecutionState

_TEST_EXECUTION_TOOL_NAMES = ("run_tests", "execute_terminal_command")

_TEST_INTERPRETATION_PROMPT = """You are the Tester for LocoPilot, an autonomous software engineering agent.
You are given the raw output of an actual test run. Summarize it into a structured TestResult.
Do not invent results beyond what the raw output shows."""


class TesterAgent(BaseAgent):
    name = "tester"

    async def run(self, state: ExecutionState) -> dict:
        available = self.tools.available_tools()
        execution_tool = next((name for name in _TEST_EXECUTION_TOOL_NAMES if name in available), None)

        if execution_tool is None:
            test_result = TestResult(
                status="unavailable",
                commands=[],
                passed=0,
                failed=0,
                errors=[],
                summary=(
                    "Test execution is not available: no sandboxed, execute-capable tool is "
                    "registered yet. This requires the Phase 1.4 Docker sandbox."
                ),
            )
            return {
                "test_results": test_result,
                "current_agent": self.name,
                "execution_status": "reviewing",
                "messages": ["Tester: execution capability unavailable; no tests were run."],
            }

        result = await self.tools.call(execution_tool, {})

        if self.llm_client is not None:
            test_result = await self.llm_client.generate(
                system=_TEST_INTERPRETATION_PROMPT,
                user=f"Raw test execution result (status={result.status}):\n{result.output or result.error}",
                output_model=TestResult,
            )
        else:
            test_result = TestResult(
                status="passed" if result.status == "success" else "error",
                commands=[execution_tool],
                errors=[] if result.status == "success" else [result.error or "unknown error"],
                summary="Executed without LLM interpretation of output (no LLM client configured).",
            )

        return {
            "test_results": test_result,
            "current_agent": self.name,
            "execution_status": "reviewing",
            "messages": [f"Tester: {test_result.summary}"],
        }
