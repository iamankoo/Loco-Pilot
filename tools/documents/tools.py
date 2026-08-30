"""Document/spreadsheet generation and conversion tools: generate_pdf,
generate_docx, generate_xlsx, generate_csv, convert_file.

Every tool resolves paths through `context.workspace.resolve()` — the
same single security boundary every filesystem tool uses — and verifies
its own output file actually exists with real content before reporting
success, matching the verification discipline `tools/filesystem/tools.py`
already applies to write_file/edit_file/delete_file.
"""

from __future__ import annotations

from pathlib import Path

from tools.base import Permission, Tool, ToolContext, ToolError
from tools.binary_output import resolve_output_path, verify_written
from tools.documents import rendering
from tools.documents.schemas import (
    ConvertFileInput,
    ConvertFileOutput,
    GenerateCsvInput,
    GenerateCsvOutput,
    GenerateDocxInput,
    GenerateDocxOutput,
    GeneratePdfInput,
    GeneratePdfOutput,
    GenerateXlsxInput,
    GenerateXlsxOutput,
    SpreadsheetSheet,
)
from tools.workspace import WorkspaceError

# Generous headroom over MAX_WRITE_BYTES (tools/filesystem/schemas.py, sized
# for source-text files) — a real multi-page PDF/XLSX with actual content
# legitimately needs more room than a source file.
MAX_DOCUMENT_BYTES = 20_000_000

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _resolve_output(context: ToolContext, path: str, *, overwrite: bool) -> Path:
    return resolve_output_path(context, path, overwrite=overwrite)


def _verify_written(target: Path, path: str) -> int:
    return verify_written(target, path, max_bytes=MAX_DOCUMENT_BYTES)


class GeneratePdfTool(Tool[GeneratePdfInput, GeneratePdfOutput]):
    name = "generate_pdf"
    description = (
        "Generate a real PDF file within the workspace from a title/sections/body — use for "
        "reports, invoices, resumes, or any document deliverable. Produces genuine PDF bytes, "
        "never placeholder text."
    )
    permission = Permission.WRITE
    input_model = GeneratePdfInput
    output_model = GeneratePdfOutput

    async def run(self, tool_input: GeneratePdfInput, context: ToolContext) -> GeneratePdfOutput:
        target = _resolve_output(context, tool_input.path, overwrite=tool_input.overwrite)
        created = not target.exists()
        try:
            pages = rendering.render_pdf(
                target, title=tool_input.title, sections=tool_input.sections, body=tool_input.body
            )
        except Exception as exc:  # noqa: BLE001 - a rendering failure is a well-formed tool failure, not a crash
            raise ToolError(f"Failed to generate PDF: {exc}") from exc

        bytes_written = _verify_written(target, tool_input.path)
        return GeneratePdfOutput(path=tool_input.path, bytes_written=bytes_written, pages=pages, created=created)


class GenerateDocxTool(Tool[GenerateDocxInput, GenerateDocxOutput]):
    name = "generate_docx"
    description = (
        "Generate a real DOCX (Word) document within the workspace from a title/sections/body. "
        "Produces genuine .docx bytes, never placeholder text."
    )
    permission = Permission.WRITE
    input_model = GenerateDocxInput
    output_model = GenerateDocxOutput

    async def run(self, tool_input: GenerateDocxInput, context: ToolContext) -> GenerateDocxOutput:
        target = _resolve_output(context, tool_input.path, overwrite=tool_input.overwrite)
        created = not target.exists()
        try:
            rendering.render_docx(target, title=tool_input.title, sections=tool_input.sections, body=tool_input.body)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Failed to generate DOCX: {exc}") from exc

        bytes_written = _verify_written(target, tool_input.path)
        return GenerateDocxOutput(path=tool_input.path, bytes_written=bytes_written, created=created)


class GenerateXlsxTool(Tool[GenerateXlsxInput, GenerateXlsxOutput]):
    name = "generate_xlsx"
    description = (
        "Generate a real XLSX spreadsheet within the workspace from one or more sheets (headers + "
        "rows). Produces genuine .xlsx bytes, never placeholder text."
    )
    permission = Permission.WRITE
    input_model = GenerateXlsxInput
    output_model = GenerateXlsxOutput

    async def run(self, tool_input: GenerateXlsxInput, context: ToolContext) -> GenerateXlsxOutput:
        target = _resolve_output(context, tool_input.path, overwrite=tool_input.overwrite)
        created = not target.exists()
        try:
            sheet_count, row_count = rendering.render_xlsx(target, tool_input.sheets)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Failed to generate XLSX: {exc}") from exc

        bytes_written = _verify_written(target, tool_input.path)
        return GenerateXlsxOutput(
            path=tool_input.path, bytes_written=bytes_written, sheet_count=sheet_count,
            row_count=row_count, created=created,
        )


