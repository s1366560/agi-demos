"""Web scrape tool for ReAct agent using Playwright.

This tool allows the agent to extract content from web pages,
including JavaScript-rendered content.
"""

import contextlib
import logging
import re
from typing import Any, ClassVar, cast

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

from src.configuration.config import get_settings
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class WebScrapeTool(AgentTool):
    """
    Tool for scraping web pages using Playwright.

    This tool extracts main content from web pages, handling
    JavaScript-rendered content and various edge cases.
    """

    # Default user agent
    USER_AGENT = "Mozilla/5.0 (compatible; MemStackBot/1.0; +https://memstack.ai/bot)"

    # URL validation pattern
    URL_PATTERN = re.compile(
        r"^https?://"  # http or https
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"  # domain
        r"localhost|"  # localhost
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # IP
        r"(?::\d+)?"  # optional port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )

    # Blocked domains (security)
    BLOCKED_DOMAINS: ClassVar[dict[str, str]] = {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
    }

    # Content selectors for main content extraction
    CONTENT_SELECTORS: ClassVar[list[str]] = [
        "article",
        "main",
        '[role="main"]',
        ".content",
        "#content",
        ".post-content",
        ".article-content",
        "main article",
    ]

    # Unwanted element selectors to remove
    UNWANTED_SELECTORS: ClassVar[list[str]] = [
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

    def __init__(self) -> None:
        """
        Initialize the web scrape tool.
        """
        super().__init__(
            name="web_scrape",
            description=(
                "Extract and read the content of a web page. "
                "Use this tool after finding URLs via web_search to get detailed information. "
                "Handles JavaScript-rendered pages automatically. "
                "Input: url (string) - the full URL to scrape. "
                "Optional: selector (string) - CSS selector for specific content area. "
                "Returns: page title, metadata, and extracted text content."
            ),
        )
        self._settings = get_settings()

    def get_parameters_schema(self) -> dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The full URL to scrape (e.g., 'https://example.com/page')",
                },
                "selector": {
                    "type": "string",
                    "description": "Optional CSS selector to extract specific content area",
                },
            },
            "required": ["url"],
        }

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate that url argument is provided and valid."""
        url = kwargs.get("url")
        if not isinstance(url, str) or not url.strip():
            return False

        # Basic URL validation
        if not self._is_valid_url(url):
            return False

        # Check for blocked domains
        return not self._is_blocked_domain(url)

    def _is_valid_url(self, url: str) -> bool:
        """Check if URL is valid."""
        return bool(self.URL_PATTERN.match(url))

    def _is_blocked_domain(self, url: str) -> bool:
        """Check if URL domain is blocked for security."""
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            # Use hostname instead of netloc to strip port number
            # netloc includes port (e.g., "localhost:8080"), hostname does not
            domain = parsed.hostname
            if domain is None:
                return True  # Block if hostname cannot be parsed

            domain = domain.lower()

            # Check exact matches
            if domain in self.BLOCKED_DOMAINS:
                return True

            # Check for private IP ranges (simplified)
            return bool(domain.startswith("192.168.") or domain.startswith("10."))
        except Exception:
            return True  # Block on parsing errors

    def _sanitize_url(self, url: str) -> str:
        """Ensure URL has a scheme."""
        if not url.startswith(("http://", "https://")):
            return "https://" + url
        return url

    async def _extract_meta_description(self, page: Any) -> str:
        """Extract meta description from the page.

        Args:
            page: Playwright page object.

        Returns:
            Meta description string, or empty string if not found.
        """
        try:
            desc_elem = await page.query_selector('meta[name="description"]')
            if desc_elem:
                return await desc_elem.get_attribute("content") or ""
        except Exception:
            pass
        return ""

    async def _remove_unwanted_elements(self, page: Any) -> None:
        """Remove unwanted elements (nav, header, footer, etc.) from the page.

        Args:
            page: Playwright page object.
        """
        for unwanted in self.UNWANTED_SELECTORS:
            with contextlib.suppress(Exception):
                await page.evaluate(
                    f"document.querySelectorAll('{unwanted}').forEach(el => el.remove())"
                )

    async def _extract_with_selector(self, page: Any, selector: str) -> str:
        """Extract content using a custom CSS selector.

        Args:
            page: Playwright page object.
            selector: CSS selector string.

        Returns:
            Extracted text content.

        Raises:
            ValueError: If selector found no elements or extraction failed.
        """
        try:
            element = await page.query_selector(selector)
            if element:
                return cast(str, await element.inner_text())
            raise ValueError(f"Selector '{selector}' found no elements on page")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Error extracting content with selector: {e!s}") from e

    async def _extract_auto_content(self, page: Any) -> str:
        """Auto-detect and extract main content from the page.

        Tries a list of common content selectors, falling back to body text.

        Args:
            page: Playwright page object.

        Returns:
            Extracted text content.
        """
        for content_selector in self.CONTENT_SELECTORS:
            try:
                element = await page.query_selector(content_selector)
                if element:
                    content = await element.inner_text()
                    logger.debug(f"Found content using selector: {content_selector}")
                    return cast(str, content)
            except Exception:
                continue

        # Fallback to body content
        return cast(str, await page.inner_text("body"))

    async def _scrape_page(self, url: str, selector: str | None) -> str:
        """Launch browser, navigate to URL, and extract content.

        Args:
            url: The URL to scrape.
            selector: Optional CSS selector for specific content area.

        Returns:
            Formatted result string with title, URL, description, and content.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self._settings.playwright_headless,
                args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"],
            )

            try:
                context = await browser.new_context(
                    user_agent=self.USER_AGENT,
                    viewport={"width": 1280, "height": 720},
                    ignore_https_errors=True,
                )
                page = await context.new_page()

                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self._settings.playwright_timeout,
                )

                title = await page.title()
                description = await self._extract_meta_description(page)

                if selector:
                    content = await self._extract_with_selector(page, selector)
                else:
                    await self._remove_unwanted_elements(page)
                    content = await self._extract_auto_content(page)

                content = self._clean_content(content)
                content = self._truncate_content(content)

                result = self._format_result(title, url, description, content)
                await context.close()
                return result

            finally:
                await browser.close()

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute web scrape.

        Args:
            **kwargs: Must contain 'url' (URL to scrape)
                      Optional: 'selector' (CSS selector for specific content)

        Returns:
            String containing scraped content
        """
        url = kwargs.get("url", "")
        selector = kwargs.get("selector")

        if not url:
            return "Error: url parameter is required for web_scrape"

        url = self._sanitize_url(url)

        try:
            logger.info(f"Scraping URL: {url[:100]}...")
            return await self._scrape_page(url, selector)

        except PlaywrightTimeoutError:
            return f"Error: Timeout after {self._settings.playwright_timeout}ms loading page"
        except ValueError as e:
            return f"Error: {e!s}"
        except Exception as e:
            error_msg = f"Error scraping page: {e!s}"
            logger.error(error_msg)
            return f"Error: {error_msg}"

    def _clean_content(self, content: str) -> str:
        """Clean extracted content."""
        # Remove excessive whitespace
        content = re.sub(r"\s+", " ", content)
        # Split into lines and filter
        lines = content.split("\n")
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            # Keep lines with meaningful content
            if len(stripped) > 20:
                # Skip common boilerplate
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
                if not any(phrase in lower for phrase in skip_phrases):
                    cleaned_lines.append(stripped)
        return " ".join(cleaned_lines)

    def _truncate_content(self, content: str) -> str:
        """Truncate content to max length."""
        max_len = self._settings.playwright_max_content_length
        if len(content) > max_len:
            content = content[:max_len] + "... (content truncated)"
        return content

    def _format_result(self, title: str, url: str, description: str, content: str) -> str:
        """Format scrape result as readable string."""
        lines = [
            f"Title: {title}",
            f"URL: {url}",
        ]

        if description:
            lines.append(f"Description: {description[:200]}...")

        lines.append("")
        lines.append("Content:")
        lines.append(content)

        return "\n".join(lines)
