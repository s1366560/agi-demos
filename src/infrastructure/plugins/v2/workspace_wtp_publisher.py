"""Generation-owned Workspace Task Protocol publisher Provider."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from src.domain.model.workspace.wtp_envelope import WtpEnvelope
from src.infrastructure.agent.workspace.workspace_supervisor import publish_envelope
from src.infrastructure.agent.workspace.wtp_publisher_runtime import (
    WorkspaceWtpPublisherProtocolV2,
)

from .redis_runtime import RedisRuntimeServiceV2
from .runtime import (
    ContextV2,
    EffectResultV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

WORKSPACE_WTP_PUBLISHER_MODULE_V2 = "builtin://memstack/workspace/wtp-publisher"
WORKSPACE_WTP_PUBLISHER_SERVICE_V2 = "service:agent.workspace-wtp-publisher"
WORKSPACE_WTP_PUBLISHER_REDIS_INJECT_V2 = "redis"


class RedisWorkspaceWtpPublisherV2:
    """Borrow one generation's Redis projection without owning the host client."""

    def __init__(self, *, redis_runtime: RedisRuntimeServiceV2) -> None:
        super().__init__()
        self._redis_client = redis_runtime.client
        self._closed = False

    async def publish(self, envelope: WtpEnvelope) -> str | None:
        if self._closed:
            raise RuntimeV2Error(
                "disposed_workspace_wtp_publisher",
                "Workspace WTP publisher is already disposed",
            )
        if self._redis_client is None or not callable(getattr(self._redis_client, "xadd", None)):
            raise RuntimeV2Error(
                "workspace_wtp_redis_unavailable",
                "Workspace WTP publisher requires an available Redis stream client",
            )
        entry_id = await publish_envelope(cast(Any, self._redis_client), envelope)
        if entry_id is None:
            raise RuntimeV2Error(
                "workspace_wtp_publish_failed",
                "Workspace WTP publisher could not persist the envelope",
            )
        return entry_id

    def close(self) -> None:
        """Invalidate this projection without closing the process-owned Redis client."""
        self._closed = True


def _apply_workspace_wtp_publisher_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> EffectResultV2:
    if config.get("strategy") != "generation-redis-adapter":
        raise ValueError("Workspace WTP publisher requires strategy generation-redis-adapter")
    redis_runtime = context.require(WORKSPACE_WTP_PUBLISHER_REDIS_INJECT_V2)
    if not isinstance(redis_runtime, RedisRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_workspace_wtp_redis_runtime",
            "Workspace WTP publisher received an invalid Redis runtime projection",
        )
    publisher = RedisWorkspaceWtpPublisherV2(redis_runtime=redis_runtime)
    _ = context.provide(
        WORKSPACE_WTP_PUBLISHER_SERVICE_V2,
        publisher,
        label="workspace-wtp-publisher",
    )
    return publisher.close


def workspace_wtp_publisher_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=WORKSPACE_WTP_PUBLISHER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(WORKSPACE_WTP_PUBLISHER_MODULE_V2),
        apply=_apply_workspace_wtp_publisher_v2,
    )


__all__ = [
    "WORKSPACE_WTP_PUBLISHER_MODULE_V2",
    "WORKSPACE_WTP_PUBLISHER_REDIS_INJECT_V2",
    "WORKSPACE_WTP_PUBLISHER_SERVICE_V2",
    "RedisWorkspaceWtpPublisherV2",
    "WorkspaceWtpPublisherProtocolV2",
    "workspace_wtp_publisher_definition_v2",
]
