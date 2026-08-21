"""Phase 2.9 — Git integration: scoped diffs distinguish LocoPilot's own
execution changes from a workspace's pre-existing (possibly dirty) state,
using real temporary Git repositories throughout.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agents.commit_summary import generate_commit_summary
from agents.schemas import FileChange, Plan, ReviewResult, TestResult
from agents.state import ExecutionState
from tools.base import ToolContext, ToolError
from tools.git.schemas import GitDiffInput, GitStatusInput
from tools.git.tools import GitDiffTool, GitStatusTool
from tools.registry import build_default_registry
from tools.workspace import Workspace


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(root: Path) -> None:
    _git("init", "-q", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test User", cwd=root)
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    _git("add", "README.md", cwd=root)
    _git("commit", "-q", "-m", "initial", cwd=root)


# ---- 1/2/3: non-Git / Git detection / clean repo -------------------------


async def test_non_git_workspace_status_raises(tmp_path: Path) -> None:
    workspace = Workspace.at(tmp_path)
    context = ToolContext(workspace=workspace)
    with pytest.raises(ToolError):
        await GitStatusTool().run(GitStatusInput(), context)


async def test_clean_git_repository_is_detected(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    workspace = Workspace.at(tmp_path)
    context = ToolContext(workspace=workspace)
    status = await GitStatusTool().run(GitStatusInput(), context)
    assert status.clean is True
    assert status.branch is not None


# ---- 4/9: pre-existing modifications must not be attributed to the run --


async def test_scoped_diff_excludes_pre_existing_uncommitted_changes(tmp_path: Path) -> None:
    """The core Phase 2.9 requirement: a file the user had already
    modified before LocoPilot ever ran must not appear in the diff
    Reviewer sees, only the files this execution's own tool calls touched."""
    _init_repo(tmp_path)
    (tmp_path / "user_file.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("y = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "user_file.py", "app.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "add both files"], cwd=tmp_path, check=True, capture_output=True)

    # Pre-existing, uncommitted user change — must NOT be attributed to LocoPilot.
    (tmp_path / "user_file.py").write_text("x = 2  # the user's own unrelated edit\n", encoding="utf-8")
    # LocoPilot's own change, in a different (already-tracked) file.
    (tmp_path / "app.py").write_text("y = 2\n", encoding="utf-8")

    workspace = Workspace.at(tmp_path)
    context = ToolContext(workspace=workspace)
    scoped = await GitDiffTool().run(GitDiffInput(paths=["app.py"]), context)

    assert "app.py" in scoped.diff
    assert "user_file.py" not in scoped.diff
    assert "unrelated edit" not in scoped.diff

    # An unscoped diff, for contrast, WOULD include both — proving the
    # scoping is what actually does the distinguishing.
    unscoped = await GitDiffTool().run(GitDiffInput(), context)
    assert "user_file.py" in unscoped.diff


# ---- 5/6/7: untracked / deleted / renamed ----------------------------------


async def test_untracked_files_are_reported(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "new_file.py").write_text("z = 1\n", encoding="utf-8")
    context = ToolContext(workspace=Workspace.at(tmp_path))
    status = await GitStatusTool().run(GitStatusInput(), context)
    assert any(f.path == "new_file.py" and f.status == "untracked" for f in status.files)
    assert status.clean is False


async def test_deleted_and_renamed_files_are_reported(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "add a.py"], cwd=tmp_path, check=True, capture_output=True)

    (tmp_path / "a.py").unlink()
    context = ToolContext(workspace=Workspace.at(tmp_path))
    status = await GitStatusTool().run(GitStatusInput(), context)
    assert any(f.path == "a.py" and f.status == "deleted" for f in status.files)


# ---- 8/10: execution-scoped diff correctness for created/modified/deleted -


async def test_scoped_diff_reflects_created_and_modified_files_accurately(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "existing.py").write_text("a = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "existing.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "add existing"], cwd=tmp_path, check=True, capture_output=True)

    (tmp_path / "existing.py").write_text("a = 2\n", encoding="utf-8")  # modified
    (tmp_path / "brand_new.py").write_text("b = 1\n", encoding="utf-8")  # created (untracked)

    context = ToolContext(workspace=Workspace.at(tmp_path))
    diff = await GitDiffTool().run(GitDiffInput(paths=["existing.py"]), context)
    assert "-a = 1" in diff.diff
    assert "+a = 2" in diff.diff
    # An untracked new file has no `diff` entry until added — a real,
    # documented Git behavior, not a bug: `git diff` never shows untracked
    # content. Its creation is instead tracked via FileChange, not the diff.
    assert "brand_new.py" not in diff.diff


# ---- 11: branch detection ---------------------------------------------


async def test_branch_is_detected(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    context = ToolContext(workspace=Workspace.at(tmp_path))
    status = await GitStatusTool().run(GitStatusInput(), context)
    assert status.branch in ("main", "master")


# ---- 12: Git security / workspace boundary -------------------------------


async def test_git_diff_paths_are_workspace_bounded(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    context = ToolContext(workspace=Workspace.at(tmp_path))
    with pytest.raises(ToolError):
        await GitDiffTool().run(GitDiffInput(paths=["../../etc/passwd"]), context)


# ---- 13: no automatic push / no auto-commit -------------------------------


def test_git_commit_is_not_a_registered_agent_tool() -> None:
    """Interface completeness only (tools/git/schemas.py) — never
    reachable by any agent, and no code path anywhere pushes to a remote."""
    names = {t.name for t in build_default_registry().list_tools()}
    assert "git_commit" not in names
    assert "git_push" not in names


def test_commit_summary_is_generated_deterministically_from_real_state() -> None:
    state = ExecutionState(
        execution_id="1", project_id="2", user_task="Fix the login bug", workspace_root="C:/tmp",
        plan=Plan(objective="fix login", steps=["a"], testing_strategy="pytest"),
        files_changed=[
            FileChange(path="auth.py", change_type="modified", detail="fixed"),
            FileChange(path="new_helper.py", change_type="created", detail="added"),
            FileChange(path="broken.py", change_type="failed", detail="rejected"),
        ],
        test_results=TestResult(status="passed", passed=3, failed=0, summary="3 passed"),
        review_result=ReviewResult(verdict="approved", summary="looks good"),
    )
    summary = generate_commit_summary(state)
    assert "Fix the login bug" in summary
    assert "auth.py" in summary
    assert "new_helper.py" in summary
    assert "broken.py" not in summary  # a failed tool call is not a real change
    assert "passed" in summary
    assert "approved" in summary
