"""Data-plane snapshot reconciliation with last-good retention."""

from __future__ import annotations

from typing import Any

import pytest

from src.domain.model.plugins import PluginManifest, parse_plugin_manifest
from src.infrastructure.plugins import CapabilityRegistry
from src.infrastructure.plugins.llm_adapters import LlmAdapterProviderRegistry
from src.infrastructure.plugins.profile import (
    PROFILE_SNAPSHOT_TYPE_URL,
    ProfileSnapshot,
    compose_profile,
    control_envelope,
    parse_profile_document,
)
from src.infrastructure.plugins.snapshot_reconciler import (
    PlatformPluginSnapshotReconciler,
)


def _manifest(
    plugin_id: str,
    *,
    runtime: str = "python-trusted",
    trust: str = "builtin",
    provides: list[dict[str, Any]] | None = None,
) -> PluginManifest:
    return parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": plugin_id,
            "version": "1.0.0",
            "runtime": runtime,
            "trust": trust,
            "provides": provides
            or [
                {
                    "kind": "channel",
                    "id": f"{plugin_id}-channel",
                    "contract": f"channel:{plugin_id}",
                    "permissions": ["channel.message.read"],
                }
            ],
        }
    )


def _snapshot(*manifests: PluginManifest, profile_id: str = "reconciler-test") -> ProfileSnapshot:
    document = parse_profile_document(
        {
            "profile": {
                "id": profile_id,
                "layers": [
                    {
                        "id": "base",
                        "plugins": [{"id": manifest.id} for manifest in manifests],
                    }
                ],
            }
        }
    )
    return compose_profile(document, {manifest.id: manifest for manifest in manifests})


def _llm_manifest(plugin_id: str, provider_id: str, **kwargs: Any) -> PluginManifest:
    return _manifest(
        plugin_id,
        provides=[
            {
                "kind": "llm_provider",
                "id": provider_id,
                "contract": f"llm_adapter:{provider_id}",
                "permissions": ["llm.invoke"],
            }
        ],
        **kwargs,
    )


@pytest.mark.unit
def test_first_apply_activates_capabilities() -> None:
    reconciler = PlatformPluginSnapshotReconciler()
    snapshot = _snapshot(_manifest("plugin-a"))

    receipt = reconciler.apply(snapshot, control_envelope(snapshot, version=1))

    assert receipt.status == "ack"
    assert receipt.applied_version == 1
    assert receipt.applied_digest == snapshot.digest
    assert reconciler.applied_version == 1
    assert reconciler.capability_registry.list_capabilities("plugin-a")


@pytest.mark.unit
def test_same_version_same_digest_is_idempotent_ack() -> None:
    reconciler = PlatformPluginSnapshotReconciler()
    snapshot = _snapshot(_manifest("plugin-a"))
    first = reconciler.apply(snapshot, control_envelope(snapshot, version=1))
    active_records = reconciler.capability_registry.list_capabilities("plugin-a")

    second = reconciler.apply(snapshot, control_envelope(snapshot, version=1))

    assert first.status == second.status == "ack"
    assert second.applied_version == 1
    assert reconciler.capability_registry.list_capabilities("plugin-a") == active_records


@pytest.mark.unit
def test_same_version_new_digest_is_nack_and_retains_generation() -> None:
    reconciler = PlatformPluginSnapshotReconciler()
    original = _snapshot(_manifest("plugin-a"))
    reconciler.apply(original, control_envelope(original, version=1))

    changed = _snapshot(_manifest("plugin-b"))
    receipt = reconciler.apply(changed, control_envelope(changed, version=1))

    assert receipt.status == "nack"
    assert "digest" in (receipt.error_message or "")
    assert receipt.applied_version == 1
    assert receipt.applied_digest == original.digest
    assert reconciler.capability_registry.list_capabilities("plugin-a")
    assert reconciler.capability_registry.list_capabilities("plugin-b") == ()


