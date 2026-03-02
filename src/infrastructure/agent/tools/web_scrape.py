"""Web scrape tool for ReAct agent using Playwright.

This tool allows the agent to extract content from web pages,
including JavaScript-rendered content.
"""

from __future__ import annotations

import contextlib
import logging
import re
from typing import Any, cast

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

from src.configuration.config import get_settings
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


# === New @tool_define based implementation ===


def configure_web_scrape() -> None:
    """Configure the web scrape tool.

    Placeholder configurator for consistency with other tools.
    Web scrape reads settings inline via get_settings().
    """


# ---------------------------------------------------------------------------
# Helper constants (extracted from class attributes)
# ---------------------------------------------------------------------------

_WS_USER_AGENT = "Mozilla/5.0 (compatible; MemStackBot/1.0; +https://memstack.ai/bot)"

_WS_URL_PATTERN = re.compile(
    r"^https?://"
    r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"
    r"localhost|"
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
    r"(?::\d+)?"
    r"(?:/?|[/?]\S+)$",
    re.IGNORECASE,
)

_WS_BLOCKED_DOMAINS: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
    }
)

_WS_CONTENT_SELECTORS: list[str] = [
    "article",
    "main",
    '[role="main"]',
    ".content",
    "#content",
    ".post-content",
    ".article-content",
    "main article",
]

_WS_UNWANTED_SELECTORS: list[str] = [
    "nav",
    "header",
    "footer",
    "aside",
    ".sidebar",
    ".advertisement",
    ".ads",
    "script",
    "style",
    "noscript",
    "iframe",
]


# ---------------------------------------------------------------------------
# Helper functions (extracted from class methods)
# ---------------------------------------------------------------------------


