"""Slack Alert Service Implementation.

Sends alerts to Slack via webhook.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

from src.domain.ports.services.alert_service_port import (
    Alert,
    AlertServicePort,
    AlertSeverity,
)

logger = logging.getLogger(__name__)


class SlackAlertService(AlertServicePort):
    """Slack webhook-based alerting service.

    Sends alerts to a Slack channel via incoming webhook URL.
    """

    # Severity to color mapping
    SEVERITY_COLORS = {
        AlertSeverity.INFO: "#36a64f",  # green
        AlertSeverity.WARNING: "#ff9900",  # orange
        AlertSeverity.ERROR: "#ff0000",  # red
        AlertSeverity.CRITICAL: "#990000",  # dark red
    }

    # Severity to emoji mapping
    SEVERITY_EMOJIS = {
        AlertSeverity.INFO: ":information_source:",
        AlertSeverity.WARNING: ":warning:",
        AlertSeverity.ERROR: ":x:",
        AlertSeverity.CRITICAL: ":rotating_light:",
    }

    def __init__(
        self,
        webhook_url: str,
        channel: Optional[str] = None,
        username: str = "MemStack Alerts",
        timeout_seconds: float = 10.0,
    ):
        """Initialize Slack alert service.

        Args:
            webhook_url: Slack incoming webhook URL
            channel: Override channel (optional, uses webhook default if not set)
            username: Bot username to display
            timeout_seconds: HTTP request timeout
        """
        self._webhook_url = webhook_url
        self._channel = channel
        self._username = username
        self._timeout = timeout_seconds

    async def send_alert(self, alert: Alert) -> bool:
        """Send alert to Slack channel.

        Args:
            alert: The alert to send

        Returns:
            True if alert was sent successfully
        """
        payload = self._build_slack_payload(alert)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._webhook_url,
                    json=payload,
                )

                if response.status_code == 200:
                    logger.info(f"Alert sent to Slack: {alert.title}")
                    return True
                else:
                    logger.error(
                        f"Failed to send Slack alert: {response.status_code} - {response.text}"
                    )
                    return False

        except httpx.TimeoutException:
            logger.error(f"Timeout sending Slack alert: {alert.title}")
            return False
        except Exception as e:
            logger.error(f"Error sending Slack alert: {e}")
            return False

    async def send_alert_with_retry(
        self, alert: Alert, max_retries: int = 3, retry_delay_seconds: float = 1.0
    ) -> bool:
        """Send alert with exponential backoff retry."""
        for attempt in range(max_retries):
            if await self.send_alert(alert):
                return True

            if attempt < max_retries - 1:
                delay = retry_delay_seconds * (2**attempt)
                logger.warning(f"Retrying Slack alert in {delay}s (attempt {attempt + 2}/{max_retries})")
                await asyncio.sleep(delay)

        return False

    async def health_check(self) -> bool:
        """Check if Slack webhook is accessible.

        Returns:
            True if webhook is valid
        """
        try:
            # Send a minimal test payload
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    self._webhook_url,
                    json={"text": "Health check"},
                )
                return response.status_code == 200
        except Exception:
            return False

    def _build_slack_payload(self, alert: Alert) -> Dict[str, Any]:
        """Build Slack message payload from alert."""
        color = self.SEVERITY_COLORS.get(alert.severity, "#808080")
        emoji = self.SEVERITY_EMOJIS.get(alert.severity, ":bell:")

        # Build attachment with alert details
        attachment: Dict[str, Any] = {
            "color": color,
            "title": f"{emoji} {alert.title}",
            "text": alert.message,
            "fields": [
                {
                    "title": "Severity",
                    "value": alert.severity.value.upper(),
                    "short": True,
                },
                {
                    "title": "Source",
                    "value": alert.source,
                    "short": True,
                },
                {
                    "title": "Time",
                    "value": alert.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "short": True,
                },
            ],
            "fallback": f"{alert.title}: {alert.message}",
        }

        # Add metadata as additional fields
        if alert.metadata:
            for key, value in alert.metadata.items():
                if len(attachment["fields"]) < 10:  # Slack field limit
                    attachment["fields"].append(
                        {
                            "title": key.replace("_", " ").title(),
                            "value": str(value)[:500],  # Truncate long values
                            "short": len(str(value)) < 50,
                        }
                    )

        payload: Dict[str, Any] = {
            "username": self._username,
            "attachments": [attachment],
        }

        if self._channel:
            payload["channel"] = self._channel

        return payload
