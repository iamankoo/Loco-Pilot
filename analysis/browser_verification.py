"""Real browser verification for a running web/UI runtime — the visual
counterpart to `analysis.static_site`'s static, file-level checks.

Uses Playwright (an already-installed, real browser automation library —
see pyproject.toml) to actually load the platform's own verified
`runtime_url` (never an arbitrary or agent-claimed URL) in a headless
Chromium instance and observe what a real user's browser would: does the
page render any visible content, do images actually load, are there
console errors, how many interactive elements exist, and — when a
`screenshot_path` is given — a real PNG screenshot saved to disk as
evidence.

Playwright/its browser binary is an optional runtime dependency: if it
isn't installed (e.g. `playwright install chromium` was never run in this
deployment), `verify_in_browser` reports `available=False` with a clear
reason rather than raising — callers (agents.tester) must never let a
missing optional capability fail an otherwise-successful execution, and
must never claim visual verification happened when it didn't.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BrowserVerificationResult:
    # False whenever real browser verification could not be attempted at
    # all (Playwright/Chromium unavailable, or navigation itself failed to
    # even reach the page) — distinct from `ok`, which judges what was
    # actually observed once a real page load occurred.
    available: bool
    # True only when `available` and the page shows real signs of a
    # rendered, non-empty, error-free page. Meaningless when `available`
    # is False.
    ok: bool = False
    reason: str = ""
    console_errors: list[str] = field(default_factory=list)
    # Local (same-origin/relative) <img> srcs that returned a non-2xx
    # response or otherwise never loaded — a strong "broken imagery" signal
    # a plain HTTP reachability check can't see.
    broken_images: list[str] = field(default_factory=list)
    visible_text_length: int = 0
    heading_count: int = 0
    image_count: int = 0
    interactive_count: int = 0
    # Workspace-relative path the screenshot was actually written to, or
    # None if no screenshot was requested/captured.
    screenshot_path: str | None = None


_NAV_TIMEOUT_MS = 15_000
_SETTLE_TIMEOUT_MS = 3_000
_MIN_VISIBLE_TEXT_FOR_NON_BLANK = 40


async def verify_in_browser(
    url: str,
    *,
    screenshot_file: Path | None = None,
    timeout_ms: int = _NAV_TIMEOUT_MS,
) -> BrowserVerificationResult:
    """Navigates a real headless Chromium to `url` and inspects the
    rendered page. `screenshot_file`, if given, is an absolute filesystem
    path (inside the workspace) to save a real PNG screenshot to — the
    caller is responsible for turning that into a workspace-relative path
    for the caller's own evidence record.

    Never raises: any failure (missing Playwright, missing browser
    binary, navigation timeout, a page that errors before it can be
    inspected) becomes `available=False` with `reason` explaining why,
    so a deployment without this optional capability still completes
    executions normally — just without visual evidence."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return BrowserVerificationResult(
            available=False,
            reason="Playwright is not installed in this deployment; browser verification is unavailable.",
        )

    console_errors: list[str] = []
    try:
        async with async_playwright() as playwright:
            try:
                browser = await playwright.chromium.launch(headless=True)
            except Exception as exc:  # noqa: BLE001 - a missing browser binary must not crash the caller
                return BrowserVerificationResult(
                    available=False,
                    reason=f"Could not launch a headless browser: {exc}",
                )

            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 800})
                page.on(
                    "console",
                    lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
                )

                try:
                    await page.goto(url, timeout=timeout_ms, wait_until="load")
                except Exception as exc:  # noqa: BLE001 - report as unreachable, never raise
                    return BrowserVerificationResult(
                        available=True,
                        ok=False,
                        reason=f"Page did not load: {exc}",
                        console_errors=console_errors,
                    )

                await page.wait_for_timeout(_SETTLE_TIMEOUT_MS)

                metrics = await page.evaluate(
                    """() => {
                        const imgs = Array.from(document.images || []);
                        const broken = imgs
                            .filter(img => img.src && (!img.complete || img.naturalWidth === 0))
                            .map(img => img.getAttribute('src') || img.src);
                        // A common LLM markup mistake: `<svg src="...">` — SVG has no `src`
                        // attribute, so the browser silently renders an empty element instead
                        // of the referenced file. Not visible in document.images (only real
                        // <img> elements appear there), so it needs its own check here to be
                        // treated as the broken reference it actually is.
                        const invalidSvgRefs = Array.from(document.querySelectorAll('svg[src]'))
                            .map(svg => svg.getAttribute('src'));
                        const text = (document.body && document.body.innerText || '').trim();
                        return {
                            visibleTextLength: text.length,
                            headingCount: document.querySelectorAll('h1, h2, h3').length,
                            imageCount: imgs.length + invalidSvgRefs.length,
                            brokenImages: broken.concat(invalidSvgRefs).slice(0, 20),
                            interactiveCount: document.querySelectorAll(
                                'button, a[href], input, select, textarea'
                            ).length,
                        };
                    }"""
                )

                screenshot_saved: str | None = None
                if screenshot_file is not None:
                    try:
                        screenshot_file.parent.mkdir(parents=True, exist_ok=True)
                        await page.screenshot(path=str(screenshot_file), full_page=False)
                        screenshot_saved = str(screenshot_file)
                    except Exception as exc:  # noqa: BLE001 - missing screenshot must not fail verification itself
                        console_errors.append(f"(screenshot capture failed: {exc})")

                visible_text_length = int(metrics.get("visibleTextLength", 0))
                broken_images = list(metrics.get("brokenImages") or [])
                ok = visible_text_length >= _MIN_VISIBLE_TEXT_FOR_NON_BLANK and not broken_images
                reason = (
                    "Page rendered with visible content and no broken images."
                    if ok
                    else (
                        "Page appears blank or has too little visible text."
                        if visible_text_length < _MIN_VISIBLE_TEXT_FOR_NON_BLANK
                        else f"{len(broken_images)} local image reference(s) failed to load."
                    )
                )

                return BrowserVerificationResult(
                    available=True,
                    ok=ok,
                    reason=reason,
                    console_errors=console_errors[:20],
                    broken_images=broken_images,
                    visible_text_length=visible_text_length,
                    heading_count=int(metrics.get("headingCount", 0)),
                    image_count=int(metrics.get("imageCount", 0)),
                    interactive_count=int(metrics.get("interactiveCount", 0)),
                    screenshot_path=screenshot_saved,
                )
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001 - any unexpected Playwright failure degrades to "unavailable"
        return BrowserVerificationResult(
            available=False,
            reason=f"Browser verification failed unexpectedly: {exc}",
        )
