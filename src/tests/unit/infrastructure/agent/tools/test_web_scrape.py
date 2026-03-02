"""Unit tests for web_scrape module-level functions and tool.

This test module focuses on security validation since web_scrape
interacts with external websites and must prevent SSRF attacks.
"""


from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.web_scrape import (
    _WS_BLOCKED_DOMAINS,
    _WS_CONTENT_SELECTORS,
    _WS_UNWANTED_SELECTORS,
    _WS_URL_PATTERN,
    _ws_clean_content,
    _ws_format_result,
    _ws_is_blocked_domain,
    _ws_sanitize_url,
    web_scrape_tool,
)


def _make_ctx() -> ToolContext:
    """Create a minimal ToolContext for testing."""
    return ToolContext(
        session_id="test-session",
        message_id="test-msg",
        call_id="test-call",
        agent_name="test-agent",
        conversation_id="test-conv",
    )


class TestWebScrapeToolInit:
    """Test web_scrape tool registration and module-level constants."""

    def test_init_sets_correct_name(self) -> None:
        """Test tool is registered under 'web_scrape'."""
        assert web_scrape_tool.name == "web_scrape"

    def test_init_sets_description(self) -> None:
        """Test tool has a meaningful description."""
        desc = web_scrape_tool.description.lower()
        assert "scrape" in desc or "extract" in desc
        assert "web" in desc or "page" in desc

    def test_blocked_domains_defined(self) -> None:
        """Test _WS_BLOCKED_DOMAINS is properly defined."""
        assert "localhost" in _WS_BLOCKED_DOMAINS
        assert "127.0.0.1" in _WS_BLOCKED_DOMAINS
        assert "0.0.0.0" in _WS_BLOCKED_DOMAINS

    def test_content_selectors_defined(self) -> None:
        """Test _WS_CONTENT_SELECTORS is properly defined."""
        assert "article" in _WS_CONTENT_SELECTORS
        assert "main" in _WS_CONTENT_SELECTORS


class TestWebScrapeToolValidation:
    """Test URL validation via _WS_URL_PATTERN."""

    def test_validate_args_with_valid_url(self) -> None:
        """Test URL pattern matches valid URLs."""
        assert _WS_URL_PATTERN.match("https://example.com") is not None
        assert _WS_URL_PATTERN.match("http://example.com/page") is not None
        m = _WS_URL_PATTERN.match("https://sub.example.com/path?q=1")
        assert m is not None

    def test_validate_args_with_empty_url(self) -> None:
        """Test URL pattern rejects empty string."""
        assert _WS_URL_PATTERN.match("") is None

    def test_validate_args_with_whitespace_only(self) -> None:
        """Test URL pattern rejects whitespace-only string."""
        assert _WS_URL_PATTERN.match("   ") is None

    def test_validate_args_invalid_url_format(self) -> None:
        """Test URL pattern rejects non-URL strings."""
        assert _WS_URL_PATTERN.match("not-a-url") is None
        assert _WS_URL_PATTERN.match("ftp://example.com") is None
        assert _WS_URL_PATTERN.match("javascript:alert(1)") is None


class TestWebScrapeToolSecurityValidation:
    """Test SSRF prevention -- CRITICAL TESTS.

    These tests ensure that internal/local addresses are blocked
    to prevent SSRF (Server-Side Request Forgery) attacks.
    """

    def test_validate_args_blocks_localhost(self) -> None:
        """Test blocked-domain check blocks localhost."""
        assert _ws_is_blocked_domain("http://localhost") is True
        assert _ws_is_blocked_domain("https://localhost") is True

    def test_validate_args_blocks_localhost_with_port(self) -> None:
        """Test blocked-domain check blocks localhost with port."""
        assert _ws_is_blocked_domain("http://localhost:8080") is True
        assert _ws_is_blocked_domain("http://localhost/path") is True

    def test_validate_args_blocks_127_0_0_1(self) -> None:
        """Test blocked-domain check blocks 127.0.0.1."""
        assert _ws_is_blocked_domain("http://127.0.0.1") is True

    def test_validate_args_blocks_127_0_0_1_with_port(self) -> None:
        """Test blocked-domain check blocks 127.0.0.1 with port."""
        assert _ws_is_blocked_domain("http://127.0.0.1:3000") is True
        assert _ws_is_blocked_domain("https://127.0.0.1/admin") is True

    def test_validate_args_blocks_0_0_0_0(self) -> None:
        """Test blocked-domain check blocks 0.0.0.0."""
        assert _ws_is_blocked_domain("http://0.0.0.0") is True

    def test_validate_args_blocks_0_0_0_0_with_port(self) -> None:
        """Test blocked-domain check blocks 0.0.0.0 with port."""
        assert _ws_is_blocked_domain("http://0.0.0.0:8000") is True

    def test_validate_args_blocks_ipv6_localhost(self) -> None:
        """Test blocked-domain check blocks IPv6 localhost (::1)."""
        assert _ws_is_blocked_domain("http://[::1]") is True
        assert _ws_is_blocked_domain("http://[::1]:8080") is True

    def test_validate_args_blocks_private_ip_192_168(self) -> None:
        """Test blocked-domain check blocks 192.168.x.x range."""
        assert _ws_is_blocked_domain("http://192.168.1.1") is True
        assert _ws_is_blocked_domain("http://192.168.0.1:8080") is True
        url = "https://192.168.100.50/api"
        assert _ws_is_blocked_domain(url) is True

    def test_validate_args_blocks_private_ip_10_x(self) -> None:
        """Test blocked-domain check blocks 10.x.x.x range."""
        assert _ws_is_blocked_domain("http://10.0.0.1") is True
        assert _ws_is_blocked_domain("http://10.10.10.10:3000") is True
        assert _ws_is_blocked_domain("https://10.255.255.255") is True

    def test_validate_args_allows_public_urls(self) -> None:
        """Test blocked-domain check allows public URLs."""
        assert _ws_is_blocked_domain("https://example.com") is False
        assert _ws_is_blocked_domain("https://www.google.com") is False
        url = "https://github.com/user/repo"
        assert _ws_is_blocked_domain(url) is False
        url2 = "http://news.ycombinator.com"
        assert _ws_is_blocked_domain(url2) is False


