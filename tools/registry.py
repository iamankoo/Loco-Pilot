"""Central registry of controlled tools.

Agents never import tool implementations directly — they ask the registry
for a named tool (or the subset of tools their permission set allows), so
a Planner/Reviewer can be handed a read-only tool set while a Developer
gets read+write, without any tool implementation needing to know about
agent roles.
"""

from __future__ import annotations

from tools.base import Permission, Tool


class ToolNotFoundError(Exception):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Unknown tool: {name!r}") from exc

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self, *, permissions: set[Permission] | None = None) -> list[Tool]:
        tools = list(self._tools.values())
        if permissions is not None:
            tools = [t for t in tools if t.permission in permissions]
        return tools

    def schemas(self, *, permissions: set[Permission] | None = None) -> list[dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "permission": tool.permission.value,
                "input_schema": tool.input_schema(),
                "output_schema": tool.output_schema(),
            }
            for tool in self.list_tools(permissions=permissions)
        ]


# Convenience permission sets for restricting an agent's tool surface.
READ_ONLY: set[Permission] = {Permission.READ}
DEVELOPER: set[Permission] = {Permission.READ, Permission.WRITE, Permission.GIT_WRITE}
FULL_ACCESS: set[Permission] = {Permission.READ, Permission.WRITE, Permission.GIT_WRITE, Permission.EXECUTE}


def build_default_registry() -> ToolRegistry:
    """Constructs the registry with every Phase 1.2 tool registered.

    Deliberately excludes: `git_commit` (interface exists, not yet exposed
    for agent use) and any terminal/execute tool (Phase 1.2 only defines
    the terminal contract; nothing implementing `Permission.EXECUTE` is
    registered until the Phase 1.3 Docker sandbox exists).
    """
    from tools.filesystem.tools import (
        EditFileTool,
        ListDirectoryTool,
        ReadFileTool,
        SearchFilesTool,
        WriteFileTool,
    )
    from tools.git.tools import (
        GitBranchTool,
        GitCreateBranchTool,
        GitDiffTool,
        GitStatusTool,
    )

    registry = ToolRegistry()
    for tool in (
        ListDirectoryTool(),
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        SearchFilesTool(),
        GitStatusTool(),
        GitDiffTool(),
        GitBranchTool(),
        GitCreateBranchTool(),
    ):
        registry.register(tool)
    return registry
