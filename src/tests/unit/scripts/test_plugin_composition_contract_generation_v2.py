"""Generated public contracts for protocol-v2 bundle/profile composition."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from src.domain.model.plugins.generated_v2 import (
    BundleArtifactV2,
    BundleManifestV2,
    BundleReferenceV2,
    DesiredBundleSetV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSourceReferenceV2,
    ProfileSourceV2,
)

_ROOT = Path(__file__).resolve().parents[4]
_SCHEMA_PATH = _ROOT / "shared/schemas/plugins/platform-plugin-protocol.v2.schema.json"
_RUST_TYPES_PATH = _ROOT / "agi-stack/crates/plugin-host/src/protocol_v2/generated.rs"
_TYPESCRIPT_TYPES_PATH = _ROOT / "agi-stack/packages/plugin-runtime/src/generated.ts"


def _definition_validator(name: str) -> jsonschema.Draft202012Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "$ref": f"#/$defs/{name}",
        }
    )


def _profile_layer(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "layer_id": "profile-base",
        "kind": "profile",
        "scope": {"kind": "root"},
        "entries": [],
        "replacements": [],
        "disabled_entry_ids": ["entry-a"],
    }
    payload.update(overrides)
    return payload


@pytest.mark.unit
def test_composition_contracts_are_generated_from_the_shared_schema() -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    definitions = schema["$defs"]

    assert definitions["ProfileLayerKindV2"]["enum"] == [
        "bundle",
        "profile",
        "tenant",
        "project",
        "session",
    ]
    assert [field.name for field in fields(ProfileLayerV2)] == [
        "layer_id",
        "kind",
        "scope",
        "entries",
        "replacements",
        "disabled_entry_ids",
    ]
    assert [field.name for field in fields(ProfileSourceV2)] == [
        "schema_version",
        "source_id",
        "profile_id",
        "revision",
        "digest",
        "provenance",
        "layers",
    ]
    assert [field.name for field in fields(ProfileSourceReferenceV2)] == [
        "source_id",
        "revision",
        "digest",
    ]
    assert [field.name for field in fields(BundleReferenceV2)] == [
        "bundle_id",
        "version",
        "digest",
        "source",
    ]
    assert [field.name for field in fields(BundleArtifactV2)] == [
        "artifact_id",
        "target",
        "path",
        "digest",
        "size_bytes",
        "media_type",
    ]
    assert [field.name for field in fields(BundleManifestV2)] == [
        "schema_version",
        "bundle_id",
        "version",
        "manifests",
        "layers",
        "artifacts",
        "digest",
        "signature",
        "provenance",
    ]
    assert [field.name for field in fields(DesiredBundleSetV2)] == [
        "schema_version",
        "desired_set_id",
        "revision",
        "bundles",
        "profile_source",
        "digest",
    ]
    assert tuple(ProfileLayerKindV2) == (
        ProfileLayerKindV2.BUNDLE,
        ProfileLayerKindV2.PROFILE,
        ProfileLayerKindV2.TENANT,
        ProfileLayerKindV2.PROJECT,
        ProfileLayerKindV2.SESSION,
    )


@pytest.mark.unit
def test_rust_and_typescript_exports_include_the_same_composition_contracts() -> None:
    rust = _RUST_TYPES_PATH.read_text(encoding="utf-8")
    typescript = _TYPESCRIPT_TYPES_PATH.read_text(encoding="utf-8")

    for name in (
        "BundleArtifactV2",
        "BundleManifestV2",
        "BundleReferenceV2",
        "DesiredBundleSetV2",
        "ProfileLayerKindV2",
        "ProfileLayerV2",
        "ProfileSourceReferenceV2",
        "ProfileSourceV2",
    ):
        assert f"pub struct {name}" in rust or f"pub enum {name}" in rust
        assert f"export interface {name}" in typescript or f"export type {name}" in typescript


@pytest.mark.unit
def test_profile_layer_requires_at_least_one_explicit_operation() -> None:
    validator = _definition_validator("ProfileLayerV2")

    assert validator.is_valid(_profile_layer())
    assert not validator.is_valid(
        _profile_layer(entries=[], replacements=[], disabled_entry_ids=[])
    )


@pytest.mark.unit
def test_desired_bundle_set_uses_an_exact_profile_source_reference() -> None:
    digest = f"sha256:{'a' * 64}"
    payload = {
        "schema_version": 2,
        "desired_set_id": "tenant-a-default",
        "revision": 1,
        "bundles": [],
        "profile_source": {
            "source_id": "tenant-a-profile",
            "revision": 3,
            "digest": digest,
        },
        "digest": digest,
    }
    validator = _definition_validator("DesiredBundleSetV2")

    assert validator.is_valid(payload)
    payload["profile_source"] = {
        "schema_version": 2,
        "source_id": "tenant-a-profile",
        "profile_id": "memstack-default-v2",
        "revision": 3,
        "digest": digest,
        "provenance": None,
        "layers": [_profile_layer()],
    }
    assert not validator.is_valid(payload)
