"""Deterministic verification for a static HTML/CSS/JS project — the
project-type-aware counterpart to `agents.tester`'s conventional
pytest/Jest/etc. path, for a project with no recognized test framework at
all. Never LLM-driven: every fact here (does the entry HTML exist, does a
referenced local asset exist, is a binary asset's content actually the
format its extension claims) comes from reading real files on disk through
the same `Workspace` boundary every other deterministic platform code
(`analysis.context`, `agents.graph`'s orchestrator node) already uses
directly — not through the agent tool-call/permission layer, since this is
platform code, not an LLM's own choice, exactly like `analysis.context`'s
own relationship to `tools.filesystem`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from tools.filesystem.schemas import DEFAULT_EXCLUDED_DIRS
from tools.workspace import Workspace

_ASSET_SCAN_MAX_DEPTH = 4
_ASSET_SCAN_MAX_FILES = 2000

_EXTERNAL_PREFIXES = ("http://", "https://", "//", "data:", "mailto:", "tel:", "javascript:")

# Magic-byte signatures for the binary image formats a generated static site
# plausibly uses. SVG is XML text, not binary, so it is checked separately.
_IMAGE_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),  # bytes 8-12 must additionally be b"WEBP" — checked separately below
    ".ico": (b"\x00\x00\x01\x00",),
}


@dataclass
class AssetRef:
    kind: str  # "stylesheet" | "script" | "image"
    raw_href: str
    # Workspace-relative resolved path, or None if raw_href couldn't be
    # resolved to a workspace-relative path at all (e.g. an absolute
    # filesystem path, which is simply not a real local reference here).
    resolved_path: str | None


class _AssetRefExtractor(HTMLParser):
    """A minimal, best-effort HTML asset-reference scanner using only the
    standard library — deliberately not a full HTML/DOM parser (no new
    dependency for this), so malformed markup is tolerated the same way a
    browser tolerates it: whatever tags parse, parse; the rest is ignored,
    never a crash."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str]] = []  # (kind, raw_href)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        if tag == "link":
            rel = attr_dict.get("rel", "").lower()
            href = attr_dict.get("href", "")
            if href and ("stylesheet" in rel or "icon" in rel):
                self.refs.append(("stylesheet" if "stylesheet" in rel else "image", href))
        elif tag == "script":
            src = attr_dict.get("src", "")
            if src:
                self.refs.append(("script", src))
        elif tag == "img":
            src = attr_dict.get("src", "")
            if src:
                self.refs.append(("image", src))


def _is_external(href: str) -> bool:
    return href.lower().startswith(_EXTERNAL_PREFIXES)


def extract_local_asset_refs(html_text: str, *, html_dir: str) -> list[AssetRef]:
    """`html_dir` is the workspace-relative directory the HTML file itself
    lives in (e.g. "" for a root-level index.html, "cartoon-site" for
    cartoon-site/index.html) — relative asset hrefs resolve against it."""
    parser = _AssetRefExtractor()
    try:
        parser.feed(html_text)
    except Exception:  # noqa: BLE001 - malformed HTML must not crash verification, just yield fewer refs
        pass

    refs: list[AssetRef] = []
    for kind, raw_href in parser.refs:
        if _is_external(raw_href):
            refs.append(AssetRef(kind=kind, raw_href=raw_href, resolved_path=None))
            continue
        # Strip a query string/fragment (e.g. "style.css?v=2") — irrelevant
        # to whether the underlying local file exists.
        path_part = urlsplit(raw_href).path
        if not path_part:
            refs.append(AssetRef(kind=kind, raw_href=raw_href, resolved_path=None))
            continue
        if path_part.startswith("/"):
            # A site-root-relative path (e.g. "/style.css") — resolve
            # against the workspace root, not the HTML file's directory.
            resolved = path_part.lstrip("/")
        else:
            resolved = os.path.normpath(os.path.join(html_dir, path_part)).replace(os.sep, "/")
        refs.append(AssetRef(kind=kind, raw_href=raw_href, resolved_path=resolved))
    return refs


def _looks_like_svg(data: bytes) -> bool:
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n")
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2000])


