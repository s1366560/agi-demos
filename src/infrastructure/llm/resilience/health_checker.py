"""
Health checker for LLM providers.

Provides periodic health monitoring for LLM providers to enable
intelligent routing and automatic failover.

Features:
- Periodic health checks with configurable intervals
- Simple API endpoint testing
- Health status tracking with history
- Integration with circuit breakers

Example:
    checker = HealthChecker()
    await checker.start()  # Start background health checks

    # Get current health status
    status = await checker.get_health(ProviderType.OPENAI)
    if status.is_healthy:
        # Use this provider
        pass
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, NamedTuple

import httpx

from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.llm.provider_credentials import from_decrypted_api_key
from src.infrastructure.security.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Health status of a provider."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"  # Slow but working
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a single health check."""

    provider_type: ProviderType
    status: HealthStatus
    response_time_ms: float | None = None
    error_message: str | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_healthy(self) -> bool:
        """Check if provider is usable."""
        return self.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)


@dataclass
class HealthCheckConfig:
    """Configuration for health checking."""

    # How often to check each provider (seconds)
    check_interval: int = 30

    # Timeout for health check requests (seconds)
    timeout: float = 5.0

    # Response time threshold for degraded status (ms)
    degraded_threshold_ms: float = 2000.0

    # Number of recent results to keep for each provider
    history_size: int = 10

    # Callback when health status changes
    on_status_change: Callable[[ProviderType, HealthStatus, HealthStatus], None] | None = None


class _HealthEndpoint(NamedTuple):
    """Health check endpoint configuration for a provider."""

    url: str
    headers: dict[str, str | None] | None
    acceptable_statuses: frozenset[int]


# Standard acceptable status (200 only)
_OK_ONLY: frozenset[int] = frozenset({200})
# Some providers return 404 for models endpoint but are still reachable
_OK_OR_NOT_FOUND: frozenset[int] = frozenset({200, 404})


def _bearer_auth(api_key: str | None) -> dict[str, str | None]:
    """Build standard Bearer authorization header."""
    return {"Authorization": f"Bearer {api_key}"}


def _endpoint_openai(
    _config: ProviderConfig,
    api_key: str | None,
) -> _HealthEndpoint:
    return _HealthEndpoint(
        url="https://api.openai.com/v1/models",
        headers=_bearer_auth(api_key),
        acceptable_statuses=_OK_ONLY,
    )


def _endpoint_gemini(
    config: ProviderConfig,
    api_key: str | None,
) -> _HealthEndpoint:
    model = config.llm_model or "gemini-pro"
    return _HealthEndpoint(
        url=f"https://generativelanguage.googleapis.com/v1beta/models/{model}",
        headers={"x-goog-api-key": api_key},
        acceptable_statuses=_OK_ONLY,
    )


def _endpoint_dashscope(
    config: ProviderConfig,
    api_key: str | None,
) -> _HealthEndpoint:
    base_url = config.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    return _HealthEndpoint(
        url=f"{base_url}/models",
        headers=_bearer_auth(api_key),
        acceptable_statuses=_OK_ONLY,
    )


def _endpoint_anthropic(
    _config: ProviderConfig,
    api_key: str | None,
) -> _HealthEndpoint:
    return _HealthEndpoint(
        url="https://api.anthropic.com/v1/models",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        acceptable_statuses=_OK_OR_NOT_FOUND,
    )


def _endpoint_deepseek(
    config: ProviderConfig,
    api_key: str | None,
) -> _HealthEndpoint:
    base_url = config.base_url or "https://api.deepseek.com/v1"
    return _HealthEndpoint(
        url=f"{base_url}/models",
        headers=_bearer_auth(api_key),
        acceptable_statuses=_OK_ONLY,
    )


def _endpoint_minimax(
    config: ProviderConfig,
    api_key: str | None,
) -> _HealthEndpoint:
    base_url = config.base_url or "https://api.minimax.chat/v1"
    return _HealthEndpoint(
        url=f"{base_url}/models",
        headers=_bearer_auth(api_key),
        acceptable_statuses=_OK_ONLY,
    )


def _endpoint_zai(
    config: ProviderConfig,
    api_key: str | None,
) -> _HealthEndpoint:
    base_url = config.base_url or "https://open.bigmodel.cn/api/paas/v4"
    return _HealthEndpoint(
        url=f"{base_url}/models",
        headers=_bearer_auth(api_key),
        acceptable_statuses=_OK_OR_NOT_FOUND,
    )


