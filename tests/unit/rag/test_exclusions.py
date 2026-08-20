from __future__ import annotations

from pathlib import Path

from rag.exclusions import is_excluded_dir, is_supported_file


def test_excludes_git_and_common_vendor_dirs() -> None:
    for name in (".git", "node_modules", ".venv", "__pycache__", "dist", "build"):
        assert is_excluded_dir(name) is True


def test_does_not_exclude_ordinary_source_dirs() -> None:
    for name in ("src", "app", "tests", "lib"):
        assert is_excluded_dir(name) is False


def test_supports_common_source_extensions() -> None:
    for name in ("main.py", "index.ts", "App.jsx", "README.md", "config.yaml"):
        assert is_supported_file(Path(name)) is True


def test_rejects_unsupported_extensions() -> None:
    for name in ("image.png", "archive.zip", "binary.exe", "data.bin"):
        assert is_supported_file(Path(name)) is False
