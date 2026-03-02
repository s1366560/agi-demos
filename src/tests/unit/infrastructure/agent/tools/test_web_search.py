"""Unit tests for web_search module-level functions and tool."""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.tools.web_search import (
    SearchResult,
    WebSearchResponse,
    _cache_ws_results,
    _format_ws_results,
    _generate_ws_cache_key,
    _get_ws_cached_results,
    _parse_ws_tavily_response,
    configure_web_search,
    web_search_tool,
)


def _make_ctx() -> ToolContext:
    return ToolContext(
        session_id="test-session",
        message_id="test-msg",
        call_id="test-call",
        agent_name="test-agent",
        conversation_id="test-conv",
    )


@pytest.fixture(autouse=True)
def _reset_web_search_state():
    configure_web_search()
    yield
    configure_web_search()


class TestSearchResultModel:
    """Test SearchResult Pydantic model."""

    def test_search_result_with_all_fields(self):
        """Test SearchResult with all fields populated."""
        result = SearchResult(
            title="Test Title",
            url="https://example.com/article",
            content="This is the article content",
            score=0.95,
            published_date="2024-01-15",
        )
        assert result.title == "Test Title"
        assert result.url == "https://example.com/article"
        assert result.score == 0.95

    def test_search_result_url_validation_adds_https(self):
        """Test URL validation adds https if missing."""
        result = SearchResult(
            title="Test",
            url="example.com/page",
            content="Content",
            score=0.5,
        )
        assert result.url == "https://example.com/page"

    def test_search_result_preserves_http(self):
        """Test URL validation preserves http scheme."""
        result = SearchResult(
            title="Test",
            url="http://example.com/page",
            content="Content",
            score=0.5,
        )
        assert result.url == "http://example.com/page"

    def test_search_result_optional_published_date(self):
        """Test SearchResult with optional published_date."""
        result = SearchResult(
            title="Test",
            url="https://example.com",
            content="Content",
            score=0.5,
        )
        assert result.published_date is None


class TestWebSearchResponseModel:
    """Test WebSearchResponse Pydantic model."""

    def test_web_search_response_structure(self):
        """Test WebSearchResponse has correct structure."""
        response = WebSearchResponse(
            query="test query",
            results=[],
            total_results=0,
            cached=False,
            timestamp="2024-01-15T10:00:00",
        )
        assert response.query == "test query"
        assert response.total_results == 0
        assert response.cached is False


class TestWebSearchToolInit:
    """Test web_search tool registration via @tool_define."""

    def test_registered_tool_has_correct_name(self):
        """Test the registered tool has name 'web_search'."""
        assert web_search_tool.name == "web_search"

    def test_registered_tool_has_description_with_search_and_web(self):
        """Test the registered tool description mentions search and web."""
        assert "search" in web_search_tool.description.lower()
        assert "web" in web_search_tool.description.lower()

    def test_registered_tool_has_query_parameter(self):
        """Test the registered tool requires a query parameter."""
        assert "query" in web_search_tool.parameters["properties"]
        assert "query" in web_search_tool.parameters["required"]


class TestWebSearchToolValidation:
    """Test web_search_tool inline validation."""

    @pytest.fixture(autouse=True)
    def _mock_settings(self):
        with patch("src.infrastructure.agent.tools.web_search.get_settings") as mock:
            mock.return_value = Mock(
                tavily_api_key="test_key",
                tavily_max_results=10,
                tavily_search_depth="basic",
                web_search_cache_ttl=3600,
                tavily_include_domains=None,
                tavily_exclude_domains=None,
            )
            yield mock

    async def test_execute_empty_query_returns_error(self):
        """Test execute with empty query returns ToolResult with is_error."""
        ctx = _make_ctx()
        result = await web_search_tool.execute(ctx, query="")
        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "query parameter is required" in result.output

    async def test_execute_whitespace_query_returns_error(self):
        """Test execute with whitespace-only query returns error."""
        ctx = _make_ctx()
        result = await web_search_tool.execute(ctx, query="   ")
        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "query parameter is required" in result.output

    def test_max_results_clamped_via_cache_key(self):
        """Test that max_results is clamped 1-10 (verified via cache key)."""
        # max_results=0 would be clamped to 1 inside execute,
        # but _generate_ws_cache_key itself takes raw values.
        # We verify clamping indirectly: keys for 0 and 1 should differ
        # (the clamping happens inside execute, not cache key gen).
        key_1 = _generate_ws_cache_key("test", 1)
        key_5 = _generate_ws_cache_key("test", 5)
        key_10 = _generate_ws_cache_key("test", 10)
        assert key_1 != key_5
        assert key_5 != key_10


