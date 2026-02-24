"""Alerting infrastructure module.

Provides alerting services for critical events and escalations.
"""

from src.domain.ports.services.alert_service_port import (
    Alert,
    AlertServicePort,
    AlertSeverity,
    CompositeAlertServicePort,
    NullAlertService,
)
from src.infrastructure.alerting.slack_alert_service import SlackAlertService

__all__ = [
    "Alert",
    "AlertServicePort",
    "AlertSeverity",
    "CompositeAlertServicePort",
    "NullAlertService",
    "SlackAlertService",
]
