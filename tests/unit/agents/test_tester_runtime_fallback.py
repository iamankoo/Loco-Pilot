from __future__ import annotations

from dataclasses import dataclass

from agents.state import ExecutionState
from agents.tester import (
    _DEFAULT_STATIC_SITE_RUN_COMMAND,
    _DEFAULT_STATIC_SITE_RUN_PORT,
    _task_implies_local_run,
    TesterAgent,
)
from analysis.browser_verification import BrowserVerificationResult
from tests.fakes import FakeToolRunner
from tools.workspace import Workspace


async def _fake_verify_in_browser_ok(url: str, *, screenshot_file=None, timeout_ms=15000) -> BrowserVerificationResult:
    return BrowserVerificationResult(available=True, ok=True, reason="looks fine", heading_count=1)


def _state(workspace: Workspace, *, user_task: str, plan=None) -> ExecutionState:
    return ExecutionState(
        execution_id="11111111-1111-1111-1111-111111111111",
        project_id="22222222-2222-2222-2222-222222222222",
        user_task=user_task,
        workspace_root=str(workspace.root),
        plan=plan,
    )


def test_task_implies_local_run_detects_common_phrasings() -> None:
    assert _task_implies_local_run("Make a cartoon website and run it on local host")
    assert _task_implies_local_run("build a site and run it on localhost")
    assert _task_implies_local_run("serve the site please")
    assert _task_implies_local_run("start the server once it's built")
    assert not _task_implies_local_run("just create index.html, nothing else")


@dataclass
class _FakeRuntimeRecord:
    status: str
    detail: str

    class _Runtime:
        def __init__(self, url: str) -> None:
            self.url = url

    def __post_init__(self) -> None:
        self.runtime = self._Runtime("http://127.0.0.1:54321")


async def test_static_site_check_uses_deterministic_default_run_command_when_plan_omits_it(
    tmp_workspace: Workspace, monkeypatch
) -> None:
    """The exact bug this closes: Planner unreliably fills run_command/
    run_port via LLM structured output — when it doesn't, a task that
    explicitly asked to "run it on local host" must still get a real
    runtime started and verified, using a deterministic, always-safe
    default rather than silently skipping verification."""
    (tmp_workspace.root / "index.html").write_text("<html><body>Cartoon</body></html>", encoding="utf-8")

    captured = {}

    async def _fake_start_runtime(execution_id, workspace, *, command, container_port, **kwargs):
        captured["command"] = command
        captured["container_port"] = container_port
        return _FakeRuntimeRecord(status="running", detail="HTTP 200")

    monkeypatch.setattr("agents.tester.runtime_service.start_runtime", _fake_start_runtime)
    monkeypatch.setattr("agents.tester.verify_in_browser", _fake_verify_in_browser_ok)

    state = _state(tmp_workspace, user_task="Make a cartoon website and run it on local host", plan=None)
    agent = TesterAgent(llm_client=None, tools=FakeToolRunner(allowed={"execute_terminal_command"}))
    update = await agent.run(state)

    assert captured["command"] == _DEFAULT_STATIC_SITE_RUN_COMMAND
    assert captured["container_port"] == _DEFAULT_STATIC_SITE_RUN_PORT
    result = update["test_results"]
    assert result.status == "passed"
    assert result.runtime_status == "running"
    assert result.runtime_url == "http://127.0.0.1:54321"
    # Never the LocoPilot backend's own conventional port as the reported URL.
    assert ":8000" not in result.runtime_url
    assert result.visual_verification_kind == "browser"
    assert result.visual_ok is True


async def test_static_site_check_does_not_start_a_runtime_when_task_does_not_ask_for_one(
    tmp_workspace: Workspace, monkeypatch
) -> None:
    (tmp_workspace.root / "index.html").write_text("<html><body>Just files</body></html>", encoding="utf-8")

    called = {"n": 0}

    async def _fake_start_runtime(*args, **kwargs):
        called["n"] += 1
        return _FakeRuntimeRecord(status="running", detail="HTTP 200")

    monkeypatch.setattr("agents.tester.runtime_service.start_runtime", _fake_start_runtime)

    state = _state(tmp_workspace, user_task="Just create index.html for me", plan=None)
    agent = TesterAgent(llm_client=None, tools=FakeToolRunner(allowed={"execute_terminal_command"}))
    update = await agent.run(state)

    assert called["n"] == 0
    assert update["test_results"].runtime_status is None


async def test_static_site_check_prefers_plans_own_run_command_when_present(
    tmp_workspace: Workspace, monkeypatch
) -> None:
    from agents.schemas import Plan

    (tmp_workspace.root / "index.html").write_text("<html></html>", encoding="utf-8")
    plan = Plan(
        objective="x", steps=["x"], testing_strategy="x",
        run_command=["node", "server.js"], run_port=3000,
    )

    captured = {}

    async def _fake_start_runtime(execution_id, workspace, *, command, container_port, **kwargs):
        captured["command"] = command
        captured["container_port"] = container_port
        return _FakeRuntimeRecord(status="running", detail="HTTP 200")

    monkeypatch.setattr("agents.tester.runtime_service.start_runtime", _fake_start_runtime)
    monkeypatch.setattr("agents.tester.verify_in_browser", _fake_verify_in_browser_ok)

    state = _state(tmp_workspace, user_task="run it on local host", plan=plan)
    agent = TesterAgent(llm_client=None, tools=FakeToolRunner(allowed={"execute_terminal_command"}))
    await agent.run(state)

    assert captured["command"] == ["node", "server.js"]
    assert captured["container_port"] == 3000