def _endpoint_kimi(
    config: ProviderConfig,
    api_key: str | None,
) -> _HealthEndpoint:
    base_url = config.base_url or "https://api.moonshot.cn/v1"
    return _HealthEndpoint(
        url=f"{base_url}/models",
        headers=_bearer_auth(api_key),
        acceptable_statuses=_OK_ONLY,
    )


def _endpoint_ollama(
    config: ProviderConfig,
    _api_key: str | None,
) -> _HealthEndpoint:
    base_url = config.base_url or "http://localhost:11434"
    return _HealthEndpoint(
        url=f"{base_url}/api/tags",
        headers=None,
        acceptable_statuses=_OK_ONLY,
    )


def _endpoint_lmstudio(
    config: ProviderConfig,
    api_key: str | None,
) -> _HealthEndpoint:
    base_url = config.base_url or "http://localhost:1234/v1"
    headers = _bearer_auth(api_key) if api_key else None
    return _HealthEndpoint(
        url=f"{base_url}/models",
        headers=headers,
        acceptable_statuses=_OK_ONLY,
    )


_HEALTH_ENDPOINT_REGISTRY: dict[
    ProviderType,
    Callable[[ProviderConfig, str | None], _HealthEndpoint],
] = {
    ProviderType.OPENAI: _endpoint_openai,
    ProviderType.GEMINI: _endpoint_gemini,
    ProviderType.DASHSCOPE: _endpoint_dashscope,
    ProviderType.ANTHROPIC: _endpoint_anthropic,
    ProviderType.DEEPSEEK: _endpoint_deepseek,
    ProviderType.MINIMAX: _endpoint_minimax,
    ProviderType.ZAI: _endpoint_zai,
    ProviderType.KIMI: _endpoint_kimi,
    ProviderType.OLLAMA: _endpoint_ollama,
    ProviderType.LMSTUDIO: _endpoint_lmstudio,
}


