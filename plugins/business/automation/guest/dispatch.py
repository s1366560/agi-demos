"""Map admitted command names onto guest shapers."""

from __future__ import annotations

from plugins.business.automation.guest.commands import OPERATIONS

__all__ = ["OPERATIONS", "TOOLS"]

TOOLS = {
    "automation.list-playbooks": "app.automation.playbooks.read",
    "automation.list-schedules": "app.automation.schedules.read",
    "automation.save-schedule": "app.automation.schedules.write",
    "automation.run-schedule": "app.automation.schedules.run",
    "automation.delete-schedule": "app.automation.schedules.delete",
    "automation.list-patterns": "app.automation.patterns.read",
    "automation.delete-pattern": "app.automation.patterns.delete",
    "automation.list-verdicts": "app.automation.verdicts.read",
    "automation.read-events": "app.automation.events.read",
    "automation.event-types": "app.automation.events.types",
    "automation.list-webhooks": "app.automation.webhooks.read",
    "automation.create-webhook": "app.automation.webhooks.create",
    "automation.update-webhook": "app.automation.webhooks.update",
    "automation.delete-webhook": "app.automation.webhooks.delete",
    "automation.schedule-conversations": "app.automation.conversations.read",
}
