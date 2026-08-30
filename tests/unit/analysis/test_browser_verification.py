"""Phase 8: real browser (Playwright) verification of a running runtime.

Playwright and its Chromium binary are an optional dependency (see
pyproject.toml's `browser` extra) — the "unavailable" path is tested
unconditionally (it must work even when Playwright genuinely isn't
installed), while the real-navigation tests are skipped when the
dependency truly isn't present, exactly the graceful-degradation contract
`analysis.browser_verification` itself implements.
"""

from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

from analysis.browser_verification import verify_in_browser

playwright = pytest.importorskip("playwright", reason="playwright is an optional dependency")


async def test_verify_in_browser_reports_unavailable_when_playwright_missing(monkeypatch) -> None:
    """Simulates a deployment where Playwright is not installed at all —
    setting a module to None in sys.modules makes any subsequent `import`/
    `from ... import ...` of it raise ImportError (a documented CPython
    mechanism), without actually uninstalling the real package."""
    import sys

    monkeypatch.setitem(sys.modules, "playwright.async_api", None)

    result = await verify_in_browser("http://example.invalid")

    assert result.available is False
    assert "not installed" in result.reason.lower()


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # noqa: D401 - silence test server logging
        pass

    def do_GET(self) -> None:  # noqa: N802 - required override name
        if self.path == "/broken.png":
            self.send_response(404)
            self.end_headers()
            return
        body = (
            b"<html><body><h1>Wonderyard</h1>"
            b"<p>" + b"A" * 60 + b"</p>"
            b"<img src='/broken.png'>"
            b"<svg src='character.svg' alt='invalid svg src'></svg>"
            b"</body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def local_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


async def test_verify_in_browser_detects_broken_image_and_captures_screenshot(local_server, tmp_path: Path) -> None:
    screenshot = tmp_path / "shot.png"
    result = await verify_in_browser(local_server, screenshot_file=screenshot)

    assert result.available is True
    assert result.ok is False  # the broken /broken.png reference must be caught
    assert "/broken.png" in " ".join(result.broken_images)
    # `<svg src="...">` is invalid markup (SVG has no `src` attribute) — a
    # real mistake generated markup can make, invisible to document.images
    # since it's never a real <img> element, so it needs its own check.
    assert "character.svg" in " ".join(result.broken_images)
    assert result.heading_count == 1
    assert screenshot.is_file()
    assert result.screenshot_path == str(screenshot)


async def test_verify_in_browser_reports_unreachable_url_without_raising() -> None:
    result = await verify_in_browser("http://127.0.0.1:1")  # nothing listens here
    assert result.available is True
    assert result.ok is False
    assert "did not load" in result.reason.lower()
