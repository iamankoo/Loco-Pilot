"""generate_image: the extension point for creating a real visual asset
when a task needs one, without requiring the user to upload an image.

Inert until a real image-generation API is configured (IMAGE_PROVIDER/
IMAGE_BASE_URL/IMAGE_MODEL/IMAGE_API_KEY — see
`backend.app.core.image.factory`): reports a clear "not configured" tool
error rather than fabricating placeholder image content. Developer's own
system prompt already steers it toward an inline SVG or CSS-only visual
first when that achieves the same result — this tool is for when a real
raster image is genuinely required and a real provider is available.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.core.config import get_settings
from backend.app.core.image.base import ImageGenerationError
from backend.app.core.image.factory import get_image_provider
from tools.assets.provenance import new_entry, record_asset
from tools.base import Permission, Tool, ToolContext, ToolError
from tools.binary_output import resolve_output_path, verify_written

MAX_IMAGE_BYTES = 20_000_000


class GenerateImageInput(BaseModel):
    path: str
    prompt: str
    width: int = Field(default=1024, gt=0, le=4096)
    height: int = Field(default=1024, gt=0, le=4096)
    overwrite: bool = True


class GenerateImageOutput(BaseModel):
    path: str
    bytes_written: int
    created: bool


class GenerateImageTool(Tool[GenerateImageInput, GenerateImageOutput]):
    name = "generate_image"
    description = (
        "Generate a real raster image asset (e.g. a hero illustration, icon, or background) from a "
        "text prompt and save it into the workspace. Only available when a real image-generation "
        "API is configured (IMAGE_PROVIDER/IMAGE_BASE_URL/IMAGE_MODEL/IMAGE_API_KEY) — prefer an "
        "inline SVG or CSS-only visual when that achieves the same result without needing this tool."
    )
    permission = Permission.WRITE
    input_model = GenerateImageInput
    output_model = GenerateImageOutput

    async def run(self, tool_input: GenerateImageInput, context: ToolContext) -> GenerateImageOutput:
        provider = get_image_provider()
        if provider is None:
            raise ToolError(
                "Image generation is not configured on this deployment: set IMAGE_PROVIDER, "
                "IMAGE_BASE_URL, IMAGE_MODEL, and IMAGE_API_KEY to a real text-to-image API to enable "
                "this tool. Use an inline SVG or CSS-only visual instead.",
                code="IMAGE_GENERATION_NOT_CONFIGURED",
            )

        target = resolve_output_path(context, tool_input.path, overwrite=tool_input.overwrite)
        created = not target.exists()

        try:
            image_bytes = await provider.generate(tool_input.prompt, width=tool_input.width, height=tool_input.height)
        except ImageGenerationError as exc:
            raise ToolError(f"Image generation failed: {exc}") from exc

        try:
            target.write_bytes(image_bytes)
        except OSError as exc:
            raise ToolError(f"Failed to write generated image: {exc}") from exc

        bytes_written = verify_written(target, tool_input.path, max_bytes=MAX_IMAGE_BYTES)

        record_asset(
            context.workspace,
            new_entry(
                local_path=tool_input.path,
                asset_type="image",
                acquisition_method="image_generation",
                source_provider=get_settings().image_provider or "unknown",
                attribution=f"Generated from prompt: {tool_input.prompt}",
            ),
        )

        return GenerateImageOutput(path=tool_input.path, bytes_written=bytes_written, created=created)
