from __future__ import annotations

from agents.schemas import FileChange
from analysis.document_artifact import verify_document_artifacts
from tools.workspace import Workspace


def test_verify_document_artifacts_returns_not_found_when_no_document_tool_used(tmp_workspace: Workspace) -> None:
    changes = [FileChange(path="notes.txt", change_type="created", detail="write_file applied")]
    result = verify_document_artifacts(tmp_workspace, changes)
    assert result.found_any is False
    assert result.ok is False


def test_verify_document_artifacts_accepts_a_real_pdf(tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "report.pdf").write_bytes(b"%PDF-1.4\n...")
    changes = [FileChange(path="report.pdf", change_type="created", detail="generate_pdf applied")]
    result = verify_document_artifacts(tmp_workspace, changes)
    assert result.found_any is True
    assert result.ok is True
    assert result.checked_paths == ["report.pdf"]


def test_verify_document_artifacts_rejects_a_fake_pdf(tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "report.pdf").write_bytes(b"this is not really a pdf")
    changes = [FileChange(path="report.pdf", change_type="created", detail="generate_pdf applied")]
    result = verify_document_artifacts(tmp_workspace, changes)
    assert result.found_any is True
    assert result.ok is False
    assert result.invalid_paths[0][0] == "report.pdf"


def test_verify_document_artifacts_rejects_missing_file(tmp_workspace: Workspace) -> None:
    changes = [FileChange(path="ghost.pdf", change_type="created", detail="generate_pdf applied")]
    result = verify_document_artifacts(tmp_workspace, changes)
    assert result.found_any is True
    assert result.missing_paths == ["ghost.pdf"]


def test_verify_document_artifacts_accepts_real_xlsx_and_docx_zip_magic(tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "data.xlsx").write_bytes(b"PK\x03\x04fakezipbytes")
    (tmp_workspace.root / "doc.docx").write_bytes(b"PK\x03\x04fakezipbytes")
    changes = [
        FileChange(path="data.xlsx", change_type="created", detail="generate_xlsx applied"),
        FileChange(path="doc.docx", change_type="created", detail="generate_docx applied"),
    ]
    result = verify_document_artifacts(tmp_workspace, changes)
    assert result.ok is True


def test_verify_document_artifacts_ignores_failed_changes(tmp_workspace: Workspace) -> None:
    changes = [FileChange(path="report.pdf", change_type="failed", detail="generate_pdf applied")]
    result = verify_document_artifacts(tmp_workspace, changes)
    assert result.found_any is False


def test_verify_document_artifacts_accepts_real_csv(tmp_workspace: Workspace) -> None:
    (tmp_workspace.root / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    changes = [FileChange(path="data.csv", change_type="created", detail="generate_csv applied")]
    result = verify_document_artifacts(tmp_workspace, changes)
    assert result.ok is True
