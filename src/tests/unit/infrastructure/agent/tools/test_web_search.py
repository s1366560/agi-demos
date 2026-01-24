"""Unit tests for WebSearchTool."""

import json
from unittest.mock import Mock, patch

import pytest

from src.infrastructure.agent.tools.web_search import (
    SearchResult,
    WebSearchResponse,
    WebSearchTool,
)


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
    """Test WebSearchTool initialization."""

    def test_init_sets_correct_name(self, mock_redis_client):
        """Test tool initializes with correct name."""
        with patch("src.infrastructure.agent.tools.web_search.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                tavily_api_key="test_key",
                tavily_max_results=10,
                tavily_search_depth="basic",
                web_search_cache_ttl=3600,
                tavily_include_domains=None,
                tavily_exclude_domains=None,
            )
            tool = WebSearchTool(mock_redis_client)
            assert tool.name == "web_search"

    def test_init_sets_description(self, mock_redis_client):
        """Test tool initializes with meaningful description."""
        with patch("src.infrastructure.agent.tools.web_search.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                tavily_api_key="test_key",
                tavily_max_results=10,
                tavily_search_depth="basic",
                web_search_cache_ttl=3600,
                tavily_include_domains=None,
                tavily_exclude_domains=None,
            )
            tool = WebSearchTool(mock_redis_client)
            assert "search" in tool.description.lower()
            assert "web" in tool.description.lower()


class TestWebSearchToolValidation:
    """Test WebSearchTool argument validation."""

    @pytest.fixture
    def web_search_tool(self, mock_redis_client):
        """Create WebSearchTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_search.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                tavily_api_key="test_key",
                tavily_max_results=10,
                tavily_search_depth="basic",
                web_search_cache_ttl=3600,
                tavily_include_domains=None,
                tavily_exclude_domains=None,
            )
            return WebSearchTool(mock_redis_client)

    def test_validate_args_with_valid_query(self, web_search_tool):
        """Test validation passes with valid query."""
        assert web_search_tool.validate_args(query="AI news 2024") is True

    def test_validate_args_with_empty_query(self, web_search_tool):
        """Test validation fails with empty query."""
        assert web_search_tool.validate_args(query="") is False

    def test_validate_args_with_whitespace_only(self, web_search_tool):
        """Test validation fails with whitespace-only query."""
        assert web_search_tool.validate_args(query="   ") is False

    def test_validate_args_missing_query(self, web_search_tool):
        """Test validation fails when query is missing."""
        assert web_search_tool.validate_args() is False

    def test_validate_args_max_results_valid_range(self, web_search_tool):
        """Test validation passes with valid max_results."""
        assert web_search_tool.validate_args(query="test", max_results=1) is True
        assert web_search_tool.validate_args(query="test", max_results=50) is True

    def test_validate_args_max_results_invalid_range(self, web_search_tool):
        """Test validation fails with invalid max_results."""
        assert web_search_tool.validate_args(query="test", max_results=0) is False
        assert web_search_tool.validate_args(query="test", max_results=51) is False
        assert web_search_tool.validate_args(query="test", max_results=-1) is False

    def test_validate_args_search_depth_valid(self, web_search_tool):
        """Test validation passes with valid search_depth."""
        assert web_search_tool.validate_args(query="test", search_depth="basic") is True
        assert web_search_tool.validate_args(query="test", search_depth="advanced") is True

    def test_validate_args_search_depth_invalid(self, web_search_tool):
        """Test validation fails with invalid search_depth."""
        assert web_search_tool.validate_args(query="test", search_depth="deep") is False
        assert web_search_tool.validate_args(query="test", search_depth="invalid") is False


class TestWebSearchToolCaching:
    """Test WebSearchTool caching functionality."""

    @pytest.fixture
    def web_search_tool(self, mock_redis_client):
        """Create WebSearchTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_search.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                tavily_api_key="test_key",
                tavily_max_results=10,
                tavily_search_depth="basic",
                web_search_cache_ttl=3600,
                tavily_include_domains=None,
                tavily_exclude_domains=None,
            )
            return WebSearchTool(mock_redis_client)

    def test_generate_cache_key_consistency(self, web_search_tool):
        """Test cache key is consistent for same query."""
        key1 = web_search_tool._generate_cache_key("AI news", 10)
        key2 = web_search_tool._generate_cache_key("AI news", 10)
        assert key1 == key2

    def test_generate_cache_key_different_for_different_queries(self, web_search_tool):
        """Test cache key differs for different queries."""
        key1 = web_search_tool._generate_cache_key("AI news", 10)
        key2 = web_search_tool._generate_cache_key("ML trends", 10)
        assert key1 != key2

    def test_generate_cache_key_different_for_different_limits(self, web_search_tool):
        """Test cache key differs for different max_results."""
        key1 = web_search_tool._generate_cache_key("AI news", 5)
        key2 = web_search_tool._generate_cache_key("AI news", 10)
        assert key1 != key2

    def test_generate_cache_key_normalizes_query(self, web_search_tool):
        """Test cache key normalizes query (lowercase, strip)."""
        key1 = web_search_tool._generate_cache_key("AI News", 10)
        key2 = web_search_tool._generate_cache_key("ai news", 10)
        key3 = web_search_tool._generate_cache_key("  AI news  ", 10)
        assert key1 == key2 == key3

    @pytest.mark.asyncio
    async def test_get_cached_results_hit(self, web_search_tool, mock_redis_client):
        """Test cache hit returns cached response."""
        cached_data = {
            "query": "AI news",
            "results": [],
            "total_results": 0,
            "timestamp": "2024-01-15T10:00:00",
        }
        mock_redis_client.get.return_value = json.dumps(cached_data)

        result = await web_search_tool._get_cached_results("test_key")

        assert result is not None
        assert result.cached is True

    @pytest.mark.asyncio
    async def test_get_cached_results_miss(self, web_search_tool, mock_redis_client):
        """Test cache miss returns None."""
        mock_redis_client.get.return_value = None

        result = await web_search_tool._get_cached_results("test_key")

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_results_calls_setex(self, web_search_tool, mock_redis_client):
        """Test caching calls Redis setex with TTL."""
        response = WebSearchResponse(
            query="test",
            results=[],
            total_results=0,
            cached=False,
            timestamp="2024-01-15T10:00:00",
        )

        await web_search_tool._cache_results("test_key", response)

        mock_redis_client.setex.assert_called_once()
        call_args = mock_redis_client.setex.call_args
        assert call_args[0][0] == "test_key"
        assert call_args[0][1] == 3600  # TTL


