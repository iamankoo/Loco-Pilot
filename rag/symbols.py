"""Lightweight, regex-based symbol extraction — deliberately NOT an
AST/tree-sitter parser. Gives retrieval a cheap "does this chunk actually
define the thing the query is asking about" signal across common
languages, at the cost of missing or mis-detecting unusual syntax (this is
a retrieval hint, not a claim of correct parsing — see the Phase 2.4
README section on chunking/symbol tradeoffs).
"""

from __future__ import annotations

import re

MAX_SYMBOLS_PER_CHUNK = 20

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"

_PATTERNS: dict[str, list[re.Pattern]] = {
    ".py": [
        re.compile(rf"^\s*(?:async\s+)?def\s+({_IDENT})", re.MULTILINE),
        re.compile(rf"^\s*class\s+({_IDENT})", re.MULTILINE),
    ],
    ".js": [
        re.compile(rf"^\s*(?:export\s+(?:default\s+)?)?function\s*\*?\s+({_IDENT})", re.MULTILINE),
        re.compile(rf"^\s*(?:export\s+(?:default\s+)?)?class\s+({_IDENT})", re.MULTILINE),
        re.compile(rf"^\s*(?:export\s+)?const\s+({_IDENT})\s*=\s*(?:async\s*)?\(", re.MULTILINE),
    ],
    ".go": [
        re.compile(rf"^\s*func\s+(?:\([^)]*\)\s*)?({_IDENT})", re.MULTILINE),
        re.compile(rf"^\s*type\s+({_IDENT})\s+struct", re.MULTILINE),
    ],
    ".rs": [
        re.compile(rf"^\s*(?:pub\s+)?(?:async\s+)?fn\s+({_IDENT})", re.MULTILINE),
        re.compile(rf"^\s*(?:pub\s+)?struct\s+({_IDENT})", re.MULTILINE),
        re.compile(rf"^\s*(?:pub\s+)?enum\s+({_IDENT})", re.MULTILINE),
    ],
    ".java": [
        re.compile(rf"\bclass\s+({_IDENT})"),
        re.compile(rf"\binterface\s+({_IDENT})"),
        re.compile(rf"(?:public|private|protected)\s+(?:static\s+)?[\w<>\[\],\s]+?\s+({_IDENT})\s*\("),
    ],
    ".dart": [
        re.compile(rf"^\s*class\s+({_IDENT})", re.MULTILINE),
        re.compile(rf"^\s*(?:Future<[^>]*>|void|[A-Za-z_][\w<>,\s]*)\s+({_IDENT})\s*\(", re.MULTILINE),
    ],
    ".c": [re.compile(rf"^[A-Za-z_][\w\s*]*?\b({_IDENT})\s*\([^;{{]*\)\s*\{{", re.MULTILINE)],
    ".cpp": [re.compile(rf"^[A-Za-z_][\w\s*&:<>]*?\b({_IDENT})\s*\([^;{{]*\)\s*\{{", re.MULTILINE)],
}
_PATTERNS[".jsx"] = _PATTERNS[".js"]
_PATTERNS[".ts"] = _PATTERNS[".js"]
_PATTERNS[".tsx"] = _PATTERNS[".js"]
_PATTERNS[".h"] = _PATTERNS[".c"]
_PATTERNS[".hpp"] = _PATTERNS[".cpp"]
_PATTERNS[".cc"] = _PATTERNS[".cpp"]

_KEYWORDS_TO_SKIP = {"if", "for", "while", "switch", "catch", "return"}


def extract_symbols(content: str, file_extension: str) -> list[str]:
    """Bounded, best-effort function/class/struct names found in `content`
    for the given extension (e.g. ".py"). Returns an empty list for an
    unsupported extension rather than guessing."""
    patterns = _PATTERNS.get(file_extension.lower())
    if not patterns:
        return []

    found: list[str] = []
    for pattern in patterns:
        for match in pattern.finditer(content):
            name = match.group(1)
            if name in _KEYWORDS_TO_SKIP or name in found:
                continue
            found.append(name)
            if len(found) >= MAX_SYMBOLS_PER_CHUNK:
                return found
    return found
