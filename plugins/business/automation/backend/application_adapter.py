"""Deployment-owned cloud application operations for the signed automation package."""

from collections.abc import Mapping
from typing import Any

from src.host.operations.deployment_adapters import ApplicationAdapter, provide_application_adapter
from src.infrastructure.plugins.v2.runtime_context import ContextV2

from .playbook_operation import read_playbooks
from .schedule_operations import SCHEDULE_OPERATIONS


def apply(ctx: ContextV2, _config: Mapping[str, Any]) -> None:
    provide_application_adapter(
        ctx,
        ApplicationAdapter(
            plugin_id="memstack-automation",
            project={**SCHEDULE_OPERATIONS, "app.automation.playbooks.read": read_playbooks},
        ),
    )