class TestWebScrapeToolUrlProcessing:
    """Test URL pattern matching and sanitization."""

    def test_is_valid_url_with_http(self) -> None:
        """Test URL pattern matches http scheme."""
        assert _WS_URL_PATTERN.match("http://example.com") is not None

    def test_is_valid_url_with_https(self) -> None:
        """Test URL pattern matches https scheme."""
        assert _WS_URL_PATTERN.match("https://example.com") is not None

    def test_is_valid_url_without_scheme(self) -> None:
        """Test URL pattern rejects URL without scheme."""
        assert _WS_URL_PATTERN.match("example.com") is None

    def test_is_valid_url_with_path(self) -> None:
        """Test URL pattern matches URL with path."""
        m = _WS_URL_PATTERN.match("https://example.com/path/to/page")
        assert m is not None

    def test_is_valid_url_with_query(self) -> None:
        """Test URL pattern matches URL with query string."""
        m = _WS_URL_PATTERN.match("https://example.com?q=test&page=1")
        assert m is not None

    def test_is_valid_url_with_port(self) -> None:
        """Test URL pattern matches URL with port."""
        m = _WS_URL_PATTERN.match("https://example.com:8443")
        assert m is not None

    def test_sanitize_url_adds_https(self) -> None:
        """Test _ws_sanitize_url adds https if missing."""
        assert _ws_sanitize_url("example.com") == "https://example.com"

    def test_sanitize_url_preserves_http(self) -> None:
        """Test _ws_sanitize_url preserves http scheme."""
        result = _ws_sanitize_url("http://example.com")
        assert result == "http://example.com"

    def test_sanitize_url_preserves_https(self) -> None:
        """Test _ws_sanitize_url preserves https scheme."""
        result = _ws_sanitize_url("https://example.com")
        assert result == "https://example.com"


class TestWebScrapeToolContentCleaning:
    """Test _ws_clean_content function."""

    def test_clean_content_removes_excessive_whitespace(self) -> None:
        """Test content cleaning removes excessive whitespace."""
        content = "Hello    world\n\n\nTest"
        cleaned = _ws_clean_content(content)
        assert "    " not in cleaned

    def test_clean_content_removes_boilerplate_cookie_policy(self) -> None:
        """Test content cleaning removes cookie policy text."""
        content = "Article content here. Cookie policy statement. More content."
        cleaned = _ws_clean_content(content)
        assert "cookie policy" not in cleaned.lower()

    def test_clean_content_removes_boilerplate_privacy_policy(self) -> None:
        """Test content cleaning removes privacy policy text."""
        content = "Main content. Privacy policy applies. Article continues."
        cleaned = _ws_clean_content(content)
        assert "privacy policy" not in cleaned.lower()

    def test_clean_content_removes_subscribe_prompts(self) -> None:
        """Test content cleaning removes subscribe prompts."""
        content = "Article text. Subscribe to our newsletter. More article text."
        cleaned = _ws_clean_content(content)
        assert "subscribe to our" not in cleaned.lower()

    def test_clean_content_keeps_meaningful_lines(self) -> None:
        """Test content cleaning keeps meaningful long lines."""
        content = "This is a meaningful long line with good content"
        cleaned = _ws_clean_content(content)
        assert "meaningful" in cleaned


