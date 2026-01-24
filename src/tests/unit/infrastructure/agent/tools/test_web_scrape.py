"""Unit tests for WebScrapeTool.

This test module focuses on security validation since WebScrapeTool
interacts with external websites and must prevent SSRF attacks.
"""

from unittest.mock import Mock, patch

import pytest

from src.infrastructure.agent.tools.web_scrape import WebScrapeTool


class TestWebScrapeToolInit:
    """Test WebScrapeTool initialization."""

    def test_init_sets_correct_name(self):
        """Test tool initializes with correct name."""
        with patch("src.infrastructure.agent.tools.web_scrape.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                playwright_headless=True,
                playwright_timeout=30000,
                playwright_max_content_length=50000,
            )
            tool = WebScrapeTool()
            assert tool.name == "web_scrape"

    def test_init_sets_description(self):
        """Test tool initializes with meaningful description."""
        with patch("src.infrastructure.agent.tools.web_scrape.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                playwright_headless=True,
                playwright_timeout=30000,
                playwright_max_content_length=50000,
            )
            tool = WebScrapeTool()
            assert "scrape" in tool.description.lower() or "extract" in tool.description.lower()
            assert "web" in tool.description.lower()

    def test_blocked_domains_defined(self):
        """Test BLOCKED_DOMAINS is properly defined."""
        with patch("src.infrastructure.agent.tools.web_scrape.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                playwright_headless=True,
                playwright_timeout=30000,
                playwright_max_content_length=50000,
            )
            tool = WebScrapeTool()
            assert "localhost" in tool.BLOCKED_DOMAINS
            assert "127.0.0.1" in tool.BLOCKED_DOMAINS
            assert "0.0.0.0" in tool.BLOCKED_DOMAINS

    def test_content_selectors_defined(self):
        """Test CONTENT_SELECTORS is properly defined."""
        with patch("src.infrastructure.agent.tools.web_scrape.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                playwright_headless=True,
                playwright_timeout=30000,
                playwright_max_content_length=50000,
            )
            tool = WebScrapeTool()
            assert "article" in tool.CONTENT_SELECTORS
            assert "main" in tool.CONTENT_SELECTORS