class GenerateCsvTool(Tool[GenerateCsvInput, GenerateCsvOutput]):
    name = "generate_csv"
    description = "Generate a real CSV file within the workspace from headers + rows."
    permission = Permission.WRITE
    input_model = GenerateCsvInput
    output_model = GenerateCsvOutput

    async def run(self, tool_input: GenerateCsvInput, context: ToolContext) -> GenerateCsvOutput:
        target = _resolve_output(context, tool_input.path, overwrite=tool_input.overwrite)
        created = not target.exists()
        try:
            rendering.render_csv(target, headers=tool_input.headers, rows=tool_input.rows)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Failed to generate CSV: {exc}") from exc

        bytes_written = _verify_written(target, tool_input.path)
        return GenerateCsvOutput(
            path=tool_input.path, bytes_written=bytes_written, row_count=len(tool_input.rows), created=created
        )


def _infer_conversion(source_ext: str, target_ext: str) -> str:
    if source_ext == ".txt" and target_ext == ".pdf":
        return "text_to_pdf"
    if source_ext == ".md" and target_ext == ".pdf":
        return "markdown_to_pdf"
    if source_ext in _IMAGE_EXTENSIONS and target_ext == ".pdf":
        return "image_to_pdf"
    if source_ext == ".pdf" and target_ext == ".txt":
        return "pdf_to_text"
    if source_ext == ".csv" and target_ext == ".xlsx":
        return "csv_to_xlsx"
    if source_ext == ".xlsx" and target_ext == ".csv":
        return "xlsx_to_csv"
    supported = "text->pdf, markdown->pdf, image->pdf, pdf->text, csv->xlsx, xlsx->csv"
    raise ToolError(
        f"Unsupported conversion: {source_ext} -> {target_ext}. Supported conversions: {supported}.",
        code="UNSUPPORTED_CONVERSION",
    )


class ConvertFileTool(Tool[ConvertFileInput, ConvertFileOutput]):
    name = "convert_file"
    description = (
        "Convert a file already in the workspace to another real format. Supported: text->pdf, "
        "markdown->pdf, image->pdf, pdf->text, csv->xlsx, xlsx->csv (inferred from the source/target "
        "extensions). docx->pdf is NOT supported — no reliable local conversion path exists."
    )
    permission = Permission.WRITE
    input_model = ConvertFileInput
    output_model = ConvertFileOutput

    async def run(self, tool_input: ConvertFileInput, context: ToolContext) -> ConvertFileOutput:
        try:
            source = context.workspace.resolve(tool_input.source_path)
        except WorkspaceError as exc:
            raise ToolError(f"Invalid source_path: {exc}", code="PATH_OUTSIDE_WORKSPACE") from exc
        if not source.is_file():
            raise ToolError(f"Source file not found: {tool_input.source_path}", code="FILE_NOT_FOUND")

        conversion = _infer_conversion(source.suffix.lower(), Path(tool_input.target_path).suffix.lower())
        target = _resolve_output(context, tool_input.target_path, overwrite=tool_input.overwrite)
        created = not target.exists()

        try:
            if conversion == "text_to_pdf":
                rendering.render_pdf(target, title=None, sections=[], body=source.read_text(encoding="utf-8", errors="replace"))
            elif conversion == "markdown_to_pdf":
                rendering.render_markdown_as_pdf(target, source.read_text(encoding="utf-8", errors="replace"))
            elif conversion == "image_to_pdf":
                rendering.render_image_as_pdf(target, source)
            elif conversion == "pdf_to_text":
                target.write_text(rendering.extract_pdf_text(source), encoding="utf-8")
            elif conversion == "csv_to_xlsx":
                import csv as csv_module

                with source.open(newline="", encoding="utf-8", errors="replace") as fh:
                    rows = list(csv_module.reader(fh))
                headers, data_rows = (rows[0], rows[1:]) if rows else ([], [])
                rendering.render_xlsx(target, [SpreadsheetSheet(headers=headers, rows=data_rows)])
            elif conversion == "xlsx_to_csv":
                rows = rendering.read_xlsx_first_sheet(source)
                headers = [str(v) if v is not None else "" for v in rows[0]] if rows else []
                data_rows = [[v for v in row] for row in rows[1:]] if rows else []
                rendering.render_csv(target, headers=headers, rows=data_rows)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Conversion failed ({conversion}): {exc}") from exc

        bytes_written = _verify_written(target, tool_input.target_path)
        return ConvertFileOutput(
            source_path=tool_input.source_path, target_path=tool_input.target_path,
            conversion=conversion, bytes_written=bytes_written, created=created,
        )
