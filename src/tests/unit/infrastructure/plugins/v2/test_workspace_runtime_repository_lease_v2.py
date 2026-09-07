"""Workspace transport persistence uses a real leased V2 provider generation."""

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    bind_operation_context_v2,
    clear_process_generation_host_v2,
    current_generation_v2,
    current_operation_context_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.protocol import PluginProtocolV2Error
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.workspace_runtime_repository_lease_v2 import (
    lease_workspace_runtime_repositories_v2,
)

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).resolve().parents[6]
_PROFILE = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_ARGS = {"tenant_id": "tenant-a", "project_id": "project-a", "conversation_id": "session-a"}


async def _publish(host, version):
    result = await host.bootstrap(
        profile_path=_PROFILE, manifest_paths=(_MANIFEST,), generation=version, version=version
    )
    assert result.accepted, result.receipt
    return host.manager.current


@pytest_asyncio.fixture(loop_scope="function")
async def authority():
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    generation = await _publish(host, 1701)
    install_process_generation_host_v2(host)
    async with AsyncSession() as db:
        try:
            yield host, generation, db
        finally:
            clear_process_generation_host_v2(host)
            await host.close()


async def test_exact_operation_and_existing_context_are_preserved(authority):
    _host, generation, db = authority
    async with OperationContextV2(
        generation=generation, operation_id="outer", scope=ScopeV2(kind=ScopeKindV2.ROOT)
    ) as outer:
        with bind_operation_context_v2(outer):
            async with lease_workspace_runtime_repositories_v2(db=db, **_ARGS) as repositories:
                operation = repositories.operation
                assert operation is not outer
                assert operation.context.scope == ScopeV2(kind=ScopeKindV2.ROOT)
                assert operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
                assert operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "session_id": "session-a",
                }
                assert current_operation_context_v2() is outer
                with pytest.raises(RuntimeV2Error) as unbound:
                    current_generation_v2()
                assert unbound.value.code == "generation_not_pinned"
                assert repositories.conversation._session is db
                assert repositories.execution_event._session is db
            assert operation.phase is FiberPhaseV2.DISPOSED
            assert current_operation_context_v2() is outer


async def test_hmr_retains_real_generation_until_repository_scope_exits(authority):
    host, generation, db = authority
    async with lease_workspace_runtime_repositories_v2(db=db, **_ARGS) as repositories:
        await _publish(host, 1702)
        assert repositories.operation.generation is generation
        assert all(fiber.phase is FiberPhaseV2.ACTIVE for fiber in generation.fibers)
    # release waits for actual retired-generation disposal; do not drive disposal in this test.
    assert all(fiber.phase is FiberPhaseV2.DISPOSED for fiber in generation.fibers)


@pytest.mark.parametrize("cancel", [False, True])
async def test_failure_and_cancellation_release_generation(authority, cancel):
    host, generation, db = authority
    entered = asyncio.Event()
    forever = asyncio.Event()
    operations = []
    failure = RuntimeError("consumer failed")

    async def consume():
        async with lease_workspace_runtime_repositories_v2(db=db, **_ARGS) as repositories:
            operations.append(repositories.operation)
            entered.set()
            await forever.wait()
            raise failure

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), 5)
    await _publish(host, 1702)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        forever.set()
        with pytest.raises(RuntimeError) as caught:
            await task
        assert caught.value is failure
    assert operations[0].phase is FiberPhaseV2.DISPOSED
    assert all(fiber.phase is FiberPhaseV2.DISPOSED for fiber in generation.fibers)


@pytest.mark.parametrize("field", tuple(_ARGS))
async def test_invalid_identity_is_rejected_before_host_lookup(field):
    async with AsyncSession() as db:
        args = {**_ARGS, field: " "}
        with pytest.raises(PluginProtocolV2Error) as caught:
            async with lease_workspace_runtime_repositories_v2(db=db, **args):
                pytest.fail("invalid identity admitted")
        assert caught.value.code == "invalid_scope"


@pytest.mark.parametrize(
    "service",
    [
        "service:persistence.conversation-repository-provider",
        "service:persistence.agent-event-query-repository-provider",
    ],
)
async def test_disabled_repository_provider_fails_closed_without_static_fallback(
    authority, service
):
    import json

    from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
    from src.tests.unit.infrastructure.plugins.v2.runtime_test_support import (
        disable_service_provider_closure_v2,
    )

    host, _generation, db = authority
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST.read_text()))
    published = await host.bootstrap(
        profile_path=_PROFILE,
        manifest_paths=(_MANIFEST,),
        generation=1702,
        version=1702,
        profile_projector=lambda document: disable_service_provider_closure_v2(
            document,
            manifest,
            missing_service=service,
            kept_consumer_module_ref="unused-test-subject",
        ),
    )
    assert published.accepted, published.receipt
    generation = host.manager.current
    with pytest.raises(RuntimeV2Error) as caught:
        async with lease_workspace_runtime_repositories_v2(db=db, **_ARGS):
            pytest.fail("disabled repository provider resolved")
    assert caught.value.code == "missing_service"
    await host.close()
    assert all(fiber.phase is FiberPhaseV2.DISPOSED for fiber in generation.fibers)
