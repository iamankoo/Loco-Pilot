"""Filesystem tools: list_directory, read_file, write_file, edit_file,
delete_file, move_file, file_exists, search_files.

Every tool resolves paths through `context.workspace.resolve()` — that is
the only place a path is turned into something touching the real
filesystem. No tool builds a path by string concatenation, and no tool
ever shells out for a filesystem operation (pathlib/os/shutil only).
"""

from __future__ import annotations

import base64
import binascii
import fnmatch
import os
import shutil
from pathlib import Path

from tools.base import Permission, Tool, ToolContext, ToolError
from tools.diffing import compute_diff
from tools.filesystem.schemas import (
    DEFAULT_EXCLUDED_DIRS,
    MAX_SEARCH_FILE_BYTES,
    MAX_WRITE_BYTES,
    DeleteFileInput,
    DeleteFileOutput,
    DirEntry,
    EditFileInput,
    EditFileOutput,
    FileExistsInput,
    FileExistsOutput,
    ListDirectoryInput,
    ListDirectoryOutput,
    MoveFileInput,
    MoveFileOutput,
    ReadFileInput,
    ReadFileOutput,
    SearchFilesInput,
    SearchFilesOutput,
    SearchMatch,
    WriteFileInput,
    WriteFileOutput,
)
from tools.workspace import WorkspaceError

# The diff and "before content" helpers cap themselves at this size purely
# to decide whether a text diff is worth computing at all — a file this
# large is already at the edge of what `read_file` would even hand an
# agent, so a byte-for-byte diff of it is not useful context either.
_MAX_DIFFABLE_BYTES = MAX_WRITE_BYTES


def _is_probably_binary(data: bytes) -> bool:
    return b"\x00" in data[:8000]


def _read_text_for_diff(path: Path) -> str | None:
    """Best-effort "before" snapshot for diff generation — never raises:
    a missing/binary/oversized/unreadable file just means no diff, not a
    failed operation."""
    try:
        if not path.is_file() or path.stat().st_size > _MAX_DIFFABLE_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if _is_probably_binary(raw):
        return None
    return raw.decode("utf-8", errors="replace")


class ListDirectoryTool(Tool[ListDirectoryInput, ListDirectoryOutput]):
    name = "list_directory"
    description = (
        "List the contents of a directory within the workspace. `max_depth` (default 1) controls how "
        "many levels below `path` are included; noise directories (.git, node_modules, .venv, ...) are "
        "never recursed into, though they still appear as an entry at whatever depth they're found."
    )
    permission = Permission.READ
    input_model = ListDirectoryInput
    output_model = ListDirectoryOutput

    async def run(self, tool_input: ListDirectoryInput, context: ToolContext) -> ListDirectoryOutput:
        try:
            target = context.workspace.resolve(tool_input.path)
        except WorkspaceError as exc:
            raise ToolError(str(exc), code="PATH_OUTSIDE_WORKSPACE") from exc

        if not target.exists():
            raise ToolError(f"Directory not found: {tool_input.path}", code="FILE_NOT_FOUND")
        if not target.is_dir():
            raise ToolError(f"Not a directory: {tool_input.path}", code="INVALID_PATH")

        entries: list[DirEntry] = []
        truncated = False

        try:
            for dirpath, dirnames, filenames in os.walk(target):
                current = Path(dirpath)
                depth = len(current.relative_to(target).parts)
                child_depth = depth + 1

                listed_dirnames = sorted(dirnames, key=str.lower)
                if child_depth > tool_input.max_depth:
                    dirnames[:] = []
                    continue
                dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDED_DIRS]

                for name in listed_dirnames:
                    entries.append(DirEntry(name=name, path=context.workspace.relative(current / name), is_dir=True))
                    if len(entries) >= tool_input.max_results:
                        truncated = True
                        break
                if not truncated:
                    for name in sorted(filenames, key=str.lower):
                        child = current / name
                        try:
                            size = child.stat().st_size
                        except OSError:
                            size = None
                        entries.append(
                            DirEntry(name=name, path=context.workspace.relative(child), is_dir=False, size_bytes=size)
                        )
                        if len(entries) >= tool_input.max_results:
                            truncated = True
                            break
                if truncated:
                    break
        except OSError as exc:
            raise ToolError(f"Failed to list directory: {exc}") from exc

        return ListDirectoryOutput(path=tool_input.path, entries=entries, truncated=truncated)