@pytest.mark.unit
def test_stale_version_is_nack() -> None:
    reconciler = PlatformPluginSnapshotReconciler()
    first = _snapshot(_manifest("plugin-a"))
    reconciler.apply(first, control_envelope(first, version=2))

    stale = _snapshot(_manifest("plugin-b"))
    receipt = reconciler.apply(stale, control_envelope(stale, version=1))

    assert receipt.status == "nack"
    assert "stale" in (receipt.error_message or "")
    assert reconciler.applied_version == 2
    assert reconciler.capability_registry.list_capabilities("plugin-b") == ()


@pytest.mark.unit
def test_envelope_digest_mismatch_is_nack() -> None:
    reconciler = PlatformPluginSnapshotReconciler()
    snapshot = _snapshot(_manifest("plugin-a"))
    envelope = control_envelope(_snapshot(_manifest("plugin-b")), version=1)

    receipt = reconciler.apply(snapshot, envelope)

    assert receipt.status == "nack"
    assert "does not match" in (receipt.error_message or "")
    assert reconciler.applied_version is None
    assert reconciler.capability_registry.list_capabilities() == ()


@pytest.mark.unit
def test_unknown_type_url_is_nack() -> None:
    reconciler = PlatformPluginSnapshotReconciler()
    snapshot = _snapshot(_manifest("plugin-a"))
    envelope = control_envelope(snapshot, version=1, type_url="types.memstack.ai/other.v9")

    receipt = reconciler.apply(snapshot, envelope)

    assert receipt.status == "nack"
    assert PROFILE_SNAPSHOT_TYPE_URL not in (receipt.error_message or "")
    assert reconciler.applied_version is None


@pytest.mark.unit
def test_failed_activation_retains_last_good_generation() -> None:
    capabilities = CapabilityRegistry()
    adapters = LlmAdapterProviderRegistry()
    reconciler = PlatformPluginSnapshotReconciler(
        capabilities,
        adapter_registry=adapters,
    )
    good = _snapshot(_manifest("plugin-a"))
    reconciler.apply(good, control_envelope(good, version=1))

    bad = _snapshot(
        _llm_manifest("evil-llm", "openai", runtime="wasm", trust="untrusted"),
    )
    receipt = reconciler.apply(bad, control_envelope(bad, version=2))

    assert receipt.status == "nack"
    assert "trusted python runtime" in (receipt.error_message or "")
    assert receipt.applied_version == 1
    assert receipt.applied_digest == good.digest
    assert reconciler.capability_registry.list_capabilities("plugin-a")
    assert reconciler.capability_registry.list_capabilities("evil-llm") == ()
    assert adapters.get("openai") is None


@pytest.mark.unit
def test_failed_activation_does_not_leak_partial_registrations() -> None:
    capabilities = CapabilityRegistry()
    adapters = LlmAdapterProviderRegistry()
    reconciler = PlatformPluginSnapshotReconciler(
        capabilities,
        adapter_registry=adapters,
    )
    bad = _snapshot(
        _llm_manifest("good-llm", "openai"),
        _llm_manifest("evil-llm", "deepseek", runtime="wasm", trust="untrusted"),
    )

    receipt = reconciler.apply(bad, control_envelope(bad, version=1))

    assert receipt.status == "nack"
    assert reconciler.applied_version is None
    assert reconciler.capability_registry.list_capabilities() == ()
    assert adapters.list() == ()


@pytest.mark.unit
def test_newer_version_swaps_generation_and_disposes_previous() -> None:
    reconciler = PlatformPluginSnapshotReconciler()
    first = _snapshot(_manifest("plugin-a"))
    reconciler.apply(first, control_envelope(first, version=1))

    second = _snapshot(_manifest("plugin-b"))
    receipt = reconciler.apply(second, control_envelope(second, version=2))

    assert receipt.status == "ack"
    assert receipt.applied_version == 2
    assert reconciler.capability_registry.list_capabilities("plugin-a") == ()
    assert reconciler.capability_registry.list_capabilities("plugin-b")


@pytest.mark.unit
def test_dispose_tears_down_active_generation() -> None:
    reconciler = PlatformPluginSnapshotReconciler()
    snapshot = _snapshot(_manifest("plugin-a"))
    reconciler.apply(snapshot, control_envelope(snapshot, version=1))

    reconciler.dispose()

    assert reconciler.applied_version is None
    assert reconciler.applied_digest is None
    assert reconciler.capability_registry.list_capabilities() == ()


