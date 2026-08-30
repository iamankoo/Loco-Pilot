"""Phase 8: web-asset research/sourcing (search_web_images, download_web_asset)
— the fallback below real image generation and above a placeholder box.
Real network calls are replaced with `httpx.MockTransport` (no real
network access in unit tests), but every other code path — the SSRF host
allowlist, real content validation, and provenance recording into
asset-manifest.json — runs unmodified against real bytes."""

from __future__ import annotations

import json

import httpx
import pytest

from tools.assets.provenance import read_manifest
from tools.assets.schemas import (
    DownloadWebAssetInput,
    MAX_ASSET_BYTES,
    SearchWebImagesInput,
)
from tools.assets.tools import DownloadWebAssetTool, SearchWebImagesTool
from tools.base import ToolContext, ToolError
from tools.workspace import Workspace

# A real 1x1 red PNG (genuine magic bytes/structure), reused from
# tests/unit/tools/test_image_tool.py's pattern.
_REAL_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c49444154789c63f8cfc0000003010100c9fe92ef0000000049454e44ae426082"
)

_COMMONS_SEARCH_RESPONSE = {
    "query": {
        "pages": {
            "1": {
                "title": "File:Castle.jpg",
                "imageinfo": [
                    {
                        "url": "https://upload.wikimedia.org/wikipedia/commons/castle.jpg",
                        "mime": "image/jpeg",
                        "width": 800,
                        "height": 600,
                        "extmetadata": {
                            "LicenseShortName": {"value": "CC BY-SA 4.0"},
                            "Artist": {"value": "Jane Doe"},
                        },
                    }
                ],
            }
        }
    }
}


@pytest.fixture
def ctx(tmp_workspace: Workspace) -> ToolContext:
    return ToolContext(workspace=tmp_workspace)


# Captured before any monkeypatching — `monkeypatch.setattr("tools.assets.tools.httpx.AsyncClient", ...)`
# patches the *shared* httpx module object (tools.assets.tools.httpx IS this
# same module, not a copy), so a factory that called `httpx.AsyncClient(...)`
# from in here would recursively call itself instead of the real client.
_RealAsyncClient = httpx.AsyncClient


def _mock_client_factory(handler):
    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return factory


async def test_search_web_images_parses_real_license_metadata(ctx: ToolContext, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "commons.wikimedia.org" in str(request.url)
        return httpx.Response(200, json=_COMMONS_SEARCH_RESPONSE)

    monkeypatch.setattr("tools.assets.tools.httpx.AsyncClient", _mock_client_factory(handler))

    out = await SearchWebImagesTool().run(SearchWebImagesInput(query="castle"), ctx)

    assert len(out.candidates) == 1
    candidate = out.candidates[0]
    assert candidate.url == "https://upload.wikimedia.org/wikipedia/commons/castle.jpg"
    assert candidate.license == "CC BY-SA 4.0"
    assert candidate.attribution == "Jane Doe"


async def test_search_web_images_surfaces_http_errors(ctx: ToolContext, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    monkeypatch.setattr("tools.assets.tools.httpx.AsyncClient", _mock_client_factory(handler))

    with pytest.raises(ToolError):
        await SearchWebImagesTool().run(SearchWebImagesInput(query="castle"), ctx)


async def test_download_web_asset_rejects_disallowed_host(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as exc:
        await DownloadWebAssetTool().run(
            DownloadWebAssetInput(url="https://evil.example.com/payload.png", path="hero.png"), ctx
        )
    assert exc.value.code == "DISALLOWED_ASSET_HOST"
    assert not (ctx.workspace.root / "hero.png").exists()


async def test_download_web_asset_writes_real_bytes_and_records_provenance(ctx: ToolContext, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_REAL_PNG_BYTES, headers={"content-type": "image/png"})

    monkeypatch.setattr("tools.assets.tools.httpx.AsyncClient", _mock_client_factory(handler))

    out = await DownloadWebAssetTool().run(
        DownloadWebAssetInput(
            url="https://upload.wikimedia.org/wikipedia/commons/castle.jpg",
            path="assets/images/castle.png",
            asset_type="hero image",
            license="CC BY-SA 4.0",
            attribution="Jane Doe",
            source_provider="wikimedia_commons",
        ),
        ctx,
    )

    assert out.bytes_written == len(_REAL_PNG_BYTES)
    assert (ctx.workspace.root / "assets/images/castle.png").read_bytes() == _REAL_PNG_BYTES

    manifest = read_manifest(ctx.workspace)
    assert len(manifest) == 1
    entry = manifest[0]
    assert entry.local_path == "assets/images/castle.png"
    assert entry.asset_type == "hero image"
    assert entry.acquisition_method == "web_download"
    assert entry.source_provider == "wikimedia_commons"
    assert entry.license == "CC BY-SA 4.0"
    assert entry.attribution == "Jane Doe"


async def test_download_web_asset_rejects_non_image_content(ctx: ToolContext, monkeypatch) -> None:
    """A redirect to an HTML error page (or any non-image response) must
    never silently become a "successful" asset download — the same
    discipline that closed the earlier base64-text-in-a-.png bug class."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not an image</html>", headers={"content-type": "image/png"})

    monkeypatch.setattr("tools.assets.tools.httpx.AsyncClient", _mock_client_factory(handler))

    with pytest.raises(ToolError) as exc:
        await DownloadWebAssetTool().run(
            DownloadWebAssetInput(url="https://upload.wikimedia.org/wikipedia/commons/fake.png", path="hero.png"), ctx
        )
    assert exc.value.code == "INVALID_DOWNLOADED_ASSET"
    assert not (ctx.workspace.root / "hero.png").exists()


async def test_download_web_asset_rejects_oversized_content(ctx: ToolContext, monkeypatch) -> None:
    oversized = b"\x89PNG\r\n\x1a\n" + b"0" * (MAX_ASSET_BYTES + 1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=oversized, headers={"content-type": "image/png"})

    monkeypatch.setattr("tools.assets.tools.httpx.AsyncClient", _mock_client_factory(handler))

    with pytest.raises(ToolError) as exc:
        await DownloadWebAssetTool().run(
            DownloadWebAssetInput(url="https://upload.wikimedia.org/wikipedia/commons/huge.png", path="hero.png"), ctx
        )
    assert exc.value.code == "FILE_TOO_LARGE"
    assert not (ctx.workspace.root / "hero.png").exists()


async def test_download_web_asset_accepts_dicebear_svg(ctx: ToolContext, monkeypatch) -> None:
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"

    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.dicebear.com" in str(request.url)
        return httpx.Response(200, content=svg, headers={"content-type": "image/svg+xml"})

    monkeypatch.setattr("tools.assets.tools.httpx.AsyncClient", _mock_client_factory(handler))

    out = await DownloadWebAssetTool().run(
        DownloadWebAssetInput(
            url="https://api.dicebear.com/9.x/adventurer/svg?seed=wonderyard-hero",
            path="assets/characters/hero.svg",
            asset_type="character",
        ),
        ctx,
    )
    assert out.mime_type == "image/svg+xml"
    assert (ctx.workspace.root / "assets/characters/hero.svg").read_bytes() == svg
