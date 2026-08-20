"""Reusable filtering rules for what the repository indexer should touch.

Extends the same excluded-directory set the `search_files` tool uses
(`tools.filesystem.schemas.DEFAULT_EXCLUDED_DIRS`) rather than maintaining
a second list, plus a few indexer-specific extras (build/coverage output
directories) that aren't relevant to an interactive workspace search.
"""

from __future__ import annotations

from pathlib import Path

from tools.filesystem.schemas import DEFAULT_EXCLUDED_DIRS

EXCLUDED_DIRS = DEFAULT_EXCLUDED_DIRS | {"coverage", ".next", "target", ".idea", ".vscode", "htmlcov"}

SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".mdx", ".txt", ".json", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".java", ".go", ".rs", ".rb", ".php", ".c", ".h", ".cpp", ".hpp",
    ".css", ".scss", ".html", ".sql", ".sh", ".ps1",
}

MAX_INDEXABLE_FILE_BYTES = 500_000


def is_excluded_dir(name: str) -> bool:
    return name in EXCLUDED_DIRS


def is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS
