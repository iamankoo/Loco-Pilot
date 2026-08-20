"""Filesystem tools: list_directory, read_file, write_file, edit_file, search_files.

Every tool resolves paths through `context.workspace.resolve()` — that is
the only place a path is turned into something touching the real
filesystem. No tool builds a path by string concatenation.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from tools.base import Permission, Tool, ToolContext, ToolError
from tools.filesystem.schemas import (
    DEFAULT_EXCLUDED_DIRS,
    MAX_SEARCH_FILE_BYTES,
    MAX_WRITE_BYTES,
    DirEntry,
    EditFileInput,
    EditFileOutput,
    ListDirectoryInput,
    ListDirectoryOutput,
    ReadFileInput,
    ReadFileOutput,
    SearchFilesInput,
    SearchFilesOutput,
    SearchMatch,
    WriteFileInput,
    WriteFileOutput,
)
from tools.workspace import WorkspaceError


def _is_probably_binary(data: bytes) -> bool:
    return b"\x00" in data[:8000]


class ListDirectoryTool(Tool[ListDirectoryInput, ListDirectoryOutput]):
    name = "list_directory"
    description = "List the immediate contents of a directory within the workspace."
    permission = Permission.READ
    input_model = ListDirectoryInput
    output_model = ListDirectoryOutput

    async def run(self, tool_input: ListDirectoryInput, context: ToolContext) -> ListDirectoryOutput:
        try:
            target = context.workspace.resolve(tool_input.path)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc

        if not target.exists():
            raise ToolError(f"Directory not found: {tool_input.path}")
        if not target.is_dir():
            raise ToolError(f"Not a directory: {tool_input.path}")

        entries: list[DirEntry] = []
        try:
            children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as exc:
            raise ToolError(f"Failed to list directory: {exc}") from exc

        for child in children:
            is_dir = child.is_dir()
            size = None if is_dir else child.stat().st_size
            entries.append(
                DirEntry(
                    name=child.name,
                    path=context.workspace.relative(child),
                    is_dir=is_dir,
                    size_bytes=size,
                )
            )

        return ListDirectoryOutput(path=tool_input.path, entries=entries)


class ReadFileTool(Tool[ReadFileInput, ReadFileOutput]):
    name = "read_file"
    description = "Read the text content of a file within the workspace."
    permission = Permission.READ
    input_model = ReadFileInput
    output_model = ReadFileOutput

    async def run(self, tool_input: ReadFileInput, context: ToolContext) -> ReadFileOutput:
        try:
            target = context.workspace.resolve(tool_input.path)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc

        if not target.exists():
            raise ToolError(f"File not found: {tool_input.path}")
        if not target.is_file():
            raise ToolError(f"Not a file: {tool_input.path}")

        size_bytes = target.stat().st_size
        try:
            raw = target.read_bytes()[: tool_input.max_bytes]
        except OSError as exc:
            raise ToolError(f"Failed to read file: {exc}") from exc

        if _is_probably_binary(raw):
            raise ToolError(f"Refusing to read binary file: {tool_input.path}")

        content = raw.decode("utf-8", errors="replace")
        truncated = size_bytes > tool_input.max_bytes

        return ReadFileOutput(path=tool_input.path, content=content, truncated=truncated, size_bytes=size_bytes)


class WriteFileTool(Tool[WriteFileInput, WriteFileOutput]):
    name = "write_file"
    description = "Write text content to a file within the workspace, creating or overwriting it."
    permission = Permission.WRITE
    input_model = WriteFileInput
    output_model = WriteFileOutput

    async def run(self, tool_input: WriteFileInput, context: ToolContext) -> WriteFileOutput:
        content_bytes = tool_input.content.encode("utf-8")
        if len(content_bytes) > MAX_WRITE_BYTES:
            raise ToolError(f"Content exceeds maximum write size of {MAX_WRITE_BYTES} bytes.")

        try:
            target = context.workspace.resolve(tool_input.path)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc

        already_existed = target.exists()
        if already_existed and target.is_dir():
            raise ToolError(f"Cannot write to a directory: {tool_input.path}")
        if already_existed and not tool_input.overwrite:
            raise ToolError(f"File already exists and overwrite=False: {tool_input.path}")

        if not target.parent.exists():
            if not tool_input.create_parents:
                raise ToolError(f"Parent directory does not exist: {tool_input.path}")
            target.parent.mkdir(parents=True, exist_ok=True)

        try:
            target.write_bytes(content_bytes)
        except OSError as exc:
            raise ToolError(f"Failed to write file: {exc}") from exc

        return WriteFileOutput(
            path=tool_input.path,
            bytes_written=len(content_bytes),
            created=not already_existed,
        )


class EditFileTool(Tool[EditFileInput, EditFileOutput]):
    name = "edit_file"
    description = (
        "Replace an exact, unique occurrence of old_string with new_string in a workspace file. "
        "Fails if old_string is missing or not unique, so edits are deterministic."
    )
    permission = Permission.WRITE
    input_model = EditFileInput
    output_model = EditFileOutput

    async def run(self, tool_input: EditFileInput, context: ToolContext) -> EditFileOutput:
        if tool_input.old_string == "":
            raise ToolError("old_string must not be empty.")
        if tool_input.old_string == tool_input.new_string:
            raise ToolError("old_string and new_string are identical; nothing to edit.")

        try:
            target = context.workspace.resolve(tool_input.path)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc

        if not target.exists():
            raise ToolError(f"File not found: {tool_input.path}")
        if not target.is_file():
            raise ToolError(f"Not a file: {tool_input.path}")

        try:
            original = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"Refusing to edit binary/non-UTF-8 file: {tool_input.path}") from exc
        except OSError as exc:
            raise ToolError(f"Failed to read file: {exc}") from exc

        occurrences = original.count(tool_input.old_string)
        if occurrences == 0:
            raise ToolError("old_string was not found in the file.")
        if occurrences > 1:
            raise ToolError(f"old_string is not unique ({occurrences} matches); provide more surrounding context.")

        updated = original.replace(tool_input.old_string, tool_input.new_string, 1)
        try:
            target.write_text(updated, encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Failed to write file: {exc}") from exc

        return EditFileOutput(path=tool_input.path, replaced=True, occurrences=occurrences)


class SearchFilesTool(Tool[SearchFilesInput, SearchFilesOutput]):
    name = "search_files"
    description = "Search text files in the workspace for a query string, returning matching lines."
    permission = Permission.READ
    input_model = SearchFilesInput
    output_model = SearchFilesOutput

    async def run(self, tool_input: SearchFilesInput, context: ToolContext) -> SearchFilesOutput:
        if not tool_input.query:
            raise ToolError("query must not be empty.")

        try:
            search_root = context.workspace.resolve(tool_input.path)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc

        if not search_root.exists() or not search_root.is_dir():
            raise ToolError(f"Search path is not a directory: {tool_input.path}")

        needle = tool_input.query if tool_input.case_sensitive else tool_input.query.lower()
        matches: list[SearchMatch] = []
        truncated = False

        for dirpath, dirnames, filenames in os.walk(search_root):
            dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDED_DIRS]
            for filename in sorted(filenames):
                if tool_input.glob and not fnmatch.fnmatch(filename, tool_input.glob):
                    continue

                file_path = Path(dirpath) / filename
                try:
                    if file_path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                        continue
                    raw = file_path.read_bytes()
                except OSError:
                    continue
                if _is_probably_binary(raw):
                    continue

                text = raw.decode("utf-8", errors="replace")
                for line_number, line in enumerate(text.splitlines(), start=1):
                    haystack = line if tool_input.case_sensitive else line.lower()
                    if needle in haystack:
                        matches.append(
                            SearchMatch(
                                path=context.workspace.relative(file_path),
                                line_number=line_number,
                                line=line.strip()[:500],
                            )
                        )
                        if len(matches) >= tool_input.max_results:
                            truncated = True
                            break
                if truncated:
                    break
            if truncated:
                break

        return SearchFilesOutput(query=tool_input.query, matches=matches, truncated=truncated)
