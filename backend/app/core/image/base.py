"""Provider-agnostic image-generation interface — the image-generation
counterpart to `backend.app.core.llm.base.LLMProvider`. No concrete
provider exists in this codebase yet (no text-to-image model is available
on the currently configured NVIDIA account); this interface exists so
`tools.image.GenerateImageTool` and `backend.app.core.image.factory` have
something real to depend on the moment a real provider is added, without
either needing to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ImageGenerationError(Exception):
    """A well-formed image-generation failure (bad request, provider error,
    quota exceeded) — distinct from "not configured at all" (see
    `backend.app.core.image.factory.get_image_provider` returning None)."""


class ImageProvider(ABC):
    """A named provider capable of generating a real raster image."""

    name: str

    @abstractmethod
    async def generate(self, prompt: str, *, width: int, height: int) -> bytes:
        """Returns real, complete image bytes (PNG or JPEG) for `prompt` —
        never placeholder/fake content. Raises `ImageGenerationError` for
        any provider-side failure."""
        raise NotImplementedError
