from __future__ import annotations

import subprocess

import pytest


def _docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _sandbox_image_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "locopilot-sandbox-python:1.0"], capture_output=True, timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.fixture(autouse=True)
def _require_docker_and_image() -> None:
    if not _docker_available():
        pytest.skip("Docker is not available in this environment.")
    if not _sandbox_image_available():
        pytest.skip(
            "locopilot-sandbox-python:1.0 image is not built. Run: "
            "docker build -t locopilot-sandbox-python:1.0 -f execution/docker/Dockerfile execution/docker"
        )
