from __future__ import annotations

import pytest

from tools.base import ToolContext, ToolError
from tools.documents.schemas import (
    ConvertFileInput,
    DocumentSection,
    GenerateCsvInput,
    GenerateDocxInput,
    GeneratePdfInput,
    GenerateXlsxInput,
    SpreadsheetSheet,
)
from tools.documents.tools import (
    ConvertFileTool,
    GenerateCsvTool,
    GenerateDocxTool,
    GeneratePdfTool,
    GenerateXlsxTool,
)
from tools.filesystem.tools import WriteFileTool
from tools.filesystem.schemas import WriteFileInput
from tools.workspace import Workspace


@pytest.fixture
def ctx(tmp_workspace: Workspace) -> ToolContext:
    return ToolContext(workspace=tmp_workspace)


def _read_bytes(ctx: ToolContext, path: str) -> bytes:
    return (ctx.workspace.root / path).read_bytes()


async def test_generate_pdf_produces_real_pdf(ctx: ToolContext) -> None:
    out = await GeneratePdfTool().run(
        GeneratePdfInput(
            path="report.pdf", title="Report",
            sections=[DocumentSection(heading="Intro", body="Hello world.")],
        ),
        ctx,
    )
    assert out.created is True
    assert out.pages >= 1
    assert out.bytes_written > 0
    assert _read_bytes(ctx, "report.pdf").startswith(b"%PDF-")


async def test_generate_pdf_rejects_overwrite_false_when_exists(ctx: ToolContext) -> None:
    await GeneratePdfTool().run(GeneratePdfInput(path="report.pdf", body="one"), ctx)
    with pytest.raises(ToolError) as exc:
        await GeneratePdfTool().run(GeneratePdfInput(path="report.pdf", body="two", overwrite=False), ctx)
    assert exc.value.code == "DESTINATION_EXISTS"


async def test_generate_pdf_rejects_workspace_escape(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as exc:
        await GeneratePdfTool().run(GeneratePdfInput(path="../escape.pdf", body="x"), ctx)
    assert exc.value.code == "PATH_OUTSIDE_WORKSPACE"


async def test_generate_docx_produces_real_docx(ctx: ToolContext) -> None:
    out = await GenerateDocxTool().run(
        GenerateDocxInput(path="doc.docx", title="Doc", sections=[DocumentSection(heading="H", body="text")]), ctx
    )
    assert out.created is True
    assert out.bytes_written > 0
    # A real .docx is a real zip archive (OOXML) — starts with the local-file-header magic bytes.
    assert _read_bytes(ctx, "doc.docx").startswith(b"PK")


async def test_generate_xlsx_produces_real_xlsx(ctx: ToolContext) -> None:
    out = await GenerateXlsxTool().run(
        GenerateXlsxInput(
            path="data.xlsx",
            sheets=[SpreadsheetSheet(name="Sheet1", headers=["a", "b"], rows=[[1, 2], [3, 4]])],
        ),
        ctx,
    )
    assert out.created is True
    assert out.sheet_count == 1
    assert out.row_count == 2
    assert _read_bytes(ctx, "data.xlsx").startswith(b"PK")


async def test_generate_csv_produces_real_csv(ctx: ToolContext) -> None:
    out = await GenerateCsvTool().run(
        GenerateCsvInput(path="data.csv", headers=["x", "y"], rows=[[1, 2], [3, 4]]), ctx
    )
    assert out.created is True
    assert out.row_count == 2
    content = (ctx.workspace.root / "data.csv").read_text(encoding="utf-8")
    assert "x,y" in content
    assert "1,2" in content


async def test_convert_text_to_pdf(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="notes.txt", content="Some plain text."), ctx)
    out = await ConvertFileTool().run(ConvertFileInput(source_path="notes.txt", target_path="notes.pdf"), ctx)
    assert out.conversion == "text_to_pdf"
    assert _read_bytes(ctx, "notes.pdf").startswith(b"%PDF-")


async def test_convert_markdown_to_pdf(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="readme.md", content="# Title\n\nSome **bold** text."), ctx)
    out = await ConvertFileTool().run(ConvertFileInput(source_path="readme.md", target_path="readme.pdf"), ctx)
    assert out.conversion == "markdown_to_pdf"
    assert _read_bytes(ctx, "readme.pdf").startswith(b"%PDF-")


async def test_convert_pdf_to_text_round_trip(ctx: ToolContext) -> None:
    await GeneratePdfTool().run(GeneratePdfInput(path="a.pdf", body="Round trip content."), ctx)
    out = await ConvertFileTool().run(ConvertFileInput(source_path="a.pdf", target_path="a.txt"), ctx)
    assert out.conversion == "pdf_to_text"
    assert "Round trip content." in (ctx.workspace.root / "a.txt").read_text(encoding="utf-8")


async def test_convert_csv_to_xlsx_and_back(ctx: ToolContext) -> None:
    await GenerateCsvTool().run(GenerateCsvInput(path="a.csv", headers=["a", "b"], rows=[[1, 2]]), ctx)
    to_xlsx = await ConvertFileTool().run(ConvertFileInput(source_path="a.csv", target_path="a.xlsx"), ctx)
    assert to_xlsx.conversion == "csv_to_xlsx"
    assert _read_bytes(ctx, "a.xlsx").startswith(b"PK")

    to_csv = await ConvertFileTool().run(ConvertFileInput(source_path="a.xlsx", target_path="b.csv"), ctx)
    assert to_csv.conversion == "xlsx_to_csv"
    content = (ctx.workspace.root / "b.csv").read_text(encoding="utf-8")
    assert "a,b" in content


async def test_convert_rejects_unsupported_pair(ctx: ToolContext) -> None:
    await WriteFileTool().run(WriteFileInput(path="a.docx", content="not really a docx"), ctx)
    with pytest.raises(ToolError) as exc:
        await ConvertFileTool().run(ConvertFileInput(source_path="a.docx", target_path="a.pdf"), ctx)
    assert exc.value.code == "UNSUPPORTED_CONVERSION"


async def test_convert_rejects_missing_source(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as exc:
        await ConvertFileTool().run(ConvertFileInput(source_path="missing.txt", target_path="out.pdf"), ctx)
    assert exc.value.code == "FILE_NOT_FOUND"


async def test_convert_rejects_source_workspace_escape(ctx: ToolContext) -> None:
    with pytest.raises(ToolError) as exc:
        await ConvertFileTool().run(ConvertFileInput(source_path="../outside.txt", target_path="out.pdf"), ctx)
    assert exc.value.code == "PATH_OUTSIDE_WORKSPACE"
