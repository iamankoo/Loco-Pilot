"""An image-generation provider for any OpenAI-images-API-compatible
endpoint (`POST {base_url}/images/generations`, base64 response) — the
same shape OpenAI's own Images API uses, and one many third-party
providers mirror. Configured entirely through settings (base URL / model /
API key), never tied to one vendor — swapping providers is a config
change, not a code change, matching `backend.app.core.llm`'s own pattern.
"""

from __future__ import annotations

import base64

import httpx

from backend.app.core.image.base import ImageGenerationError, ImageProvider


class OpenAICompatibleImageProvider(ImageProvider):
    name = "openai_compatible"

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    async def generate(self, prompt: str, *, width: int, height: int) -> bytes:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.post(
                    f"{self._base_url}/images/generations",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self._model,
                        "prompt": prompt,
                        "size": f"{width}x{height}",
                        "response_format": "b64_json",
                        "n": 1,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ImageGenerationError(f"Image generation request failed: {exc}") from exc

        try:
            payload = response.json()
            b64_data = payload["data"][0]["b64_json"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ImageGenerationError(f"Image generation response was not in the expected shape: {exc}") from exc

        try:
            return base64.b64decode(b64_data, validate=True)
        except (ValueError, TypeError) as exc:
            raise ImageGenerationError(f"Image generation response was not valid base64: {exc}") from exc
