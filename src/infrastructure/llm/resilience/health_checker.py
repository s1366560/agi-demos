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
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

import httpx

from src.domain.llm_providers.models import ProviderConfig, ProviderType
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
    response_time_ms: Optional[float] = None
    error_message: Optional[str] = None
    checked_at: datetime = field(default_factory=datetime.utcnow)

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
    on_status_change: Optional[Callable[[ProviderType, HealthStatus, HealthStatus], None]] = None


class HealthChecker:
    """
    Health checker for LLM providers.

    Performs periodic health checks and maintains status history.
    """

    def __init__(
        self,
        config: Optional[HealthCheckConfig] = None,
    ):
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
        self._task: Optional[asyncio.Task] = None
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
            try:
                await self._task
            except asyncio.CancelledError:
                pass
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

        start_time = datetime.utcnow()
        result: HealthCheckResult

        try:
            # Decrypt API key
            api_key = self._encryption_service.decrypt(provider_config.api_key_encrypted)

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
        api_key: str,
    ) -> float:
        """
        Perform the actual health check request.

        Returns:
            Response time in milliseconds
        """
        import time

        start = time.time()

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            if provider_type == ProviderType.OPENAI:
                response = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                response.raise_for_status()

            elif provider_type == ProviderType.GEMINI:
                model = provider_config.llm_model or "gemini-pro"
                response = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}",
                    headers={"x-goog-api-key": api_key},
                )
                response.raise_for_status()

            elif provider_type == ProviderType.QWEN:
                base_url = (
                    provider_config.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
                )
                response = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                response.raise_for_status()

            elif provider_type == ProviderType.ANTHROPIC:
                # Anthropic doesn't have a models endpoint, check with a minimal request
                response = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                # May return 404 but that's ok - we're just checking connectivity
                if response.status_code not in (200, 404):
                    response.raise_for_status()

            elif provider_type == ProviderType.DEEPSEEK:
                base_url = provider_config.base_url or "https://api.deepseek.com/v1"
                response = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                response.raise_for_status()

            elif provider_type == ProviderType.ZAI:
                base_url = provider_config.base_url or "https://open.bigmodel.cn/api/paas/v4"
                response = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                # ZAI may return different status codes
                if response.status_code not in (200, 404):
                    response.raise_for_status()

            else:
                # For unknown providers, just check if we can connect
                logger.debug(
                    f"No specific health check for {provider_type.value}, marking as healthy"
                )

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

    def get_all_statuses(self) -> dict[str, dict]:
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
_health_checker: Optional[HealthChecker] = None


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
