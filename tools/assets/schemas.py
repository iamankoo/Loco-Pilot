from __future__ import annotations

from pydantic import BaseModel, Field

MAX_ASSET_BYTES = 8_000_000
MAX_SEARCH_RESULTS = 10


class SearchWebImagesInput(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=MAX_SEARCH_RESULTS)


class WebImageCandidate(BaseModel):
    title: str
    url: str
    mime_type: str
    width: int | None = None
    height: int | None = None
    license: str | None = None
    attribution: str | None = None
    source_provider: str = "wikimedia_commons"


class SearchWebImagesOutput(BaseModel):
    query: str
    candidates: list[WebImageCandidate]


class DownloadWebAssetInput(BaseModel):
    url: str
    path: str
    # What this asset actually IS in the generated product (a hero image,
    # a character illustration, a decorative icon, ...) — the caller
    # knows this; guessing purely from MIME type would misclassify e.g. an
    # SVG character illustration as a generic "icon".
    asset_type: str = "image"
    # Provenance the caller already knows (e.g. from a prior
    # search_web_images candidate) — recorded into asset-manifest.json
    # alongside the download so the source/license is never lost.
    license: str | None = None
    attribution: str | None = None
    source_provider: str = "web"
    overwrite: bool = True


class DownloadWebAssetOutput(BaseModel):
    path: str
    bytes_written: int
    mime_type: str
    created: bool
