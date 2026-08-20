"""Defense-in-depth secret redaction applied to tool output/input before
it is persisted or logged.

This is a pattern-based safety net, not a claim of perfect secret
detection — repository/command output is untrusted and can contain
anything; the goal is to catch the obvious, common credential shapes
before they land in the database, not to guarantee nothing sensitive ever
appears in generated code review by a human later.

Applied at the two actual persistence write-points: `ToolCall` rows
(`backend.app.services.tool_execution.execute_tool`) and `AgentStep`
output-metadata summaries (`agents.graph.make_agent_node`). What an agent
receives back from a tool call to reason with is NOT scrubbed — an agent
fixing a hardcoded secret needs to see it to know what to remove.
"""

from __future__ import annotations

import re

REDACTED = "***REDACTED***"

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    # OpenAI-style API keys
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    # AWS access key IDs
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    # GitHub personal access tokens (classic and fine-grained prefixes)
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    # PEM private key blocks
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----[\s\S]*?"
            r"-----END (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"
        ),
    ),
    # Bearer tokens in headers/output
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-_.]{10,}")),
    # Generic `key = "value"` / `token: value` style assignments for common credential names
    (
        "generic_credential_assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|"
            r"private[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9\-_/+=.]{8,}['\"]?"
        ),
    ),
)


def scrub_secrets(value: object) -> object:
    if isinstance(value, str):
        result = value
        for _name, pattern in _SECRET_PATTERNS:
            result = pattern.sub(REDACTED, result)
        return result
    if isinstance(value, dict):
        return {k: scrub_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_secrets(v) for v in value]
    return value
