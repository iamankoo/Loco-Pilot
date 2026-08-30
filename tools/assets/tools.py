"""search_web_images / download_web_asset: real, controlled web-asset
research and sourcing — the fallback below "real image generation" and
above "placeholder box" in the visual-asset hierarchy (see tools/image.py
for the generation path itself).

search_web_images queries Wikimedia Commons' public search API (no key
required, no account, genuinely free) — a real, reputable source with
explicit machine-readable licensing/attribution metadata for every result,
unlike scraping arbitrary image search results. download_web_asset then
fetches ONE selected URL and writes it into the workspace, recording
provenance into asset-manifest.json (tools/assets/provenance.py).

Security: download_web_asset only accepts a URL whose host is on a small,
explicit allowlist of asset providers (never an arbitrary attacker/LLM-
controlled host) — this is a real SSRF boundary, not merely a style
preference, since the URL ultimately comes from model output. Downloaded
content is also verified to actually be image bytes (magic-byte check)
before being written, and size-capped.
"""

from __future__ import annotations

import re

import httpx
from pydantic import BaseModel

from analysis.static_site import validate_binary_asset
from tools.assets.provenance import new_entry, record_asset
from tools.assets.schemas import (
    DownloadWebAssetInput,
    DownloadWebAssetOutput,
    SearchWebImagesInput,
    SearchWebImagesOutput,
    WebImageCandidate,
    MAX_ASSET_BYTES,
)
from tools.base import Permission, Tool, ToolContext, ToolError
from tools.binary_output import resolve_output_path, verify_written

_USER_AGENT = "LocoPilot/0.1 (autonomous-coding-agent asset research; +https://github.com/iamankoo/Loco-Pilot)"
_REQUEST_TIMEOUT = 15.0

# A real SSRF boundary: only these known, reputable, static-content asset
# hosts may ever be fetched — never an arbitrary URL an LLM proposes.
_ALLOWED_ASSET_HOSTS = {"upload.wikimedia.org", "commons.wikimedia.org", "api.dicebear.com"}

_SVG_MIME_RE = re.compile(r"svg", re.IGNORECASE)


class SearchWebImagesTool(Tool[SearchWebImagesInput, SearchWebImagesOutput]):
    name = "search_web_images"
    description = (
        "Search Wikimedia Commons (a real, reputable, freely-licensed media source) for images matching "
        "a query — returns candidate URLs with license/attribution metadata. Use when the task needs a "
        "real photo/illustration and image generation is unavailable; prefer this over inventing an "
        "image URL, and prefer an inline SVG/CSS visual when that achieves the same result without "
        "needing an external asset at all."
    )
    permission = Permission.READ
    input_model = SearchWebImagesInput
    output_model = SearchWebImagesOutput

    async def run(self, tool_input: SearchWebImagesInput, context: ToolContext) -> SearchWebImagesOutput:
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": tool_input.query,
            "gsrnamespace": 6,  # File: namespace
            "gsrlimit": tool_input.limit,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime|size",
        }
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                response = await client.get(
                    "https://commons.wikimedia.org/w/api.php",
                    params=params,
                    headers={"User-Agent": _USER_AGENT},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ToolError(f"Web image search failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ToolError(f"Web image search returned an unexpected response: {exc}") from exc

        pages = (data.get("query") or {}).get("pages") or {}
        candidates: list[WebImageCandidate] = []
        for page in pages.values():
            info_list = page.get("imageinfo") or []
            if not info_list:
                continue
            info = info_list[0]
            url = info.get("url")
            mime = info.get("mime", "")
            if not url or not mime.startswith("image/"):
                continue
            meta = info.get("extmetadata") or {}
            candidates.append(
                WebImageCandidate(
                    title=page.get("title", ""),
                    url=url,
                    mime_type=mime,
                    width=info.get("width"),
                    height=info.get("height"),
                    license=(meta.get("LicenseShortName") or {}).get("value"),
                    attribution=(meta.get("Artist") or {}).get("value") or (meta.get("Credit") or {}).get("value"),
                )
            )

        return SearchWebImagesOutput(query=tool_input.query, candidates=candidates)


class DownloadWebAssetTool(Tool[DownloadWebAssetInput, DownloadWebAssetOutput]):
    name = "download_web_asset"
    description = (
        "Download a real image from a URL returned by search_web_images, or from DiceBear "
        "(https://api.dicebear.com/9.x/{style}/svg?seed=... — a real, free, deterministic cartoon "
        "avatar/character generator API, no key needed; styles include 'adventurer', 'bottts', "
        "'big-smile', 'fun-emoji', 'thumbs') into the workspace, verifying it is genuinely a valid "
        "image and recording its source/license into asset-manifest.json. Only a small allowlist of "
        "reputable asset hosts is accepted — never an arbitrary or invented URL. Set asset_type to "
        "describe what it actually is (e.g. 'hero image', 'character', 'icon')."
    )
    permission = Permission.WRITE
    input_model = DownloadWebAssetInput
    output_model = DownloadWebAssetOutput

    async def run(self, tool_input: DownloadWebAssetInput, context: ToolContext) -> DownloadWebAssetOutput:
        parsed = httpx.URL(tool_input.url)
        if parsed.scheme != "https" or parsed.host not in _ALLOWED_ASSET_HOSTS:
            allowed = ", ".join(sorted(_ALLOWED_ASSET_HOSTS))
            raise ToolError(
                f"URL host {parsed.host!r} is not an allowed asset source (allowed: {allowed}). "
                "Use search_web_images to find a real, allowed URL rather than an invented one.",
                code="DISALLOWED_ASSET_HOST",
            )

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
                response = await client.get(tool_input.url, headers={"User-Agent": _USER_AGENT})
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ToolError(f"Failed to download asset: {exc}") from exc

        content = response.content
        if len(content) > MAX_ASSET_BYTES:
            raise ToolError(f"Downloaded asset exceeds the maximum size of {MAX_ASSET_BYTES} bytes.", code="FILE_TOO_LARGE")

        mime_type = response.headers.get("content-type", "").split(";")[0].strip() or "application/octet-stream"

        target = resolve_output_path(context, tool_input.path, overwrite=tool_input.overwrite)
        created = not target.exists()

        try:
            target.write_bytes(content)
        except OSError as exc:
            raise ToolError(f"Failed to write downloaded asset: {exc}") from exc

        # Real content validation — the same discipline that closed the
        # base64-text-in-a-.png bug: a redirect to an HTML error page or a
        # non-image response must not silently become a "successful" asset.
        if not _SVG_MIME_RE.search(mime_type):
            ok, reason = validate_binary_asset(target)
            if not ok:
                target.unlink(missing_ok=True)
                raise ToolError(f"Downloaded content is not a valid image: {reason}", code="INVALID_DOWNLOADED_ASSET")

        bytes_written = verify_written(target, tool_input.path, max_bytes=MAX_ASSET_BYTES)

        record_asset(
            context.workspace,
            new_entry(
                local_path=tool_input.path,
                asset_type=tool_input.asset_type,
                acquisition_method="web_download",
                source_provider=tool_input.source_provider,
                source_url=tool_input.url,
                license=tool_input.license,
                attribution=tool_input.attribution,
            ),
        )

        return DownloadWebAssetOutput(path=tool_input.path, bytes_written=bytes_written, mime_type=mime_type, created=created)
