"""Image-provider factory — mirrors `backend.app.core.llm.factory`'s shape.

Returns `None` (not an error) when image generation isn't configured at
all — `IMAGE_PROVIDER`/`IMAGE_BASE_URL`/`IMAGE_MODEL`/`IMAGE_API_KEY` are
all optional and unset by default (no image-generation model exists on a
typical NVIDIA NIM account today). `tools.image.GenerateImageTool` checks
for `None` and reports a clear "not configured" tool error rather than
attempting a call that could never succeed.
"""

from __future__ import annotations

from functools import lru_cache

from backend.app.core.config import Settings, get_settings
from backend.app.core.image.base import ImageProvider
from backend.app.core.image.openai_compatible_provider import OpenAICompatibleImageProvider

_PROVIDERS: dict[str, type[ImageProvider]] = {
    "openai_compatible": OpenAICompatibleImageProvider,
}


def build_image_provider(settings: Settings) -> ImageProvider | None:
    if not (settings.image_provider and settings.image_base_url and settings.image_model and settings.image_api_key):
        return None
    provider_cls = _PROVIDERS.get(settings.image_provider)
    if provider_cls is None:
        known = ", ".join(sorted(_PROVIDERS))
        raise ValueError(f"Unknown IMAGE_PROVIDER '{settings.image_provider}'. Known providers: {known}")
    return provider_cls(base_url=settings.image_base_url, api_key=settings.image_api_key, model=settings.image_model)


@lru_cache
def get_image_provider() -> ImageProvider | None:
    return build_image_provider(get_settings())
