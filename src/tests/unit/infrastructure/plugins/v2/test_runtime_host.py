"""Production host and HTTP generation-boundary tests for runtime v2."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.processor.run_context import RunContext
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2,
    PluginGenerationMiddlewareV2,
    ReservedGenerationV2,
    attach_current_generation_v2,
    clear_process_generation_host_v2,
    current_generation_v2,
    current_operation_context_v2,
    detached_operation_task_context_v2,
    fork_current_agent_operation_v2,
    install_process_generation_host_v2,
    pin_agent_turn_operation_v2,
    pin_generation_v2,
    pin_operation_context_v2,
    reserve_current_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import (
    RUNTIME_BOUNDARY_SERVICE_V2,
    RuntimeBoundaryServiceV2,
    builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.protocol import PluginProtocolV2Error
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import (
    DataPlaneGenerationAdmissionV2,
    PlatformPluginRuntimeHostV2,
)

_ROOT = Path(__file__).resolve().parents[6]


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"profile_id": "default-v2", "generation": 1, "digest": "a" * 64, "extra": 1},
        {"profile_id": "", "generation": 1, "digest": "a" * 64},
        {"profile_id": "default-v2", "generation": True, "digest": "a" * 64},
        {"profile_id": "default-v2", "generation": 0, "digest": "a" * 64},
        {"profile_id": "default-v2", "generation": 1, "digest": "A" * 64},
        {"profile_id": "default-v2", "generation": 1, "digest": "a" * 63},
    ],
)
def test_generation_descriptor_rejects_noncanonical_payload(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="plugin generation"):
        PluginGenerationDescriptorV2.from_payload(payload)


@pytest.mark.unit
def test_generation_descriptor_round_trips_canonical_payload() -> None:
    payload: dict[str, Any] = {
        "profile_id": "default-v2",
        "generation": 7,
        "digest": "a" * 64,
    }

    descriptor = PluginGenerationDescriptorV2.from_payload(payload)

    assert descriptor.to_payload() == payload


@pytest.mark.unit
async def test_host_bootstraps_strict_profile_and_exposes_generation_lease() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="bootstrap-1",
    )

    assert publication.accepted
    async with await host.acquire() as generation:
        boundary = generation.resolve(
            RUNTIME_BOUNDARY_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
        assert isinstance(boundary, RuntimeBoundaryServiceV2)
        assert generation.snapshot.profile_id == "memstack-default-v2"
    await host.close()


@pytest.mark.unit
async def test_host_bootstrap_projects_profile_before_generation_one_composition() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        profile_projector=lambda document: replace(document, profile_id="projected-default-v2"),
    )

    assert publication.accepted
    assert publication.snapshot.profile_id == "projected-default-v2"
    assert publication.snapshot.generation == 1
    await host.close()


@pytest.mark.unit
async def test_host_resolves_distribution_for_a_pinned_retired_generation() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="distribution-1",
    )
    first = host.current_distribution
    assert first is not None

    async with pin_operation_context_v2(
        host,
        operation_id="old-turn",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ) as operation:
        await host.bootstrap(
            profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
            manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
            generation=2,
            version=2,
            nonce="distribution-2",
        )
        second = host.current_distribution
        assert second is not None

        assert host.distribution_for_generation(operation.generation) == first
        assert second.descriptor.generation == 2

    await host.close()


@pytest.mark.unit
async def test_remote_host_validates_complete_distribution_before_publish() -> None:
    source = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await source.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=4,
        nonce="distribution-4",
    )
    distribution = source.current_distribution
    assert distribution is not None
    target = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    publication = await target.apply_distribution(distribution.to_payload())

    assert publication.accepted
    assert target.current_distribution == distribution

    mismatched = distribution.to_payload()
    mismatched["descriptor"] = {**mismatched["descriptor"], "generation": 2}
    with pytest.raises(ValueError, match="does not match snapshot"):
        await target.apply_distribution(mismatched)
    assert target.manager.current is not None
    assert target.manager.current.descriptor == distribution.descriptor

    incompatible = distribution.to_payload()
    incompatible["snapshot"] = {"schema_version": 1, "plugins": []}
    with pytest.raises(PluginProtocolV2Error) as error:
        await target.apply_distribution(incompatible)
    assert error.value.code == "incompatible_schema_version"
    assert target.manager.current is not None
    assert target.manager.current.descriptor == distribution.descriptor

    await target.close()
    await source.close()


@pytest.mark.unit
async def test_remote_admission_rejects_retired_descriptor_without_distribution() -> None:
    admission = DataPlaneGenerationAdmissionV2(builtin_runtime_definitions_v2())
    descriptor = {
        "profile_id": "default-v2",
        "generation": 7,
        "digest": "a" * 64,
    }

    with pytest.raises(RuntimeV2Error) as error:
        async with admission.admit(
            descriptor_payload=descriptor,
            distribution_payload=None,
            operation_id="hitl-resume:request-a",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            pass

    assert error.value.code == "generation_payload_required"
    await admission.close()


@pytest.mark.unit
async def test_remote_admission_rejects_missing_generation_descriptor() -> None:
    admission = DataPlaneGenerationAdmissionV2(builtin_runtime_definitions_v2())

    with pytest.raises(RuntimeV2Error) as error:
        async with admission.admit(
            descriptor_payload=None,
            distribution_payload=None,
            operation_id="ray-turn:message-a",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            pass

    assert error.value.code == "generation_descriptor_missing"
    await admission.close()


@pytest.mark.unit
async def test_remote_admission_requires_descriptor_for_an_active_generation() -> None:
    admission = DataPlaneGenerationAdmissionV2(builtin_runtime_definitions_v2())
    await admission.host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="active-generation",
    )

    with pytest.raises(RuntimeV2Error) as error:
        async with admission.admit(
            descriptor_payload=None,
            distribution_payload=None,
            operation_id="ray-turn:message-a",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            pass

    assert error.value.code == "generation_descriptor_missing"
    await admission.close()


@pytest.mark.unit
async def test_host_rejects_v1_manifest_without_publishing(tmp_path: Path) -> None:
    manifest = json.loads(
        (_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json").read_text()
    )
    manifest["schema_version"] = 1
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    with pytest.raises(ValueError, match="schema_version must be 2"):
        await host.bootstrap(
            profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
            manifest_paths=(manifest_path,),
            generation=1,
            version=1,
        )

    assert host.manager.current is None


@pytest.mark.unit
async def test_http_middleware_pins_one_generation_until_response_finishes() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    observed: list[tuple[int, int]] = []

    async def app(scope, _receive, send) -> None:
        pinned = current_generation_v2()
        observed.append((pinned.generation, scope["state"]["plugin_generation_v2"].generation))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = PluginGenerationMiddlewareV2(app, host_provider=lambda _scope: host)
    messages: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    await middleware(
        {"type": "http", "method": "GET", "path": "/health", "state": {}},
        receive,
        send,
    )

    assert observed == [(1, 1)]
    assert messages[-1]["body"] == b"ok"
    with pytest.raises(RuntimeError, match="not pinned"):
        current_generation_v2()
    await host.close()


@pytest.mark.unit
async def test_operation_boundary_pins_old_generation_until_cleanup_finishes() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    scope = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a")

    async with pin_operation_context_v2(
        host,
        operation_id="turn-a",
        scope=scope,
        services={OPERATION_DB_SESSION_SERVICE_V2: "db-a"},
    ) as operation:
        await host.bootstrap(
            profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
            manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
            generation=2,
            version=2,
            nonce="generation-2",
        )
        assert operation.descriptor.generation == 1
        assert current_operation_context_v2() is operation
        assert operation.require(OPERATION_DB_SESSION_SERVICE_V2) == "db-a"
        run_context = RunContext()
        attach_current_generation_v2(run_context)
        assert run_context.plugin_generation == operation.descriptor
        mismatched_context = RunContext(
            plugin_generation=PluginGenerationDescriptorV2(
                profile_id="memstack-default-v2",
                generation=2,
                digest="b" * 64,
            )
        )
        with pytest.raises(RuntimeError, match="does not match the pinned operation"):
            attach_current_generation_v2(mismatched_context)
        assert host.manager.current is not None
        assert host.manager.current.generation == 2
        assert isinstance(
            operation.generation.resolve(
                RUNTIME_BOUNDARY_SERVICE_V2, ScopeV2(kind=ScopeKindV2.ROOT)
            ),
            RuntimeBoundaryServiceV2,
        )

    with pytest.raises(RuntimeError, match="generation is disposed"):
        operation.generation.resolve(
            RUNTIME_BOUNDARY_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
    await host.close()


@pytest.mark.unit
async def test_operation_boundary_resets_context_when_dispose_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="cancelled-operation-boundary",
    )
    original_dispose = OperationContextV2.dispose

    async def dispose_then_cancel(operation: OperationContextV2) -> None:
        await original_dispose(operation)
        raise asyncio.CancelledError

    monkeypatch.setattr(OperationContextV2, "dispose", dispose_then_cancel)

    async def exercise_boundary() -> bool:
        with pytest.raises(asyncio.CancelledError):
            async with pin_operation_context_v2(
                host,
                operation_id="cancelled-operation",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ):
                pass
        try:
            current_operation_context_v2()
        except RuntimeV2Error as exc:
            return exc.code == "operation_context_not_pinned"
        return False

    try:
        assert await asyncio.create_task(exercise_boundary()) is True
    finally:
        await host.close()


@pytest.mark.unit
async def test_copied_task_rejects_the_parent_operation_after_dispose() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="disposed-copied-operation",
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def copied_task() -> str:
        entered.set()
        await release.wait()
        try:
            current_operation_context_v2()
        except RuntimeV2Error as exc:
            return exc.code
        return "unexpected-active-operation"

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="parent-operation",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ):
            task = asyncio.create_task(copied_task())
            await entered.wait()

        release.set()
        assert await task == "operation_context_not_pinned"
    finally:
        release.set()
        await host.close()


@pytest.mark.unit
async def test_agent_turn_boundary_acquires_process_host_and_publishes_operation_services() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="agent-turn-boundary",
    )
    install_process_generation_host_v2(host)

    try:
        async with pin_agent_turn_operation_v2(
            operation_id="agent-turn:message-a",
            tenant_id="tenant-a",
            project_id="project-a",
            session_id="conversation-a",
            services={OPERATION_DB_SESSION_SERVICE_V2: "db-a"},
        ) as operation:
            assert operation.context.scope == ScopeV2(
                kind=ScopeKindV2.SESSION,
                tenant_id="tenant-a",
                project_id="project-a",
                session_id="conversation-a",
            )
            assert current_operation_context_v2() is operation
            assert operation.require(OPERATION_DB_SESSION_SERVICE_V2) == "db-a"
            assert operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
            }
            assert operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "agent-turn",
                "conversation_id": "conversation-a",
            }
            distribution = operation.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2)
            assert distribution["descriptor"] == operation.descriptor.to_payload()
    finally:
        clear_process_generation_host_v2(host)
        await host.close()


@pytest.mark.unit
async def test_forked_agent_operation_keeps_exact_generation_and_safe_services() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="forked-agent-generation-1",
    )
    install_process_generation_host_v2(host)
    parent_generation = None

    try:
        async with pin_agent_turn_operation_v2(
            operation_id="agent-turn:parent",
            tenant_id="tenant-a",
            project_id="project-a",
            session_id="conversation-a",
            services={
                OPERATION_DB_SESSION_SERVICE_V2: "db-parent",
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": "tenant-a",
                    "user_id": "user-a",
                },
            },
        ) as parent:
            parent_generation = parent.generation
            fork = await fork_current_agent_operation_v2()
            await host.bootstrap(
                profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
                manifest_paths=(
                    _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",
                ),
                generation=2,
                version=2,
                nonce="forked-agent-generation-2",
            )

        async with fork.admit(
            operation_id="detached-subagent:run-a",
            metadata={"kind": "detached-subagent", "run_id": "run-a"},
            services={OPERATION_DB_SESSION_SERVICE_V2: "db-child"},
        ) as child:
            assert child.generation is parent_generation
            assert child.descriptor.generation == 1
            assert child.require(OPERATION_DB_SESSION_SERVICE_V2) == "db-child"
            assert child.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert child.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "detached-subagent",
                "run_id": "run-a",
                "parent_operation_id": "agent-turn:parent",
            }
            distribution = child.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2)
            assert distribution["descriptor"] == child.descriptor.to_payload()
            assert host.manager.current is not None
            assert host.manager.current.generation == 2

        assert parent_generation is not None
        with pytest.raises(RuntimeV2Error) as disposed_error:
            parent_generation.resolve(
                RUNTIME_BOUNDARY_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
        assert disposed_error.value.code == "disposed_generation"
    finally:
        clear_process_generation_host_v2(host)
        await host.close()


@pytest.mark.unit
async def test_reserved_generation_keeps_exact_generation_for_detached_boundary() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="reserved-generation-1",
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    first_generation = None

    async def detached_boundary(reservation: ReservedGenerationV2) -> int:
        with pytest.raises(RuntimeV2Error) as inherited_error:
            current_generation_v2()
        assert inherited_error.value.code == "generation_not_pinned"
        async with reservation.admit() as generation:
            entered.set()
            await release.wait()
            assert current_generation_v2() is generation
            return generation.descriptor.generation

    try:
        async with pin_generation_v2(host) as parent_generation:
            first_generation = parent_generation
            reservation = await reserve_current_generation_v2()
            task = asyncio.create_task(
                detached_boundary(reservation),
                context=detached_operation_task_context_v2(),
            )
            await entered.wait()
            await host.bootstrap(
                profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
                manifest_paths=(
                    _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",
                ),
                generation=2,
                version=2,
                nonce="reserved-generation-2",
            )

        assert first_generation is not None
        assert isinstance(
            first_generation.resolve(
                RUNTIME_BOUNDARY_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            ),
            RuntimeBoundaryServiceV2,
        )
        release.set()
        assert await task == 1
        with pytest.raises(RuntimeV2Error) as disposed_error:
            first_generation.resolve(
                RUNTIME_BOUNDARY_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
        assert disposed_error.value.code == "disposed_generation"
    finally:
        release.set()
        await host.close()


@pytest.mark.unit
async def test_agent_turn_boundary_resets_context_when_dispose_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="cancelled-agent-turn-boundary",
    )
    install_process_generation_host_v2(host)
    original_dispose = OperationContextV2.dispose

    async def dispose_then_cancel(operation: OperationContextV2) -> None:
        await original_dispose(operation)
        raise asyncio.CancelledError

    monkeypatch.setattr(OperationContextV2, "dispose", dispose_then_cancel)

    async def exercise_boundary() -> bool:
        with pytest.raises(asyncio.CancelledError):
            async with pin_agent_turn_operation_v2(
                operation_id="cancelled-agent-turn",
                tenant_id="tenant-a",
                project_id="project-a",
                session_id="conversation-a",
            ):
                pass
        try:
            current_operation_context_v2()
        except RuntimeV2Error as exc:
            return exc.code == "operation_context_not_pinned"
        return False

    try:
        assert await asyncio.create_task(exercise_boundary()) is True
    finally:
        clear_process_generation_host_v2(host)
        await host.close()


@pytest.mark.unit
async def test_agent_turn_boundary_fails_closed_without_process_host() -> None:
    with pytest.raises(RuntimeV2Error) as error:
        async with pin_agent_turn_operation_v2(
            operation_id="agent-turn:message-a",
            tenant_id="tenant-a",
            project_id="project-a",
            session_id="conversation-a",
        ):
            pass

    assert error.value.code == "process_generation_host_not_configured"


@pytest.mark.unit
async def test_agent_turn_boundary_keeps_outer_generation_when_host_advances() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="outer-generation-1",
    )
    install_process_generation_host_v2(host)

    try:
        async with pin_generation_v2(host) as outer_generation:
            await host.bootstrap(
                profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
                manifest_paths=(
                    _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",
                ),
                generation=2,
                version=2,
                nonce="outer-generation-2",
            )
            async with pin_agent_turn_operation_v2(
                operation_id="agent-turn:message-a",
                tenant_id="tenant-a",
                project_id="project-a",
                session_id="conversation-a",
            ) as operation:
                distribution = operation.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2)
                assert operation.generation is outer_generation
                assert operation.descriptor.generation == 1
                assert distribution["descriptor"] == operation.descriptor.to_payload()
                assert host.manager.current is not None
                assert host.manager.current.generation == 2
    finally:
        clear_process_generation_host_v2(host)
        await host.close()


@pytest.mark.unit
async def test_agent_turn_boundary_can_force_an_independent_process_host_lease() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="copied-http-generation-1",
    )
    install_process_generation_host_v2(host)

    try:
        async with pin_generation_v2(host) as copied_http_generation:
            await host.bootstrap(
                profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
                manifest_paths=(
                    _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",
                ),
                generation=2,
                version=2,
                nonce="background-generation-2",
            )
            async with pin_agent_turn_operation_v2(
                operation_id="approved-plan:run-a",
                tenant_id="tenant-a",
                project_id="project-a",
                session_id="conversation-a",
                force_process_host_lease=True,
            ) as operation:
                distribution = operation.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2)
                assert operation.generation is not copied_http_generation
                assert operation.descriptor.generation == 2
                assert distribution["descriptor"] == operation.descriptor.to_payload()
    finally:
        clear_process_generation_host_v2(host)
        await host.close()


@pytest.mark.unit
async def test_non_http_scope_bypasses_generation_lease() -> None:
    called = False

    async def app(_scope, _receive, _send) -> None:
        nonlocal called
        called = True

    middleware = PluginGenerationMiddlewareV2(
        app,
        host_provider=lambda _scope: pytest.fail("host must not be resolved"),
    )
    await middleware({"type": "lifespan"}, None, None)

    assert called
