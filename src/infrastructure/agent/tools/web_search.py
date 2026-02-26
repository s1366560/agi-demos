"""Web search tool for ReAct agent using Tavily API.

This tool allows the agent to search the web for current information,
which is then cached in Redis for performance.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from pydantic import BaseModel, field_validator

from src.configuration.config import get_settings
from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


class SearchResult(BaseModel):
    """A single search result from Tavily."""

    title: str
    url: str
    content: str
    score: float
    published_date: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Ensure URL starts with http/https."""
        if not v.startswith(("http://", "https://")):
            return f"https://{v}"
        return v


class WebSearchResponse(BaseModel):
    """Response from web search tool."""

    query: str
    results: list[SearchResult]
    total_results: int
    cached: bool = False
    timestamp: str


class WebSearchTool(AgentTool):
    """
    Tool for searching the web using Tavily API.

    This tool performs web searches with Redis caching to avoid
    redundant API calls for similar queries within the TTL period.
    """

    # Cache key prefix
    CACHE_PREFIX = "web_search:"

    # Maximum query length for cache key
    MAX_QUERY_LENGTH = 200

    def __init__(self, redis_client: Any) -> None:
        """
        Initialize the web search tool.

        Args:
            redis_client: Redis async client for caching
        """
        super().__init__(
            name="web_search",
            description=(
                "Search the web for current information using a search engine. "
                "Use this tool when you need to find recent news, factual information, "
                "or topics not covered in the knowledge graph. "
                "Input: query (string) - the search query (e.g., 'latest AI developments 2024'). "
                "Optional: max_results (integer, default: 10, max: 50), "
                "search_depth (string: 'basic' or 'advanced', default: 'basic')."
            ),
        )
        self._settings = get_settings()
        self._redis = redis_client
        self._http_client: httpx.AsyncClient | None = None

    def get_parameters_schema(self) -> dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query (e.g., 'latest AI developments 2024')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10, max: 50)",
                    "default": 10,
                },
                "search_depth": {
                    "type": "string",
                    "description": "Search depth: 'basic' or 'advanced' (default: 'basic')",
                    "enum": ["basic", "advanced"],
                    "default": "basic",
                },
            },
            "required": ["query"],
        }

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._http_client

    async def _close_http_client(self) -> None:
        """Close HTTP client if open."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def _generate_cache_key(self, query: str, max_results: int) -> str:
        """
        Generate a cache key for the search query.

        Args:
            query: Search query string
            max_results: Maximum number of results

        Returns:
            Redis cache key
        """
        # Normalize query
        normalized_query = query.strip().lower()[: self.MAX_QUERY_LENGTH]
        # Create hash for consistent key length
        query_hash = hashlib.sha256(normalized_query.encode()).hexdigest()[:16]
        return f"{self.CACHE_PREFIX}{query_hash}:results:{max_results}"

    async def _get_cached_results(self, cache_key: str) -> WebSearchResponse | None:
        """
        Get cached search results from Redis.

        Args:
            cache_key: Redis cache key

        Returns:
            Cached response or None if not found
        """
        try:
            cached = await self._redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                logger.info(f"Cache hit for search query: {cache_key[:40]}...")
                return WebSearchResponse(**data, cached=True)
        except Exception as e:
            logger.warning(f"Failed to get cached results: {e}")
        return None

    async def _cache_results(self, cache_key: str, response: WebSearchResponse) -> None:
        """
        Cache search results in Redis.

        Args:
            cache_key: Redis cache key
            response: Response to cache
        """
        try:
            ttl = self._settings.web_search_cache_ttl
            await self._redis.setex(
                cache_key,
                ttl,
                json.dumps(response.model_dump(), default=str),
            )
            logger.debug(f"Cached search results for {ttl}s: {cache_key[:40]}...")
        except Exception as e:
            logger.warning(f"Failed to cache results: {e}")

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate that query argument is provided."""
        query = kwargs.get("query")
        if not isinstance(query, str) or len(query.strip()) == 0:
            return False

        # Validate max_results if provided
        max_results = kwargs.get("max_results", 10)
        if not isinstance(max_results, int) or max_results < 1 or max_results > 50:
            return False

        # Validate search_depth if provided
        search_depth = kwargs.get("search_depth", "basic")
        return search_depth in ("basic", "advanced")

    async def _call_tavily_api(
        self, query: str, max_results: int, search_depth: str
    ) -> dict[str, Any]:
        """
        Call Tavily Search API.

        Args:
            query: Search query
            max_results: Maximum number of results
            search_depth: Search depth (basic or advanced)

        Returns:
            API response as dictionary

        Raises:
            httpx.HTTPError: If API call fails
            ValueError: If API key is not configured
        """
        api_key = self._settings.tavily_api_key
        if not api_key:
            raise ValueError("TAVILY_API_KEY is not configured")

        url = "https://api.tavily.com/search"

        payload = {
            "api_key": api_key,
            "query": query,
            "max_results": min(max_results, 10),  # Tavily max is 10
            "search_depth": search_depth,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }

        # Optional domain filtering
        if self._settings.tavily_include_domains:
            payload["include_domains"] = self._settings.tavily_include_domains
        if self._settings.tavily_exclude_domains:
            payload["exclude_domains"] = self._settings.tavily_exclude_domains

        client = await self._get_http_client()
        response = await client.post(url, json=payload)
        response.raise_for_status()

        return cast(dict[str, Any], response.json())

    def _parse_tavily_response(self, tavily_data: dict[str, Any]) -> list[SearchResult]:
        """
        Parse Tavily API response into SearchResult objects.

        Args:
            tavily_data: Raw API response

        Returns:
            List of SearchResult objects
        """
        results = []

        for item in tavily_data.get("results", []):
            results.append(
                SearchResult(
                    title=item.get("title", "Untitled"),
                    url=item.get("url", ""),
                    content=item.get("content", "")[:1000],  # Limit content length
                    score=item.get("score", 0.0),
                    published_date=item.get("published_date"),
                )
            )

        return results

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute web search.

        Args:
            **kwargs: Must contain 'query' (search string)
                      Optional: 'max_results', 'search_depth'

        Returns:
            String containing formatted search results
        """
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", self._settings.tavily_max_results)
        search_depth = kwargs.get("search_depth", self._settings.tavily_search_depth)

        if not query:
            return "Error: query parameter is required for web_search"

        try:
            return await self._search_and_cache(query, max_results, search_depth)
        except ValueError as e:
            error_msg = f"Configuration error: {e!s}"
        except httpx.HTTPStatusError as e:
            error_msg = f"Tavily API error ({e.response.status_code}): {e.response.text[:200]}"
        except httpx.HTTPError as e:
            error_msg = f"Network error during search: {e!s}"
        except Exception as e:
            logger.exception(f"Unexpected error in web_search: {e}")
            return "Error: An unexpected error occurred during web search"
        logger.error(error_msg)
        return f"Error: {error_msg}"

    async def _search_and_cache(self, query: str, max_results: int, search_depth: str) -> str:
        """Search via Tavily API with Redis caching.

        Returns:
            Formatted search results string.
        """
        cache_key = self._generate_cache_key(query, max_results)
        cached_response = await self._get_cached_results(cache_key)
        if cached_response:
            return self._format_results(cached_response)

        logger.info(f"Searching Tavily for: {query[:100]}...")
        tavily_response = await self._call_tavily_api(query, max_results, search_depth)
        search_results = self._parse_tavily_response(tavily_response)

        response = WebSearchResponse(
            query=query,
            results=search_results,
            total_results=len(search_results),
            cached=False,
            timestamp=datetime.now(UTC).isoformat(),
        )

        await self._cache_results(cache_key, response)
        return self._format_results(response)

    def _format_results(self, response: WebSearchResponse) -> str:
        """
        Format search results as readable string.

        Args:
            response: Web search response

        Returns:
            Formatted string
        """
        cache_indicator = " (cached)" if response.cached else ""
        lines = [
            f"Found {response.total_results} result(s) for '{response.query}'{cache_indicator}:\n"
        ]

        for i, result in enumerate(response.results, 1):
            lines.append(f"{i}. {result.title}")
            lines.append(f"   URL: {result.url}")
            if result.published_date:
                lines.append(f"   Published: {result.published_date}")
            lines.append(f"   Score: {result.score:.2f}")
            # Truncate content for display
            content_preview = (
                result.content[:200] + "..." if len(result.content) > 200 else result.content
            )
            lines.append(f"   Content: {content_preview}")
            lines.append("")  # Empty line separator

        return "\n".join(lines)


# === New @tool_define based implementation ===


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_ws_redis_client: Any = None


def configure_web_search(redis_client: Any = None) -> None:
    """Configure the web search tool with its dependencies.

    Called at agent startup to inject the Redis client for caching.
    """
    global _ws_redis_client
    _ws_redis_client = redis_client


# ---------------------------------------------------------------------------
# Helper functions (extracted from class methods)
# ---------------------------------------------------------------------------


def _generate_ws_cache_key(query: str, max_results: int) -> str:
    """Generate a Redis cache key for the search query."""
    normalized_query = query.strip().lower()[:200]
    query_hash = hashlib.sha256(
        normalized_query.encode(),
    ).hexdigest()[:16]
    return f"web_search:{query_hash}:results:{max_results}"


async def _get_ws_cached_results(
    redis: Any,
    cache_key: str,
) -> WebSearchResponse | None:
    """Get cached search results from Redis."""
    try:
        cached = await redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            logger.info(
                "Cache hit for search query: %s...",
                cache_key[:40],
            )
            return WebSearchResponse(**data, cached=True)
    except Exception as e:
        logger.warning("Failed to get cached results: %s", e)
    return None


async def _cache_ws_results(
    redis: Any,
    cache_key: str,
    response: WebSearchResponse,
    ttl: int,
) -> None:
    """Cache search results in Redis."""
    try:
        await redis.setex(
            cache_key,
            ttl,
            json.dumps(response.model_dump(), default=str),
        )
        logger.debug(
            "Cached search results for %ds: %s...",
            ttl,
            cache_key[:40],
        )
    except Exception as e:
        logger.warning("Failed to cache results: %s", e)


def _format_ws_results(response: WebSearchResponse) -> str:
    """Format search results as readable string."""
    cache_indicator = " (cached)" if response.cached else ""
    lines: list[str] = [
        f"Found {response.total_results} result(s) for '{response.query}'{cache_indicator}:\n"
    ]

    for i, result in enumerate(response.results, 1):
        lines.append(f"{i}. {result.title}")
        lines.append(f"   URL: {result.url}")
        if result.published_date:
            lines.append(f"   Published: {result.published_date}")
        lines.append(f"   Score: {result.score:.2f}")
        content_preview = (
            result.content[:200] + "..." if len(result.content) > 200 else result.content
        )
        lines.append(f"   Content: {content_preview}")
        lines.append("")  # Empty line separator

    return "\n".join(lines)


def _parse_ws_tavily_response(
    tavily_data: dict[str, Any],
) -> list[SearchResult]:
    """Parse Tavily API response into SearchResult objects."""
    results: list[SearchResult] = []
    for item in tavily_data.get("results", []):
        results.append(
            SearchResult(
                title=item.get("title", "Untitled"),
                url=item.get("url", ""),
                content=item.get("content", "")[:1000],
                score=item.get("score", 0.0),
                published_date=item.get("published_date"),
            )
        )
    return results


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool_define(
    name="web_search",
    description=(
        "Search the web for current information using a search engine. "
        "Use this tool when you need to find recent news, factual "
        "information, or topics not covered in the knowledge graph. "
        "Input: query (string) - the search query "
        "(e.g., 'latest AI developments 2024'). "
        "Optional: max_results (integer, default: 5, max: 10)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": ("The search query (e.g., 'latest AI developments 2024')"),
            },
            "max_results": {
                "type": "integer",
                "description": ("Maximum number of results to return (default: 5, max: 10)"),
                "default": 5,
            },
        },
        "required": ["query"],
    },
    permission="web_search",
    category="web",
    tags=frozenset({"web", "search"}),
)
async def web_search_tool(
    ctx: ToolContext,
    *,
    query: str,
    max_results: int = 5,
) -> ToolResult:
    """Search the web via Tavily API with Redis caching."""
    if not query.strip():
        return ToolResult(
            output="Error: query parameter is required for web_search",
            is_error=True,
        )

    settings = get_settings()
    api_key = settings.tavily_api_key
    if not api_key:
        return ToolResult(
            output="Error: TAVILY_API_KEY is not configured",
            is_error=True,
        )

    max_results = min(max(max_results, 1), 10)
    search_depth = settings.tavily_search_depth

    # Check cache
    redis = _ws_redis_client
    cache_key = _generate_ws_cache_key(query, max_results)
    if redis is not None:
        cached_response = await _get_ws_cached_results(
            redis,
            cache_key,
        )
        if cached_response:
            return ToolResult(
                output=_format_ws_results(cached_response),
                title=f"Web search: {query[:60]}",
                metadata={"query": query, "cached": True},
            )

    # Call Tavily API
    try:
        logger.info("Searching Tavily for: %s...", query[:100])
        payload: dict[str, Any] = {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        if settings.tavily_include_domains:
            payload["include_domains"] = settings.tavily_include_domains
        if settings.tavily_exclude_domains:
            payload["exclude_domains"] = settings.tavily_exclude_domains

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
        ) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json=payload,
            )
            response.raise_for_status()
            tavily_data = cast(
                dict[str, Any],
                response.json(),
            )

        search_results = _parse_ws_tavily_response(tavily_data)
        ws_response = WebSearchResponse(
            query=query,
            results=search_results,
            total_results=len(search_results),
            cached=False,
            timestamp=datetime.now(UTC).isoformat(),
        )

        # Cache results
        if redis is not None:
            await _cache_ws_results(
                redis,
                cache_key,
                ws_response,
                settings.web_search_cache_ttl,
            )

        return ToolResult(
            output=_format_ws_results(ws_response),
            title=f"Web search: {query[:60]}",
            metadata={"query": query, "cached": False},
        )

    except (httpx.HTTPStatusError, httpx.HTTPError) as e:
        if isinstance(e, httpx.HTTPStatusError):
            msg = f"Tavily API error ({e.response.status_code}): {e.response.text[:200]}"
        else:
            msg = f"Network error during search: {e!s}"
        logger.error(msg)
        return ToolResult(output=f"Error: {msg}", is_error=True)
    except Exception as e:
        logger.exception("Unexpected error in web_search: %s", e)
        return ToolResult(
            output="Error: An unexpected error occurred during web search",
            is_error=True,
        )
