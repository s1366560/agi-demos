"""Web search tool for ReAct agent using Tavily API.

This tool allows the agent to search the web for current information,
which is then cached in Redis for performance.
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from pydantic import BaseModel, field_validator

from src.configuration.config import get_settings
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo, tool_define
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


# === New @tool_define based implementation ===


# ---------------------------------------------------------------------------
# Operation-bound runtime
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True, slots=True)
class WebSearchRuntime:
    """Optional cache dependency captured by one tool contribution."""

    redis_client: Any


_web_search_runtime: ContextVar[WebSearchRuntime | None] = ContextVar(
    f"{__name__}.web_search_runtime",
    default=None,
)


def configure_web_search(redis_client: Any = None) -> None:
    """Bind a compatibility runtime in the current context.

    Production composition uses :func:`make_web_search_tool`, which captures
    the cache dependency on the returned ToolInfo.
    """
    _ = _web_search_runtime.set(WebSearchRuntime(redis_client=redis_client))


def _current_web_search_redis() -> Any:
    runtime = _web_search_runtime.get()
    return runtime.redis_client if runtime is not None else None


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
    redis = _current_web_search_redis()
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


@dataclass(frozen=True, kw_only=True, slots=True)
class _BoundWebSearchExecutor:
    template: ToolInfo
    runtime: WebSearchRuntime

    async def __call__(self, ctx: ToolContext, **kwargs: Any) -> Any:
        token = _web_search_runtime.set(self.runtime)
        try:
            return await self.template.execute(ctx, **kwargs)
        finally:
            _web_search_runtime.reset(token)


def make_web_search_tool(redis_client: Any = None) -> ToolInfo:
    """Return a Web Search ToolInfo bound to one generation dependency set."""
    runtime = WebSearchRuntime(redis_client=redis_client)
    return replace(
        web_search_tool,
        execute=_BoundWebSearchExecutor(template=web_search_tool, runtime=runtime),
    )
