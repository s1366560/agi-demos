"""Real scoped HITL Redis ownership and failed admission side-effect boundaries."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.configuration import config as config_module
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2, ServiceRequiredV2
from src.infrastructure.adapters.primary.web.websocket.handlers import (
    hitl_handler,
    subscription_handler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.secondary.persistence import sql_hitl_request_repository
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2,
    current_operation_context_v2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.scoped_runtime_registry import ScopedRuntimeRegistryV2
from src.infrastructure.plugins.v2.service_closure import project_service_closure_v2

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).resolve().parents[9]


def _context() -> MessageContext:
    return MessageContext(
        websocket=SimpleNamespace(send_json=AsyncMock()),
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="socket-1",
        db=MagicMock(),
        container=MagicMock(),
    )


async def _publish(context: MessageContext) -> bool:
    return await hitl_handler._publish_hitl_response_to_redis(
        context=context,
        tenant_id="tenant-1",
        project_id="project-1",
        conversation_id="conversation-1",
        message_id="message-1",
        request_id="request-1",
        hitl_type="decision",
        response_data={"decision": "approve"},
        user_id="user-1",
        agent_mode="default",
    )


@pytest.mark.parametrize("cancel", [False, True])
async def test_publish_uses_scoped_redis_and_releases_on_cancellation(monkeypatch, cancel):
    entered = asyncio.Event()
    observed = []

    async def xadd(*_args, **_kwargs):
        operation = current_operation_context_v2()
        assert operation is not None
        distribution = operation.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2)
        observed.append(distribution["descriptor"]["generation"])
        entered.set()
        if cancel:
            await asyncio.Event().wait()
        return "1-0"

    redis = SimpleNamespace(
        xadd=xadd,
        aclose=AsyncMock(),
        get=AsyncMock(),
        set=AsyncMock(),
        delete=AsyncMock(),
        scan_iter=MagicMock(),
    )

    async def redis_factory():
        return redis

    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    registry = ScopedRuntimeRegistryV2(
        builtin_runtime_definitions_v2(redis_runtime_factory=redis_factory)
    )
    try:
        root = await host.bootstrap(
            profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
            manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
            generation=1,
            version=1,
        )
        assert root.accepted
        scope = ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id="tenant-1",
            project_id="project-1",
            session_id="conversation-1",
        )
        snapshot = project_service_closure_v2(
            root.snapshot,
            scope=scope,
            required_services=(
                ServiceRequiredV2(
                    service="service:agent.turn-service", version="1.0.0", alias="turn"
                ),
                ServiceRequiredV2(
                    service="service:agent.worker-runtime", version="1.0.0", alias="worker"
                ),
            ),
        )
        snapshot = compose_profile_v2(
            ProfileDocumentV2(profile_id=snapshot.profile_id, entries=snapshot.entries),
            {manifest.plugin_id: manifest for manifest in snapshot.manifests},
            generation=2,
        )
        assert (
            await registry.publish(scope, snapshot, control_envelope_v2(snapshot, version=2))
        ).accepted
        monkeypatch.setattr(
            config_module, "get_settings", lambda: SimpleNamespace(hitl_realtime_enabled=True)
        )
        reservation = await registry.acquire_bound(scope)
        acquire = AsyncMock(return_value=reservation)
        monkeypatch.setattr(hitl_handler, "acquire_existing_scoped_session_v2", acquire)
        context = _context()
        async with pin_generation_v2(host):
            if cancel:
                task = asyncio.create_task(_publish(context))
                try:
                    await asyncio.wait_for(entered.wait(), timeout=5)
                finally:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
            else:
                assert await _publish(context)
        assert observed == [2]
        assert reservation.lease._released
        acquire.assert_awaited_once_with(
            context,
            conversation_id="conversation-1",
            project_id="project-1",
            hitl_request_id="request-1",
        )
    finally:
        await registry.close()
        await host.close()
    redis.aclose.assert_awaited_once()


@pytest.mark.parametrize("entry", ["publish", "recovery"])
async def test_failed_scoped_admission_has_no_redis_subscription_or_bridge(monkeypatch, entry):
    context = _context()
    manager = SimpleNamespace(bridge_tasks={}, subscribe=AsyncMock())
    context._connection_manager = manager
    acquire = AsyncMock(side_effect=RuntimeV2Error("scope_unavailable", "unavailable"))
    redis = MagicMock(side_effect=AssertionError("No Redis without admission"))
    start = AsyncMock()
    monkeypatch.setattr(
        config_module, "get_settings", lambda: SimpleNamespace(hitl_realtime_enabled=True)
    )
    monkeypatch.setattr(hitl_handler, "acquire_existing_scoped_session_v2", acquire)
    monkeypatch.setattr(hitl_handler, "current_agent_worker_redis_client_v2", redis)
    monkeypatch.setattr(subscription_handler, "_start_recovery_bridge_task_v2", start)
    monkeypatch.setattr(
        sql_hitl_request_repository,
        "SqlHITLRequestRepository",
        lambda _db: SimpleNamespace(
            get_by_id=AsyncMock(
                return_value=SimpleNamespace(
                    conversation_id="conversation-1", project_id="project-1"
                )
            )
        ),
    )
    if entry == "publish":
        assert not await _publish(context)
    else:
        await hitl_handler._start_hitl_stream_bridge(context, "request-1")
    acquire.assert_awaited_once_with(
        context,
        conversation_id="conversation-1",
        project_id="project-1",
        hitl_request_id="request-1",
    )
    redis.assert_not_called()
    manager.subscribe.assert_not_awaited()
    start.assert_not_awaited()