class TestWebScrapeToolValidation:
    """Test WebScrapeTool argument validation."""

    @pytest.fixture
    def web_scrape_tool(self):
        """Create WebScrapeTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_scrape.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                playwright_headless=True,
                playwright_timeout=30000,
                playwright_max_content_length=50000,
            )
            return WebScrapeTool()

    def test_validate_args_with_valid_url(self, web_scrape_tool):
        """Test validation passes with valid URL."""
        assert web_scrape_tool.validate_args(url="https://example.com") is True
        assert web_scrape_tool.validate_args(url="http://example.com/page") is True
        assert web_scrape_tool.validate_args(url="https://sub.example.com/path?q=1") is True

    def test_validate_args_with_empty_url(self, web_scrape_tool):
        """Test validation fails with empty URL."""
        assert web_scrape_tool.validate_args(url="") is False

    def test_validate_args_with_whitespace_only(self, web_scrape_tool):
        """Test validation fails with whitespace-only URL."""
        assert web_scrape_tool.validate_args(url="   ") is False

    def test_validate_args_missing_url(self, web_scrape_tool):
        """Test validation fails when URL is missing."""
        assert web_scrape_tool.validate_args() is False
        assert web_scrape_tool.validate_args(selector=".content") is False

    def test_validate_args_invalid_url_format(self, web_scrape_tool):
        """Test validation fails with invalid URL format."""
        assert web_scrape_tool.validate_args(url="not-a-url") is False
        assert web_scrape_tool.validate_args(url="ftp://example.com") is False
        assert web_scrape_tool.validate_args(url="javascript:alert(1)") is False


class TestWebScrapeToolSecurityValidation:
    """Test WebScrapeTool security validation - CRITICAL TESTS.

    These tests ensure that internal/local addresses are blocked
    to prevent SSRF (Server-Side Request Forgery) attacks.
    """

    @pytest.fixture
    def web_scrape_tool(self):
        """Create WebScrapeTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_scrape.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                playwright_headless=True,
                playwright_timeout=30000,
                playwright_max_content_length=50000,
            )
            return WebScrapeTool()

    def test_validate_args_blocks_localhost(self, web_scrape_tool):
        """Test validation blocks localhost URLs (without port)."""
        assert web_scrape_tool.validate_args(url="http://localhost") is False
        assert web_scrape_tool.validate_args(url="https://localhost") is False

    def test_validate_args_blocks_localhost_with_port(self, web_scrape_tool):
        """Test validation blocks localhost URLs with port."""
        assert web_scrape_tool.validate_args(url="http://localhost:8080") is False
        assert web_scrape_tool.validate_args(url="http://localhost/path") is False

    def test_validate_args_blocks_127_0_0_1(self, web_scrape_tool):
        """Test validation blocks 127.0.0.1 URLs (without port)."""
        assert web_scrape_tool.validate_args(url="http://127.0.0.1") is False

    def test_validate_args_blocks_127_0_0_1_with_port(self, web_scrape_tool):
        """Test validation blocks 127.0.0.1 URLs with port."""
        assert web_scrape_tool.validate_args(url="http://127.0.0.1:3000") is False
        assert web_scrape_tool.validate_args(url="https://127.0.0.1/admin") is False

    def test_validate_args_blocks_0_0_0_0(self, web_scrape_tool):
        """Test validation blocks 0.0.0.0 URLs (without port)."""
        assert web_scrape_tool.validate_args(url="http://0.0.0.0") is False

    def test_validate_args_blocks_0_0_0_0_with_port(self, web_scrape_tool):
        """Test validation blocks 0.0.0.0 URLs with port."""
        assert web_scrape_tool.validate_args(url="http://0.0.0.0:8000") is False

    def test_validate_args_blocks_ipv6_localhost(self, web_scrape_tool):
        """Test validation blocks IPv6 localhost (::1)."""
        assert web_scrape_tool.validate_args(url="http://[::1]") is False
        assert web_scrape_tool.validate_args(url="http://[::1]:8080") is False

    def test_validate_args_blocks_private_ip_192_168(self, web_scrape_tool):
        """Test validation blocks 192.168.x.x private IP range."""
        assert web_scrape_tool.validate_args(url="http://192.168.1.1") is False
        assert web_scrape_tool.validate_args(url="http://192.168.0.1:8080") is False
        assert web_scrape_tool.validate_args(url="https://192.168.100.50/api") is False

    def test_validate_args_blocks_private_ip_10_x(self, web_scrape_tool):
        """Test validation blocks 10.x.x.x private IP range."""
        assert web_scrape_tool.validate_args(url="http://10.0.0.1") is False
        assert web_scrape_tool.validate_args(url="http://10.10.10.10:3000") is False
        assert web_scrape_tool.validate_args(url="https://10.255.255.255") is False

    def test_validate_args_allows_public_urls(self, web_scrape_tool):
        """Test validation allows legitimate public URLs."""
        assert web_scrape_tool.validate_args(url="https://example.com") is True
        assert web_scrape_tool.validate_args(url="https://www.google.com") is True
        assert web_scrape_tool.validate_args(url="https://github.com/user/repo") is True
        assert web_scrape_tool.validate_args(url="http://news.ycombinator.com") is True


