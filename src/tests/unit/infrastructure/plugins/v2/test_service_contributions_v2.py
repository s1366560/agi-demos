"""Explicit contribution edges retain registrations without collecting plain consumers."""

from dataclasses import replace

import pytest

from src.infrastructure.plugins.v2.protocol import (
    build_profile_snapshot_v2,
    plugin_contract_digest_v2,
)
from src.tests.unit.infrastructure.plugins.v2.test_runtime import _entry, _snapshot
from src.tests.unit.infrastructure.plugins.v2.test_service_closure import TENANT, _project

pytestmark = pytest.mark.unit


def _with_contributions(snapshot, module_refs):
    manifests = []
    for manifest in snapshot.manifests:
        modules = []
        for module in manifest.modules:
            contract = module.contract
            if module.module_ref in module_refs:
                contract = replace(
                    contract,
                    services=replace(
                        contract.services,
                        requires=tuple(
                            replace(requirement, contributes=True)
                            for requirement in contract.services.requires
                        ),
                    ),
                )
            modules.append(
                replace(
                    module, contract=contract, contract_digest=plugin_contract_digest_v2(contract)
                )
            )
        manifests.append(replace(manifest, modules=tuple(modules)))
    return build_profile_snapshot_v2(
        profile_id=snapshot.profile_id,
        generation=snapshot.generation,
        manifests=tuple(manifests),
        entries=snapshot.entries,
    )


def test_explicit_contributor_and_its_dependencies_are_retained_but_plain_consumer_is_not():
    entries = (
        _entry("registry", "test://registry"),
        _entry("dependency", "test://dependency"),
        _entry(
            "contribution",
            "test://contribution",
            inject={"catalog": "service:result", "input": "service:input"},
        ),
        _entry("consumer", "test://consumer", inject={"catalog": "service:result"}),
    )
    snapshot = _with_contributions(
        _snapshot(
            1,
            entries,
            provides={
                "test://registry": ("service:result",),
                "test://dependency": ("service:input",),
            },
        ),
        {"test://contribution"},
    )
    projected = _project(snapshot)
    assert projected.entries == entries[:3]
    assert projected.manifests[0].modules[2].contract.services.requires[0].contributes is True


def test_contribution_uses_exact_nearest_provider_and_isolation():
    entries = (
        _entry("root", "test://root"),
        _entry("tenant", "test://tenant", scope=TENANT),
        _entry(
            "root_contribution", "test://root_contribution", inject={"catalog": "service:result"}
        ),
        _entry(
            "tenant_contribution",
            "test://tenant_contribution",
            scope=TENANT,
            inject={"catalog": "service:result"},
        ),
        _entry(
            "unrelated_isolation",
            "test://unrelated_isolation",
            scope=TENANT,
            inject={"catalog": "service:result"},
            isolate={"service:result": "unavailable"},
        ),
        _entry(
            "disabled_contribution",
            "test://disabled_contribution",
            enabled=False,
            inject={"catalog": "service:result"},
        ),
    )
    snapshot = _with_contributions(
        _snapshot(
            1,
            entries,
            provides={
                "test://root": ("service:result",),
                "test://tenant": ("service:result",),
            },
        ),
        {entry.module_ref for entry in entries[2:]},
    )
    assert _project(snapshot).entries == (entries[1], entries[3])
