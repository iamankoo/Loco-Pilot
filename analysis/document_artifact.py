"""Deterministic verification for a generated document/spreadsheet
deliverable — the document-generation counterpart to `analysis.static_site`
for a project with neither a recognized test framework nor an HTML entry
point. Without this, a task like "create a PDF report" could never
honestly reach `agents.state.compute_honest_status`'s "passed" (it
requires a real `TestResult.status == "passed"`), permanently capping even
a correctly-completed document task at "needs_review" — the same problem
`analysis.static_site` solves for websites.

Only ever looks at files a document tool (`tools.documents.tools`) actually
reported creating/modifying via `agents.state.FileChange.detail` — never
guesses from a file extension alone, since an unrelated `write_file` call
could coincidentally produce a `.csv`/`.pdf`-named file for other reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agents.schemas import FileChange
from tools.workspace import Workspace

_DOCUMENT_TOOL_PREFIXES = ("generate_pdf ", "generate_docx ", "generate_xlsx ", "generate_csv ", "convert_file ")

# Real magic-byte/structural checks — the same discipline
# `analysis.static_site.validate_binary_asset` applies to images.
_ZIP_MAGIC = b"PK"  # DOCX/XLSX are both OOXML: a real ZIP archive
_PDF_MAGIC = b"%PDF-"


def _looks_like_valid(path: Path) -> tuple[bool, str]:
    suffix = path.suffix.lower()
    try:
        head = path.read_bytes()[:16]
    except OSError as exc:
        return False, f"could not read {path.name}: {exc}"

    if suffix == ".pdf":
        return (True, "ok") if head.startswith(_PDF_MAGIC) else (False, f"{path.name} does not look like a valid PDF file")
    if suffix in (".docx", ".xlsx"):
        return (True, "ok") if head.startswith(_ZIP_MAGIC) else (False, f"{path.name} does not look like a valid {suffix.lstrip('.').upper()} file")
    if suffix == ".csv":
        try:
            import csv

            with path.open(newline="", encoding="utf-8", errors="replace") as fh:
                rows = list(csv.reader(fh))
        except OSError as exc:
            return False, f"could not parse {path.name} as CSV: {exc}"
        return (True, "ok") if rows else (False, f"{path.name} is empty")
    return True, "ok"  # not a document extension this checks — existence alone is the relevant fact


@dataclass
class DocumentArtifactVerification:
    checked_paths: list[str] = field(default_factory=list)
    missing_paths: list[str] = field(default_factory=list)
    invalid_paths: list[tuple[str, str]] = field(default_factory=list)

    @property
    def found_any(self) -> bool:
        return bool(self.checked_paths)

    @property
    def ok(self) -> bool:
        return self.found_any and not self.missing_paths and not self.invalid_paths


def verify_document_artifacts(workspace: Workspace, files_changed: list[FileChange]) -> DocumentArtifactVerification:
    result = DocumentArtifactVerification()
    seen: set[str] = set()
    for change in files_changed:
        if change.change_type == "failed":
            continue
        if not change.detail or not change.detail.startswith(_DOCUMENT_TOOL_PREFIXES):
            continue
        if change.path in seen:
            continue
        seen.add(change.path)
        result.checked_paths.append(change.path)

        try:
            resolved = workspace.resolve(change.path)
        except Exception:  # noqa: BLE001 - an escaping/invalid path is "missing", not a crash
            result.missing_paths.append(change.path)
            continue
        if not resolved.is_file():
            result.missing_paths.append(change.path)
            continue

        ok, reason = _looks_like_valid(resolved)
        if not ok:
            result.invalid_paths.append((change.path, reason))

    return result
