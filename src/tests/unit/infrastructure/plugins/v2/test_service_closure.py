"""Real contracts and Loader checks for scope-private service closure."""

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2, ServiceRequiredV2
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.service_closure import project_service_closure_v2
from src.tests.unit.infrastructure.plugins.v2.runtime_test_support import (
    RuntimeTestArtifactResolverV2,
)
from src.tests.unit.infrastructure.plugins.v2.test_runtime import (
    _catalog,
    _definition,
    _entry,
    _snapshot,
)

pytestmark = pytest.mark.unit
TENANT = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="a")


def _project(snapshot, service="service:result", **kwargs):
    return project_service_closure_v2(
        snapshot,
        scope=TENANT,
        required_services=(ServiceRequiredV2(alias="result", service=service, version="1.0.0"),),
        **kwargs,
    )


async def test_transitive_inject_and_parent_closure_preserves_artifacts_and_loads():
    entries = (
        _entry("parent", "test://parent"),
        _entry("dependency", "test://dependency"),
        _entry(
            "consumer",
            "test://consumer",
            parent_entry_id="parent",
            scope=TENANT,
            inject={"input": "service:input"},
        ),
        _entry("unused", "test://unused", inject={"missing": "service:unavailable"}),
    )
    snapshot = _snapshot(
        1,
        entries,
        provides={
            "test://dependency": ("service:input",),
            "test://consumer": ("service:result",),
        },
    )
    projected = _project(snapshot)
    assert projected.entries == entries[:3]
    assert projected.manifests[0].modules == snapshot.manifests[0].modules[:3]
    assert projected.digest != snapshot.digest
    seen = []

    def apply(context, _config):
        seen.append(context.entry_id)
        if context.entry_id == "dependency":
            context.provide("service:input", "input")
        elif context.entry_id == "consumer":
            context.provide("service:result", context.require("input"))

    generation = await LoaderV2(
        tuple(_definition(projected, entry.module_ref, apply) for entry in projected.entries),
        target_catalog=_catalog(projected),
        artifact_resolver=RuntimeTestArtifactResolverV2(),
    ).stage(projected)
    await generation.dispose()
    assert seen == ["parent", "dependency", "consumer"]


def test_nearest_scope_and_isolation_match_runtime_provider_selection():
    entries = (
        _entry("root", "test://root"),
        _entry("tenant", "test://tenant", scope=TENANT),
        _entry("isolated", "test://isolated", scope=TENANT, isolate={"service:result": "own"}),
        _entry("foreign", "test://foreign", scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="b")),
    )
    snapshot = _snapshot(
        1, entries, provides={entry.module_ref: ("service:result",) for entry in entries}
    )
    assert _project(snapshot).entries == (entries[1],)
    assert _project(snapshot, isolate={"service:result": "own"}).entries == (entries[2],)


@pytest.mark.parametrize(
    "case,code",
    [
        ("missing", "missing_inject_provider"),
        ("disabled", "missing_inject_provider"),
        ("ambiguous", "ambiguous_inject_provider"),
        ("version", "service_version_mismatch"),
        ("route", "scope_global_route_service"),
    ],
)
def test_invalid_service_closure_rejects(case, code):
    entries = (_entry("one", "test://one", enabled=case != "disabled"),)
    if case == "ambiguous":
        entries += (_entry("two", "test://two"),)
    services = () if case == "missing" else ("service:result",)
    if case == "route":
        services += (ROUTE_TABLE_BUILDER_SERVICE_V2,)
    snapshot = _snapshot(1, entries, provides={entry.module_ref: services for entry in entries})
    required = ServiceRequiredV2(
        alias="result", service="service:result", version="2.0.0" if case == "version" else "1.0.0"
    )
    with pytest.raises(RuntimeV2Error) as caught:
        project_service_closure_v2(snapshot, scope=TENANT, required_services=(required,))
    assert caught.value.code == code


def test_empty_explicit_roots_produce_valid_empty_projection():
    snapshot = _snapshot(1, (_entry("unused", "test://unused"),))
    result = project_service_closure_v2(snapshot, scope=TENANT, required_services=())
    assert result.entries == ()
    assert result.manifests == ()


@pytest.mark.parametrize(
    "case,code",
    [
        ("missing", "missing_inject_provider"),
        ("route", "scope_global_route_service"),
        ("parent", "missing_parent_entry"),
        ("cycle", "entry_dependency_cycle"),
    ],
)
def test_transitive_dependency_failures_are_not_pruned(case, code):
    consumer = _entry(
        "consumer",
        "test://consumer",
        inject={"input": "service:input"},
        parent_entry_id="dependency" if case == "parent" else None,
    )
    dependency = _entry(
        "dependency",
        "test://dependency",
        enabled=case != "parent",
        inject={"back": "service:result"} if case == "cycle" else {},
    )
    services = () if case == "missing" else ("service:input",)
    if case == "route":
        services += (ROUTE_TABLE_BUILDER_SERVICE_V2,)
    if case == "parent":
        consumer = _entry("consumer", "test://consumer", parent_entry_id="dependency")
    snapshot = _snapshot(
        1,
        (dependency, consumer),
        provides={
            "test://consumer": ("service:result",),
            "test://dependency": services,
        },
    )
    with pytest.raises(RuntimeV2Error) as caught:
        _project(snapshot)
    assert caught.value.code == code
