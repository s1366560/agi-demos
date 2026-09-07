"""Contract tests for the intentionally incompatible plugin protocol v2."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    ArtifactReferenceV2,
    DataPlaneTargetV2,
    EventContractsV2,
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
    TrustKindV2,
)
from src.infrastructure.plugins.v2.protocol import (
    PluginProtocolV2Error,
    build_profile_snapshot_v2,
    canonical_json_v2,
    control_envelope_v2,
    control_envelope_v2_to_payload,
    parse_control_envelope_v2,
    parse_profile_snapshot_v2,
    parse_snapshot_apply_receipt_v2,
    plugin_contract_digest_v2,
    profile_snapshot_v2_to_payload,
    snapshot_apply_receipt_v2_to_payload,
)

_DIGEST = "sha256:" + "a" * 64
_ROOT = Path(__file__).resolve().parents[6]


def _manifest(*module_refs: str) -> PluginManifestV2:
    contract = PluginContractV2(
        services=ServiceContractV2(provides=(), requires=()),
        events=EventContractsV2(emits=(), handles=()),
        config_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
        },
    )
    return PluginManifestV2(
        schema_version=2,
        plugin_id="example-plugin",
        version="1.0.0",
        runtime=RuntimeKindV2.PYTHON_TRUSTED,
        trust=TrustKindV2.BUILTIN,
        modules=tuple(
            PluginModuleV2(
                module_ref=module_ref,
                entrypoint="tests:apply",
                artifact=ArtifactReferenceV2(
                    digest=_DIGEST,
                    source="package://builtin/example-plugin",
                ),
                targets=(DataPlaneTargetV2.PYTHON,),
                contract=contract,
                contract_digest=plugin_contract_digest_v2(contract),
            )
            for module_ref in module_refs
        ),
        permissions=(),
        quotas=QuotaV2(),
    )


def _entry(
    entry_id: str,
    module_ref: str,
    *,
    parent_entry_id: str | None = None,
    scope: ScopeV2 | None = None,
) -> ProfileEntryV2:
    return ProfileEntryV2(
        entry_id=entry_id,
        parent_entry_id=parent_entry_id,
        plugin_ref="example-plugin",
        module_ref=module_ref,
        enabled=True,
        config={},
        inject={},
        isolate={},
        scope=scope or ScopeV2(kind=ScopeKindV2.ROOT),
        permissions=(),
        quotas=QuotaV2(),
        restart_policy=RestartPolicyV2.HOT_GENERATION,
    )


@pytest.mark.unit
def test_canonical_json_uses_rfc8785_number_and_unicode_rules() -> None:
    assert canonical_json_v2({"z": 1.0, "中文": "值", "a": 2}) == (
        b'{"a":2,"z":1,"\xe4\xb8\xad\xe6\x96\x87":"\xe5\x80\xbc"}'
    )


@pytest.mark.unit
def test_build_and_parse_snapshot_round_trips_and_derives_digest() -> None:
    manifest = _manifest("builtin://example/root")
    snapshot = build_profile_snapshot_v2(
        profile_id="default-v2",
        generation=1,
        manifests=(manifest,),
        entries=(_entry("root", "builtin://example/root"),),
    )

    reparsed = parse_profile_snapshot_v2(profile_snapshot_v2_to_payload(snapshot))

    assert reparsed == snapshot
    assert len(snapshot.digest) == 64


@pytest.mark.unit
def test_control_envelope_round_trips_through_strict_schema() -> None:
    snapshot = build_profile_snapshot_v2(
        profile_id="default-v2",
        generation=1,
        manifests=(_manifest("builtin://example/root"),),
        entries=(_entry("root", "builtin://example/root"),),
    )
    envelope = control_envelope_v2(snapshot, version=7, nonce="distribution-7")

    reparsed = parse_control_envelope_v2(control_envelope_v2_to_payload(envelope))

    assert reparsed == envelope


@pytest.mark.unit
def test_control_envelope_rejects_v1_type_url() -> None:
    payload = {
        "version": 1,
        "nonce": "legacy",
        "snapshot_digest": "a" * 64,
        "type_url": "types.memstack.ai/plugin.profile.v1",
    }

    with pytest.raises(PluginProtocolV2Error) as error:
        parse_control_envelope_v2(payload)

    assert error.value.code == "schema_validation_failed"


@pytest.mark.unit
def test_snapshot_apply_receipt_round_trips_through_strict_schema() -> None:
    payload = {
        "status": "ack",
        "requested_version": 7,
        "requested_digest": "a" * 64,
        "applied_version": 7,
        "applied_digest": "a" * 64,
        "error_code": None,
        "error_message": None,
    }

    receipt = parse_snapshot_apply_receipt_v2(payload)

    assert receipt.status is ApplyStatusV2.ACK
    assert snapshot_apply_receipt_v2_to_payload(receipt) == payload


@pytest.mark.unit
def test_snapshot_apply_receipt_rejects_unknown_fields() -> None:
    payload = {
        "status": "nack",
        "requested_version": 8,
        "requested_digest": "b" * 64,
        "applied_version": None,
        "applied_digest": None,
        "error_code": "staging_failed",
        "error_message": "rejected",
        "legacy_status": "failed",
    }

    with pytest.raises(PluginProtocolV2Error) as error:
        parse_snapshot_apply_receipt_v2(payload)

    assert error.value.code == "schema_validation_failed"


@pytest.mark.unit
def test_v1_snapshot_is_explicitly_rejected() -> None:
    with pytest.raises(PluginProtocolV2Error) as error:
        parse_profile_snapshot_v2({"schema_version": 1, "plugins": []})

    assert error.value.code == "incompatible_schema_version"


@pytest.mark.unit
def test_unknown_field_is_rejected() -> None:
    snapshot = build_profile_snapshot_v2(
        profile_id="default-v2",
        generation=1,
        manifests=(_manifest("builtin://example/root"),),
        entries=(_entry("root", "builtin://example/root"),),
    )
    payload = profile_snapshot_v2_to_payload(snapshot)
    payload["unexpected"] = True

    with pytest.raises(PluginProtocolV2Error) as error:
        parse_profile_snapshot_v2(payload)

    assert error.value.code == "schema_validation_failed"


@pytest.mark.unit
@pytest.mark.parametrize("targets", [[], ["python", "python"]])
def test_module_targets_must_be_non_empty_and_unique(targets: list[str]) -> None:
    snapshot = build_profile_snapshot_v2(
        profile_id="default-v2",
        generation=1,
        manifests=(_manifest("builtin://example/root"),),
        entries=(_entry("root", "builtin://example/root"),),
    )
    payload = profile_snapshot_v2_to_payload(snapshot)
    payload["manifests"][0]["modules"][0]["targets"] = targets

    with pytest.raises(PluginProtocolV2Error) as error:
        parse_profile_snapshot_v2(payload)

    assert error.value.code == "schema_validation_failed"


@pytest.mark.unit
def test_digest_mismatch_is_rejected() -> None:
    snapshot = build_profile_snapshot_v2(
        profile_id="default-v2",
        generation=1,
        manifests=(_manifest("builtin://example/root"),),
        entries=(_entry("root", "builtin://example/root"),),
    )
    payload = profile_snapshot_v2_to_payload(snapshot)
    payload["digest"] = "0" * 64

    with pytest.raises(PluginProtocolV2Error) as error:
        parse_profile_snapshot_v2(payload)

    assert error.value.code == "digest_mismatch"


@pytest.mark.unit
def test_parent_cycle_is_rejected_before_activation() -> None:
    manifest = _manifest("builtin://example/a", "builtin://example/b")
    entries = (
        _entry("a", "builtin://example/a", parent_entry_id="b"),
        _entry("b", "builtin://example/b", parent_entry_id="a"),
    )

    with pytest.raises(PluginProtocolV2Error) as error:
        build_profile_snapshot_v2(
            profile_id="default-v2",
            generation=1,
            manifests=(manifest,),
            entries=entries,
        )

    assert error.value.code == "entry_cycle"


@pytest.mark.unit
def test_parent_must_contain_child_scope() -> None:
    manifest = _manifest("builtin://example/parent", "builtin://example/child")
    parent = _entry(
        "parent",
        "builtin://example/parent",
        scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
    )
    child = _entry(
        "child",
        "builtin://example/child",
        parent_entry_id="parent",
        scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-b"),
    )

    with pytest.raises(PluginProtocolV2Error) as error:
        build_profile_snapshot_v2(
            profile_id="default-v2",
            generation=1,
            manifests=(manifest,),
            entries=(parent, child),
        )

    assert error.value.code == "invalid_parent_scope"


@pytest.mark.unit
def test_child_module_targets_must_be_subset_of_parent_targets() -> None:
    manifest = replace(
        _manifest("builtin://example/parent", "builtin://example/child"),
        modules=(
            replace(
                _manifest("builtin://example/parent").modules[0],
                targets=(DataPlaneTargetV2.PYTHON,),
            ),
            replace(
                _manifest("builtin://example/child").modules[0],
                targets=(DataPlaneTargetV2.PYTHON, DataPlaneTargetV2.WEB),
            ),
        ),
    )

    with pytest.raises(PluginProtocolV2Error) as error:
        build_profile_snapshot_v2(
            profile_id="default-v2",
            generation=1,
            manifests=(manifest,),
            entries=(
                _entry("parent", "builtin://example/parent"),
                _entry(
                    "child",
                    "builtin://example/child",
                    parent_entry_id="parent",
                ),
            ),
        )

    assert error.value.code == "invalid_parent_targets"


@pytest.mark.unit
def test_scope_identifiers_must_match_scope_kind() -> None:
    manifest = _manifest("builtin://example/root")
    invalid = replace(
        _entry("root", "builtin://example/root"),
        scope=ScopeV2(kind=ScopeKindV2.PROJECT, project_id="project-a"),
    )

    with pytest.raises(PluginProtocolV2Error) as error:
        build_profile_snapshot_v2(
            profile_id="default-v2",
            generation=1,
            manifests=(manifest,),
            entries=(invalid,),
        )

    assert error.value.code == "invalid_scope"


@pytest.mark.unit
def test_shared_snapshot_and_conformance_fixtures_are_self_consistent() -> None:
    snapshot_path = _ROOT / "shared/fixtures/platform-plugin-profile.v2.json"
    conformance_path = _ROOT / "shared/fixtures/plugin-runtime-conformance.v2.json"
    snapshot = parse_profile_snapshot_v2(json.loads(snapshot_path.read_text(encoding="utf-8")))
    conformance = json.loads(conformance_path.read_text(encoding="utf-8"))

    assert snapshot.digest == conformance["snapshot_digest"]
    assert conformance["target_projection"] == {
        "desktop-renderer": [],
        "desktop-sidecar": [],
        "python": ["root-provider", "session-consumer"],
        "rust-server": ["root-provider", "session-consumer"],
        "web": ["root-provider", "session-consumer"],
    }
    vector = conformance["canonical_json"][0]
    assert canonical_json_v2(vector["input"]).decode("utf-8") == vector["expected"]
