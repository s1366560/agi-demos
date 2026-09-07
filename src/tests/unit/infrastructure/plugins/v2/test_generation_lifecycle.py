"""Cross-generation provider removal and reassembly conformance for runtime v2."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from src.domain.model.plugins.generated_v2 import ProfileSnapshotV2
from src.infrastructure.plugins.v2.protocol import (
    build_profile_snapshot_v2,
    parse_profile_snapshot_v2,
)
from src.infrastructure.plugins.v2.runtime import (
    GenerationManagerV2,
    LoaderV2,
    PluginDefinitionV2,
)
from src.tests.unit.infrastructure.plugins.v2.runtime_test_support import (
    RuntimeTestArtifactResolverV2,
    target_catalog_from_snapshot_v2,
)

_ROOT = Path(__file__).resolve().parents[6]


def _base_snapshot() -> ProfileSnapshotV2:
    payload = json.loads(
        (_ROOT / "shared/fixtures/platform-plugin-profile.v2.json").read_text(encoding="utf-8")
    )
    return parse_profile_snapshot_v2(payload)


def _lifecycle_fixture() -> Mapping[str, Any]:
    payload = cast(
        "dict[str, Any]",
        json.loads(
            (_ROOT / "shared/fixtures/plugin-runtime-conformance.v2.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    return cast("Mapping[str, Any]", payload["provider_generation_lifecycle"])


def _snapshot(
    base: ProfileSnapshotV2,
    generation: int,
    *,
    entries_enabled: bool,
) -> ProfileSnapshotV2:
    return build_profile_snapshot_v2(
        profile_id=base.profile_id,
        generation=generation,
        manifests=base.manifests,
        entries=base.entries if entries_enabled else (),
    )


def _definitions(
    snapshot: ProfileSnapshotV2,
    generation: int,
    events: list[str],
) -> tuple[PluginDefinitionV2, PluginDefinitionV2]:
    digests = {
        module.module_ref: module.contract_digest
        for manifest in snapshot.manifests
        for module in manifest.modules
    }

    def provider(context: Any, _config: Mapping[str, Any]) -> Any:
        events.append(f"provider-apply:{generation}")
        context.provide("service:clock", generation)
        return lambda: events.append(f"provider-dispose:{generation}")

    def consumer(context: Any, _config: Mapping[str, Any]) -> Any:
        provider_generation = context.require("clock")
        events.append(f"consumer-apply:{generation}->{provider_generation}")
        return lambda: events.append(f"consumer-dispose:{generation}")

    return (
        PluginDefinitionV2(
            module_ref="builtin://conformance/root-provider",
            contract_digest=digests["builtin://conformance/root-provider"],
            apply=provider,
        ),
        PluginDefinitionV2(
            module_ref="builtin://conformance/session-consumer",
            contract_digest=digests["builtin://conformance/session-consumer"],
            apply=consumer,
        ),
    )


def _loader(
    snapshot: ProfileSnapshotV2,
    definitions: Sequence[PluginDefinitionV2],
) -> LoaderV2:
    return LoaderV2(
        definitions,
        target_catalog=target_catalog_from_snapshot_v2(snapshot),
        artifact_resolver=RuntimeTestArtifactResolverV2(),
    )


@pytest.mark.unit
async def test_provider_removal_disposes_consumers_then_restore_reassembles() -> None:
    fixture = _lifecycle_fixture()
    initial_generation = cast("int", fixture["initial_generation"])
    removed_generation = cast("int", fixture["removed_generation"])
    restored_generation = cast("int", fixture["restored_generation"])
    base = _base_snapshot()
    events: list[str] = []
    manager = GenerationManagerV2()

    initial_snapshot = _snapshot(base, initial_generation, entries_enabled=True)
    initial = await _loader(
        initial_snapshot,
        _definitions(initial_snapshot, initial_generation, events),
    ).stage(initial_snapshot)
    await manager.publish(initial)
    assert events == fixture["after_initial"]

    removed_snapshot = _snapshot(base, removed_generation, entries_enabled=False)
    removed = await _loader(removed_snapshot, ()).stage(removed_snapshot)
    await manager.publish(removed)
    assert events == fixture["after_removal"]

    restored_snapshot = _snapshot(base, restored_generation, entries_enabled=True)
    restored = await _loader(
        restored_snapshot,
        _definitions(restored_snapshot, restored_generation, events),
    ).stage(restored_snapshot)
    await manager.publish(restored)
    assert events == fixture["after_restore"]

    await manager.close()
    assert events == fixture["after_close"]
