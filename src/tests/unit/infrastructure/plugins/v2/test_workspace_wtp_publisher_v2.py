"""Tests for the generation-owned Workspace WTP publisher."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.domain.model.workspace.wtp_envelope import WtpEnvelope, WtpVerb
from src.infrastructure.agent.workspace import worker_launch
from src.infrastructure.agent.workspace.wtp_publisher_runtime import (
    bind_workspace_wtp_publisher_v2,
    current_workspace_wtp_publisher_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    pin_operation_context_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import (
    RUNTIME_BOUNDARY_MODULE_V2,
    builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.redis_runtime import REDIS_RUNTIME_MODULE_V2
from src.infrastructure.plugins.v2.runtime import (
    GenerationLeaseV2,
    GenerationManagerV2,
    LoaderV2,
    RuntimeGenerationV2,
    RuntimeV2Error,
)
from src.infrastructure.plugins.v2.workspace_wtp_publisher import (
    WORKSPACE_WTP_PUBLISHER_MODULE_V2,
    WORKSPACE_WTP_PUBLISHER_SERVICE_V2,
    WorkspaceWtpPublisherProtocolV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_ROOT_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)


def _snapshot(*, generation: int):
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    document = load_profile_document_v2(_PROFILE_PATH)
    selected_modules = {
        RUNTIME_BOUNDARY_MODULE_V2,
        REDIS_RUNTIME_MODULE_V2,
        WORKSPACE_WTP_PUBLISHER_MODULE_V2,
    }
    entries = tuple(entry for entry in document.entries if entry.module_ref in selected_modules)
    return compose_profile_v2(
        replace(document, entries=entries),
        {manifest.plugin_id: manifest},
        generation=generation,
    )


async def _generation(*, generation: int, redis_client: object):
    return await LoaderV2(builtin_runtime_definitions_v2(sandbox_redis_client=redis_client)).stage(
        _snapshot(generation=generation)
    )


def _envelope() -> WtpEnvelope:
    return WtpEnvelope(
        verb=WtpVerb.TASK_PROGRESS,
        workspace_id="workspace-1",
        task_id="task-1",
        attempt_id="attempt-1",
        correlation_id="correlation-1",
        payload={"summary": "still working"},
    )


@pytest.mark.unit
def test_workspace_wtp_publisher_is_an_explicit_profile_entry() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    matching = [
        entry for entry in document.entries if entry.module_ref == WORKSPACE_WTP_PUBLISHER_MODULE_V2
    ]

    assert len(matching) == 1
    assert matching[0].enabled is True
    assert matching[0].inject == {"redis": "service:runtime.redis-client"}


@pytest.mark.unit
async def test_publisher_uses_generation_redis_xadd_and_disposes() -> None:
    redis = MagicMock()
    redis.xadd = AsyncMock(return_value="1-0")
    generation = await _generation(generation=401, redis_client=redis)
    publisher = generation.resolve(WORKSPACE_WTP_PUBLISHER_SERVICE_V2, _ROOT_SCOPE)

    assert isinstance(publisher, WorkspaceWtpPublisherProtocolV2)
    assert await publisher.publish(_envelope()) == "1-0"
    redis.xadd.assert_awaited_once()
    call = redis.xadd.await_args
    assert call.args[0] == "workspace:wtp:inbox"
    assert json.loads(call.args[1]["data"])["correlation_id"] == "correlation-1"
    assert call.kwargs == {"maxlen": 10_000, "approximate": True}

    await generation.dispose()
    with pytest.raises(RuntimeV2Error) as error:
        await publisher.publish(_envelope())
    assert error.value.code == "disposed_workspace_wtp_publisher"


@pytest.mark.unit
async def test_publisher_rejects_an_unavailable_redis_projection_on_use() -> None:
    generation = await _generation(generation=402, redis_client=None)
    publisher = generation.resolve(WORKSPACE_WTP_PUBLISHER_SERVICE_V2, _ROOT_SCOPE)

    with pytest.raises(RuntimeV2Error) as error:
        _ = await publisher.publish(_envelope())

    assert error.value.code == "workspace_wtp_redis_unavailable"
    await generation.dispose()


@pytest.mark.unit
async def test_publisher_surfaces_redis_write_failure_as_structured_error() -> None:
    redis = MagicMock()
    redis.xadd = AsyncMock(side_effect=RuntimeError("redis unavailable"))
    generation = await _generation(generation=403, redis_client=redis)
    publisher = generation.resolve(WORKSPACE_WTP_PUBLISHER_SERVICE_V2, _ROOT_SCOPE)

    with pytest.raises(RuntimeV2Error) as error:
        _ = await publisher.publish(_envelope())

    assert error.value.code == "workspace_wtp_publish_failed"
    await generation.dispose()


@pytest.mark.unit
async def test_generation_replacement_keeps_exact_publisher_until_lease_release() -> None:
    first_redis = MagicMock()
    first_redis.xadd = AsyncMock(return_value="1-0")
    second_redis = MagicMock()
    second_redis.xadd = AsyncMock(return_value="2-0")
    first = await _generation(generation=404, redis_client=first_redis)
    second = await _generation(generation=405, redis_client=second_redis)
    manager = GenerationManagerV2()
    await manager.publish(first)
    old_lease = await manager.acquire()
    old_publisher = old_lease.generation.resolve(
        WORKSPACE_WTP_PUBLISHER_SERVICE_V2,
        _ROOT_SCOPE,
    )

    await manager.publish(second)
    new_lease = await manager.acquire()
    new_publisher = new_lease.generation.resolve(
        WORKSPACE_WTP_PUBLISHER_SERVICE_V2,
        _ROOT_SCOPE,
    )

    assert await old_publisher.publish(_envelope()) == "1-0"
    assert await new_publisher.publish(_envelope()) == "2-0"
    first_redis.xadd.assert_awaited_once()
    second_redis.xadd.assert_awaited_once()

    await old_lease.release()
    with pytest.raises(RuntimeV2Error) as error:
        await old_publisher.publish(_envelope())
    assert error.value.code == "disposed_workspace_wtp_publisher"

    await new_lease.release()
    await manager.close()


@pytest.mark.unit
async def test_detached_worker_retains_exact_generation_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_redis = MagicMock()
    first_redis.xadd = AsyncMock(return_value="old-generation-entry")
    second_redis = MagicMock()
    second_redis.xadd = AsyncMock(return_value="new-generation-entry")
    first = await _generation(generation=406, redis_client=first_redis)
    second = await _generation(generation=407, redis_client=second_redis)
    manager = GenerationManagerV2()
    await manager.publish(first)

    class _ExactHost:
        async def acquire(self) -> GenerationLeaseV2:
            return await manager.acquire()

        async def acquire_exact(
            self,
            generation: RuntimeGenerationV2,
            descriptor: PluginGenerationDescriptorV2,
        ) -> GenerationLeaseV2:
            assert generation.descriptor == descriptor
            return await manager.retain(generation)

        def distribution_for_generation(self, generation: RuntimeGenerationV2) -> object:
            return SimpleNamespace(
                to_payload=lambda: {"descriptor": generation.descriptor.to_payload()}
            )

    started = asyncio.Event()
    continue_launch = asyncio.Event()

    async def _fake_launch(**_kwargs: object) -> dict[str, object]:
        started.set()
        await continue_launch.wait()
        entry_id = await current_workspace_wtp_publisher_v2().publish(_envelope())
        return {"launched": True, "entry_id": entry_id}

    monkeypatch.setattr(worker_launch, "launch_worker_session", _fake_launch)
    host = _ExactHost()
    before = set(worker_launch._background_tasks)
    async with pin_operation_context_v2(
        host,
        operation_id="detached-worker-publisher",
        scope=_ROOT_SCOPE,
        services={OPERATION_IDENTITY_SERVICE_V2: {"user_id": "user-1"}},
    ) as operation:
        publisher = operation.require(WORKSPACE_WTP_PUBLISHER_SERVICE_V2)
        assert isinstance(publisher, WorkspaceWtpPublisherProtocolV2)
        with bind_workspace_wtp_publisher_v2(publisher):
            await worker_launch.schedule_worker_session(
                workspace_id="workspace-1",
                task=MagicMock(id="task-1"),
                worker_agent_id="worker-1",
                actor_user_id="user-1",
            )
            scheduled = tuple(set(worker_launch._background_tasks) - before)
            assert len(scheduled) == 1
            await started.wait()

    await manager.publish(second)
    continue_launch.set()
    await scheduled[0]
    await asyncio.sleep(0)

    first_redis.xadd.assert_awaited_once()
    second_redis.xadd.assert_not_awaited()
    with pytest.raises(RuntimeV2Error) as error:
        _ = await publisher.publish(_envelope())
    assert error.value.code == "disposed_workspace_wtp_publisher"

    await manager.close()
