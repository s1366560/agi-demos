"""Production host and HTTP generation-boundary tests for runtime v2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.processor.run_context import RunContext
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    PluginGenerationMiddlewareV2,
    attach_current_generation_v2,
    current_generation_v2,
    current_operation_context_v2,
    pin_operation_context_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import (
    RUNTIME_BOUNDARY_SERVICE_V2,
    RuntimeBoundaryServiceV2,
    builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.protocol import PluginProtocolV2Error
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
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