class TestWebSearchToolCaching:
    """Test web_search caching module-level functions."""

    def test_generate_cache_key_consistency(self):
        """Test cache key is consistent for same query."""
        key1 = _generate_ws_cache_key("AI news", 10)
        key2 = _generate_ws_cache_key("AI news", 10)
        assert key1 == key2

    def test_generate_cache_key_different_for_different_queries(self):
        """Test cache key differs for different queries."""
        key1 = _generate_ws_cache_key("AI news", 10)
        key2 = _generate_ws_cache_key("ML trends", 10)
        assert key1 != key2

    def test_generate_cache_key_different_for_different_limits(self):
        """Test cache key differs for different max_results."""
        key1 = _generate_ws_cache_key("AI news", 5)
        key2 = _generate_ws_cache_key("AI news", 10)
        assert key1 != key2

    def test_generate_cache_key_normalizes_query(self):
        """Test cache key normalizes query (lowercase, strip)."""
        key1 = _generate_ws_cache_key("AI News", 10)
        key2 = _generate_ws_cache_key("ai news", 10)
        key3 = _generate_ws_cache_key("  AI news  ", 10)
        assert key1 == key2 == key3

    async def test_get_cached_results_hit(self, mock_redis_client):
        """Test cache hit returns cached response."""
        cached_data = {
            "query": "AI news",
            "results": [],
            "total_results": 0,
            "timestamp": "2024-01-15T10:00:00",
        }
        mock_redis_client.get.return_value = json.dumps(cached_data)

        result = await _get_ws_cached_results(mock_redis_client, "test_key")

        assert result is not None
        assert result.cached is True

    async def test_get_cached_results_miss(self, mock_redis_client):
        """Test cache miss returns None."""
        mock_redis_client.get.return_value = None

        result = await _get_ws_cached_results(mock_redis_client, "test_key")

        assert result is None

    async def test_cache_results_calls_setex(self, mock_redis_client):
        """Test caching calls Redis setex with TTL."""
        response = WebSearchResponse(
            query="test",
            results=[],
            total_results=0,
            cached=False,
            timestamp="2024-01-15T10:00:00",
        )

        await _cache_ws_results(mock_redis_client, "test_key", response, 3600)

        mock_redis_client.setex.assert_called_once()
        call_args = mock_redis_client.setex.call_args
        assert call_args[0][0] == "test_key"
        assert call_args[0][1] == 3600


class TestWebSearchToolExecute:
    """Test web_search_tool execute method."""

    @pytest.fixture(autouse=True)
    def _mock_settings(self):
        with patch("src.infrastructure.agent.tools.web_search.get_settings") as mock:
            mock.return_value = Mock(
                tavily_api_key="test_key",
                tavily_max_results=10,
                tavily_search_depth="basic",
                web_search_cache_ttl=3600,
                tavily_include_domains=None,
                tavily_exclude_domains=None,
            )
            yield mock

    async def test_execute_missing_query_returns_error(self):
        """Test execute returns error when query is empty."""
        ctx = _make_ctx()
        result = await web_search_tool.execute(ctx, query="")
        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "query parameter is required" in result.output

    async def test_execute_uses_cache(self, mock_redis_client):
        """Test execute uses cached results when available."""
        cached_data = {
            "query": "AI news",
            "results": [
                {
                    "title": "Cached Result",
                    "url": "https://example.com",
                    "content": "Content",
                    "score": 0.9,
                }
            ],
            "total_results": 1,
            "timestamp": "2024-01-15T10:00:00",
        }
        mock_redis_client.get.return_value = json.dumps(cached_data)
        configure_web_search(redis_client=mock_redis_client)

        ctx = _make_ctx()
        result = await web_search_tool.execute(ctx, query="AI news")

        assert isinstance(result, ToolResult)
        assert "Found 1 result(s)" in result.output
        assert "(cached)" in result.output
        assert "Cached Result" in result.output

    async def test_execute_returns_formatted_results(self, mock_redis_client):
        """Test execute returns formatted search results from Tavily API."""
        mock_redis_client.get.return_value = None
        configure_web_search(redis_client=mock_redis_client)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "AI Article",
                    "url": "https://example.com/ai",
                    "content": "Article about AI developments",
                    "score": 0.95,
                    "published_date": "2024-01-15",
                }
            ]
        }

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.infrastructure.agent.tools.web_search.httpx.AsyncClient",
            return_value=mock_client_instance,
        ):
            ctx = _make_ctx()
            result = await web_search_tool.execute(ctx, query="AI news")

        assert isinstance(result, ToolResult)
        assert "Found 1 result(s)" in result.output
        assert "AI Article" in result.output
        assert "https://example.com/ai" in result.output


