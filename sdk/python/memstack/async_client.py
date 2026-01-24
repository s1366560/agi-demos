"""
Asynchronous client for MemStack API.
"""

import asyncio
from typing import Dict, List, Optional
from urllib.parse import urljoin

import httpx

from .exceptions import APIError, AuthenticationError, NetworkError, RateLimitError
from .models import (
    APIKey,
    APIKeyCreate,
    EpisodeCreate,
    EpisodeResponse,
    Memo,
    MemoCreate,
    MemoryQuery,
    MemoryResponse,
    MemoUpdate,
)


class MemStackAsyncClient:
    """
    Asynchronous client for MemStack API.

    Example:
        >>> async with MemStackAsyncClient(api_key="ms_sk_...") as client:
        ...     episode = await client.create_episode(
        ...         name="User Preference",
        ...         content="User loves hiking",
        ...     )
        ...     results = await client.search_memory("outdoor activities")
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8000",
        timeout: float = 60.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize MemStack async client.

        Args:
            api_key: MemStack API key (starts with 'ms_sk_')
            base_url: Base URL of the MemStack API
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_delay: Initial delay between retries (exponential backoff)
        """
        if not api_key or not api_key.startswith("ms_sk_"):
            raise AuthenticationError("Invalid API key format. API keys should start with 'ms_sk_'")

        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers=self._get_headers(),
        )

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "memstack-python/0.1.0",
        }

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """
        Make HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            json_data: JSON request body
            params: URL query parameters

        Returns:
            Response JSON data

        Raises:
            AuthenticationError: If authentication fails
            RateLimitError: If rate limit is exceeded
            APIError: If API returns an error
            NetworkError: If network request fails
        """
        url = urljoin(self.base_url, endpoint)
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                response = await self._client.request(
                    method=method,
                    url=url,
                    json=json_data,
                    params=params,
                )

                # Handle specific status codes
                if response.status_code == 401:
                    raise AuthenticationError(f"Authentication failed: {response.text}")
                elif response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    raise RateLimitError(
                        f"Rate limit exceeded. Retry after {retry_after} seconds.",
                        retry_after=retry_after,
                    )
                elif response.status_code >= 400:
                    raise APIError(
                        f"API error: {response.text}",
                        status_code=response.status_code,
                        response_body=response.json() if response.content else None,
                    )

                response.raise_for_status()
                return response.json()

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exception = NetworkError(f"Network error: {str(e)}")
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                raise last_exception

            except (AuthenticationError, RateLimitError, APIError):
                raise

            except Exception as e:
                last_exception = APIError(f"Unexpected error: {str(e)}")
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                raise last_exception

        raise last_exception or APIError("Max retries exceeded")

    async def create_episode(
        self,
        name: str,
        content: str,
        source_type: str = "text",
        source_description: Optional[str] = None,
        group_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> EpisodeResponse:
        """
        Create a new episode.

        Args:
            name: Episode name
            content: Episode content (text or JSON string)
            source_type: Type of source ('text' or 'json')
            source_description: Optional description of the source
            group_id: Optional group ID for organizing episodes
            metadata: Optional additional metadata

        Returns:
            Episode response with ID and status
        """
        episode = EpisodeCreate(
            name=name,
            content=content,
            source_type=source_type,
            source_description=source_description,
            group_id=group_id,
            metadata=metadata,
        )

        response_data = await self._make_request(
            method="POST",
            endpoint="/api/v1/episodes/",
            json_data=episode.model_dump(exclude_none=True),
        )

        return EpisodeResponse(**response_data)

    async def search_memory(
        self,
        query: str,
        limit: int = 10,
        tenant_id: Optional[str] = None,
        filters: Optional[dict] = None,
    ) -> MemoryResponse:
        """
        Search the knowledge graph for relevant memories.

        Args:
            query: Search query text
            limit: Maximum number of results (1-100)
            tenant_id: Optional tenant ID for multi-tenancy
            filters: Optional additional filters

        Returns:
            Memory search results
        """
        memory_query = MemoryQuery(
            query=query,
            limit=limit,
            tenant_id=tenant_id,
            filters=filters,
        )

        response_data = await self._make_request(
            method="POST",
            endpoint="/api/v1/memory/search",
            json_data=memory_query.model_dump(exclude_none=True),
        )

        return MemoryResponse(**response_data)

    async def health_check(self) -> dict:
        """
        Check API health status.

        Returns:
            Health status information
        """
        return await self._make_request(
            method="GET",
            endpoint="/health",
        )

    async def create_api_key(
        self, name: str, permissions: List[str], expires_in_days: Optional[int] = None
    ) -> APIKey:
        """Create a new API key."""
        key_data = APIKeyCreate(name=name, permissions=permissions, expires_in_days=expires_in_days)
        response = await self._make_request(
            "POST", "/api/v1/auth/keys", json_data=key_data.model_dump(exclude_none=True)
        )
        return APIKey(**response)

    async def list_api_keys(self) -> List[APIKey]:
        """List all API keys."""
        response = await self._make_request("GET", "/api/v1/auth/keys")
        return [APIKey(**key) for key in response]

    async def revoke_api_key(self, key_id: str) -> None:
        """Revoke an API key."""
        await self._make_request("DELETE", f"/api/v1/auth/keys/{key_id}")

    async def create_memo(
        self, content: str, visibility: str = "PRIVATE", tags: List[str] = None
    ) -> Memo:
        """Create a new memo."""
        memo_data = MemoCreate(content=content, visibility=visibility, tags=tags or [])
        response = await self._make_request(
            "POST", "/api/v1/memos", json_data=memo_data.model_dump(exclude_none=True)
        )
        return Memo(**response)

    async def list_memos(self, limit: int = 20, offset: int = 0) -> List[Memo]:
        """List memos."""
        response = await self._make_request(
            "GET", "/api/v1/memos", params={"limit": limit, "offset": offset}
        )
        return [Memo(**memo) for memo in response]

    async def get_memo(self, memo_id: str) -> Memo:
        """Get a memo by ID."""
        response = await self._make_request("GET", f"/api/v1/memos/{memo_id}")
        return Memo(**response)

    async def update_memo(
        self,
        memo_id: str,
        content: Optional[str] = None,
        visibility: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Memo:
        """Update a memo."""
        memo_data = MemoUpdate(content=content, visibility=visibility, tags=tags)
        response = await self._make_request(
            "PATCH",
            f"/api/v1/memos/{memo_id}",
            json_data=memo_data.model_dump(exclude_none=True),
        )
        return Memo(**response)

    async def delete_memo(self, memo_id: str) -> None:
        """Delete a memo."""
        await self._make_request("DELETE", f"/api/v1/memos/{memo_id}")

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
