from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from execution.docker.errors import WorkspaceTransferError
from execution.docker.policy import NetworkPolicy, ResourceLimits
from execution.docker.sandbox import Sandbox
from tools.workspace import Workspace


def _inspect(name: str) -> dict:
    result = subprocess.run(["docker", "inspect", name], capture_output=True, text=True)
    return json.loads(result.stdout)[0]


async def test_only_workspace_bind_mount_exists(tmp_workspace: Workspace) -> None:
    """The only host path made available is the explicit project workspace
    — no full host filesystem mount, structurally verified via Docker's
    own mount list rather than trusting a functional probe."""
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        data = _inspect(sandbox.name)
        bind_mounts = [m for m in data["Mounts"] if m["Type"] == "bind"]
        assert len(bind_mounts) == 1
        assert Path(bind_mounts[0]["Source"]).resolve() == tmp_workspace.root.resolve()
        assert bind_mounts[0]["Destination"] == "/workspace"
    finally:
        await sandbox.destroy()


async def test_cwd_parent_traversal_escape_rejected(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        await sandbox.start()
        with pytest.raises(WorkspaceTransferError):
            await sandbox.execute(["python", "-c", "print(1)"], cwd="../../etc")
    finally:
        await sandbox.destroy()


async def test_cwd_absolute_path_escape_rejected(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        await sandbox.start()
        with pytest.raises(WorkspaceTransferError):
            await sandbox.execute(["python", "-c", "print(1)"], cwd="/etc")
    finally:
        await sandbox.destroy()


async def test_host_environment_variables_are_not_leaked(monkeypatch, tmp_workspace: Workspace) -> None:
    monkeypatch.setenv("LOCOPILOT_TEST_HOST_SECRET", "should-not-leak")
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        await sandbox.start()
        result = await sandbox.execute(
            ["python", "-c", "import os; print(os.environ.get('LOCOPILOT_TEST_HOST_SECRET', 'NOT_PRESENT'))"]
        )
        assert result.stdout.strip() == "NOT_PRESENT"
    finally:
        await sandbox.destroy()


async def test_explicit_env_is_passed_through_when_given(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        await sandbox.start()
        result = await sandbox.execute(
            ["python", "-c", "import os; print(os.environ.get('EXPLICIT_VAR'))"],
            env={"EXPLICIT_VAR": "hello"},
        )
        assert result.stdout.strip() == "hello"
    finally:
        await sandbox.destroy()


async def test_network_disabled_by_default_at_docker_level(tmp_workspace: Workspace) -> None:
    """Structural check (not a live connection attempt, which would be
    unreliable on an offline test host either way): the container's
    NetworkMode is literally "none"."""
    sandbox = Sandbox(tmp_workspace)
    try:
        await sandbox.create()
        data = _inspect(sandbox.name)
        assert data["HostConfig"]["NetworkMode"] == "none"
    finally:
        await sandbox.destroy()


async def test_network_disabled_actually_blocks_a_connection_attempt(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        await sandbox.start()
        result = await sandbox.execute(
            ["python", "-c", "import socket; socket.create_connection(('8.8.8.8', 53), timeout=3)"]
        )
        assert result.exit_code != 0
    finally:
        await sandbox.destroy()


async def test_network_allowed_policy_sets_a_real_network_mode(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, network_policy=NetworkPolicy.ALLOWED)
    try:
        await sandbox.create()
        data = _inspect(sandbox.name)
        assert data["HostConfig"]["NetworkMode"] != "none"
    finally:
        await sandbox.destroy()


async def test_network_restricted_is_not_implemented_yet(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, network_policy=NetworkPolicy.RESTRICTED)
    with pytest.raises(NotImplementedError):
        await sandbox.create()


async def test_container_runs_as_non_root(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        await sandbox.start()
        result = await sandbox.execute(["id", "-u"])
        assert result.stdout.strip() == "1000"
        assert result.stdout.strip() != "0"
    finally:
        await sandbox.destroy()


async def test_container_is_never_privileged(tmp_workspace: Workspace) -> None:
    """Sandbox.create() never passes --privileged — verified by constructing
    a real container and checking Docker's own record of it, not just
    reading the source."""
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        data = _inspect(sandbox.name)
        assert data["HostConfig"]["Privileged"] is False
        assert data["HostConfig"]["ReadonlyRootfs"] is True
        assert "ALL" in (data["HostConfig"].get("CapDrop") or [])
    finally:
        await sandbox.destroy()


async def test_read_only_rootfs_rejects_writes_outside_workspace(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        await sandbox.start()
        result = await sandbox.execute(["python", "-c", "open('/etc/should-fail', 'w').write('x')"])
        assert result.exit_code != 0
    finally:
        await sandbox.destroy()


async def test_workspace_writes_remain_possible_and_visible_on_host(tmp_workspace: Workspace) -> None:
    sandbox = Sandbox(tmp_workspace, resource_limits=ResourceLimits(timeout_seconds=10))
    try:
        await sandbox.create()
        await sandbox.start()
        result = await sandbox.execute(["python", "-c", "open('written.txt', 'w').write('ok')"])
        assert result.exit_code == 0
    finally:
        await sandbox.destroy()

    assert (tmp_workspace.root / "written.txt").read_text() == "ok"
