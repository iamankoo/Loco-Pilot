"""Structured application error foundation.

Agents/tools in later phases raise `LocoPilotError` subclasses so the API
layer can translate failures into consistent, structured responses instead
of leaking raw tracebacks.
"""

from __future__ import annotations


class LocoPilotError(Exception):
    """Base class for application errors with an HTTP status and error code."""

    def __init__(self, message: str, *, status_code: int = 500, code: str = "internal_error") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class LLMConfigurationError(LocoPilotError):
    """Raised when an LLM provider is misconfigured (e.g. missing API key)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=503, code="llm_configuration_error")
