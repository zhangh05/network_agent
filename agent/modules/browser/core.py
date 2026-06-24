# agent/modules/browser/core.py
"""Browser automation — Playwright-based web interaction."""

from __future__ import annotations

import asyncio
from typing import Optional

_playwright = None
_browser = None
_page = None


def _ensure_playwright():
    global _playwright
    if _playwright is None:
        try:
            from playwright.async_api import async_playwright
            _playwright = async_playwright
        except ImportError:
            raise ImportError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )


async def _get_page():
    global _browser, _page, _playwright
    _ensure_playwright()
    if _browser is None:
        pw = await _playwright().start()
        _browser = await pw.chromium.launch(headless=True)
    if _page is None or _page.is_closed():
        ctx = await _browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        _page = await ctx.new_page()
    return _page


def browser_navigate(url: str, wait_selector: str = "") -> dict:
    """Navigate browser to URL. Returns page title and visible text."""
    async def _nav():
        page = await _get_page()
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        if wait_selector:
            await page.wait_for_selector(wait_selector, timeout=10000)
        title = await page.title()
        text = await page.inner_text("body")
        return {
            "ok": True,
            "url": url,
            "title": title,
            "text": text[:5000],
        }
    try:
        return asyncio.run(_nav())
    except Exception as e:
        return {"ok": False, "error": f"Browser navigate failed: {str(e)[:200]}"}


def browser_screenshot(url: str, full_page: bool = False) -> dict:
    """Take screenshot of a web page. Returns base64 PNG."""
    import base64

    async def _shot():
        page = await _get_page()
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        data = await page.screenshot(full_page=full_page)
        return base64.b64encode(data).decode()

    try:
        b64 = asyncio.run(_shot())
        return {"ok": True, "url": url, "screenshot_base64": b64[:100] + f"... ({len(b64)} chars total)"}
    except Exception as e:
        return {"ok": False, "error": f"Browser screenshot failed: {str(e)[:200]}"}


def browser_click(selector: str) -> dict:
    """Click an element on the current page."""

    async def _click():
        page = await _get_page()
        await page.click(selector, timeout=5000)
        title = await page.title()
        return {"ok": True, "clicked": selector, "title": title}

    try:
        return asyncio.run(_click())
    except Exception as e:
        return {"ok": False, "error": f"Browser click failed: {str(e)[:200]}"}


def browser_extract(url: str, selector: str = "body") -> dict:
    """Extract text content from a specific element on a page."""

    async def _extract():
        page = await _get_page()
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        text = await page.inner_text(selector)
        return {"ok": True, "url": url, "selector": selector, "text": text[:8000]}

    try:
        return asyncio.run(_extract())
    except Exception as e:
        return {"ok": False, "error": f"Browser extract failed: {str(e)[:200]}"}


def browser_close() -> dict:
    """Close the browser instance and stop Playwright."""

    async def _close():
        global _browser, _page
        if _page and not _page.is_closed():
            await _page.close()
        if _browser:
            await _browser.close()
        _page = None
        _browser = None
        return {"ok": True, "closed": True}

    try:
        return asyncio.run(_close())
    except Exception as e:
        return {"ok": False, "error": str(e)}