def validate_binary_asset(path: Path) -> tuple[bool, str]:
    """Checks that a file's real content matches the binary format its
    extension claims — the exact class of bug this closes: a model writing
    literal base64 TEXT (or any other non-image content) to a file named
    `*.png` via a text-only write path. Returns (ok, reason)."""
    suffix = path.suffix.lower()
    if suffix == ".svg":
        try:
            data = path.read_bytes()[:2000]
        except OSError as exc:
            return False, f"could not read {path.name}: {exc}"
        return (True, "ok") if _looks_like_svg(data) else (False, f"{path.name} does not look like valid SVG markup")

    signatures = _IMAGE_MAGIC.get(suffix)
    if signatures is None:
        # Not an image extension this checks (e.g. .css/.js/.html/.json) —
        # existence alone (checked by the caller) is the relevant fact.
        return True, "ok"

    try:
        head = path.read_bytes()[:16]
    except OSError as exc:
        return False, f"could not read {path.name}: {exc}"

    if suffix == ".webp":
        ok = head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    else:
        ok = any(head.startswith(sig) for sig in signatures)

    if ok:
        return True, "ok"
    looks_like_text = all(32 <= b < 127 or b in (9, 10, 13) for b in head)
    hint = " (content looks like text, not binary image data)" if looks_like_text else ""
    return False, f"{path.name} does not look like a valid {suffix.lstrip('.').upper()} file{hint}"


@dataclass
class StaticSiteVerification:
    entry_path: str | None = None
    checked_assets: list[str] = field(default_factory=list)
    missing_assets: list[str] = field(default_factory=list)
    invalid_assets: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)

    @property
    def ok(self) -> bool:
        return self.entry_path is not None and not self.missing_assets and not self.invalid_assets


def _find_html_entrypoint(workspace: Workspace, hint_paths: list[str]) -> str | None:
    for candidate in hint_paths:
        if candidate.lower().endswith(".html"):
            resolved = (workspace.root / candidate)
            if resolved.is_file():
                return candidate

    root_index = workspace.root / "index.html"
    if root_index.is_file():
        return "index.html"

    found: list[str] = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(workspace.root):
        current = Path(dirpath)
        depth = len(current.relative_to(workspace.root).parts)
        if depth >= _ASSET_SCAN_MAX_DEPTH:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDED_DIRS]
        for name in filenames:
            scanned += 1
            if scanned > _ASSET_SCAN_MAX_FILES:
                break
            if name.lower() == "index.html":
                return workspace.relative(current / name)
            if name.lower().endswith(".html"):
                found.append(workspace.relative(current / name))
        if scanned > _ASSET_SCAN_MAX_FILES:
            break
    return found[0] if found else None


def verify_static_site(workspace: Workspace, *, hint_paths: list[str] | None = None) -> StaticSiteVerification:
    """The deterministic check `agents.tester` runs for a project with no
    recognized automated-test framework but a real HTML entry point: find
    it, parse it for local stylesheet/script/image references, and confirm
    each one actually exists and — for images — actually contains the
    binary format its extension claims."""
    entry_path = _find_html_entrypoint(workspace, hint_paths or [])
    result = StaticSiteVerification(entry_path=entry_path)
    if entry_path is None:
        return result

    entry_file = workspace.root / entry_path
    try:
        html_text = entry_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        result.missing_assets.append(entry_path)
        result.entry_path = None
        return result

    html_dir = str(Path(entry_path).parent).replace("\\", "/")
    if html_dir == ".":
        html_dir = ""

    for ref in extract_local_asset_refs(html_text, html_dir=html_dir):
        if ref.resolved_path is None:
            continue  # external or unresolvable reference — nothing local to verify
        result.checked_assets.append(ref.resolved_path)
        try:
            resolved = workspace.resolve(ref.resolved_path)
        except Exception:  # noqa: BLE001 - an escaping/invalid href is "missing", not a crash
            result.missing_assets.append(ref.resolved_path)
            continue
        if not resolved.is_file():
            result.missing_assets.append(ref.resolved_path)
            continue
        if ref.kind == "image":
            ok, reason = validate_binary_asset(resolved)
            if not ok:
                result.invalid_assets.append((ref.resolved_path, reason))

    return result
