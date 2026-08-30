from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MAX_READ_BYTES = 1_000_000
MAX_WRITE_BYTES = 2_000_000
MAX_SEARCH_FILE_BYTES = 2_000_000
MAX_LIST_RESULTS = 1000
MAX_LIST_DEPTH = 8
DEFAULT_EXCLUDED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "build", "dist", ".pytest_cache", ".mypy_cache"}


class DirEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None = None


class ListDirectoryInput(BaseModel):
    path: str = "."
    # 1 (default) preserves the original immediate-children-only behavior.
    # >1 walks further, pruning DEFAULT_EXCLUDED_DIRS, up to this many
    # levels below `path`.
    max_depth: int = Field(default=1, ge=1, le=MAX_LIST_DEPTH)
    max_results: int = Field(default=MAX_LIST_RESULTS, gt=0, le=MAX_LIST_RESULTS)


class ListDirectoryOutput(BaseModel):
    path: str
    entries: list[DirEntry]
    truncated: bool = False


class ReadFileInput(BaseModel):
    path: str
    max_bytes: int = Field(default=MAX_READ_BYTES, gt=0, le=MAX_READ_BYTES)
    # Optional 1-indexed, inclusive line range. Both omitted reads the
    # whole (size-bounded) file, unchanged from the original contract.
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class ReadFileOutput(BaseModel):
    path: str
    content: str
    truncated: bool
    size_bytes: int
    line_count: int
    start_line: int | None = None
    end_line: int | None = None


class WriteFileInput(BaseModel):
    path: str
    content: str
    create_parents: bool = True
    overwrite: bool = True
    # "text" (default, unchanged behavior): `content` is written as UTF-8
    # text. "base64": `content` is standard base64 of the real binary bytes
    # to write (e.g. an actual PNG/JPEG) — the only way a binary asset gets
    # created correctly, since an agent has no other channel to produce raw
    # bytes. Writing base64 TEXT as if it were the file's real content
    # (encoding="text") produces a corrupt, unopenable "image".
    encoding: Literal["text", "base64"] = "text"


class WriteFileOutput(BaseModel):
    path: str
    bytes_written: int
    created: bool
    diff: str = ""
    diff_truncated: bool = False


class EditFileInput(BaseModel):
    path: str
    old_string: str
    new_string: str


class EditFileOutput(BaseModel):
    path: str
    replaced: bool
    occurrences: int
    diff: str = ""
    diff_truncated: bool = False


class DeleteFileInput(BaseModel):
    path: str
    # Required to delete a non-empty directory — an empty directory (or a
    # single file) can always be deleted without it, so the flag only ever
    # gates the genuinely destructive case.
    recursive: bool = False


class DeleteFileOutput(BaseModel):
    path: str
    deleted: bool
    was_directory: bool
    diff: str = ""
    diff_truncated: bool = False


class MoveFileInput(BaseModel):
    source_path: str
    destination_path: str
    overwrite: bool = False


class MoveFileOutput(BaseModel):
    source_path: str
    destination_path: str
    moved: bool
    was_directory: bool


class FileExistsInput(BaseModel):
    path: str


class FileExistsOutput(BaseModel):
    path: str
    exists: bool
    type: Literal["file", "directory", "none"]


class SearchFilesInput(BaseModel):
    query: str
    path: str = "."
    glob: str | None = None
    max_results: int = Field(default=200, gt=0, le=1000)
    case_sensitive: bool = False
    # "content" (default, original behavior) matches file text; "filename"
    # matches only the relative path itself; "both" reports either kind.
    search_type: Literal["content", "filename", "both"] = "content"


class SearchMatch(BaseModel):
    path: str
    line_number: int
    line: str
    match_type: Literal["content", "filename"] = "content"


class SearchFilesOutput(BaseModel):
    query: str
    matches: list[SearchMatch]
    truncated: bool
