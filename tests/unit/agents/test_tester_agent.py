from __future__ import annotations

from agents.schemas import FileChange
from agents.state import ExecutionState
from agents.tester import TesterAgent
from analysis.context import ProjectContext
from analysis.scanner import RepositoryStructure
from tests.fakes import FakeStructuredLLMClient, FakeToolRunner
from tools.execution_result import ToolExecutionResult


def _project_context(
    *, test_frameworks: list[str], files: list[str], test_directories: list[str], config_files: list[str] | None = None
) -> ProjectContext:
    return ProjectContext(
        workspace_root="C:/tmp/does-not-matter",
        test_frameworks=test_frameworks,
        structure=RepositoryStructure(
            root="C:/tmp/does-not-matter", files=files, test_directories=test_directories, config_files=config_files or []
        ),
        test_directories=test_directories,
    )


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
    """Phase 2.6: status/counts are parsed deterministically from the real
    output — Tester no longer asks an LLM to interpret the result at all,
    so a configured LLM client is irrelevant to (and untouched by) this."""
    llm = FakeStructuredLLMClient()  # would raise if Tester ever called it
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

    result = update["test_results"]
    assert result.status == "passed"
    assert result.framework == "pytest"
    assert result.passed == 3
    assert result.failed == 0
    assert result.duration_ms == 400
    assert llm.calls == []

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


async def test_tester_targets_the_changed_files_tests_when_project_context_available() -> None:
    """Phase 2.6: given a real ProjectContext (as the Orchestrator builds
    it), Tester prefers a targeted test path over the whole suite."""
    project_context = _project_context(
        test_frameworks=["pytest"],
        files=["auth/jwt.py", "payments/stripe.py", "tests/test_auth.py", "tests/test_payments.py"],
        test_directories=["tests"],
    )
    state = _state().model_copy(
        update={
            "project_context": project_context,
            "files_changed": [FileChange(path="auth/jwt.py", change_type="modified", detail="edited")],
        }
    )
    tools = FakeToolRunner(
        allowed={"execute_terminal_command"},
        responses={
            "execute_terminal_command": ToolExecutionResult(
                tool_name="execute_terminal_command",
                status="success",
                output={
                    "command": ["python", "-m", "pytest", "tests/test_auth.py"],
                    "exit_code": 0,
                    "stdout": "1 passed in 0.1s",
                    "stderr": "",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "duration_ms": 100,
                    "timed_out": False,
                },
                error=None,
                duration_ms=100,
            )
        },
    )

    agent = TesterAgent(llm_client=None, tools=tools)
    update = await agent.run(state)

    assert update["test_results"].commands == ["python -m pytest tests/test_auth.py"]
    assert update["test_results"].framework == "pytest"


async def test_tester_falls_back_to_test_directory_when_no_targeted_match() -> None:
    project_context = _project_context(
        test_frameworks=["pytest"], files=["app.py", "tests/test_widgets.py"], test_directories=["tests"]
    )
    state = _state().model_copy(update={"project_context": project_context, "user_task": "improve performance"})
    tools = FakeToolRunner(
        allowed={"execute_terminal_command"},
        responses={
            "execute_terminal_command": ToolExecutionResult(
                tool_name="execute_terminal_command",
                status="success",
                output={
                    "command": ["python", "-m", "pytest", "tests"],
                    "exit_code": 0,
                    "stdout": "1 passed",
                    "stderr": "",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "duration_ms": 50,
                    "timed_out": False,
                },
                error=None,
                duration_ms=50,
            )
        },
    )

    agent = TesterAgent(llm_client=None, tools=tools)
    update = await agent.run(state)

    assert update["test_results"].commands == ["python -m pytest tests"]


async def test_tester_prefers_pytest_over_unittest_when_a_pytest_marker_file_exists() -> None:
    """analysis.detection falls back to declaring "unittest" whenever no
    framework dependency is declared at all — Tester's own marker-file
    check upgrades that guess to pytest when a config file only pytest
    actually uses (pytest.ini) is present, since pytest is a strict
    superset of unittest's own discovery."""
    project_context = _project_context(
        test_frameworks=["unittest"],
        files=["app.py", "test_app.py"],
        test_directories=[],
        config_files=["pytest.ini"],
    )
    state = _state().model_copy(update={"project_context": project_context})
    tools = FakeToolRunner(
        allowed={"execute_terminal_command"},
        responses={
            "execute_terminal_command": ToolExecutionResult(
                tool_name="execute_terminal_command",
                status="success",
                output={
                    "command": ["python", "-m", "pytest"],
                    "exit_code": 0,
                    "stdout": "1 passed",
                    "stderr": "",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "duration_ms": 50,
                    "timed_out": False,
                },
                error=None,
                duration_ms=50,
            )
        },
    )

    agent = TesterAgent(llm_client=None, tools=tools)
    update = await agent.run(state)

    assert update["test_results"].framework == "pytest"
    assert update["test_results"].commands == ["python -m pytest"]


async def test_tester_parses_jest_style_passing_and_failing_counts() -> None:
    project_context = _project_context(
        test_frameworks=["Jest"], files=["auth.test.js"], test_directories=[]
    )
    state = _state().model_copy(update={"project_context": project_context})
    tools = FakeToolRunner(
        allowed={"execute_terminal_command"},
        responses={
            "execute_terminal_command": ToolExecutionResult(
                tool_name="execute_terminal_command",
                status="success",
                output={
                    "command": ["npx", "jest"],
                    "exit_code": 1,
                    "stdout": "Tests:       1 failed, 3 passed, 4 total",
                    "stderr": "",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "duration_ms": 200,
                    "timed_out": False,
                },
                error=None,
                duration_ms=200,
            )
        },
    )

    agent = TesterAgent(llm_client=None, tools=tools)
    update = await agent.run(state)

    result = update["test_results"]
    assert result.status == "failed"
    assert result.passed == 3
    assert result.failed == 1


async def test_tester_reports_timed_out_status_honestly() -> None:
    project_context = _project_context(test_frameworks=["pytest"], files=["app.py"], test_directories=[])
    state = _state().model_copy(update={"project_context": project_context})
    tools = FakeToolRunner(
        allowed={"execute_terminal_command"},
        responses={
            "execute_terminal_command": ToolExecutionResult(
                tool_name="execute_terminal_command",
                status="success",
                output={
                    "command": ["python", "-m", "pytest"],
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "duration_ms": 120000,
                    "timed_out": True,
                },
                error=None,
                duration_ms=120000,
            )
        },
    )

    agent = TesterAgent(llm_client=None, tools=tools)
    update = await agent.run(state)

    assert update["test_results"].status == "timed_out"