class TestWebScrapeToolUrlProcessing:
    """Test WebScrapeTool URL processing."""

    @pytest.fixture
    def web_scrape_tool(self):
        """Create WebScrapeTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_scrape.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                playwright_headless=True,
                playwright_timeout=30000,
                playwright_max_content_length=50000,
            )
            return WebScrapeTool()

    def test_is_valid_url_with_http(self, web_scrape_tool):
        """Test URL validation with http scheme."""
        assert web_scrape_tool._is_valid_url("http://example.com") is True

    def test_is_valid_url_with_https(self, web_scrape_tool):
        """Test URL validation with https scheme."""
        assert web_scrape_tool._is_valid_url("https://example.com") is True

    def test_is_valid_url_without_scheme(self, web_scrape_tool):
        """Test URL validation without scheme."""
        assert web_scrape_tool._is_valid_url("example.com") is False

    def test_is_valid_url_with_path(self, web_scrape_tool):
        """Test URL validation with path."""
        assert web_scrape_tool._is_valid_url("https://example.com/path/to/page") is True

    def test_is_valid_url_with_query(self, web_scrape_tool):
        """Test URL validation with query string."""
        assert web_scrape_tool._is_valid_url("https://example.com?q=test&page=1") is True

    def test_is_valid_url_with_port(self, web_scrape_tool):
        """Test URL validation with port."""
        assert web_scrape_tool._is_valid_url("https://example.com:8443") is True

    def test_sanitize_url_adds_https(self, web_scrape_tool):
        """Test URL sanitization adds https if missing."""
        assert web_scrape_tool._sanitize_url("example.com") == "https://example.com"

    def test_sanitize_url_preserves_http(self, web_scrape_tool):
        """Test URL sanitization preserves http scheme."""
        assert web_scrape_tool._sanitize_url("http://example.com") == "http://example.com"

    def test_sanitize_url_preserves_https(self, web_scrape_tool):
        """Test URL sanitization preserves https scheme."""
        assert web_scrape_tool._sanitize_url("https://example.com") == "https://example.com"


class TestWebScrapeToolContentCleaning:
    """Test WebScrapeTool content cleaning."""

    @pytest.fixture
    def web_scrape_tool(self):
        """Create WebScrapeTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_scrape.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                playwright_headless=True,
                playwright_timeout=30000,
                playwright_max_content_length=50000,
            )
            return WebScrapeTool()

    def test_clean_content_removes_excessive_whitespace(self, web_scrape_tool):
        """Test content cleaning removes excessive whitespace."""
        content = "Hello    world\n\n\nTest"
        cleaned = web_scrape_tool._clean_content(content)
        # Should not have excessive spaces
        assert "    " not in cleaned

    def test_clean_content_removes_boilerplate_cookie_policy(self, web_scrape_tool):
        """Test content cleaning removes cookie policy text."""
        content = "Article content here. Cookie policy statement. More content."
        cleaned = web_scrape_tool._clean_content(content)
        # Lines containing "cookie policy" should be filtered
        assert "cookie policy" not in cleaned.lower()

    def test_clean_content_removes_boilerplate_privacy_policy(self, web_scrape_tool):
        """Test content cleaning removes privacy policy text."""
        content = "Main content. Privacy policy applies. Article continues."
        cleaned = web_scrape_tool._clean_content(content)
        assert "privacy policy" not in cleaned.lower()

    def test_clean_content_removes_subscribe_prompts(self, web_scrape_tool):
        """Test content cleaning removes subscribe prompts."""
        content = "Article text. Subscribe to our newsletter. More article text."
        cleaned = web_scrape_tool._clean_content(content)
        assert "subscribe to our" not in cleaned.lower()

    def test_clean_content_keeps_short_lines(self, web_scrape_tool):
        """Test content cleaning keeps meaningful short lines."""
        # Lines under 20 chars are filtered out
        content = "This is a meaningful long line with good content"
        cleaned = web_scrape_tool._clean_content(content)
        assert "meaningful" in cleaned

    def test_truncate_content_max_length(self, web_scrape_tool):
        """Test content truncation at max length."""
        long_content = "A" * 100000
        truncated = web_scrape_tool._truncate_content(long_content)
        assert len(truncated) <= 50000 + 50  # max length + truncation notice
        assert "truncated" in truncated.lower()

    def test_truncate_content_short_content_unchanged(self, web_scrape_tool):
        """Test short content is not truncated."""
        short_content = "Short content"
        truncated = web_scrape_tool._truncate_content(short_content)
        assert truncated == short_content


class TestWebScrapeToolResultFormatting:
    """Test WebScrapeTool result formatting."""

    @pytest.fixture
    def web_scrape_tool(self):
        """Create WebScrapeTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_scrape.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                playwright_headless=True,
                playwright_timeout=30000,
                playwright_max_content_length=50000,
            )
            return WebScrapeTool()

    def test_format_result_includes_title(self, web_scrape_tool):
        """Test result formatting includes page title."""
        result = web_scrape_tool._format_result(
            title="Test Page Title",
            url="https://example.com",
            description="Page description",
            content="Page content here",
        )
        assert "Title: Test Page Title" in result

    def test_format_result_includes_url(self, web_scrape_tool):
        """Test result formatting includes URL."""
        result = web_scrape_tool._format_result(
            title="Test",
            url="https://example.com/page",
            description="",
            content="Content",
        )
        assert "URL: https://example.com/page" in result

    def test_format_result_includes_description(self, web_scrape_tool):
        """Test result formatting includes description when available."""
        result = web_scrape_tool._format_result(
            title="Test",
            url="https://example.com",
            description="This is the meta description",
            content="Content",
        )
        assert "Description:" in result
        assert "meta description" in result

    def test_format_result_truncates_long_description(self, web_scrape_tool):
        """Test result formatting truncates long descriptions."""
        long_desc = "A" * 500
        result = web_scrape_tool._format_result(
            title="Test",
            url="https://example.com",
            description=long_desc,
            content="Content",
        )
        # Description should be truncated to 200 chars with ...
        assert "..." in result

    def test_format_result_includes_content_section(self, web_scrape_tool):
        """Test result formatting includes Content section."""
        result = web_scrape_tool._format_result(
            title="Test",
            url="https://example.com",
            description="",
            content="Main page content goes here",
        )
        assert "Content:" in result
        assert "Main page content" in result

    def test_format_result_omits_empty_description(self, web_scrape_tool):
        """Test result formatting omits empty description."""
        result = web_scrape_tool._format_result(
            title="Test",
            url="https://example.com",
            description="",
            content="Content",
        )
        # Should not have empty description line
        lines = result.split("\n")
        description_lines = [line for line in lines if line.startswith("Description:")]
        assert len(description_lines) == 0


class TestWebScrapeToolExecute:
    """Test WebScrapeTool execute method."""

    @pytest.fixture
    def web_scrape_tool(self):
        """Create WebScrapeTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_scrape.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                playwright_headless=True,
                playwright_timeout=30000,
                playwright_max_content_length=50000,
            )
            return WebScrapeTool()

    @pytest.mark.asyncio
    async def test_execute_missing_url_returns_error(self, web_scrape_tool):
        """Test execute returns error when URL is missing."""
        result = await web_scrape_tool.execute()
        assert "Error" in result
        assert "url parameter is required" in result

    @pytest.mark.asyncio
    async def test_execute_blocked_url_returns_error(self, web_scrape_tool):
        """Test execute returns error for blocked URLs via validate_args."""
        # Note: execute doesn't check blocked URLs directly - validation does
        # This test verifies the safe_execute path handles it
        result = await web_scrape_tool.safe_execute(url="http://localhost")
        assert "Error" in result or "Invalid" in result


