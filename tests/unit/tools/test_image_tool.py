from __future__ import annotations

import pytest

from backend.app.core.config import Settings
from backend.app.core.image.base import ImageGenerationError, ImageProvider
from backend.app.core.image.factory import build_image_provider
from backend.app.core.image.openai_compatible_provider import OpenAICompatibleImageProvider
from tools.base import ToolContext, ToolError
from tools.image import GenerateImageInput, GenerateImageTool
from tools.workspace import Workspace


@pytest.fixture
def ctx(tmp_workspace: Workspace) -> ToolContext:
    return ToolContext(workspace=tmp_workspace)


def test_build_image_provider_returns_none_when_unconfigured() -> None:
    settings = Settings(_env_file=None, image_provider=None, image_base_url=None, image_model=None, image_api_key=None)
    assert build_image_provider(settings) is None


def test_build_image_provider_returns_none_when_partially_configured() -> None:
    settings = Settings(
        _env_file=None, image_provider="openai_compatible", image_base_url="https://example.invalid",
        image_model="some-model", image_api_key=None,
    )
    assert build_image_provider(settings) is None


def test_build_image_provider_builds_when_fully_configured() -> None:
    settings = Settings(
        _env_file=None, image_provider="openai_compatible", image_base_url="https://example.invalid",
        image_model="some-model", image_api_key="test-key",
    )
    provider = build_image_provider(settings)
    assert isinstance(provider, OpenAICompatibleImageProvider)


def test_build_image_provider_rejects_unknown_provider_name() -> None:
    settings = Settings(
        _env_file=None, image_provider="does-not-exist", image_base_url="https://example.invalid",
        image_model="some-model", image_api_key="test-key",
    )
    with pytest.raises(ValueError, match="Unknown IMAGE_PROVIDER"):
        build_image_provider(settings)


class _StubProvider(ImageProvider):
    name = "stub"

    def __init__(self, *, image_bytes: bytes | None = None, error: Exception | None = None) -> None:
        self._image_bytes = image_bytes
        self._error = error

    async def generate(self, prompt: str, *, width: int, height: int) -> bytes:
        if self._error is not None:
            raise self._error
        return self._image_bytes or b""


# A real 1x1 red PNG generated via Pillow (not a placeholder string — genuine
# PNG magic bytes and structure) used to prove the tool writes real decoded
# binary content.
_REAL_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c49444154789c63f8cfc0000003010100c9fe92ef0000000049454e44ae426082"
)


async def test_generate_image_reports_not_configured_when_no_provider(ctx: ToolContext, monkeypatch) -> None:
    monkeypatch.setattr("tools.image.get_image_provider", lambda: None)
    with pytest.raises(ToolError) as exc:
        await GenerateImageTool().run(GenerateImageInput(path="hero.png", prompt="a friendly cartoon fox"), ctx)
    assert exc.value.code == "IMAGE_GENERATION_NOT_CONFIGURED"
    assert not (ctx.workspace.root / "hero.png").exists()


async def test_generate_image_writes_real_bytes_when_configured(ctx: ToolContext, monkeypatch) -> None:
    monkeypatch.setattr("tools.image.get_image_provider", lambda: _StubProvider(image_bytes=_REAL_PNG_BYTES))
    out = await GenerateImageTool().run(GenerateImageInput(path="hero.png", prompt="a friendly cartoon fox"), ctx)
    assert out.created is True
    assert out.bytes_written == len(_REAL_PNG_BYTES)
    assert (ctx.workspace.root / "hero.png").read_bytes() == _REAL_PNG_BYTES


async def test_generate_image_surfaces_provider_failure(ctx: ToolContext, monkeypatch) -> None:
    monkeypatch.setattr(
        "tools.image.get_image_provider",
        lambda: _StubProvider(error=ImageGenerationError("quota exceeded")),
    )
    with pytest.raises(ToolError, match="quota exceeded"):
        await GenerateImageTool().run(GenerateImageInput(path="hero.png", prompt="x"), ctx)
    assert not (ctx.workspace.root / "hero.png").exists()


async def test_generate_image_rejects_workspace_escape(ctx: ToolContext, monkeypatch) -> None:
    monkeypatch.setattr("tools.image.get_image_provider", lambda: _StubProvider(image_bytes=_REAL_PNG_BYTES))
    with pytest.raises(ToolError) as exc:
        await GenerateImageTool().run(GenerateImageInput(path="../escape.png", prompt="x"), ctx)
    assert exc.value.code == "PATH_OUTSIDE_WORKSPACE"
