"""Production scoped factory resource ownership with actual Loader generations."""

import json
from dataclasses import replace

import pytest

from src.infrastructure.plugins.v2 import scoped_builtin_runtime
from src.infrastructure.plugins.v2.graph_runtime import (
    GRAPH_RUNTIME_MODULE_V2,
    GRAPH_RUNTIME_SERVICE_V2,
)
from src.infrastructure.plugins.v2.protocol import (
    build_profile_snapshot_v2,
    control_envelope_v2,
    parse_plugin_manifest_v2,
)
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.sandbox_runtime import (
    SANDBOX_RUNTIME_SERVICE_V2,
    sandbox_runtime_definition_v2,
)
from src.infrastructure.plugins.v2.scoped_builtin_runtime import leased_sandbox_definition_v2
from src.infrastructure.plugins.v2.scoped_runtime_registry import ScopedRuntimeRegistryV2
from src.tests.unit.infrastructure.plugins.v2.test_graph_runtime import _MANIFEST_PATH
from src.tests.unit.infrastructure.plugins.v2.test_runtime import _catalog
from src.tests.unit.infrastructure.plugins.v2.test_sandbox_runtime_borrowed_v2 import (
    ROOT,
    _runtime,
    _snapshot,
)
from src.tests.unit.infrastructure.plugins.v2.test_scoped_runtime_registry import _scope

pytestmark = pytest.mark.unit


async def test_scoped_sandbox_retains_owner_until_last_scoped_operation_drains():
    runtime = _runtime()
    snapshot = _snapshot(required=True)
    borrowed = sandbox_runtime_definition_v2(projected_runtime=runtime)

    async def owner_apply(context, config):
        await borrowed.apply(context, config)
        return runtime.require().adapter.close

    owner = PlatformPluginRuntimeHostV2(
        loader=LoaderV2((replace(borrowed, apply=owner_apply),), target_catalog=_catalog(snapshot))
    )
    assert (await owner.apply(snapshot, control_envelope_v2(snapshot, version=1))).accepted
    scopes = []

    def factory(scope):
        scopes.append(scope)
        return (leased_sandbox_definition_v2(owner),)

    registry = ScopedRuntimeRegistryV2(
        definitions_factory=factory, target_catalog=_catalog(snapshot)
    )
    a, b = _scope("a"), _scope("b")
    try:
        for scope in (a, b):
            assert (
                await registry.publish(scope, snapshot, control_envelope_v2(snapshot, version=1))
            ).accepted
        assert scopes == [a, b]
        lease = await registry.acquire(b)
        await owner.close()
        await registry.close_scope(a)
        await registry.close_scope(b)
        assert runtime.require().adapter.actions == []
        assert lease.generation.resolve(SANDBOX_RUNTIME_SERVICE_V2, ROOT) is runtime
        await lease.release()
        assert runtime.require().adapter.actions == ["close"]
    finally:
        await registry.close()
        await owner.close()


async def test_invalid_scoped_sandbox_candidate_releases_owner_lease():
    runtime = _runtime()
    snapshot = _snapshot(required=True)
    borrowed = sandbox_runtime_definition_v2(projected_runtime=runtime)

    async def owner_apply(context, config):
        context.provide(SANDBOX_RUNTIME_SERVICE_V2, object())
        return runtime.require().adapter.close

    owner = PlatformPluginRuntimeHostV2(
        loader=LoaderV2((replace(borrowed, apply=owner_apply),), target_catalog=_catalog(snapshot))
    )
    await owner.apply(snapshot, control_envelope_v2(snapshot, version=1))
    try:
        with pytest.raises(RuntimeV2Error, match="invalid Sandbox runtime"):
            await LoaderV2(
                (leased_sandbox_definition_v2(owner),), target_catalog=_catalog(snapshot)
            ).stage(snapshot)
    finally:
        await owner.close()
    assert runtime.require().adapter.actions == ["close"]


def test_builtin_factory_binds_explicit_tenant_and_borrows_process_redis(monkeypatch):
    tenants, calls = [], []

    def graph_factory(tenant):
        tenants.append(tenant)
        return tenant

    def definitions(**kwargs):
        calls.append(kwargs)
        return (sandbox_runtime_definition_v2(),)

    monkeypatch.setattr(
        scoped_builtin_runtime, "agent_worker_graph_runtime_factory_v2", graph_factory
    )
    monkeypatch.setattr(scoped_builtin_runtime, "builtin_runtime_definitions_v2", definitions)
    redis = object()
    for tenant in ("a", "b"):
        result = scoped_builtin_runtime.scoped_builtin_runtime_definitions_v2(
            _scope(tenant), sandbox_owner_host=object(), redis_client=redis
        )
        assert len(result) == 1
    assert tenants == ["a", "b"]
    assert [call["graph_runtime_factory"] for call in calls] == tenants
    assert all(call["sandbox_redis_client"] is redis for call in calls)
    with pytest.raises(RuntimeV2Error, match="tenant"):
        scoped_builtin_runtime.scoped_builtin_runtime_definitions_v2(
            ROOT, sandbox_owner_host=object(), redis_client=redis
        )


def test_registry_rejects_mixed_definition_sources():
    with pytest.raises(ValueError, match="either"):
        ScopedRuntimeRegistryV2(
            (sandbox_runtime_definition_v2(),), definitions_factory=lambda _scope: ()
        )


async def test_real_builtin_definitions_allocate_distinct_tenant_graph_resources(monkeypatch):
    graphs = {}

    class Graph:
        closed = False

        async def close(self):
            self.closed = True

    def graph_factory(tenant):
        async def create():
            graph = Graph()
            graphs[tenant] = graph
            return graph

        return create

    monkeypatch.setattr(
        scoped_builtin_runtime, "agent_worker_graph_runtime_factory_v2", graph_factory
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text()))
    manifest = replace(
        manifest,
        modules=tuple(m for m in manifest.modules if m.module_ref == GRAPH_RUNTIME_MODULE_V2),
    )
    entry = replace(
        _snapshot().entries[0],
        entry_id="graph",
        module_ref=GRAPH_RUNTIME_MODULE_V2,
        config={"strategy": "native-adapter", "required": True},
    )
    snapshot = build_profile_snapshot_v2(
        profile_id="scoped-graph", generation=1, manifests=(manifest,), entries=(entry,)
    )
    registry = ScopedRuntimeRegistryV2(
        definitions_factory=lambda scope: scoped_builtin_runtime.scoped_builtin_runtime_definitions_v2(
            scope, sandbox_owner_host=object(), redis_client=None
        ),
        target_catalog=_catalog(snapshot),
    )
    try:
        for tenant in ("a", "b"):
            assert (
                await registry.publish(
                    _scope(tenant), snapshot, control_envelope_v2(snapshot, version=1)
                )
            ).accepted
        assert graphs["a"] is not graphs["b"]
        await registry.close_scope(_scope("a"))
        assert graphs["a"].closed
        assert not graphs["b"].closed
        async with await registry.acquire(_scope("b")) as generation:
            assert generation.resolve(GRAPH_RUNTIME_SERVICE_V2, ROOT).graph_service is graphs["b"]
    finally:
        await registry.close()
    assert graphs["b"].closed
