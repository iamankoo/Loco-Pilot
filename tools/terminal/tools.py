"""The one execute-capable tool: execute_terminal_command.

Agent -> Tool Registry -> Permission Check -> this tool -> Sandbox ->
Docker -> Command. This is the only path from an agent to Docker; agents
never import `execution.docker` themselves.
"""

from __future__ import annotations

from execution.docker.errors import SandboxError
from tools.base import Permission, Tool, ToolContext, ToolError
from tools.terminal.contract import TerminalCommandRequest, TerminalCommandResult
from tools.terminal.docker_executor import DockerTerminalExecutor


class ExecuteTerminalCommandTool(Tool[TerminalCommandRequest, TerminalCommandResult]):
    name = "execute_terminal_command"
    description = (
        "Run a command (argv, never a shell string) inside an isolated, network-disabled Docker "
        "sandbox scoped to the workspace. Use for running a project's test/build commands."
    )
    permission = Permission.EXECUTE
    input_model = TerminalCommandRequest
    output_model = TerminalCommandResult

    async def run(self, tool_input: TerminalCommandRequest, context: ToolContext) -> TerminalCommandResult:
        executor = DockerTerminalExecutor(context.workspace)
        try:
            return await executor.run(tool_input)
        except SandboxError as exc:
            raise ToolError(str(exc)) from exc
