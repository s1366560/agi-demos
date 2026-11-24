"""Deployment-owned cloud application operations for the signed agent package."""

from collections.abc import Mapping
from typing import Any

from src.host.operations.deployment_adapters import ApplicationAdapter, provide_application_adapter
from src.infrastructure.plugins.v2.runtime_context import ContextV2

from .chat_operations import AGENT_OPERATIONS
from .workbench import WORKBENCH_OPERATIONS


def apply(ctx: ContextV2, _config: Mapping[str, Any]) -> None:
    provide_application_adapter(
        ctx,
        ApplicationAdapter(
            plugin_id="memstack-agent", project={**AGENT_OPERATIONS, **WORKBENCH_OPERATIONS}
        ),
    )