class ReadFileTool(Tool[ReadFileInput, ReadFileOutput]):
    name = "read_file"
    description = (
        "Read the text content of a file within the workspace. Optionally pass start_line/end_line "
        "(1-indexed, inclusive) to read only part of a large file."
    )
    permission = Permission.READ
    input_model = ReadFileInput
    output_model = ReadFileOutput

    async def run(self, tool_input: ReadFileInput, context: ToolContext) -> ReadFileOutput:
        try:
            target = context.workspace.resolve(tool_input.path)
        except WorkspaceError as exc:
            raise ToolError(str(exc), code="PATH_OUTSIDE_WORKSPACE") from exc

        if not target.exists():
            raise ToolError(f"File not found: {tool_input.path}", code="FILE_NOT_FOUND")
        if not target.is_file():
            raise ToolError(f"Not a file: {tool_input.path}", code="INVALID_PATH")

        size_bytes = target.stat().st_size
        try:
            raw = target.read_bytes()[: tool_input.max_bytes]
        except OSError as exc:
            raise ToolError(f"Failed to read file: {exc}") from exc

        if _is_probably_binary(raw):
            raise ToolError(f"Refusing to read binary file: {tool_input.path}", code="BINARY_FILE")

        content = raw.decode("utf-8", errors="replace")
        truncated = size_bytes > tool_input.max_bytes

        lines = content.split("\n")
        line_count = len(lines) - 1 if content.endswith("\n") and lines[-1] == "" else len(lines)

        if tool_input.start_line is not None or tool_input.end_line is not None:
            start = max((tool_input.start_line or 1) - 1, 0)
            end = tool_input.end_line if tool_input.end_line is not None else line_count
            if start >= end or start >= line_count:
                raise ToolError(
                    f"Requested line range (start_line={tool_input.start_line}, end_line={tool_input.end_line}) "
                    f"is empty or out of bounds for a {line_count}-line file.",
                    code="INVALID_PATH",
                )
            content = "\n".join(lines[start:end])

        return ReadFileOutput(
            path=tool_input.path,
            content=content,
            truncated=truncated,
            size_bytes=size_bytes,
            line_count=line_count,
            start_line=tool_input.start_line,
            end_line=tool_input.end_line,
        )


