from __future__ import annotations

import httpx
import openai
import pytest
from pydantic import BaseModel

from agents.llm_client import LangChainStructuredLLMClient, LLMUnavailableError, MalformedLLMOutputError


class _Output(BaseModel):
    value: str


def _api_status_error(status_code: int, body: str = "") -> openai.APIStatusError:
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    response = httpx.Response(status_code, request=request, text=body)
    return openai.APIStatusError("boom", response=response, body=None)


class _StructuredStub:
    def __init__(self, *, result=None, exc: Exception | None = None, fail_times: int = 0) -> None:
        self._result = result
        self._exc = exc
        self._fail_times = fail_times
        self.call_count = 0

    async def ainvoke(self, messages):
        self.call_count += 1
        if self._fail_times > 0 and self.call_count <= self._fail_times:
            raise self._exc
        if self._fail_times == 0 and self._exc is not None:
            raise self._exc
        return self._result


class _ChatModelStub:
    def __init__(self, structured: _StructuredStub) -> None:
        self._structured = structured

    def with_structured_output(self, output_model):
        return self._structured


async def test_generate_returns_valid_structured_output() -> None:
    client = LangChainStructuredLLMClient(_ChatModelStub(_StructuredStub(result=_Output(value="ok"))))
    result = await client.generate(system="sys", user="usr", output_model=_Output)
    assert result == _Output(value="ok")


async def test_generate_wraps_transport_failure_as_unavailable() -> None:
    client = LangChainStructuredLLMClient(_ChatModelStub(_StructuredStub(exc=ConnectionError("boom"))))
    with pytest.raises(LLMUnavailableError):
        await client.generate(system="sys", user="usr", output_model=_Output)


async def test_generate_wraps_malformed_output() -> None:
    # returns a dict that doesn't validate against _Output (missing 'value')
    client = LangChainStructuredLLMClient(_ChatModelStub(_StructuredStub(result={"not_value": "x"})))
    with pytest.raises(MalformedLLMOutputError):
        await client.generate(system="sys", user="usr", output_model=_Output)


async def test_generate_accepts_dict_that_validates() -> None:
    client = LangChainStructuredLLMClient(_ChatModelStub(_StructuredStub(result={"value": "from-dict"})))
    result = await client.generate(system="sys", user="usr", output_model=_Output)
    assert result.value == "from-dict"


async def test_generate_retries_transient_5xx_then_succeeds() -> None:
    """A transient 503 (observed in practice from NVIDIA's hosted Nemotron
    Ultra) is retried rather than immediately failing the whole call."""
    stub = _StructuredStub(result=_Output(value="ok"), exc=_api_status_error(503), fail_times=1)
    client = LangChainStructuredLLMClient(_ChatModelStub(stub))
    result = await client.generate(system="sys", user="usr", output_model=_Output)
    assert result == _Output(value="ok")
    assert stub.call_count == 2


async def test_generate_gives_up_after_max_attempts_on_persistent_5xx() -> None:
    stub = _StructuredStub(exc=_api_status_error(500), fail_times=99)
    client = LangChainStructuredLLMClient(_ChatModelStub(stub))
    with pytest.raises(LLMUnavailableError):
        await client.generate(system="sys", user="usr", output_model=_Output)
    assert stub.call_count == 3  # _MAX_LLM_ATTEMPTS


async def test_generate_does_not_retry_non_transient_error() -> None:
    """A genuine client error (e.g. bad request) fails immediately rather
    than wasting the retry budget on something retrying can't fix."""
    stub = _StructuredStub(exc=_api_status_error(400), fail_times=99)
    client = LangChainStructuredLLMClient(_ChatModelStub(stub))
    with pytest.raises(LLMUnavailableError):
        await client.generate(system="sys", user="usr", output_model=_Output)
    assert stub.call_count == 1


async def test_generate_retries_empty_body_404_then_succeeds() -> None:
    """An empty-body 404 (observed from NVIDIA's Nemotron Ultra routing
    layer for a model confirmed present in /v1/models) is a transient
    availability blip, not a genuine "model not found"."""
    stub = _StructuredStub(result=_Output(value="ok"), exc=_api_status_error(404, body=""), fail_times=1)
    client = LangChainStructuredLLMClient(_ChatModelStub(stub))
    result = await client.generate(system="sys", user="usr", output_model=_Output)
    assert result == _Output(value="ok")
    assert stub.call_count == 2


async def test_generate_does_not_retry_404_with_error_body() -> None:
    """A 404 that DOES carry a real error body (a genuine unknown-model
    response) fails immediately — only the empty-body variant is retried."""
    stub = _StructuredStub(exc=_api_status_error(404, body='{"error": "model not found"}'), fail_times=99)
    client = LangChainStructuredLLMClient(_ChatModelStub(stub))
    with pytest.raises(LLMUnavailableError):
        await client.generate(system="sys", user="usr", output_model=_Output)
    assert stub.call_count == 1
