from __future__ import annotations

import asyncio
import base64
import mimetypes
import re
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

if TYPE_CHECKING:
    pass


def sanitize_filename(title: str, max_length: int = 100) -> str:
    """
    Sanitize title for use in filename.

    Removes invalid characters and limits length.
    No colons for Windows compatibility.
    """
    sanitized = re.sub(r'[<>:"/\\|?*]', "", title)
    sanitized = re.sub(r"\s+", "_", sanitized.strip())
    sanitized = sanitized.lower()

    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]

    sanitized = sanitized.strip("_")

    return sanitized or "webpage"


class WebpageSnapshotService:
    """Service for snapshotting webpages using Playwright."""

    def __init__(self, app=None):
        self.app = app

    async def _snapshot_webpage_async(
        self,
        url: str,
        title: str,
        html_output_dir: Path,
    ) -> Tuple[str, str]:
        """
        Snapshot a webpage to HTML format using Playwright's async API.

        Args:
            url: The URL to snapshot
            title: The page title for filename generation
            html_output_dir: Directory for HTML snapshots

        Returns:
            Tuple of (html_path, page_content)
        """
        html_output_dir = Path(html_output_dir)

        html_output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sanitized_title = sanitize_filename(title)

        html_filename = f"{sanitized_title}_{timestamp}.html"

        html_path = html_output_dir / html_filename

        if self.app:
            self.app._add_log("webpage_snapshot_start", f"Snapshotting webpage: {url}")

        try:
            async with async_playwright() as p:
                # Use WebKit (lighter); PDFs rendered via xhtml2pdf
                browser = await p.webkit.launch(headless=True)
                page = await browser.new_page()

                if self.app:
                    self.app._add_log(
                        "webpage_snapshot_loading", f"Loading page: {url}"
                    )

                await page.goto(url, wait_until="networkidle", timeout=60000)

                # Best-effort: trigger lazy loads
                try:
                    await page.evaluate(
                        "window.scrollTo(0, document.body.scrollHeight)"
                    )
                    await page.wait_for_timeout(500)
                except Exception:
                    pass

                # Inline external stylesheets for better offline fidelity
                try:
                    stylesheet_urls = await page.eval_on_selector_all(
                        'link[rel="stylesheet"]', "els => els.map(e => e.href)"
                    )
                    for href in stylesheet_urls:
                        try:
                            resp = await page.context.request.get(href)
                            if resp.ok:
                                css_text = await resp.text()
                                await page.add_style_tag(content=css_text)
                        except Exception:
                            # Skip broken styles, keep going
                            continue
                    # Remove original link tags to avoid external fetches when offline
                    await page.evaluate(
                        'Array.from(document.querySelectorAll("link[rel=\\"stylesheet\\"]")).forEach(e => e.remove())'
                    )
                except Exception:
                    # Continue even if stylesheet inlining fails
                    pass

                # Inline images as data URLs
                try:
                    img_urls = await page.eval_on_selector_all(
                        "img[src]",
                        'els => els.map(e => new URL(e.getAttribute("src"), document.baseURI).href)',
                    )
                    mapping = {}
                    for img_url in img_urls:
                        try:
                            resp = await page.context.request.get(img_url)
                            if not resp.ok:
                                continue
                            content_type = resp.headers.get(
                                "content-type", "application/octet-stream"
                            )
                            data = await resp.body()
                            b64 = base64.b64encode(data).decode("ascii")
                            mapping[img_url] = f"data:{content_type};base64,{b64}"
                        except Exception:
                            continue
                    if mapping:
                        await page.evaluate(
                            '(map) => { Array.from(document.querySelectorAll("img[src]")).forEach(img => { const abs = new URL(img.getAttribute("src"), document.baseURI).href; if (map[abs]) img.setAttribute("src", map[abs]); }); }',
                            mapping,
                        )
                except Exception:
                    # Continue even if image inlining fails
                    pass

                # Get HTML and further inline CSS url(...) from <style> tags and style="..."
                raw_html = await page.content()

                def _strip_quotes(s: str) -> str:
                    s = s.strip().strip('"').strip("'")
                    return s

                async def _inline_css_urls_on_html(html: str) -> str:
                    soup = BeautifulSoup(html, "html.parser")
                    css_regex = re.compile(r"url\(([^)]+)\)", re.IGNORECASE)

                    async def inline_css_block(css_text: str) -> str:
                        if not css_text:
                            return css_text
                        urls = set()
                        for m in css_regex.finditer(css_text):
                            u = _strip_quotes(m.group(1))
                            if not u or u.startswith("data:"):
                                continue
                            urls.add(u)

                        mapping = {}
                        for u in urls:
                            try:
                                abs_url = urljoin(url, u)
                                resp = await page.context.request.get(abs_url)
                                if not resp.ok:
                                    continue
                                content_type = (
                                    resp.headers.get("content-type")
                                    or mimetypes.guess_type(abs_url)[0]
                                    or "application/octet-stream"
                                )
                                data = await resp.body()
                                b64 = base64.b64encode(data).decode("ascii")
                                mapping[u] = f"data:{content_type};base64,{b64}"
                            except Exception:
                                continue

                        def replacer(m: re.Match) -> str:
                            inner = _strip_quotes(m.group(1))
                            repl = mapping.get(inner)
                            if repl:
                                return f'url("{repl}")'
                            return m.group(0)

                        try:
                            return css_regex.sub(replacer, css_text)
                        except Exception:
                            return css_text

                    # Inline <style> tag contents
                    for style_tag in soup.find_all("style"):
                        try:
                            css_text = (
                                style_tag.string
                                if style_tag.string is not None
                                else style_tag.get_text()
                            )
                            new_css = await inline_css_block(css_text)
                            if style_tag.string is not None:
                                style_tag.string.replace_with(new_css)
                            else:
                                style_tag.clear()
                                style_tag.append(new_css)
                        except Exception:
                            continue

                    # Inline style attributes
                    for el in soup.find_all(style=True):
                        try:
                            css_text = el.get("style", "")
                            new_css = await inline_css_block(css_text)
                            el["style"] = new_css
                        except Exception:
                            continue

                    return str(soup)

                page_content = await _inline_css_urls_on_html(raw_html)

                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(page_content)

                if self.app:
                    self.app._add_log(
                        "webpage_snapshot_html", f"HTML snapshot saved: {html_filename}"
                    )

                await browser.close()

                if self.app:
                    self.app._add_log(
                        "webpage_snapshot_success", f"Webpage snapshot complete"
                    )

                return str(html_path), page_content

        except Exception as e:
            if self.app:
                self.app._add_log(
                    "webpage_snapshot_error",
                    f"Failed to snapshot webpage: {type(e).__name__}: {str(e)}",
                )
                self.app._add_log(
                    "webpage_snapshot_error_trace", f"{traceback.format_exc()}"
                )
            raise Exception(f"Failed to snapshot webpage: {str(e)}")

    def snapshot_webpage(
        self,
        url: str,
        title: str,
        html_output_dir: Path,
    ) -> Tuple[str, str]:
        """
        Synchronous wrapper that safely runs the async snapshot in or out of an event loop.

        Returns:
            Tuple of (html_path, page_content)
        """
        try:
            # If there is a running loop, run the async task in a separate thread
            loop = asyncio.get_running_loop()

            def runner() -> Tuple[str, str]:
                return asyncio.run(
                    self._snapshot_webpage_async(
                        url=url,
                        title=title,
                        html_output_dir=html_output_dir,
                    )
                )

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(runner)
                return future.result()
        except RuntimeError:
            # No running loop; safe to run directly
            return asyncio.run(
                self._snapshot_webpage_async(
                    url=url,
                    title=title,
                    html_output_dir=html_output_dir,
                )
            )
