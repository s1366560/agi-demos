"""Unit tests for the `.mspkg` plugin bundle format."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from src.domain.model.plugins import parse_plugin_manifest
from src.infrastructure.plugins.bundle import (
    BundleError,
    PluginBundle,
    bundle_to_profile_layer,
    read_bundle,
    write_bundle,
)
from src.infrastructure.plugins.profile import ProfileLayer, ProfilePatch, ProfileRow

_MANIFEST_PAYLOAD = {
    "schemaVersion": 1,
    "id": "echo-tools",
    "version": "1.2.0",
    "runtime": "python-trusted",
    "trust": "signed",
    "provides": [{"kind": "tool", "id": "echo"}],
}


def _bundle(**overrides: object) -> PluginBundle:
    manifest = parse_plugin_manifest(_MANIFEST_PAYLOAD)
    kwargs: dict[str, object] = {
        "bundle_id": "acme-suite",
        "version": "1.0.0",
        "layer": ProfileLayer(
            id="acme.layer",
            rows=(ProfileRow(id="echo-tools", config={"level": 2}),),
        ),
        "manifests": (manifest,),
        "description": "Acme tool suite",
    }
    kwargs.update(overrides)
    return PluginBundle(**kwargs)  # type: ignore[arg-type]


@pytest.mark.unit
def test_write_then_read_round_trips(tmp_path: Path) -> None:
    bundle = _bundle(patches=(ProfilePatch(target="echo-tools", enabled=False),))
    path = tmp_path / "acme.mspkg"
    write_bundle(path, bundle)

    parsed = read_bundle(path)

    assert parsed.bundle_id == "acme-suite"
    assert parsed.version == "1.0.0"
    assert parsed.description == "Acme tool suite"
    assert parsed.layer.id == "acme.layer"
    assert parsed.layer.rows[0].id == "echo-tools"
    assert parsed.layer.rows[0].config == {"level": 2}
    assert parsed.manifests[0].id == "echo-tools"
    assert parsed.patches[0].target == "echo-tools"
    assert parsed.patches[0].enabled is False


@pytest.mark.unit
def test_bundle_to_profile_layer_appends_layer(tmp_path: Path) -> None:
    layer = bundle_to_profile_layer(_bundle())

    assert isinstance(layer, ProfileLayer)
    assert [row.id for row in layer.rows] == ["echo-tools"]


@pytest.mark.unit
def test_missing_descriptor_fails(tmp_path: Path) -> None:
    path = tmp_path / "empty.mspkg"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("other.txt", "x")

    with pytest.raises(BundleError, match="bundle.json"):
        read_bundle(path)


@pytest.mark.unit
def test_bad_schema_version_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.mspkg"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("bundle.json", json.dumps({"schemaVersion": 99}))

    with pytest.raises(BundleError, match="schemaVersion"):
        read_bundle(path)


@pytest.mark.unit
def test_row_without_manifest_fails(tmp_path: Path) -> None:
    bundle = _bundle()
    descriptor = bundle.to_descriptor()
    descriptor["manifests"] = []  # strip manifests

    path = tmp_path / "orphan.mspkg"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("bundle.json", json.dumps(descriptor))

    with pytest.raises(BundleError, match="manifests"):
        read_bundle(path)


@pytest.mark.unit
def test_patch_target_without_manifest_fails(tmp_path: Path) -> None:
    bundle = _bundle(patches=(ProfilePatch(target="ghost", remove=True),))
    path = tmp_path / "ghost.mspkg"
    write_bundle(path, bundle)

    with pytest.raises(BundleError, match="ghost"):
        read_bundle(path)


@pytest.mark.unit
def test_zip_slip_entry_fails(tmp_path: Path) -> None:
    path = tmp_path / "evil.mspkg"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("bundle.json", json.dumps(_bundle().to_descriptor()))
        archive.writestr("../escape.txt", "x")

    with pytest.raises(BundleError, match="unsafe entry name"):
        read_bundle(path)


@pytest.mark.unit
def test_invalid_manifest_fails(tmp_path: Path) -> None:
    descriptor = _bundle().to_descriptor()
    descriptor["manifests"] = [{"schemaVersion": 1, "id": "x"}]
    path = tmp_path / "badmanifest.mspkg"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("bundle.json", json.dumps(descriptor))

    with pytest.raises(BundleError, match="manifests\\[0\\]"):
        read_bundle(path)


@pytest.mark.unit
def test_not_a_zip_fails(tmp_path: Path) -> None:
    path = tmp_path / "plain.mspkg"
    path.write_bytes(b"not a zip")

    with pytest.raises(BundleError, match="zip"):
        read_bundle(path)
