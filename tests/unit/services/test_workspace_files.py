from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi import UploadFile

from backend.app.services.workspace_files import (
    WorkspaceFileError,
    list_workspace_entries,
    save_uploaded_files,
)


def _upload(filename: str, content: bytes = b"x") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename)


def test_list_workspace_entries_returns_root_contents(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("print(1)")
    (tmp_path / "sub").mkdir()
    (tmp_path / ".git").mkdir()  # excluded dir must not appear

    entries = list_workspace_entries(str(tmp_path), "")
    names = {e.name for e in entries}
    assert names == {"a.py", "sub"}


def test_list_workspace_entries_lists_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("print(2)")

    entries = list_workspace_entries(str(tmp_path), "sub")
    assert [e.name for e in entries] == ["b.py"]
    assert entries[0].path == "sub/b.py"


def test_list_workspace_entries_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceFileError, match="escapes workspace root"):
        list_workspace_entries(str(tmp_path), "../../../etc")


def test_list_workspace_entries_rejects_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceFileError):
        list_workspace_entries(str(tmp_path), "/etc/passwd")


def test_list_workspace_entries_rejects_missing_workspace_path() -> None:
    with pytest.raises(WorkspaceFileError, match="no workspace_path"):
        list_workspace_entries(None, "")


def test_list_workspace_entries_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceFileError, match="not found"):
        list_workspace_entries(str(tmp_path), "does-not-exist")


async def test_save_uploaded_files_saves_allowed_extension(tmp_path: Path) -> None:
    saved = await save_uploaded_files(str(tmp_path), [_upload("script.py", b"print('hi')")])
    assert len(saved) == 1
    assert saved[0].relative_path == "uploads/script.py"
    assert (tmp_path / "uploads" / "script.py").read_bytes() == b"print('hi')"


async def test_save_uploaded_files_rejects_disallowed_extension(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceFileError, match="not allowed"):
        await save_uploaded_files(str(tmp_path), [_upload("payload.exe", b"MZ")])


async def test_save_uploaded_files_rejects_oversized_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.app.services.workspace_files as module

    monkeypatch.setattr(module, "MAX_UPLOAD_BYTES", 4)
    with pytest.raises(WorkspaceFileError, match="too large"):
        await save_uploaded_files(str(tmp_path), [_upload("big.txt", b"way more than four bytes")])


async def test_save_uploaded_files_strips_path_from_filename(tmp_path: Path) -> None:
    # A malicious/careless client-supplied filename must never be treated
    # as a path — only its basename is used, and it lands in uploads/.
    saved = await save_uploaded_files(str(tmp_path), [_upload("../../evil.py", b"x")])
    assert saved[0].filename == "evil.py"
    assert saved[0].relative_path == "uploads/evil.py"
    assert not (tmp_path.parent.parent / "evil.py").exists()


async def test_save_uploaded_files_deduplicates_same_filename(tmp_path: Path) -> None:
    first = await save_uploaded_files(str(tmp_path), [_upload("dup.py", b"one")])
    second = await save_uploaded_files(str(tmp_path), [_upload("dup.py", b"two")])
    assert first[0].relative_path == "uploads/dup.py"
    assert second[0].relative_path == "uploads/dup-1.py"
    assert (tmp_path / "uploads" / "dup.py").read_bytes() == b"one"
    assert (tmp_path / "uploads" / "dup-1.py").read_bytes() == b"two"
