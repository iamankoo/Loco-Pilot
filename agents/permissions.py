"""Which Phase 1.2 tool permissions each agent role is granted.

Enforced twice: the registry only *shows* an agent tools within its set
(`ToolRegistry.list_tools(permissions=...)`), and `BaseAgent._call_tool`
independently *rejects* any tool name outside the set before executing it
— so a permission bypass requires breaking both, not just prompting past
the first.
"""

from __future__ import annotations

from tools.base import Permission

PLANNER_PERMISSIONS: set[Permission] = {Permission.READ}
DEVELOPER_PERMISSIONS: set[Permission] = {Permission.READ, Permission.WRITE}
TESTER_PERMISSIONS: set[Permission] = {Permission.READ}  # + Permission.EXECUTE once Phase 1.4's sandbox exists
DEBUGGER_PERMISSIONS: set[Permission] = {Permission.READ, Permission.WRITE}
REVIEWER_PERMISSIONS: set[Permission] = {Permission.READ}
# Orchestrator gets no tool access at all — it only routes and persists state.