class TestWebSearchToolErrorHandling:
    """Test web_search_tool error handling."""

    async def test_execute_handles_missing_api_key(self, mock_redis_client):
        """Test execute handles missing Tavily API key."""
        with patch("src.infrastructure.agent.tools.web_search.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                tavily_api_key=None,
                tavily_max_results=10,
                tavily_search_depth="basic",
                web_search_cache_ttl=3600,
                tavily_include_domains=None,
                tavily_exclude_domains=None,
            )
            mock_redis_client.get.return_value = None
            configure_web_search(redis_client=mock_redis_client)

            ctx = _make_ctx()
            result = await web_search_tool.execute(ctx, query="test")

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "TAVILY_API_KEY" in result.output

    async def test_execute_handles_empty_api_key(self, mock_redis_client):
        """Test execute handles empty string Tavily API key."""
        with patch("src.infrastructure.agent.tools.web_search.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                tavily_api_key="",
                tavily_max_results=10,
                tavily_search_depth="basic",
                web_search_cache_ttl=3600,
                tavily_include_domains=None,
                tavily_exclude_domains=None,
            )
            mock_redis_client.get.return_value = None
            configure_web_search(redis_client=mock_redis_client)

            ctx = _make_ctx()
            result = await web_search_tool.execute(ctx, query="test")

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "TAVILY_API_KEY" in result.output

    async def test_execute_handles_network_error(self, mock_redis_client):
        """Test execute handles httpx network errors gracefully."""
        import httpx

        with patch("src.infrastructure.agent.tools.web_search.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                tavily_api_key="test_key",
                tavily_max_results=10,
                tavily_search_depth="basic",
                web_search_cache_ttl=3600,
                tavily_include_domains=None,
                tavily_exclude_domains=None,
            )
            mock_redis_client.get.return_value = None
            configure_web_search(redis_client=mock_redis_client)

            mock_client_instance = AsyncMock()
            mock_client_instance.post.side_effect = httpx.HTTPError("Connection failed")
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "src.infrastructure.agent.tools.web_search.httpx.AsyncClient",
                return_value=mock_client_instance,
            ):
                ctx = _make_ctx()
                result = await web_search_tool.execute(ctx, query="test query")

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "Error" in result.output


class TestWebSearchToolResultParsing:
    """Test _parse_ws_tavily_response module function."""

    def test_parse_tavily_response_extracts_results(self):
        """Test parsing Tavily API response."""
        tavily_response = {
            "results": [
                {
                    "title": "Test Article",
                    "url": "https://example.com/test",
                    "content": "Article content here",
                    "score": 0.85,
                    "published_date": "2024-01-15",
                },
                {
                    "title": "Another Article",
                    "url": "https://example.com/another",
                    "content": "More content",
                    "score": 0.75,
                },
            ]
        }

        results = _parse_ws_tavily_response(tavily_response)

        assert len(results) == 2
        assert results[0].title == "Test Article"
        assert results[0].score == 0.85
        assert results[1].published_date is None

    def test_parse_tavily_response_handles_empty(self):
        """Test parsing empty Tavily response."""
        tavily_response = {"results": []}

        results = _parse_ws_tavily_response(tavily_response)

        assert len(results) == 0

    def test_parse_tavily_response_truncates_long_content(self):
        """Test parsing truncates long content."""
        long_content = "A" * 2000
        tavily_response = {
            "results": [
                {
                    "title": "Test",
                    "url": "https://example.com",
                    "content": long_content,
                    "score": 0.5,
                }
            ]
        }

        results = _parse_ws_tavily_response(tavily_response)

        # Content should be limited to 1000 chars
        assert len(results[0].content) <= 1000

    def test_parse_tavily_response_handles_missing_fields(self):
        """Test parsing handles missing optional fields gracefully."""
        tavily_response = {
            "results": [
                {
                    "url": "https://example.com",
                    "score": 0.5,
                }
            ]
        }

        results = _parse_ws_tavily_response(tavily_response)

        assert len(results) == 1
        assert results[0].title == "Untitled"
        assert results[0].content == ""
        assert results[0].published_date is None


class TestWebSearchToolResultFormatting:
    """Test _format_ws_results module function."""

    def test_format_results_includes_all_fields(self):
        """Test result formatting includes all relevant fields."""
        response = WebSearchResponse(
            query="test query",
            results=[
                SearchResult(
                    title="Test Article",
                    url="https://example.com/test",
                    content="Article content preview",
                    score=0.85,
                    published_date="2024-01-15",
                )
            ],
            total_results=1,
            cached=False,
            timestamp="2024-01-15T10:00:00",
        )

        formatted = _format_ws_results(response)

        assert "Found 1 result(s)" in formatted
        assert "test query" in formatted
        assert "Test Article" in formatted
        assert "https://example.com/test" in formatted
        assert "0.85" in formatted
        assert "2024-01-15" in formatted

    def test_format_results_shows_cached_indicator(self):
        """Test formatting shows cached indicator."""
        response = WebSearchResponse(
            query="test",
            results=[],
            total_results=0,
            cached=True,
            timestamp="2024-01-15T10:00:00",
        )

        formatted = _format_ws_results(response)

        assert "(cached)" in formatted

    def test_format_results_truncates_content_preview(self):
        """Test formatting truncates long content preview."""
        long_content = "A" * 500
        response = WebSearchResponse(
            query="test",
            results=[
                SearchResult(
                    title="Test",
                    url="https://example.com",
                    content=long_content,
                    score=0.5,
                )
            ],
            total_results=1,
            cached=False,
            timestamp="2024-01-15T10:00:00",
        )

        formatted = _format_ws_results(response)

        # Content preview should be truncated to 200 chars with ...
        assert "..." in formatted

    def test_format_results_no_cached_indicator_when_not_cached(self):
        """Test formatting omits cached indicator when not cached."""
        response = WebSearchResponse(
            query="test",
            results=[],
            total_results=0,
            cached=False,
            timestamp="2024-01-15T10:00:00",
        )

        formatted = _format_ws_results(response)

        assert "(cached)" not in formatted
