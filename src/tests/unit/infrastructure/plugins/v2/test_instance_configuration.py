"""Atomic feature configuration uses production contracts and scoped replacements."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import (
    DesiredBundleSetV2,
    ProfileSourceReferenceV2,
    ProfileSourceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.plugins.v2.instance_configuration import (
    instance_rows_v2,
    revise_instance_source_v2,
    validate_instance_candidate_v2,
)
from src.infrastructure.plugins.v2.protocol import parse_profile_snapshot_v2
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.infrastructure.plugins.v2.web_public_view import project_web_public_view_v2
from src.tests.unit.infrastructure.plugins.v2.test_web_public_view import resign

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[6]
SCOPE = ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="t", project_id="p")


def fixture():
    raw = json.loads((ROOT / "shared/profiles/memstack-default-bootstrap.v2.json").read_text())
    entry = next(
        row
        for row in raw["entries"]
        if row["module_ref"] == "builtin://memstack/web/renderer-contribution"
    )
    entry["module_ref"] = "builtin://memstack/web/renderer-feature"
    entry["config"] = {"id": "test-feature", "order": 10, "contributions": [entry["config"]]}
    snapshot = parse_profile_snapshot_v2(resign(raw))
    source = ProfileSourceV2(
        schema_version=2,
        source_id="test-source",
        profile_id=snapshot.profile_id,
        revision=1,
        digest="sha256:" + "0" * 64,
        provenance=None,
        layers=(),
    )
    desired = DesiredBundleSetV2(
        schema_version=2,
        desired_set_id="test-desired",
        revision=1,
        bundles=(),
        profile_source=ProfileSourceReferenceV2(
            source_id=source.source_id, revision=1, digest=source.digest
        ),
        digest=source.digest,
    )
    return snapshot, source, desired, entry["entry_id"]


def test_batch_replaces_only_requested_feature_and_binds_scope():
    snapshot, source, desired, key = fixture()
    updated, target = revise_instance_source_v2(
        source=source,
        desired=desired,
        snapshot=snapshot,
        scope=SCOPE,
        expected_revision=1,
        changes=[{"entry_id": key, "enabled": False}],
    )
    (row,) = updated.layers[-1].replacements
    assert row.entry_id == key and not row.enabled and row.scope == SCOPE
    assert updated.revision == target.revision == 2
    assert target.profile_source.digest == updated.digest
    assert source.layers == () and desired.revision == 1


@pytest.mark.parametrize(
    "change,code",
    [
        ({"entry_id": "unknown", "enabled": False}, "instance_change_invalid"),
        ({"enabled": "false"}, "instance_change_invalid"),
        (
            {"replacement": {"plugin_id": "untrusted", "module_ref": "evil"}},
            "instance_replacement_incompatible",
        ),
    ],
)
def test_invalid_changes_fail_atomically(change, code):
    snapshot, source, desired, key = fixture()
    with pytest.raises(RuntimeV2Error) as caught:
        revise_instance_source_v2(
            source=source,
            desired=desired,
            snapshot=snapshot,
            scope=SCOPE,
            expected_revision=1,
            changes=[{"entry_id": key, **change}],
        )
    assert caught.value.code == code
    assert source.layers == ()


def test_conflict_does_not_build_another_revision():
    snapshot, source, desired, key = fixture()
    with pytest.raises(RuntimeV2Error, match="revision changed"):
        revise_instance_source_v2(
            source=source,
            desired=desired,
            snapshot=snapshot,
            scope=SCOPE,
            expected_revision=2,
            changes=[{"entry_id": key, "enabled": False}],
        )


def test_dependency_failure_rejects_whole_candidate():
    snapshot, _, _, _ = fixture()
    entries = tuple(
        replace(row, enabled=False)
        if row.module_ref == "builtin://memstack/web/renderer-contribution-registry"
        else row
        for row in snapshot.entries
    )
    from src.infrastructure.plugins.v2.protocol import build_profile_snapshot_v2

    candidate = build_profile_snapshot_v2(
        profile_id=snapshot.profile_id, generation=2, manifests=snapshot.manifests, entries=entries
    )
    with pytest.raises(RuntimeV2Error):
        validate_instance_candidate_v2(candidate)


def test_private_configs_are_redacted_and_applied_state_is_distinct():
    snapshot, _, _, key = fixture()
    rows = instance_rows_v2(
        snapshot, scope=SCOPE, publication_status="degraded", active_snapshot=None
    )
    feature = next(row for row in rows if row["entry_id"] == key)
    assert feature["editable"] and feature["config_editable"]
    assert feature["state"]["status"] == "failed"
    private = next(
        row for row in rows if row["module_ref"] == "builtin://memstack/runtime/generation-boundary"
    )
    assert private["config"] == private["config_schema"] == {}
    assert not private["editable"]


def test_public_projection_authorizes_exact_scope_and_rejects_sibling():
    snapshot, _, _, key = fixture()
    from src.infrastructure.plugins.v2.protocol import profile_snapshot_v2_to_payload

    payload = profile_snapshot_v2_to_payload(snapshot)
    next(row for row in payload["entries"] if row["entry_id"] == key)["scope"] = {
        "kind": "project",
        "tenant_id": "t",
        "project_id": "p",
    }
    payload = resign(payload)
    view = project_web_public_view_v2(payload, authority_id="user", authorized_scope=SCOPE)
    assert view["snapshot"]["entries"]
    with pytest.raises(RuntimeV2Error) as caught:
        project_web_public_view_v2(
            payload, authority_id="user", authorized_scope=replace(SCOPE, project_id="other")
        )
    assert caught.value.code == "web_view_scope_unauthorized"
