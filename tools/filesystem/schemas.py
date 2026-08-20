from __future__ import annotations

from pydantic import BaseModel, Field

MAX_READ_BYTES = 1_000_000
MAX_WRITE_BYTES = 2_000_000
MAX_SEARCH_FILE_BYTES = 2_000_000
DEFAULT_EXCLUDED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "build", "dist", ".pytest_cache", ".mypy_cache"}


class DirEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None = None


class ListDirectoryInput(BaseModel):
    path: str = "."


class ListDirectoryOutput(BaseModel):
    path: str
    entries: list[DirEntry]


class ReadFileInput(BaseModel):
    path: str
    max_bytes: int = Field(default=MAX_READ_BYTES, gt=0, le=MAX_READ_BYTES)


class ReadFileOutput(BaseModel):
    path: str
    content: str
    truncated: bool
    size_bytes: int


class WriteFileInput(BaseModel):
    path: str
    content: str
    create_parents: bool = True
    overwrite: bool = True


class WriteFileOutput(BaseModel):
    path: str
    bytes_written: int
    created: bool


class EditFileInput(BaseModel):
    path: str
    old_string: str
    new_string: str


class EditFileOutput(BaseModel):
    path: str
    replaced: bool
    occurrences: int


class SearchFilesInput(BaseModel):
    query: str
    path: str = "."
    glob: str | None = None
    max_results: int = Field(default=200, gt=0, le=1000)
    case_sensitive: bool = False


class SearchMatch(BaseModel):
    path: str
    line_number: int
    line: str


class SearchFilesOutput(BaseModel):
    query: str
    matches: list[SearchMatch]
    truncated: bool