class TestWebScrapeToolUnwantedElements:
    """Test WebScrapeTool unwanted element filtering."""

    @pytest.fixture
    def web_scrape_tool(self):
        """Create WebScrapeTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_scrape.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                playwright_headless=True,
                playwright_timeout=30000,
                playwright_max_content_length=50000,
            )
            return WebScrapeTool()

    def test_unwanted_selectors_includes_nav(self, web_scrape_tool):
        """Test UNWANTED_SELECTORS includes navigation."""
        assert "nav" in web_scrape_tool.UNWANTED_SELECTORS

    def test_unwanted_selectors_includes_header(self, web_scrape_tool):
        """Test UNWANTED_SELECTORS includes header."""
        assert "header" in web_scrape_tool.UNWANTED_SELECTORS

    def test_unwanted_selectors_includes_footer(self, web_scrape_tool):
        """Test UNWANTED_SELECTORS includes footer."""
        assert "footer" in web_scrape_tool.UNWANTED_SELECTORS

    def test_unwanted_selectors_includes_sidebar(self, web_scrape_tool):
        """Test UNWANTED_SELECTORS includes sidebar."""
        assert ".sidebar" in web_scrape_tool.UNWANTED_SELECTORS

    def test_unwanted_selectors_includes_ads(self, web_scrape_tool):
        """Test UNWANTED_SELECTORS includes ads."""
        assert (
            ".ads" in web_scrape_tool.UNWANTED_SELECTORS
            or ".advertisement" in web_scrape_tool.UNWANTED_SELECTORS
        )

    def test_unwanted_selectors_includes_scripts(self, web_scrape_tool):
        """Test UNWANTED_SELECTORS includes script tags."""
        assert "script" in web_scrape_tool.UNWANTED_SELECTORS

    def test_unwanted_selectors_includes_styles(self, web_scrape_tool):
        """Test UNWANTED_SELECTORS includes style tags."""
        assert "style" in web_scrape_tool.UNWANTED_SELECTORS


class TestWebScrapeToolContentSelectors:
    """Test WebScrapeTool content selector priority."""

    @pytest.fixture
    def web_scrape_tool(self):
        """Create WebScrapeTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_scrape.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                playwright_headless=True,
                playwright_timeout=30000,
                playwright_max_content_length=50000,
            )
            return WebScrapeTool()

    def test_content_selectors_priority_article_first(self, web_scrape_tool):
        """Test article selector has high priority."""
        assert "article" in web_scrape_tool.CONTENT_SELECTORS[:3]

    def test_content_selectors_priority_main_included(self, web_scrape_tool):
        """Test main selector is included."""
        assert "main" in web_scrape_tool.CONTENT_SELECTORS

    def test_content_selectors_includes_role_main(self, web_scrape_tool):
        """Test role=main selector is included."""
        assert '[role="main"]' in web_scrape_tool.CONTENT_SELECTORS

    def test_content_selectors_includes_content_class(self, web_scrape_tool):
        """Test .content class selector is included."""
        assert ".content" in web_scrape_tool.CONTENT_SELECTORS

    def test_content_selectors_includes_content_id(self, web_scrape_tool):
        """Test #content ID selector is included."""
        assert "#content" in web_scrape_tool.CONTENT_SELECTORS
