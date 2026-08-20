"""Structured logging foundation.

Uses structlog so every log line can later be enriched with execution
correlation fields (execution_id, agent, tool, task) via
`bind_execution_context`, without every call site needing to know about it.
"""

from __future__ import annotations

import logging
import sys

import structlog

from backend.app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    renderer = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(**bind: object) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger().bind(**bind)


def bind_execution_context(
    *,
    execution_id: str | None = None,
    agent: str | None = None,
    tool: str | None = None,
    task: str | None = None,
) -> None:
    """Bind execution-scoped fields to all subsequent log calls on this context.

    Later agent/tool/orchestrator code calls this at the start of an
    execution (or a step within one) so every log line emitted afterwards is
    automatically correlated, without threading these fields through every
    function signature.
    """

    fields = {
        k: v
        for k, v in {
            "execution_id": execution_id,
            "agent": agent,
            "tool": tool,
            "task": task,
        }.items()
        if v is not None
    }
    structlog.contextvars.bind_contextvars(**fields)


def clear_execution_context() -> None:
    structlog.contextvars.clear_contextvars()
