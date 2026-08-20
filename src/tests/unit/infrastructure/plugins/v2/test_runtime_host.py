"""Production host and HTTP generation-boundary tests for runtime v2."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import (
    PluginGenerationMiddlewareV2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import (
    RUNTIME_BOUNDARY_SERVICE_V2,
    RuntimeBoundaryServiceV2,
    builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]


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