class HealthChecker:
    """
    Health checker for LLM providers.

    Performs periodic health checks and maintains status history.
    """

    def __init__(
        self,
        config: HealthCheckConfig | None = None,
    ) -> None:
        """
        Initialize health checker.

        Args:
            config: Health check configuration
        """
        self.config = config or HealthCheckConfig()
        self._providers: dict[ProviderType, ProviderConfig] = {}
        self._results: dict[ProviderType, list[HealthCheckResult]] = {}
        self._current_status: dict[ProviderType, HealthStatus] = {}
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._encryption_service = get_encryption_service()

    def register_provider(
        self,
        provider_type: ProviderType,
        provider_config: ProviderConfig,
    ) -> None:
        """
        Register a provider for health checking.

        Args:
            provider_type: Type of provider
            provider_config: Provider configuration with credentials
        """
        self._providers[provider_type] = provider_config
        self._results[provider_type] = []
        self._current_status[provider_type] = HealthStatus.UNKNOWN
        logger.info(f"Registered provider {provider_type.value} for health checking")

    def unregister_provider(self, provider_type: ProviderType) -> None:
        """Unregister a provider from health checking."""
        self._providers.pop(provider_type, None)
        self._results.pop(provider_type, None)
        self._current_status.pop(provider_type, None)

    async def start(self) -> None:
        """Start background health checking."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._health_check_loop())
        logger.info("Health checker started")

    async def stop(self) -> None:
        """Stop background health checking."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Health checker stopped")

    async def _health_check_loop(self) -> None:
        """Background loop for periodic health checks."""
        while self._running:
            try:
                # Check all registered providers
                for provider_type in list(self._providers.keys()):
                    try:
                        await self.check_health(provider_type)
                    except Exception as e:
                        logger.error(f"Health check failed for {provider_type.value}: {e}")

                # Wait for next interval
                await asyncio.sleep(self.config.check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
                await asyncio.sleep(5)  # Brief pause on error

    async def check_health(
        self,
        provider_type: ProviderType,
    ) -> HealthCheckResult:
        """
        Perform a health check for a specific provider.

        Args:
            provider_type: Provider to check

        Returns:
            Health check result
        """
        provider_config = self._providers.get(provider_type)
        if not provider_config:
            return HealthCheckResult(
                provider_type=provider_type,
                status=HealthStatus.UNKNOWN,
                error_message="Provider not registered",
            )

        start_time = datetime.now(UTC)
        result: HealthCheckResult

        try:
            # Decrypt API key
            decrypted_key = self._encryption_service.decrypt(provider_config.api_key_encrypted)
            api_key = from_decrypted_api_key(decrypted_key)

            # Perform health check request
            response_time_ms = await self._do_health_check(provider_type, provider_config, api_key)

            # Determine status based on response time
            if response_time_ms < self.config.degraded_threshold_ms:
                status = HealthStatus.HEALTHY
            else:
                status = HealthStatus.DEGRADED
                logger.warning(
                    f"Provider {provider_type.value} is degraded "
                    f"(response time: {response_time_ms:.0f}ms)"
                )

            result = HealthCheckResult(
                provider_type=provider_type,
                status=status,
                response_time_ms=response_time_ms,
                checked_at=start_time,
            )

        except Exception as e:
            result = HealthCheckResult(
                provider_type=provider_type,
                status=HealthStatus.UNHEALTHY,
                error_message=str(e),
                checked_at=start_time,
            )
            logger.warning(f"Provider {provider_type.value} is unhealthy: {e}")

        # Update results history
        await self._update_results(provider_type, result)

        return result

    async def _do_health_check(
        self,
        provider_type: ProviderType,
        provider_config: ProviderConfig,
        api_key: str | None,
    ) -> float:
        """
        Perform the actual health check request.

        Returns:
            Response time in milliseconds
        """
        import time

        start = time.time()

        endpoint_factory = _HEALTH_ENDPOINT_REGISTRY.get(provider_type)

        if endpoint_factory is None:
            # Unknown provider -- just mark as healthy
            logger.debug(f"No specific health check for {provider_type.value}, marking as healthy")
            return (time.time() - start) * 1000

        endpoint = endpoint_factory(provider_config, api_key)

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.get(endpoint.url, headers={k: v for k, v in endpoint.headers.items() if v is not None} if endpoint.headers else None)
            if response.status_code not in endpoint.acceptable_statuses:
                response.raise_for_status()

        return (time.time() - start) * 1000

    async def _update_results(
        self,
        provider_type: ProviderType,
        result: HealthCheckResult,
    ) -> None:
        """Update results history and current status."""
        async with self._lock:
            # Add to history
            if provider_type not in self._results:
                self._results[provider_type] = []

            self._results[provider_type].append(result)

            # Trim history
            if len(self._results[provider_type]) > self.config.history_size:
                self._results[provider_type] = self._results[provider_type][
                    -self.config.history_size :
                ]

            # Update current status and notify if changed
            old_status = self._current_status.get(provider_type, HealthStatus.UNKNOWN)
            new_status = result.status

            if old_status != new_status:
                self._current_status[provider_type] = new_status
                logger.info(
                    f"Provider {provider_type.value} health status changed: "
                    f"{old_status.value} -> {new_status.value}"
                )

                if self.config.on_status_change:
                    try:
                        self.config.on_status_change(provider_type, old_status, new_status)
                    except Exception as e:
                        logger.error(f"Error in health status change callback: {e}")
            else:
                self._current_status[provider_type] = new_status

    async def get_health(
        self,
        provider_type: ProviderType,
    ) -> HealthCheckResult:
        """
        Get current health status for a provider.

        Args:
            provider_type: Provider to check

        Returns:
            Most recent health check result
        """
        results = self._results.get(provider_type, [])
        if results:
            return results[-1]

        return HealthCheckResult(
            provider_type=provider_type,
            status=self._current_status.get(provider_type, HealthStatus.UNKNOWN),
        )

    def get_healthy_providers(self) -> list[ProviderType]:
        """Get list of currently healthy providers."""
        return [
            provider_type
            for provider_type, status in self._current_status.items()
            if status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)
        ]

    def get_all_statuses(self) -> dict[str, dict[str, Any]]:
        """Get health status for all providers."""
        result = {}
        for provider_type in self._providers.keys():
            results = self._results.get(provider_type, [])
            latest = results[-1] if results else None

            result[provider_type.value] = {
                "status": self._current_status.get(provider_type, HealthStatus.UNKNOWN).value,
                "last_check": latest.checked_at.isoformat() if latest else None,
                "response_time_ms": latest.response_time_ms if latest else None,
                "error_message": latest.error_message if latest else None,
                "check_count": len(results),
            }

        return result


# Global health checker instance
_health_checker: HealthChecker | None = None


def get_health_checker() -> HealthChecker:
    """Get the global health checker instance."""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


async def start_health_checker() -> None:
    """Start the global health checker."""
    checker = get_health_checker()
    await checker.start()


async def stop_health_checker() -> None:
    """Stop the global health checker."""
    checker = get_health_checker()
    await checker.stop()
