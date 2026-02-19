"""Alert Service Port - Interface for sending alerts.

Provides abstraction for alerting functionality, allowing different
alerting backends (Slack, Email, PagerDuty, etc.) to be plugged in.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class AlertSeverity(Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Alert data model.

    Attributes:
        title: Short alert title
        message: Detailed alert message
        severity: Alert severity level
        source: Source system/component that generated the alert
        timestamp: When the alert was generated
        metadata: Additional context as key-value pairs
    """

    title: str
    message: str
    severity: AlertSeverity
    source: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary representation."""
        return {
            "title": self.title,
            "message": self.message,
            "severity": self.severity.value,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class AlertServicePort(ABC):
    """Abstract interface for alerting services.

    Implementations can send alerts to various destinations
    (Slack, Email, PagerDuty, webhooks, etc.).
    """

    @abstractmethod
    async def send_alert(self, alert: Alert) -> bool:
        """Send an alert.

        Args:
            alert: The alert to send

        Returns:
            True if alert was sent successfully, False otherwise
        """
        pass

    @abstractmethod
    async def send_alert_with_retry(
        self, alert: Alert, max_retries: int = 3, retry_delay_seconds: float = 1.0
    ) -> bool:
        """Send an alert with retry logic.

        Args:
            alert: The alert to send
            max_retries: Maximum number of retry attempts
            retry_delay_seconds: Delay between retries (exponential backoff)

        Returns:
            True if alert was sent successfully, False otherwise
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the alerting service is healthy.

        Returns:
            True if service is healthy, False otherwise
        """
        pass


class CompositeAlertServicePort(AlertServicePort):
    """Alert service that sends to multiple destinations.

    Useful for sending critical alerts to multiple channels simultaneously.
    """

    def __init__(self, services: list[AlertServicePort]):
        """Initialize with list of alert services.

        Args:
            services: List of alert service implementations
        """
        self._services = services

    async def send_alert(self, alert: Alert) -> bool:
        """Send alert to all configured services.

        Returns True if at least one service succeeded.
        """
        results = []
        for service in self._services:
            try:
                result = await service.send_alert(alert)
                results.append(result)
            except Exception:
                results.append(False)

        return any(results)

    async def send_alert_with_retry(
        self, alert: Alert, max_retries: int = 3, retry_delay_seconds: float = 1.0
    ) -> bool:
        """Send alert with retry to all configured services."""
        import asyncio

        results = []
        for service in self._services:
            for attempt in range(max_retries):
                try:
                    result = await service.send_alert(alert)
                    if result:
                        results.append(True)
                        break
                except Exception:
                    pass

                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay_seconds * (2**attempt))

            else:
                results.append(False)

        return any(results)

    async def health_check(self) -> bool:
        """Check health of all services.

        Returns True if at least one service is healthy.
        """
        results = []
        for service in self._services:
            try:
                result = await service.health_check()
                results.append(result)
            except Exception:
                results.append(False)

        return any(results)


class NullAlertService(AlertServicePort):
    """No-op alert service that does nothing.

    Useful for testing or when alerting is disabled.
    """

    async def send_alert(self, alert: Alert) -> bool:
        """Do nothing, return True."""
        return True

    async def send_alert_with_retry(
        self, alert: Alert, max_retries: int = 3, retry_delay_seconds: float = 1.0
    ) -> bool:
        """Do nothing, return True."""
        return True

    async def health_check(self) -> bool:
        """Always return True."""
        return True
