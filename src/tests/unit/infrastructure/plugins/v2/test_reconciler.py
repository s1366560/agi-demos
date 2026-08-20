"""ACK/NACK and last-good tests for the v2 transactional reconciler."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    ControlPlaneEnvelopeV2,
    RestartPolicyV2,
)
from src.infrastructure.plugins.v2.protocol import (
    PLUGIN_PROFILE_TYPE_URL_V2,
    parse_profile_snapshot_v2,
)
from src.infrastructure.plugins.v2.reconciler import PlatformPluginSnapshotReconcilerV2
from src.infrastructure.plugins.v2.runtime import LoaderV2, PluginDefinitionV2

_ROOT = Path(__file__).resolve().parents[6]


def _snapshot():
    payload = json.loads(
        (_ROOT / "shared/fixtures/platform-plugin-profile.v2.json").read_text(encoding="utf-8")
    )
    return parse_profile_snapshot_v2(payload)


def _envelope(snapshot, version: int, **changes):
    values = {
        "version": version,
        "nonce": f"nonce-{version}",
        "snapshot_digest": snapshot.digest,
        "type_url": PLUGIN_PROFILE_TYPE_URL_V2,
        **changes,
    }
    return ControlPlaneEnvelopeV2(**values)


def _loader(*, fail: bool = False, activations: list[str] | None = None) -> LoaderV2:
    seen = activations if activations is not None else []

    def provider(context, _config):
        seen.append("provider")
        context.provide("service:clock", 7)

    def consumer(context, _config):
        seen.append("consumer")
        _ = context.require("clock")
        if fail:
            raise ValueError("boom")

    return LoaderV2(
        [
            PluginDefinitionV2(
                module_ref="builtin://conformance/root-provider",
                apply=provider,
                provides=("service:clock",),
            ),
            PluginDefinitionV2(
                module_ref="builtin://conformance/session-consumer",
                apply=consumer,
            ),
        ]
    )


@pytest.mark.unit
async def test_first_apply_stages_and_atomically_publishes_generation() -> None:
    snapshot = _snapshot()
    reconciler = PlatformPluginSnapshotReconcilerV2(_loader())

    receipt = await reconciler.apply(snapshot, _envelope(snapshot, 1))

    assert receipt.status == ApplyStatusV2.ACK
    assert reconciler.applied_version == 1
    assert reconciler.manager.current is not None
    assert reconciler.manager.current.digest == snapshot.digest


@pytest.mark.unit
async def test_same_version_and_digest_is_idempotent_without_reactivation() -> None:
    snapshot = _snapshot()
    activations: list[str] = []
    reconciler = PlatformPluginSnapshotReconcilerV2(_loader(activations=activations))
    await reconciler.apply(snapshot, _envelope(snapshot, 1))

    receipt = await reconciler.apply(snapshot, _envelope(snapshot, 1))

    assert receipt.status == ApplyStatusV2.ACK
    assert activations == ["provider", "consumer"]


@pytest.mark.unit
async def test_stale_and_same_version_digest_conflict_retain_last_good() -> None:
    snapshot = _snapshot()
    reconciler = PlatformPluginSnapshotReconcilerV2(_loader())
    await reconciler.apply(snapshot, _envelope(snapshot, 2))
    active = reconciler.manager.current
    changed = replace(snapshot, digest="1" * 64)

    stale = await reconciler.apply(changed, _envelope(changed, 1))
    conflicting = await reconciler.apply(changed, _envelope(changed, 2))

    assert stale.error_code == "stale_version"
    assert conflicting.error_code == "version_digest_conflict"
    assert reconciler.manager.current is active
    assert reconciler.applied_digest == snapshot.digest


@pytest.mark.unit
async def test_invalid_envelope_is_nack_before_staging() -> None:
    snapshot = _snapshot()
    reconciler = PlatformPluginSnapshotReconcilerV2(_loader())

    type_receipt = await reconciler.apply(
        snapshot,
        _envelope(snapshot, 1, type_url="types.memstack.ai/plugin.profile.v1"),
    )
    digest_receipt = await reconciler.apply(
        snapshot,
        _envelope(snapshot, 1, snapshot_digest="0" * 64),
    )

    assert type_receipt.error_code == "unsupported_type_url"
    assert digest_receipt.error_code == "envelope_digest_mismatch"
    assert reconciler.manager.current is None


@pytest.mark.unit
async def test_failed_staging_nacks_and_keeps_last_good_generation() -> None:
    snapshot = _snapshot()
    reconciler = PlatformPluginSnapshotReconcilerV2(_loader())
    await reconciler.apply(snapshot, _envelope(snapshot, 1))
    active = reconciler.manager.current
    reconciler.loader = _loader(fail=True)
    changed = replace(snapshot, generation=8, digest="2" * 64)

    receipt = await reconciler.apply(changed, _envelope(changed, 2))

    assert receipt.status == ApplyStatusV2.NACK
    assert receipt.error_code == "staging_failed"
    assert receipt.applied_version == 1
    assert reconciler.manager.current is active


@pytest.mark.unit
async def test_process_boundary_change_is_explicitly_rejected() -> None:
    snapshot = _snapshot()
    process_entry = replace(
        snapshot.entries[0],
        restart_policy=RestartPolicyV2.PROCESS_BOUNDARY,
    )
    first = replace(snapshot, entries=(process_entry, *snapshot.entries[1:]), digest="3" * 64)
    reconciler = PlatformPluginSnapshotReconcilerV2(_loader())
    await reconciler.apply(first, _envelope(first, 1))
    changed_entry = replace(process_entry, config={"changed": True})
    changed = replace(first, entries=(changed_entry, *first.entries[1:]), digest="4" * 64)

    receipt = await reconciler.apply(changed, _envelope(changed, 2))

    assert receipt.status == ApplyStatusV2.NACK
    assert receipt.error_code == "process_boundary_required"
    assert "root-provider" in (receipt.error_message or "")
    assert reconciler.applied_digest == first.digest


@pytest.mark.unit
async def test_newer_envelope_with_same_digest_adopts_version_without_restage() -> None:
    snapshot = _snapshot()
    activations: list[str] = []
    reconciler = PlatformPluginSnapshotReconcilerV2(_loader(activations=activations))
    await reconciler.apply(snapshot, _envelope(snapshot, 1))

    receipt = await reconciler.apply(snapshot, _envelope(snapshot, 2))

    assert receipt.status == ApplyStatusV2.ACK
    assert reconciler.applied_version == 2
    assert activations == ["provider", "consumer"]


@pytest.mark.unit
async def test_close_disposes_current_generation_and_clears_receipt_state() -> None:
    snapshot = _snapshot()
    reconciler = PlatformPluginSnapshotReconcilerV2(_loader())
    await reconciler.apply(snapshot, _envelope(snapshot, 1))

    await reconciler.close()

    assert reconciler.manager.current is None
    assert reconciler.applied_version is None
    assert reconciler.applied_digest is None