def _ws_is_blocked_domain(url: str) -> bool:
    """Check if URL domain is blocked for security."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        domain = parsed.hostname
        if domain is None:
            return True
        domain = domain.lower()
        if domain in _WS_BLOCKED_DOMAINS:
            return True
        return bool(domain.startswith("192.168.") or domain.startswith("10."))
    except Exception:
        return True


def _ws_sanitize_url(url: str) -> str:
    """Ensure URL has a scheme."""
    if not url.startswith(("http://", "https://")):
        return "https://" + url
    return url


def _ws_clean_content(content: str) -> str:
    """Clean extracted content."""
    content = re.sub(r"\s+", " ", content)
    lines = content.split("\n")
    cleaned_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) > 20:
            lower = stripped.lower()
            skip_phrases = [
                "cookie policy",
                "privacy policy",
                "terms of service",
                "subscribe to our",
                "sign up for",
                "log in",
                "click here to",
            ]
            if not any(p in lower for p in skip_phrases):
                cleaned_lines.append(stripped)
    return " ".join(cleaned_lines)


def _ws_format_result(
    title: str,
    url: str,
    description: str,
    content: str,
) -> str:
    """Format scrape result as readable string."""
    lines: list[str] = [
        f"Title: {title}",
        f"URL: {url}",
    ]
    if description:
        lines.append(f"Description: {description[:200]}...")
    lines.append("")
    lines.append("Content:")
    lines.append(content)
    return "\n".join(lines)


async def _ws_extract_meta_description(page: Any) -> str:
    """Extract meta description from the page."""
    try:
        desc_elem = await page.query_selector(
            'meta[name="description"]',
        )
        if desc_elem:
            return await desc_elem.get_attribute("content") or ""
    except Exception:
        pass
    return ""


async def _ws_remove_unwanted_elements(page: Any) -> None:
    """Remove unwanted elements from the page."""
    for unwanted in _WS_UNWANTED_SELECTORS:
        with contextlib.suppress(Exception):
            await page.evaluate(
                "document.querySelectorAll('" + unwanted + "').forEach(el => el.remove())"
            )


async def _ws_extract_with_selector(
    page: Any,
    selector: str,
) -> str:
    """Extract content using a custom CSS selector."""
    try:
        element = await page.query_selector(selector)
        if element:
            return cast(str, await element.inner_text())
        msg = f"Selector '{selector}' found no elements on page"
        raise ValueError(msg)
    except ValueError:
        raise
    except Exception as e:
        msg = f"Error extracting content with selector: {e!s}"
        raise ValueError(msg) from e


async def _ws_extract_auto_content(page: Any) -> str:
    """Auto-detect and extract main content from the page."""
    for content_selector in _WS_CONTENT_SELECTORS:
        try:
            element = await page.query_selector(content_selector)
            if element:
                content = await element.inner_text()
                logger.debug(
                    "Found content using selector: %s",
                    content_selector,
                )
                return cast(str, content)
        except Exception:
            continue
    return cast(str, await page.inner_text("body"))


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool_define(
    name="web_scrape",
    description=(
        "Extract and read the content of a web page. "
        "Use this tool after finding URLs via web_search to get "
        "detailed information. Handles JavaScript-rendered pages "
        "automatically. "
        "Input: url (string) - the full URL to scrape. "
        "Optional: selector (string) - CSS selector for specific "
        "content area. "
        "Returns: page title, metadata, and extracted text content."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": ("The full URL to scrape (e.g., 'https://example.com/page')"),
            },
            "selector": {
                "type": "string",
                "description": ("Optional CSS selector to extract specific content area"),
            },
        },
        "required": ["url"],
    },
    permission="web_scrape",
    category="web",
    tags=frozenset({"web", "scrape"}),
)
async def web_scrape_tool(
    ctx: ToolContext,
    *,
    url: str,
    selector: str | None = None,
) -> ToolResult:
    """Scrape a web page via Playwright and return its content."""
    if not url.strip():
        return ToolResult(
            output="Error: url parameter is required for web_scrape",
            is_error=True,
        )

    # Validate URL
    if not _WS_URL_PATTERN.match(url):
        url = _ws_sanitize_url(url)
        if not _WS_URL_PATTERN.match(url):
            return ToolResult(
                output=f"Error: Invalid URL: {url}",
                is_error=True,
            )

    # Check blocked domains
    if _ws_is_blocked_domain(url):
        return ToolResult(
            output="Error: This domain is blocked for security",
            is_error=True,
        )

    url = _ws_sanitize_url(url)
    settings = get_settings()

    try:
        logger.info("Scraping URL: %s...", url[:100])
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=settings.playwright_headless,
                args=[
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            try:
                context = await browser.new_context(
                    user_agent=_WS_USER_AGENT,
                    viewport={"width": 1280, "height": 720},
                    ignore_https_errors=True,
                )
                page = await context.new_page()
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=settings.playwright_timeout,
                )

                title = await page.title()
                description = await _ws_extract_meta_description(page)

                if selector:
                    content = await _ws_extract_with_selector(
                        page,
                        selector,
                    )
                else:
                    await _ws_remove_unwanted_elements(page)
                    content = await _ws_extract_auto_content(page)

                content = _ws_clean_content(content)
                max_len = settings.playwright_max_content_length
                if len(content) > max_len:
                    content = content[:max_len] + "... (content truncated)"

                formatted = _ws_format_result(
                    title,
                    url,
                    description,
                    content,
                )
                await context.close()

                return ToolResult(
                    output=formatted,
                    title=f"Scraped: {title[:60]}",
                    metadata={"url": url, "title": title},
                )
            finally:
                await browser.close()

    except PlaywrightTimeoutError:
        msg = f"Error: Timeout after {settings.playwright_timeout}ms loading page"
        return ToolResult(output=msg, is_error=True)
    except Exception as e:
        if isinstance(e, ValueError):
            error_msg = f"Error: {e!s}"
        else:
            error_msg = f"Error scraping page: {e!s}"
        logger.error(error_msg)
        return ToolResult(
            output=error_msg,
            is_error=True,
        )
