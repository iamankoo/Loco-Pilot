from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MAX_SHEET_ROWS = 100_000
MAX_SECTIONS = 500


class DocumentSection(BaseModel):
    heading: str | None = None
    body: str = ""


class GeneratePdfInput(BaseModel):
    path: str
    title: str | None = None
    sections: list[DocumentSection] = Field(default_factory=list, max_length=MAX_SECTIONS)
    # A simple single-flow document body, used when `sections` is empty —
    # a quick report/invoice/resume doesn't always need structured sections.
    body: str = ""
    overwrite: bool = True


class GeneratePdfOutput(BaseModel):
    path: str
    bytes_written: int
    pages: int
    created: bool


class GenerateDocxInput(BaseModel):
    path: str
    title: str | None = None
    sections: list[DocumentSection] = Field(default_factory=list, max_length=MAX_SECTIONS)
    body: str = ""
    overwrite: bool = True


class GenerateDocxOutput(BaseModel):
    path: str
    bytes_written: int
    created: bool


CellValue = str | float | int | None


class SpreadsheetSheet(BaseModel):
    name: str = "Sheet1"
    headers: list[str] = Field(default_factory=list)
    rows: list[list[CellValue]] = Field(default_factory=list, max_length=MAX_SHEET_ROWS)


class GenerateXlsxInput(BaseModel):
    path: str
    sheets: list[SpreadsheetSheet] = Field(min_length=1)
    overwrite: bool = True


class GenerateXlsxOutput(BaseModel):
    path: str
    bytes_written: int
    sheet_count: int
    row_count: int
    created: bool


class GenerateCsvInput(BaseModel):
    path: str
    headers: list[str] = Field(default_factory=list)
    rows: list[list[CellValue]] = Field(default_factory=list, max_length=MAX_SHEET_ROWS)
    overwrite: bool = True


class GenerateCsvOutput(BaseModel):
    path: str
    bytes_written: int
    row_count: int
    created: bool


# Only conversions with a real, reliable, local (no new external API/service)
# implementation are supported — see tools/documents/conversions.py. Notably
# absent: docx_to_pdf (no reliable pure-Python renderer exists without a much
# heavier dependency like a headless LibreOffice install).
ConversionKind = Literal[
    "text_to_pdf", "markdown_to_pdf", "image_to_pdf", "pdf_to_text", "csv_to_xlsx", "xlsx_to_csv"
]


class ConvertFileInput(BaseModel):
    source_path: str
    target_path: str
    overwrite: bool = True


class ConvertFileOutput(BaseModel):
    source_path: str
    target_path: str
    conversion: ConversionKind
    bytes_written: int
    created: bool