class TestWebScrapeToolResultFormatting:
    """Test _ws_format_result function."""

    def test_format_result_includes_title(self) -> None:
        """Test result formatting includes page title."""
        result = _ws_format_result(
            title="Test Page Title",
            url="https://example.com",
            description="Page description",
            content="Page content here",
        )
        assert "Title: Test Page Title" in result

    def test_format_result_includes_url(self) -> None:
        """Test result formatting includes URL."""
        result = _ws_format_result(
            title="Test",
            url="https://example.com/page",
            description="",
            content="Content",
        )
        assert "URL: https://example.com/page" in result

    def test_format_result_includes_description(self) -> None:
        """Test result formatting includes description."""
        result = _ws_format_result(
            title="Test",
            url="https://example.com",
            description="This is the meta description",
            content="Content",
        )
        assert "Description:" in result
        assert "meta description" in result

    def test_format_result_truncates_long_description(self) -> None:
        """Test result formatting truncates long descriptions."""
        long_desc = "A" * 500
        result = _ws_format_result(
            title="Test",
            url="https://example.com",
            description=long_desc,
            content="Content",
        )
        assert "..." in result

    def test_format_result_includes_content_section(self) -> None:
        """Test result formatting includes Content section."""
        result = _ws_format_result(
            title="Test",
            url="https://example.com",
            description="",
            content="Main page content goes here",
        )
        assert "Content:" in result
        assert "Main page content" in result

    def test_format_result_omits_empty_description(self) -> None:
        """Test result formatting omits empty description."""
        result = _ws_format_result(
            title="Test",
            url="https://example.com",
            description="",
            content="Content",
        )
        lines = result.split("\n")
        desc_lines = [line for line in lines if line.startswith("Description:")]
        assert len(desc_lines) == 0


class TestWebScrapeToolExecute:
    """Test web_scrape_tool execute function."""

    async def test_execute_missing_url_returns_error(self) -> None:
        """Test execute returns error when URL is empty."""
        ctx = _make_ctx()
        result = await web_scrape_tool.execute(ctx, url="")
        assert result.is_error
        assert "url parameter is required" in result.output

    async def test_execute_blocked_url_returns_error(self) -> None:
        """Test execute returns error for blocked URLs."""
        ctx = _make_ctx()
        result = await web_scrape_tool.execute(ctx, url="http://localhost")
        assert result.is_error
        assert "blocked" in result.output.lower()


class TestWebScrapeToolUnwantedElements:
    """Test _WS_UNWANTED_SELECTORS constant."""

    def test_unwanted_selectors_includes_nav(self) -> None:
        """Test _WS_UNWANTED_SELECTORS includes navigation."""
        assert "nav" in _WS_UNWANTED_SELECTORS

    def test_unwanted_selectors_includes_header(self) -> None:
        """Test _WS_UNWANTED_SELECTORS includes header."""
        assert "header" in _WS_UNWANTED_SELECTORS

    def test_unwanted_selectors_includes_footer(self) -> None:
        """Test _WS_UNWANTED_SELECTORS includes footer."""
        assert "footer" in _WS_UNWANTED_SELECTORS

    def test_unwanted_selectors_includes_sidebar(self) -> None:
        """Test _WS_UNWANTED_SELECTORS includes sidebar."""
        assert ".sidebar" in _WS_UNWANTED_SELECTORS

    def test_unwanted_selectors_includes_ads(self) -> None:
        """Test _WS_UNWANTED_SELECTORS includes ads."""
        assert ".ads" in _WS_UNWANTED_SELECTORS or ".advertisement" in _WS_UNWANTED_SELECTORS

    def test_unwanted_selectors_includes_scripts(self) -> None:
        """Test _WS_UNWANTED_SELECTORS includes script tags."""
        assert "script" in _WS_UNWANTED_SELECTORS

    def test_unwanted_selectors_includes_styles(self) -> None:
        """Test _WS_UNWANTED_SELECTORS includes style tags."""
        assert "style" in _WS_UNWANTED_SELECTORS


class TestWebScrapeToolContentSelectors:
    """Test _WS_CONTENT_SELECTORS constant priority."""

    def test_content_selectors_priority_article_first(self) -> None:
        """Test article selector has high priority."""
        assert "article" in _WS_CONTENT_SELECTORS[:3]

    def test_content_selectors_priority_main_included(self) -> None:
        """Test main selector is included."""
        assert "main" in _WS_CONTENT_SELECTORS

    def test_content_selectors_includes_role_main(self) -> None:
        """Test role=main selector is included."""
        assert '[role="main"]' in _WS_CONTENT_SELECTORS

    def test_content_selectors_includes_content_class(self) -> None:
        """Test .content class selector is included."""
        assert ".content" in _WS_CONTENT_SELECTORS

    def test_content_selectors_includes_content_id(self) -> None:
        """Test #content ID selector is included."""
        assert "#content" in _WS_CONTENT_SELECTORS
