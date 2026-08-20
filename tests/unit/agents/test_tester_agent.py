from __future__ import annotations

from agents.schemas import TestResult
from agents.state import ExecutionState
from agents.tester import TesterAgent
from tests.fakes import FakeStructuredLLMClient, FakeToolRunner
from tools.execution_result import ToolExecutionResult


def _state() -> ExecutionState:
    return ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task="add a function",
        workspace_root="C:/tmp/does-not-matter",
    )


_LIST_DIR_WITH_PYPROJECT = ToolExecutionResult(
    tool_name="list_directory",
    status="success",
    output={"path": ".", "entries": [{"name": "pyproject.toml", "path": "pyproject.toml", "is_dir": False}]},
    error=None,
    duration_ms=1,
)

_LIST_DIR_NO_MARKERS = ToolExecutionResult(
    tool_name="list_directory",
    status="success",
    output={"path": ".", "entries": [{"name": "README.md", "path": "README.md", "is_dir": False}]},
    error=None,
    duration_ms=1,
)


async def test_tester_reports_unavailable_when_no_execute_tool_and_makes_no_llm_call() -> None:
    """The current, real-world case when Tester lacks EXECUTE permission."""
    llm = FakeStructuredLLMClient()  # would raise AssertionError if called with no configured response
    tools = FakeToolRunner(allowed={"read_file", "search_files"})  # no execute_terminal_command

    agent = TesterAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state())

    assert update["test_results"].status == "unavailable"
    assert update["test_results"].passed == 0
    assert update["test_results"].failed == 0
    assert llm.calls == []  # never fabricated an LLM-based verdict


async def test_tester_never_claims_passed_without_execution() -> None:
    tools = FakeToolRunner(allowed={"read_file"})
    agent = TesterAgent(llm_client=None, tools=tools)
    update = await agent.run(_state())
    assert update["test_results"].status != "passed"


async def test_tester_reports_unavailable_when_no_project_marker_found() -> None:
    """An execute-capable tool exists, but Tester still won't fabricate a
    command when it can't ground one in an actual project marker file."""
    tools = FakeToolRunner(
        allowed={"list_directory", "execute_terminal_command"},
        responses={"list_directory": _LIST_DIR_NO_MARKERS},
    )
    agent = TesterAgent(llm_client=None, tools=tools)
    update = await agent.run(_state())

    assert update["test_results"].status == "unavailable"
    assert not any(name == "execute_terminal_command" for name, _ in tools.calls)


async def test_tester_detects_python_project_and_runs_pytest() -> None:
    test_result = TestResult(status="passed", commands=["python -m pytest"], passed=3, failed=0, summary="3 passed")
    llm = FakeStructuredLLMClient({"TestResult": test_result})
    tools = FakeToolRunner(
        allowed={"list_directory", "execute_terminal_command"},
        responses={
            "list_directory": _LIST_DIR_WITH_PYPROJECT,
            "execute_terminal_command": ToolExecutionResult(
                tool_name="execute_terminal_command",
                status="success",
                output={
                    "command": ["python", "-m", "pytest"],
                    "exit_code": 0,
                    "stdout": "3 passed in 0.4s",
                    "stderr": "",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "duration_ms": 400,
                    "timed_out": False,
                },
                error=None,
                duration_ms=400,
            ),
        },
    )

    agent = TesterAgent(llm_client=llm, tools=tools)
    update = await agent.run(_state())

    assert update["test_results"] == test_result
    assert len(llm.calls) == 1

    exec_calls = [inp for name, inp in tools.calls if name == "execute_terminal_command"]
    assert exec_calls[0]["command"] == ["python", "-m", "pytest"]


async def test_tester_falls_back_deterministically_without_llm_on_exit_code() -> None:
    tools = FakeToolRunner(
        allowed={"list_directory", "execute_terminal_command"},
        responses={
            "list_directory": _LIST_DIR_WITH_PYPROJECT,
            "execute_terminal_command": ToolExecutionResult(
                tool_name="execute_terminal_command",
                status="success",
                output={
                    "command": ["python", "-m", "pytest"],
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "AssertionError: 1 != 2",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "duration_ms": 200,
                    "timed_out": False,
                },
                error=None,
                duration_ms=200,
            ),
        },
    )
    agent = TesterAgent(llm_client=None, tools=tools)
    update = await agent.run(_state())

    assert update["test_results"].status == "failed"
    assert "AssertionError" in update["test_results"].errors[0]


async def test_tester_reports_error_when_execution_tool_itself_fails() -> None:
    tools = FakeToolRunner(
        allowed={"list_directory", "execute_terminal_command"},
        responses={
            "list_directory": _LIST_DIR_WITH_PYPROJECT,
            "execute_terminal_command": ToolExecutionResult(
                tool_name="execute_terminal_command",
                status="error",
                output=None,
                error="docker executable not found on PATH.",
                duration_ms=5,
            ),
        },
    )
    agent = TesterAgent(llm_client=None, tools=tools)
    update = await agent.run(_state())

    assert update["test_results"].status == "error"
    assert "docker executable not found" in update["test_results"].errors[0]