@pytest.mark.unit
def test_llm_adapter_provider_activates_and_swaps_with_generation() -> None:
    capabilities = CapabilityRegistry()
    adapters = LlmAdapterProviderRegistry()
    reconciler = PlatformPluginSnapshotReconciler(
        capabilities,
        adapter_registry=adapters,
    )
    first = _snapshot(_llm_manifest("llm-openai", "openai"))
    reconciler.apply(first, control_envelope(first, version=1))
    assert adapters.owner_of("openai") == "llm-openai"

    second = _snapshot(_llm_manifest("llm-deepseek", "deepseek"))
    receipt = reconciler.apply(second, control_envelope(second, version=2))

    assert receipt.status == "ack"
    assert adapters.get("openai") is None
    assert adapters.owner_of("deepseek") == "llm-deepseek"


@pytest.mark.unit
def test_same_plugin_reactivates_across_generations_without_conflict() -> None:
    reconciler = PlatformPluginSnapshotReconciler()
    snapshot = _snapshot(_manifest("plugin-a"))

    first = reconciler.apply(snapshot, control_envelope(snapshot, version=1))
    second_snapshot = _snapshot(_manifest("plugin-a"), _manifest("plugin-b"))
    second = reconciler.apply(second_snapshot, control_envelope(second_snapshot, version=2))

    assert first.status == "ack"
    assert second.status == "ack"
    assert reconciler.capability_registry.list_capabilities("plugin-a")
    assert reconciler.capability_registry.list_capabilities("plugin-b")


@pytest.mark.unit
def test_adapter_handoff_replaces_same_owner_and_removes_absent_providers() -> None:
    adapters = LlmAdapterProviderRegistry()
    reconciler = PlatformPluginSnapshotReconciler(adapter_registry=adapters)
    first = _snapshot(
        _llm_manifest("llm-openai", "openai"),
        _llm_manifest("llm-deepseek", "deepseek"),
    )
    reconciler.apply(first, control_envelope(first, version=1))
    initial_openai = adapters.get("openai")
    assert initial_openai is not None

    second = _snapshot(_llm_manifest("llm-openai", "openai"))
    receipt = reconciler.apply(second, control_envelope(second, version=2))

    assert receipt.status == "ack"
    replacement = adapters.get("openai")
    assert replacement is not None
    assert replacement is not initial_openai
    assert adapters.get("deepseek") is None


@pytest.mark.unit
def test_adapter_owned_by_external_actor_nacks_and_retains_last_good() -> None:
    adapters = LlmAdapterProviderRegistry()
    reconciler = PlatformPluginSnapshotReconciler(adapter_registry=adapters)
    good = _snapshot(_manifest("plugin-a"))
    reconciler.apply(good, control_envelope(good, version=1))

    adapters.register("openai", object(), owner="external-plugin")  # type: ignore[arg-type]
    conflicting = _snapshot(_llm_manifest("llm-openai", "openai"))
    receipt = reconciler.apply(conflicting, control_envelope(conflicting, version=2))

    assert receipt.status == "nack"
    assert "external-plugin" in (receipt.error_message or "")
    assert receipt.applied_version == 1
    assert adapters.owner_of("openai") == "external-plugin"
    assert reconciler.capability_registry.list_capabilities("plugin-a")


@pytest.mark.unit
def test_manager_owned_adapter_defers_to_profile_generation() -> None:
    adapters = LlmAdapterProviderRegistry()
    reconciler = PlatformPluginSnapshotReconciler(adapter_registry=adapters)
    adapters.register("openai", object(), owner="llm-provider:config-1")  # type: ignore[arg-type]

    snapshot = _snapshot(_llm_manifest("llm-openai", "openai"))
    receipt = reconciler.apply(snapshot, control_envelope(snapshot, version=1))

    assert receipt.status == "ack"
    assert adapters.owner_of("openai") == "llm-openai"

    reconciler.dispose()
    assert adapters.get("openai") is None
