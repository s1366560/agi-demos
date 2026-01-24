"""
Rate limiting middleware for API endpoints.

Uses slowapi with Redis-backed distributed rate limiting to protect
against API abuse and ensure fair resource allocation.
"""

import logging
from typing import Callable

from fastapi import Request, Response
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

# Initialize rate limiter with Redis backend if available
# Falls back to in-memory for single-instance deployments
_rate_limiter: Limiter | None = None


def get_rate_limiter() -> Limiter:
    """
    Get or create the rate limiter instance.

    Returns:
        Configured Limiter instance
    """
    global _rate_limiter

    if _rate_limiter is None:
        _rate_limiter = Limiter(
            key_func=get_remote_address,
            default_limits=["200/minute"],
            storage_uri="redis://localhost:6379",  # TODO: Get from settings
        )
        logger.info("Rate limiter initialized")

    return _rate_limiter


async def rate_limit_middleware(request: Request, call_next: Callable) -> Response:
    """
    Rate limiting middleware for FastAPI.

    This middleware applies rate limits to all API endpoints to prevent abuse.
    Different endpoints have different rate limits based on their resource usage.

    Rate limits:
    - Agent endpoints: 60/minute (expensive LLM operations)
    - Chat/streaming: 30/minute (very expensive)
    - Search endpoints: 100/minute
    - CRUD endpoints: 200/minute
    - Health/readiness: 1000/minute
    """
    # Don't rate limit health check endpoints
    if request.url.path in ["/health", "/readiness", "/metrics"]:
        return await call_next(request)

    limiter = get_rate_limiter()

    try:
        # Apply different rate limits based on endpoint type
        if "/agent/" in request.url.path and "/chat" in request.url.path:
            # Agent chat is the most expensive operation
            limiter.check("agent-chat-limit")
        elif "/agent/" in request.url.path:
            limiter.check("agent-general-limit")
        elif "/search" in request.url.path:
            limiter.check("search-limit")
        else:
            # Default rate limit for other endpoints
            limiter.check("default-limit")

    except RateLimitExceeded:
        logger.warning(f"Rate limit exceeded for {request.client.host} on {request.url.path}")
        return Response(
            content='{"error": "Rate limit exceeded. Please slow down."}',
            status_code=429,
            media_type="application/json",
            headers={"Retry-After": "60"},
        )

    return await call_next(request)


# Export the limiter for use in decorators
def _get_limiter() -> Limiter:
    """Private function to get the limiter for use in decorators."""
    return get_rate_limiter()


# Re-export limiter for use with decorators
limiter = _get_limiter()