class TestWebSearchToolExecute:
    """Test WebSearchTool execute method."""

    @pytest.fixture
    def web_search_tool(self, mock_redis_client):
        """Create WebSearchTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_search.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                tavily_api_key="test_key",
                tavily_max_results=10,
                tavily_search_depth="basic",
                web_search_cache_ttl=3600,
                tavily_include_domains=None,
                tavily_exclude_domains=None,
            )
            return WebSearchTool(mock_redis_client)

    @pytest.mark.asyncio
    async def test_execute_missing_query_returns_error(self, web_search_tool):
        """Test execute returns error when query is missing."""
        result = await web_search_tool.execute()
        assert "Error" in result
        assert "query parameter is required" in result

    @pytest.mark.asyncio
    async def test_execute_uses_cache(self, web_search_tool, mock_redis_client):
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

        result = await web_search_tool.execute(query="AI news")

        assert "Found 1 result(s)" in result
        assert "(cached)" in result
        assert "Cached Result" in result

    @pytest.mark.asyncio
    async def test_execute_returns_formatted_results(self, web_search_tool, mock_redis_client):
        """Test execute returns formatted search results."""
        mock_redis_client.get.return_value = None

        with patch.object(web_search_tool, "_call_tavily_api") as mock_api:
            mock_api.return_value = {
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

            result = await web_search_tool.execute(query="AI news")

        assert "Found 1 result(s)" in result
        assert "AI Article" in result
        assert "https://example.com/ai" in result


class TestWebSearchToolErrorHandling:
    """Test WebSearchTool error handling."""

    @pytest.fixture
    def web_search_tool(self, mock_redis_client):
        """Create WebSearchTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_search.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                tavily_api_key=None,  # No API key
                tavily_max_results=10,
                tavily_search_depth="basic",
                web_search_cache_ttl=3600,
                tavily_include_domains=None,
                tavily_exclude_domains=None,
            )
            return WebSearchTool(mock_redis_client)

    @pytest.mark.asyncio
    async def test_execute_handles_missing_api_key(self, web_search_tool, mock_redis_client):
        """Test execute handles missing Tavily API key."""
        mock_redis_client.get.return_value = None

        result = await web_search_tool.execute(query="test")

        assert "Error" in result
        assert "Configuration error" in result or "TAVILY_API_KEY" in result


class TestWebSearchToolResultParsing:
    """Test WebSearchTool result parsing."""

    @pytest.fixture
    def web_search_tool(self, mock_redis_client):
        """Create WebSearchTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_search.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                tavily_api_key="test_key",
                tavily_max_results=10,
                tavily_search_depth="basic",
                web_search_cache_ttl=3600,
                tavily_include_domains=None,
                tavily_exclude_domains=None,
            )
            return WebSearchTool(mock_redis_client)

    def test_parse_tavily_response_extracts_results(self, web_search_tool):
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

        results = web_search_tool._parse_tavily_response(tavily_response)

        assert len(results) == 2
        assert results[0].title == "Test Article"
        assert results[0].score == 0.85
        assert results[1].published_date is None

    def test_parse_tavily_response_handles_empty(self, web_search_tool):
        """Test parsing empty Tavily response."""
        tavily_response = {"results": []}

        results = web_search_tool._parse_tavily_response(tavily_response)

        assert len(results) == 0

    def test_parse_tavily_response_truncates_long_content(self, web_search_tool):
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

        results = web_search_tool._parse_tavily_response(tavily_response)

        # Content should be limited to 1000 chars
        assert len(results[0].content) <= 1000


class TestWebSearchToolResultFormatting:
    """Test WebSearchTool result formatting."""

    @pytest.fixture
    def web_search_tool(self, mock_redis_client):
        """Create WebSearchTool with mocked settings."""
        with patch("src.infrastructure.agent.tools.web_search.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                tavily_api_key="test_key",
                tavily_max_results=10,
                tavily_search_depth="basic",
                web_search_cache_ttl=3600,
                tavily_include_domains=None,
                tavily_exclude_domains=None,
            )
            return WebSearchTool(mock_redis_client)

    def test_format_results_includes_all_fields(self, web_search_tool):
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

        formatted = web_search_tool._format_results(response)

        assert "Found 1 result(s)" in formatted
        assert "test query" in formatted
        assert "Test Article" in formatted
        assert "https://example.com/test" in formatted
        assert "0.85" in formatted
        assert "2024-01-15" in formatted

    def test_format_results_shows_cached_indicator(self, web_search_tool):
        """Test formatting shows cached indicator."""
        response = WebSearchResponse(
            query="test",
            results=[],
            total_results=0,
            cached=True,
            timestamp="2024-01-15T10:00:00",
        )

        formatted = web_search_tool._format_results(response)

        assert "(cached)" in formatted

    def test_format_results_truncates_content_preview(self, web_search_tool):
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

        formatted = web_search_tool._format_results(response)

        # Content preview should be truncated to 200 chars with ...
        assert "..." in formatted
