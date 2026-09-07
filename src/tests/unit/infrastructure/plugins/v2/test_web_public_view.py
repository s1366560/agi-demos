"""Public browser projection uses trusted declarations rather than manifest claims."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.infrastructure.plugins.v2.protocol import canonical_json_v2, parse_profile_snapshot_v2
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.infrastructure.plugins.v2.web_public_view import project_web_public_view_v2

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).resolve().parents[6]
_HOST = "builtin://memstack/web/renderer-host"


def source():
    return json.loads((_ROOT / "shared/profiles/memstack-default-bootstrap.v2.json").read_text())


def resign(payload):
    payload.pop("digest", None)
    payload["digest"] = hashlib.sha256(canonical_json_v2(payload)).hexdigest()
    return payload


def host(payload):
    return next(entry for entry in payload["entries"] if entry["module_ref"] == _HOST)


def host_module(payload):
    return next(
        module
        for manifest in payload["manifests"]
        for module in manifest["modules"]
        if module["module_ref"] == _HOST
    )


def test_real_bootstrap_projects_all_six_web_entries_and_validates_its_own_digest():
    original = source()
    view = project_web_public_view_v2(original, authority_id="authenticated-scope")
    assert set(view) == {"schema_version", "target", "view_id", "snapshot"}
    snapshot = parse_profile_snapshot_v2(view["snapshot"])
    assert snapshot.profile_id == "web-public-view-v2"
    assert len(snapshot.entries) == 6
    assert snapshot.digest != original["digest"]
    assert all(entry.scope.kind.value == "root" for entry in snapshot.entries)
    assert all(
        module.targets[0].value == "web" and len(module.targets) == 1
        for manifest in snapshot.manifests
        for module in manifest.modules
    )
    assert (
        len({module.module_ref for manifest in snapshot.manifests for module in manifest.modules})
        == 3
    )
    assert original == source()


def test_nonpublic_configuration_identifiers_and_provenance_never_cross_boundary():
    payload = source()
    payload["profile_id"] = "private-profile"
    old_id = host(payload)["entry_id"]
    host(payload)["entry_id"] = "private-entry-id"
    for entry in payload["entries"]:
        if entry["parent_entry_id"] == old_id:
            entry["parent_entry_id"] = "private-entry-id"
    next(
        entry
        for entry in payload["entries"]
        if entry["module_ref"] == "builtin://memstack/runtime/generation-boundary"
    )["config"]["secret"] = "private-config"
    host_module(payload)["artifact"]["provenance"] = "private-provenance"
    view = project_web_public_view_v2(resign(payload), authority_id="private-authority")
    serialized = json.dumps(view)
    assert "private-" not in serialized
    assert "nonce" not in view and "envelope" not in view
    assert all(
        module["artifact"]["provenance"] is None
        for manifest in view["snapshot"]["manifests"]
        for module in manifest["modules"]
    )


@pytest.mark.parametrize("change", ["schema", "artifact", "unknown-config", "unknown-module"])
def test_published_contract_or_public_declaration_cannot_expand_boundary(change):
    payload = source()
    module = host_module(payload)
    if change == "schema":
        module["contract"]["config_schema"]["additionalProperties"] = True
        module["contract_digest"] = (
            "sha256:" + hashlib.sha256(canonical_json_v2(module["contract"])).hexdigest()
        )
    elif change == "artifact":
        module["artifact"]["source"] = "repo+ts://private/secret.ts"
    elif change == "unknown-config":
        host(payload)["config"]["private_extra"] = "PRIVATE"
    else:
        module["module_ref"] += "-self-declared-public"
        module["contract"]["config_schema"]["x-browser-public"] = True
        host(payload)["module_ref"] = module["module_ref"]
        module["contract_digest"] = (
            "sha256:" + hashlib.sha256(canonical_json_v2(module["contract"])).hexdigest()
        )
    with pytest.raises(RuntimeV2Error):
        project_web_public_view_v2(resign(payload), authority_id="scope")


@pytest.mark.parametrize(
    "change", ["scope", "parent", "inject", "provider", "entry-metadata", "manifest-metadata"]
)
def test_scope_dependencies_and_undeclared_metadata_fail_closed(change):
    payload = source()
    if change == "scope":
        host(payload)["scope"] = {"kind": "tenant", "tenant_id": "unapproved"}
    elif change == "parent":
        host(payload)["parent_entry_id"] = "missing-private-parent"
    elif change == "inject":
        host(payload)["inject"] = {"extra": "service:private"}
    elif change == "provider":
        payload["entries"] = [
            entry
            for entry in payload["entries"]
            if entry["module_ref"] != "builtin://memstack/web/renderer-contribution-registry"
        ]
    elif change == "entry-metadata":
        host(payload)["isolate"] = {"service:web.renderer-host": "private-label"}
    else:
        manifest = next(
            item
            for item in payload["manifests"]
            if any(module["module_ref"] == _HOST for module in item["modules"])
        )
        manifest["permissions"].append("private-permission")
    # Protocol errors (missing parent) and preflight errors are both deliberate refusal.
    with pytest.raises((RuntimeV2Error, ValueError)):
        project_web_public_view_v2(resign(payload), authority_id="scope")


def test_view_identity_binds_authority_source_and_projected_content():
    payload = source()
    first = project_web_public_view_v2(payload, authority_id="scope-one")
    assert first == project_web_public_view_v2(payload, authority_id="scope-one")
    other = project_web_public_view_v2(payload, authority_id="scope-two")
    assert first["snapshot"] == other["snapshot"]
    assert first["view_id"] != other["view_id"]
    next(
        entry
        for entry in payload["entries"]
        if entry["module_ref"] == "builtin://memstack/runtime/generation-boundary"
    )["config"]["private_value"] = "changed"
    changed = project_web_public_view_v2(resign(payload), authority_id="scope-one")
    assert first["snapshot"] == changed["snapshot"]
    assert first["view_id"] == changed["view_id"]
    payload["generation"] += 1
    revised = project_web_public_view_v2(resign(payload), authority_id="scope-one")
    assert first["view_id"] != revised["view_id"]


@pytest.mark.parametrize("fault", ["schema", "config"])
def test_source_validation_diagnostics_do_not_reveal_secret_canaries(fault):
    payload = source()
    if fault == "schema":
        payload["unexpected-private-canary"] = "secret-canary"
    else:
        host(payload)["config"]["strategy"] = "secret-canary"
    with pytest.raises(RuntimeV2Error) as caught:
        project_web_public_view_v2(resign(payload), authority_id="scope")
    assert caught.value.code in {"web_view_source_invalid", "web_view_configuration_invalid"}
    assert "secret-canary" not in str(caught.value)
    assert caught.value.__suppress_context__