class WriteFileTool(Tool[WriteFileInput, WriteFileOutput]):
    name = "write_file"
    description = (
        "Write content to a file within the workspace, creating or overwriting it. "
        "encoding='text' (default) writes `content` as UTF-8 text. encoding='base64' decodes `content` "
        "as standard base64 and writes the real binary bytes — use this for any binary asset "
        "(PNG/JPEG/GIF/WebP image, etc.); writing base64 text with encoding='text' produces a "
        "corrupt, unopenable file."
    )
    permission = Permission.WRITE
    input_model = WriteFileInput
    output_model = WriteFileOutput

    async def run(self, tool_input: WriteFileInput, context: ToolContext) -> WriteFileOutput:
        if tool_input.encoding == "base64":
            try:
                content_bytes = base64.b64decode(tool_input.content, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ToolError(f"Invalid base64 content: {exc}", code="INVALID_BASE64") from exc
        else:
            content_bytes = tool_input.content.encode("utf-8")

        if len(content_bytes) > MAX_WRITE_BYTES:
            raise ToolError(f"Content exceeds maximum write size of {MAX_WRITE_BYTES} bytes.", code="FILE_TOO_LARGE")

        try:
            target = context.workspace.resolve(tool_input.path)
        except WorkspaceError as exc:
            raise ToolError(str(exc), code="PATH_OUTSIDE_WORKSPACE") from exc

        already_existed = target.exists()
        if already_existed and target.is_dir():
            raise ToolError(f"Cannot write to a directory: {tool_input.path}", code="INVALID_PATH")
        if already_existed and not tool_input.overwrite:
            raise ToolError(f"File already exists and overwrite=False: {tool_input.path}", code="DESTINATION_EXISTS")

        before_text = _read_text_for_diff(target) if already_existed and tool_input.encoding == "text" else None

        if not target.parent.exists():
            if not tool_input.create_parents:
                raise ToolError(f"Parent directory does not exist: {tool_input.path}", code="FILE_NOT_FOUND")
            target.parent.mkdir(parents=True, exist_ok=True)

        try:
            target.write_bytes(content_bytes)
        except OSError as exc:
            raise ToolError(f"Failed to write file: {exc}") from exc

        # Verify the mutation actually happened as expected rather than
        # trusting that `write_bytes` not raising means success.
        if not target.is_file() or target.stat().st_size != len(content_bytes):
            raise ToolError(f"Write verification failed: {tool_input.path}")

        if tool_input.encoding == "base64":
            # A byte-for-byte diff of binary content isn't useful context —
            # a one-line description of what happened is (matches how
            # _read_text_for_diff already treats an existing binary file:
            # no diff, just the fact that something changed).
            diff_text = f"Binary file {'created' if not already_existed else 'replaced'}: {tool_input.path} ({len(content_bytes)} bytes)"
            diff_truncated = False
        else:
            file_diff = compute_diff(tool_input.path, before_text, tool_input.content)
            diff_text = file_diff.diff
            diff_truncated = file_diff.truncated

        return WriteFileOutput(
            path=tool_input.path,
            bytes_written=len(content_bytes),
            created=not already_existed,
            diff=diff_text,
            diff_truncated=diff_truncated,
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
            raise ToolError("old_string must not be empty.", code="INVALID_PATH")
        if tool_input.old_string == tool_input.new_string:
            raise ToolError("old_string and new_string are identical; nothing to edit.", code="INVALID_PATH")

        try:
            target = context.workspace.resolve(tool_input.path)
        except WorkspaceError as exc:
            raise ToolError(str(exc), code="PATH_OUTSIDE_WORKSPACE") from exc

        if not target.exists():
            raise ToolError(f"File not found: {tool_input.path}", code="FILE_NOT_FOUND")
        if not target.is_file():
            raise ToolError(f"Not a file: {tool_input.path}", code="INVALID_PATH")

        try:
            original = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"Refusing to edit binary/non-UTF-8 file: {tool_input.path}", code="BINARY_FILE") from exc
        except OSError as exc:
            raise ToolError(f"Failed to read file: {exc}") from exc

        occurrences = original.count(tool_input.old_string)
        if occurrences == 0:
            raise ToolError("old_string was not found in the file.", code="NO_MATCH")
        if occurrences > 1:
            raise ToolError(
                f"old_string is not unique ({occurrences} matches); provide more surrounding context.",
                code="MULTIPLE_MATCHES",
            )

        updated = original.replace(tool_input.old_string, tool_input.new_string, 1)
        try:
            target.write_text(updated, encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Failed to write file: {exc}") from exc

        # Verify: re-read and confirm the change actually landed.
        if target.read_text(encoding="utf-8") != updated:
            raise ToolError(f"Edit verification failed: {tool_input.path}")

        file_diff = compute_diff(tool_input.path, original, updated)

        return EditFileOutput(
            path=tool_input.path,
            replaced=True,
            occurrences=occurrences,
            diff=file_diff.diff,
            diff_truncated=file_diff.truncated,
        )


class DeleteFileTool(Tool[DeleteFileInput, DeleteFileOutput]):
    name = "delete_file"
    description = (
        "Delete a file or directory within the workspace. Deleting a non-empty directory requires "
        "recursive=True. Refuses to delete the workspace root."
    )
    permission = Permission.WRITE
    input_model = DeleteFileInput
    output_model = DeleteFileOutput

    async def run(self, tool_input: DeleteFileInput, context: ToolContext) -> DeleteFileOutput:
        try:
            target = context.workspace.resolve(tool_input.path)
        except WorkspaceError as exc:
            raise ToolError(str(exc), code="PATH_OUTSIDE_WORKSPACE") from exc

        if target == context.workspace.root:
            raise ToolError("Refusing to delete the workspace root.", code="INVALID_PATH")
        if not target.exists():
            raise ToolError(f"File or directory not found: {tool_input.path}", code="FILE_NOT_FOUND")

        # `workspace.resolve()` has already fully dereferenced any symlink
        # in `tool_input.path` to its real target (and already rejected one
        # escaping the workspace) — `target` here is always a real file or
        # directory, never a symlink itself, so there is no separate
        # "unlink the link without following it" case to handle.
        was_directory = target.is_dir()
        before_text = None if was_directory else _read_text_for_diff(target)

        if was_directory:
            has_children = any(target.iterdir())
            if has_children and not tool_input.recursive:
                raise ToolError(
                    f"Directory is not empty: {tool_input.path} (pass recursive=True to delete it anyway).",
                    code="DIRECTORY_NOT_EMPTY",
                )
            try:
                if has_children:
                    shutil.rmtree(target)
                else:
                    target.rmdir()
            except OSError as exc:
                raise ToolError(f"Failed to delete directory: {exc}") from exc
        else:
            try:
                target.unlink()
            except OSError as exc:
                raise ToolError(f"Failed to delete file: {exc}") from exc

        if target.exists():
            raise ToolError(f"Deletion verification failed: {tool_input.path}")

        file_diff = compute_diff(tool_input.path, before_text, None) if before_text is not None else None

        return DeleteFileOutput(
            path=tool_input.path,
            deleted=True,
            was_directory=was_directory,
            diff=file_diff.diff if file_diff else "",
            diff_truncated=file_diff.truncated if file_diff else False,
        )


class MoveFileTool(Tool[MoveFileInput, MoveFileOutput]):
    name = "move_file"
    description = (
        "Move or rename a file or directory within the workspace. Both source and destination must "
        "resolve inside the workspace; refuses to silently overwrite an existing destination unless "
        "overwrite=True (and never overwrites an existing directory)."
    )
    permission = Permission.WRITE
    input_model = MoveFileInput
    output_model = MoveFileOutput

    async def run(self, tool_input: MoveFileInput, context: ToolContext) -> MoveFileOutput:
        try:
            source = context.workspace.resolve(tool_input.source_path)
        except WorkspaceError as exc:
            raise ToolError(f"Invalid source_path: {exc}", code="PATH_OUTSIDE_WORKSPACE") from exc
        try:
            destination = context.workspace.resolve(tool_input.destination_path)
        except WorkspaceError as exc:
            raise ToolError(f"Invalid destination_path: {exc}", code="PATH_OUTSIDE_WORKSPACE") from exc

        if source == context.workspace.root:
            raise ToolError("Refusing to move the workspace root.", code="INVALID_PATH")
        if not source.exists():
            raise ToolError(f"Source not found: {tool_input.source_path}", code="FILE_NOT_FOUND")

        try:
            destination.relative_to(source)
        except ValueError:
            pass
        else:
            raise ToolError(
                f"Cannot move {tool_input.source_path} into its own subtree ({tool_input.destination_path}).",
                code="INVALID_PATH",
            )

        was_directory = source.is_dir()

        if destination.exists():
            if destination.is_dir():
                raise ToolError(
                    f"Destination directory already exists: {tool_input.destination_path}", code="DESTINATION_EXISTS"
                )
            if not tool_input.overwrite:
                raise ToolError(
                    f"Destination already exists: {tool_input.destination_path} (pass overwrite=True to replace it).",
                    code="DESTINATION_EXISTS",
                )
            try:
                destination.unlink()
            except OSError as exc:
                raise ToolError(f"Failed to remove existing destination: {exc}") from exc
        elif not destination.parent.exists():
            raise ToolError(
                f"Destination parent directory does not exist: {tool_input.destination_path}", code="FILE_NOT_FOUND"
            )

        try:
            shutil.move(str(source), str(destination))
        except OSError as exc:
            raise ToolError(f"Failed to move {tool_input.source_path} to {tool_input.destination_path}: {exc}") from exc

        if source.exists() or not destination.exists():
            raise ToolError(f"Move verification failed: {tool_input.source_path} -> {tool_input.destination_path}")

        return MoveFileOutput(
            source_path=tool_input.source_path,
            destination_path=tool_input.destination_path,
            moved=True,
            was_directory=was_directory,
        )


class FileExistsTool(Tool[FileExistsInput, FileExistsOutput]):
    name = "file_exists"
    description = "Check whether a path exists within the workspace, and whether it is a file or a directory."
    permission = Permission.READ
    input_model = FileExistsInput
    output_model = FileExistsOutput

    async def run(self, tool_input: FileExistsInput, context: ToolContext) -> FileExistsOutput:
        try:
            target = context.workspace.resolve(tool_input.path)
        except WorkspaceError as exc:
            raise ToolError(str(exc), code="PATH_OUTSIDE_WORKSPACE") from exc

        if not target.exists():
            return FileExistsOutput(path=tool_input.path, exists=False, type="none")
        return FileExistsOutput(
            path=tool_input.path, exists=True, type="directory" if target.is_dir() else "file"
        )


class SearchFilesTool(Tool[SearchFilesInput, SearchFilesOutput]):
    name = "search_files"
    description = (
        "Search the workspace for a query string. search_type='content' (default) matches file text; "
        "'filename' matches only the relative path; 'both' reports either kind of match."
    )
    permission = Permission.READ
    input_model = SearchFilesInput
    output_model = SearchFilesOutput

    async def run(self, tool_input: SearchFilesInput, context: ToolContext) -> SearchFilesOutput:
        if not tool_input.query:
            raise ToolError("query must not be empty.", code="INVALID_PATH")

        try:
            search_root = context.workspace.resolve(tool_input.path)
        except WorkspaceError as exc:
            raise ToolError(str(exc), code="PATH_OUTSIDE_WORKSPACE") from exc

        if not search_root.exists() or not search_root.is_dir():
            raise ToolError(f"Search path is not a directory: {tool_input.path}", code="INVALID_PATH")

        needle = tool_input.query if tool_input.case_sensitive else tool_input.query.lower()
        match_filenames = tool_input.search_type in ("filename", "both")
        match_content = tool_input.search_type in ("content", "both")
        matches: list[SearchMatch] = []
        truncated = False

        for dirpath, dirnames, filenames in os.walk(search_root):
            dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDED_DIRS]
            for filename in sorted(filenames):
                if tool_input.glob and not fnmatch.fnmatch(filename, tool_input.glob):
                    continue

                file_path = Path(dirpath) / filename
                relative_path = context.workspace.relative(file_path)
                haystack_path = relative_path if tool_input.case_sensitive else relative_path.lower()

                if match_filenames and needle in haystack_path:
                    matches.append(SearchMatch(path=relative_path, line_number=0, line=filename, match_type="filename"))
                    if len(matches) >= tool_input.max_results:
                        truncated = True
                        break

                if match_content:
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
                        haystack_line = line if tool_input.case_sensitive else line.lower()
                        if needle in haystack_line:
                            matches.append(
                                SearchMatch(
                                    path=relative_path,
                                    line_number=line_number,
                                    line=line.strip()[:500],
                                    match_type="content",
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
