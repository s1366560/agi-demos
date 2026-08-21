"""Lifecycle and generation tests for the v2 plugin runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from typing import Any

import pytest

from src.domain.model.plugins.generated_v2 import (
    ArtifactReferenceV2,
    DataPlaneTargetV2,
    EventContractsV2,
    EventContractV2,
    EventModeV2,
    PluginContractV2,
    PluginManifestV2,
    PluginModuleV2,
    ProfileEntryV2,
    QuotaV2,
    RestartPolicyV2,
    RuntimeKindV2,
    ScopeKindV2,
    ScopeV2,
    ServiceContractV2,
    ServiceProvidedV2,
    ServiceRequiredV2,
    TrustKindV2,
)
from src.infrastructure.plugins.v2.http_routes import RouteDefinitionV2, RouteTableBuilderV2
from src.infrastructure.plugins.v2.protocol import (
    build_profile_snapshot_v2,
    plugin_contract_digest_v2,
)
from src.infrastructure.plugins.v2.route_effects import (
    ROUTE_TABLE_BUILDER_SERVICE_V2,
    route_contribution_definition_v2,
    route_table_builder_definition_v2,
)
from src.infrastructure.plugins.v2.runtime import (
    FiberPhaseV2,
    GenerationManagerV2,
    LoaderV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
)
from src.tests.unit.infrastructure.plugins.v2.runtime_test_support import (
    RUNTIME_TEST_ARTIFACT_DIGEST_V2,
    RuntimeTestArtifactResolverV2,
    target_catalog_from_snapshot_v2,
)

_ARTIFACT_DIGEST = RUNTIME_TEST_ARTIFACT_DIGEST_V2


def _scope(
    kind: ScopeKindV2,
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
) -> ScopeV2:
    return ScopeV2(
        kind=kind,
        tenant_id=tenant_id,
        project_id=project_id,
        session_id=session_id,
    )


def _entry(
    entry_id: str,
    module_ref: str,
    *,
    parent_entry_id: str | None = None,
    scope: ScopeV2 | None = None,
    inject: Mapping[str, str] | None = None,
    isolate: Mapping[str, str] | None = None,
    enabled: bool = True,
) -> ProfileEntryV2:
    return ProfileEntryV2(
        entry_id=entry_id,
        parent_entry_id=parent_entry_id,
        plugin_ref="runtime-tests",
        module_ref=module_ref,
        enabled=enabled,
        config={},
        inject=dict(inject or {}),
        isolate=dict(isolate or {}),
        scope=scope or _scope(ScopeKindV2.ROOT),
        permissions=(),
        quotas=QuotaV2(),
        restart_policy=RestartPolicyV2.HOT_GENERATION,
    )


def _event(event: str, mode: EventModeV2) -> EventContractV2:
    if event == "transform":
        payload_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "integer",
        }
        result_schema = payload_schema
    else:
        payload_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": ["object", "null"],
        }
        result_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": ["string", "null"],
        }
    return EventContractV2(
        event=event,
        mode=mode,
        payload_schema=payload_schema,
        result_schema=result_schema,
    )


def _snapshot(
    generation: int,
    entries: tuple[ProfileEntryV2, ...],
    *,
    provides: Mapping[str, tuple[str, ...]] | None = None,
    events: Mapping[str, tuple[EventContractV2, ...]] | None = None,
):
    provided = provides or {}
    declared_events = events or {}
    modules = tuple(
        _module(
            entry, provided.get(entry.module_ref, ()), declared_events.get(entry.module_ref, ())
        )
        for entry in entries
    )
    manifest = PluginManifestV2(
        schema_version=2,
        plugin_id="runtime-tests",
        version="1.0.0",
        runtime=RuntimeKindV2.PYTHON_TRUSTED,
        trust=TrustKindV2.BUILTIN,
        modules=modules,
        permissions=(),
        quotas=QuotaV2(),
    )
    return build_profile_snapshot_v2(
        profile_id="runtime-v2-tests",
        generation=generation,
        manifests=(manifest,),
        entries=entries,
    )


def _module(
    entry: ProfileEntryV2,
    provides: tuple[str, ...],
    events: tuple[EventContractV2, ...],
) -> PluginModuleV2:
    contract = PluginContractV2(
        services=ServiceContractV2(
            provides=tuple(
                ServiceProvidedV2(service=service, version="1.0.0") for service in provides
            ),
            requires=tuple(
                ServiceRequiredV2(alias=alias, service=service, version="1.0.0")
                for alias, service in entry.inject.items()
            ),
        ),
        events=EventContractsV2(emits=events, handles=events),
        config_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
        },
    )
    return PluginModuleV2(
        module_ref=entry.module_ref,
        entrypoint="tests:apply",
        artifact=ArtifactReferenceV2(
            digest=_ARTIFACT_DIGEST,
            source=f"package://builtin/{entry.entry_id}",
        ),
        targets=(DataPlaneTargetV2.PYTHON,),
        contract=contract,
        contract_digest=plugin_contract_digest_v2(contract),
    )


def _catalog(snapshot):
    return target_catalog_from_snapshot_v2(snapshot)


def _definition(snapshot, module_ref: str, apply) -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=module_ref,
        contract_digest=_digest(snapshot, module_ref),
        apply=apply,
    )


def _digest(snapshot, module_ref: str) -> str:
    module = next(
        module
        for manifest in snapshot.manifests
        for module in manifest.modules
        if module.module_ref == module_ref
    )
    return module.contract_digest


def _loader(snapshot, definitions) -> LoaderV2:
    return LoaderV2(
        definitions,
        target_catalog=_catalog(snapshot),
        artifact_resolver=RuntimeTestArtifactResolverV2(),
    )


@pytest.mark.unit
async def test_fiber_tracks_sync_async_and_iterable_effects_in_lifo_order() -> None:
    disposed: list[str] = []

    async def apply(context, _config):
        context.provide("service:value", 42, label="provider")

        async def async_dispose() -> None:
            disposed.append("async")

        def sync_dispose() -> None:
            disposed.append("sync")

        async def effects() -> AsyncIterator[Any]:
            yield sync_dispose
            yield async_dispose

        await context.effect(effects, label="iterable")
        return lambda: disposed.append("apply")

    entry = _entry("root", "builtin://runtime/root")
    snapshot = _snapshot(
        1,
        (entry,),
        provides={entry.module_ref: ("service:value",)},
    )
    loader = _loader(snapshot, [_definition(snapshot, entry.module_ref, apply)])
    generation = await loader.stage(snapshot)

    assert generation.fibers[0].phase == FiberPhaseV2.ACTIVE
    await generation.dispose()

    assert disposed == ["apply", "async", "sync"]
    assert generation.fibers[0].phase == FiberPhaseV2.DISPOSED


@pytest.mark.unit
async def test_failed_activation_rolls_back_all_contributions() -> None:
    disposed: list[str] = []

    def provider(context, _config):
        context.provide("service:value", "visible")
        return lambda: disposed.append("provider")

    def failing(_context, _config):
        raise ValueError("boom")

    provider_entry = _entry("provider", "builtin://runtime/provider")
    failing_entry = _entry(
        "consumer",
        "builtin://runtime/failing",
        inject={"value": "service:value"},
    )
    snapshot = _snapshot(
        1,
        (provider_entry, failing_entry),
        provides={provider_entry.module_ref: ("service:value",)},
    )
    loader = _loader(
        snapshot,
        [
            _definition(snapshot, provider_entry.module_ref, provider),
            _definition(snapshot, failing_entry.module_ref, failing),
        ],
    )

    with pytest.raises(ValueError, match="boom"):
        await loader.stage(snapshot)

    assert disposed == ["provider"]


@pytest.mark.unit
async def test_loader_activates_only_entries_for_its_data_plane_target() -> None:
    python_entry = _entry("python", "builtin://runtime/python")
    web_entry = _entry("web", "builtin://runtime/web")
    snapshot = _snapshot(1, (python_entry, web_entry))
    snapshot = replace(
        snapshot,
        manifests=(
            replace(
                snapshot.manifests[0],
                modules=(
                    snapshot.manifests[0].modules[0],
                    replace(
                        snapshot.manifests[0].modules[1],
                        targets=(DataPlaneTargetV2.WEB,),
                    ),
                ),
            ),
        ),
    )
    activated: list[str] = []

    loader = _loader(
        snapshot,
        [
            _definition(
                snapshot,
                python_entry.module_ref,
                lambda _context, _config: activated.append("python"),
            )
        ],
    )
    generation = await loader.stage(snapshot)

    assert activated == ["python"]
    assert [fiber.entry.entry_id for fiber in generation.fibers] == ["python"]


@pytest.mark.unit
async def test_inactive_fiber_rejects_new_effects() -> None:
    captured: dict[str, Any] = {}

    def apply(context, _config):
        captured["context"] = context

    entry = _entry("root", "builtin://runtime/root")
    snapshot = _snapshot(1, (entry,))
    generation = await _loader(
        snapshot,
        [_definition(snapshot, entry.module_ref, apply)],
    ).stage(snapshot)
    await generation.dispose()

    with pytest.raises(RuntimeV2Error) as error:
        captured["context"].provide("service:late", object())

    assert error.value.code == "inactive_effect"


@pytest.mark.unit
async def test_route_contribution_effect_freezes_and_unloads_with_its_fiber() -> None:
    builder = RouteTableBuilderV2()
    provider_entry = _entry("route-builder", "builtin://runtime/route-builder")
    contributor_entry = _entry(
        "route-contributor",
        "builtin://runtime/route-contributor",
        inject={"route_table": ROUTE_TABLE_BUILDER_SERVICE_V2},
    )
    route = RouteDefinitionV2(
        owner_entry_id=contributor_entry.entry_id,
        path="/api/v2/contributed",
        methods=("GET",),
        endpoint=lambda: {"ok": True},
        name="contributed-route",
    )
    snapshot = _snapshot(
        1,
        (provider_entry, contributor_entry),
        provides={provider_entry.module_ref: (ROUTE_TABLE_BUILDER_SERVICE_V2,)},
    )
    generation = await _loader(
        snapshot,
        (
            route_table_builder_definition_v2(
                module_ref=provider_entry.module_ref,
                builder=builder,
                contract_digest=_digest(snapshot, provider_entry.module_ref),
            ),
            route_contribution_definition_v2(
                module_ref=contributor_entry.module_ref,
                routes=(route,),
                contract_digest=_digest(snapshot, contributor_entry.module_ref),
            ),
        ),
    ).stage(snapshot)

    assert (
        generation.resolve(
            ROUTE_TABLE_BUILDER_SERVICE_V2,
            _scope(ScopeKindV2.ROOT),
        )
        is builder
    )
    assert builder.definitions == (route,)
    frozen = builder.freeze()
    with pytest.raises(RuntimeV2Error) as error:
        builder.contribute(
            replace(route, path="/api/v2/late", name="late-route"),
        )
    assert error.value.code == "route_table_frozen"

    await generation.dispose()

    assert builder.definitions == ()
    assert frozen.definitions == (route,)


@pytest.mark.unit
async def test_route_contribution_conflict_rolls_back_staged_effects() -> None:
    builder = RouteTableBuilderV2()
    provider_entry = _entry("route-builder", "builtin://runtime/route-builder")
    first_entry = _entry(
        "first-route",
        "builtin://runtime/first-route",
        inject={"route_table": ROUTE_TABLE_BUILDER_SERVICE_V2},
    )
    second_entry = _entry(
        "second-route",
        "builtin://runtime/second-route",
        inject={"route_table": ROUTE_TABLE_BUILDER_SERVICE_V2},
    )
    first_route = RouteDefinitionV2(
        owner_entry_id=first_entry.entry_id,
        path="/api/v2/conflict",
        methods=("GET",),
        endpoint=lambda: {"owner": "first"},
        name="first-route",
    )
    second_route = replace(
        first_route,
        owner_entry_id=second_entry.entry_id,
        endpoint=lambda: {"owner": "second"},
        name="second-route",
    )

    snapshot = _snapshot(
        1,
        (provider_entry, first_entry, second_entry),
        provides={provider_entry.module_ref: (ROUTE_TABLE_BUILDER_SERVICE_V2,)},
    )
    with pytest.raises(RuntimeV2Error) as error:
        await _loader(
            snapshot,
            (
                route_table_builder_definition_v2(
                    module_ref=provider_entry.module_ref,
                    builder=builder,
                    contract_digest=_digest(snapshot, provider_entry.module_ref),
                ),
                route_contribution_definition_v2(
                    module_ref=first_entry.module_ref,
                    routes=(first_route,),
                    contract_digest=_digest(snapshot, first_entry.module_ref),
                ),
                route_contribution_definition_v2(
                    module_ref=second_entry.module_ref,
                    routes=(second_route,),
                    contract_digest=_digest(snapshot, second_entry.module_ref),
                ),
            ),
        ).stage(snapshot)

    assert error.value.code == "route_conflict"
    assert builder.definitions == ()


@pytest.mark.unit
async def test_nearest_scope_provider_wins_for_explicit_inject() -> None:
    observed: list[str] = []
    tenant_scope = _scope(ScopeKindV2.TENANT, tenant_id="tenant-a")
    session_scope = _scope(
        ScopeKindV2.SESSION,
        tenant_id="tenant-a",
        project_id="project-a",
        session_id="session-a",
    )

    def root_provider(context, _config):
        context.provide("service:value", "root")

    def tenant_provider(context, _config):
        context.provide("service:value", "tenant")

    def consumer(context, _config):
        observed.append(context.require("value"))

    entries = (
        _entry("root-provider", "builtin://runtime/root-provider"),
        _entry("tenant-provider", "builtin://runtime/tenant-provider", scope=tenant_scope),
        _entry(
            "consumer",
            "builtin://runtime/consumer",
            scope=session_scope,
            inject={"value": "service:value"},
        ),
    )
    snapshot = _snapshot(
        1,
        entries,
        provides={
            entries[0].module_ref: ("service:value",),
            entries[1].module_ref: ("service:value",),
        },
    )
    definitions = (
        _definition(snapshot, entries[0].module_ref, root_provider),
        _definition(snapshot, entries[1].module_ref, tenant_provider),
        _definition(snapshot, entries[2].module_ref, consumer),
    )

    generation = await _loader(snapshot, definitions).stage(snapshot)

    assert observed == ["tenant"]
    assert generation.resolve("service:value", session_scope) == "tenant"


@pytest.mark.unit
async def test_undeclared_inject_is_rejected() -> None:
    def apply(context, _config):
        context.require("secret")

    entry = _entry("root", "builtin://runtime/root")
    snapshot = _snapshot(1, (entry,))

    with pytest.raises(RuntimeV2Error) as error:
        await _loader(
            snapshot,
            [_definition(snapshot, entry.module_ref, apply)],
        ).stage(snapshot)

    assert error.value.code == "undeclared_require"


@pytest.mark.unit
async def test_isolation_domain_must_match_provider() -> None:
    def provider(context, _config):
        context.provide("service:value", "isolated")

    def consumer(context, _config):
        context.require("value")

    provider_entry = _entry(
        "provider",
        "builtin://runtime/provider",
        isolate={"service:value": "domain-a"},
    )
    consumer_entry = _entry(
        "consumer",
        "builtin://runtime/consumer",
        inject={"value": "service:value"},
        isolate={"service:value": "domain-b"},
    )

    snapshot = _snapshot(
        1,
        (provider_entry, consumer_entry),
        provides={provider_entry.module_ref: ("service:value",)},
    )
    with pytest.raises(RuntimeV2Error) as error:
        await _loader(
            snapshot,
            [
                _definition(snapshot, provider_entry.module_ref, provider),
                _definition(snapshot, consumer_entry.module_ref, consumer),
            ],
        ).stage(snapshot)

    assert error.value.code == "missing_inject_provider"


@pytest.mark.unit
async def test_interceptor_is_applied_without_mutating_parent_context() -> None:
    contexts: dict[str, Any] = {}

    def provider(context, _config):
        context.provide("service:value", 10)
        contexts["provider"] = context

    def consumer(context, _config):
        contexts["consumer"] = context

    provider_entry = _entry("provider", "builtin://runtime/provider")
    consumer_entry = _entry(
        "consumer",
        "builtin://runtime/consumer",
        inject={"value": "service:value"},
    )
    snapshot = _snapshot(
        1,
        (provider_entry, consumer_entry),
        provides={provider_entry.module_ref: ("service:value",)},
    )
    generation = await _loader(
        snapshot,
        [
            _definition(snapshot, provider_entry.module_ref, provider),
            _definition(snapshot, consumer_entry.module_ref, consumer),
        ],
    ).stage(snapshot)

    intercepted = contexts["consumer"].intercept("service:value", lambda value: value + 5)

    assert contexts["consumer"].require("value") == 10
    assert intercepted.require("value") == 15
    await generation.dispose()


@pytest.mark.unit
async def test_events_support_bail_waterfall_and_disappear_on_dispose() -> None:
    captured: dict[str, Any] = {}

    def apply(context, _config):
        captured["context"] = context
        context.on("choose", lambda _value: None)
        context.on("choose", lambda _value: "selected")

        async def plus_one(value, next_):
            return await next_(value + 1)

        async def times_two(value, next_):
            return await next_(value * 2)

        context.on("transform", plus_one)
        context.on("transform", times_two)

    entry = _entry("root", "builtin://runtime/root")
    snapshot = _snapshot(
        1,
        (entry,),
        events={
            entry.module_ref: (
                _event("choose", EventModeV2.BAIL),
                _event("transform", EventModeV2.WATERFALL),
            )
        },
    )
    generation = await _loader(
        snapshot,
        [_definition(snapshot, entry.module_ref, apply)],
    ).stage(snapshot)
    context = captured["context"]

    assert await context.dispatch("choose", None) == "selected"
    assert await context.dispatch("transform", 2) == 6
    await generation.dispose()
    assert await context.dispatch("choose", None) is None


@pytest.mark.unit
async def test_same_scope_event_handlers_follow_profile_declaration_order() -> None:
    contexts: list[Any] = []

    def definition(label: str):
        def apply(context, _config):
            contexts.append(context)
            context.on("ordered", lambda _payload: label)

        return apply

    entries = (
        _entry("z-declared-first", "builtin://runtime/declared-first"),
        _entry("a-declared-second", "builtin://runtime/declared-second"),
    )
    ordered_event = _event("ordered", EventModeV2.SERIAL)
    snapshot = _snapshot(
        1,
        entries,
        events={entry.module_ref: (ordered_event,) for entry in entries},
    )
    generation = await _loader(
        snapshot,
        [
            _definition(snapshot, entries[0].module_ref, definition("first")),
            _definition(snapshot, entries[1].module_ref, definition("second")),
        ],
    ).stage(snapshot)

    assert await contexts[0].dispatch("ordered", {}) == ("first", "second")
    await generation.dispose()


@pytest.mark.unit
async def test_generation_lease_pins_old_generation_until_release() -> None:
    disposed: list[int] = []

    def definition(version: int):
        def apply(context, _config):
            context.provide("service:value", version)
            return lambda: disposed.append(version)

        return apply

    entry = _entry("root", "builtin://runtime/root")
    scope = _scope(ScopeKindV2.ROOT)
    first_snapshot = _snapshot(
        1,
        (entry,),
        provides={entry.module_ref: ("service:value",)},
    )
    first = await _loader(
        first_snapshot,
        [_definition(first_snapshot, entry.module_ref, definition(1))],
    ).stage(first_snapshot)
    second_entry = replace(entry, module_ref="builtin://runtime/root-v2")
    second_snapshot = _snapshot(
        2,
        (second_entry,),
        provides={second_entry.module_ref: ("service:value",)},
    )
    second = await _loader(
        second_snapshot,
        [_definition(second_snapshot, second_entry.module_ref, definition(2))],
    ).stage(second_snapshot)
    manager = GenerationManagerV2()
    await manager.publish(first)
    old_lease = await manager.acquire()

    await manager.publish(second)
    new_lease = await manager.acquire()

    assert old_lease.generation.resolve("service:value", scope) == 1
    assert new_lease.generation.resolve("service:value", scope) == 2
    assert disposed == []
    await old_lease.release()
    assert disposed == [1]
    await new_lease.release()
    await manager.close()
    assert disposed == [1, 2]


@pytest.mark.unit
async def test_operation_context_derives_scope_chain_and_isolates_temporary_services() -> None:
    entry = _entry("root", "builtin://runtime/root")
    snapshot = _snapshot(3, (entry,))
    generation = await _loader(
        snapshot,
        [_definition(snapshot, entry.module_ref, lambda _context, _config: None)],
    ).stage(snapshot)
    scope = _scope(
        ScopeKindV2.SESSION,
        tenant_id="tenant-a",
        project_id="project-a",
        session_id="session-a",
    )

    first = OperationContextV2(generation=generation, operation_id="turn-a", scope=scope)
    second = OperationContextV2(generation=generation, operation_id="turn-b", scope=scope)
    async with first, second:
        first.provide("service:db-session", "db-a")
        second.provide("service:db-session", "db-b")

        assert [context.scope.kind for context in first.contexts] == [
            ScopeKindV2.ROOT,
            ScopeKindV2.TENANT,
            ScopeKindV2.PROJECT,
            ScopeKindV2.SESSION,
        ]
        assert first.require("service:db-session") == "db-a"
        assert second.require("service:db-session") == "db-b"

    with pytest.raises(RuntimeV2Error) as error:
        first.provide("service:late", object())
    assert error.value.code == "inactive_effect"


@pytest.mark.unit
async def test_operation_context_disposes_temporary_effects_in_lifo_order() -> None:
    entry = _entry("root", "builtin://runtime/root")
    snapshot = _snapshot(4, (entry,))
    generation = await _loader(
        snapshot,
        [_definition(snapshot, entry.module_ref, lambda _context, _config: None)],
    ).stage(snapshot)
    disposed: list[str] = []
    operation = OperationContextV2(
        generation=generation,
        operation_id="background-a",
        scope=_scope(ScopeKindV2.ROOT),
    )

    async with operation:
        await operation.effect(lambda: lambda: disposed.append("first"), label="first")
        await operation.effect(lambda: lambda: disposed.append("second"), label="second")

    assert disposed == ["second", "first"]
    assert operation.descriptor.profile_id == "runtime-v2-tests"
    assert operation.descriptor.generation == 4
    assert operation.descriptor.digest == generation.digest
