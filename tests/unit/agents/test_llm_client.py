from __future__ import annotations

import pytest
from pydantic import BaseModel

from agents.llm_client import LangChainStructuredLLMClient, LLMUnavailableError, MalformedLLMOutputError


class _Output(BaseModel):
    value: str


class _StructuredStub:
    def __init__(self, *, result=None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc

    async def ainvoke(self, messages):
        if self._exc is not None:
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
