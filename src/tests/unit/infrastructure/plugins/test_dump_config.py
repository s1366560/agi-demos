"""Unit tests for the effective-profile dump (dsh --dump-config equivalent)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.infrastructure.plugins.builtin_manifests import default_builtin_manifests
from src.infrastructure.plugins.dump_config import (
    DumpConfigError,
    dump_profile,
    load_patch_overlays,
    load_profile_document,
    render_dump,
)
from src.infrastructure.plugins.profile import compose_profile

_REPO_ROOT = Path(__file__).resolve().parents[5]
_DEFAULT_PROFILE = _REPO_ROOT / "config" / "plugin-profiles" / "memstack-default.yaml"


def _write(path: Path, payload: object) -> Path:
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


@pytest.mark.unit
def test_default_profile_composes_with_kernel_rows() -> None:
    output = dump_profile(_DEFAULT_PROFILE)

    assert "# effective profile: memstack-default" in output
    assert "# == layer memstack.kernel-base" in output
    assert "workspace-runtime" in output
    assert "sisyphus-runtime" in output
    # Disabled rows are excluded from the effective composition.
    assert "memory-runtime" not in output
    assert "skill-evolution" not in output


@pytest.mark.unit
def test_yaml_dump_reparses_to_the_same_row_ids() -> None:
    output = dump_profile(_DEFAULT_PROFILE)
    parsed = yaml.safe_load(output)

    assert parsed["profile_id"] == "memstack-default"
    row_ids = sorted(row["id"] for row in parsed["plugins"])
    assert row_ids == ["sisyphus-runtime", "workspace-runtime"]
    assert parsed["digest"]


@pytest.mark.unit
def test_json_dump_matches_canonical_snapshot_form(tmp_path: Path) -> None:
    document = load_profile_document(_DEFAULT_PROFILE)
    snapshot = compose_profile(document, default_builtin_manifests())

    output = dump_profile(_DEFAULT_PROFILE, fmt="json")

    assert json.loads(output) == json.loads(snapshot.to_json())


@pytest.mark.unit
def test_patch_overlay_replaces_whole_config(tmp_path: Path) -> None:
    profile = _write(
        tmp_path / "profile.yaml",
        {
            "schemaVersion": 1,
            "profile": {
                "id": "test-profile",
                "layers": [
                    {
                        "id": "base",
                        "plugins": [
                            {
                                "id": "workspace-runtime",
                                "config": {"mode": "base", "extra": True},
                            }
                        ],
                    }
                ],
            },
        },
    )
    overlay = _write(
        tmp_path / "overlay.yaml",
        {"patches": [{"target": "workspace-runtime", "config": {"mode": "patched"}}]},
    )

    output = dump_profile(profile, (overlay,))

    parsed = yaml.safe_load(output)
    (row,) = parsed["plugins"]
    assert row["config"] == {"mode": "patched"}
    assert str(overlay) in output


@pytest.mark.unit
def test_patch_overlay_remove_drops_row(tmp_path: Path) -> None:
    overlay = _write(
        tmp_path / "overlay.yaml",
        [{"target": "sisyphus-runtime", "remove": True}],
    )

    output = dump_profile(_DEFAULT_PROFILE, (overlay,))
    parsed = yaml.safe_load(output)

    assert [row["id"] for row in parsed["plugins"]] == ["workspace-runtime"]


@pytest.mark.unit
def test_unknown_plugin_id_fails_loud(tmp_path: Path) -> None:
    profile = _write(
        tmp_path / "profile.yaml",
        {
            "schemaVersion": 1,
            "profile": {
                "id": "bad-profile",
                "layers": [{"id": "base", "plugins": [{"id": "ghost-plugin"}]}],
            },
        },
    )

    with pytest.raises(DumpConfigError, match="ghost-plugin"):
        dump_profile(profile)


@pytest.mark.unit
def test_missing_overlay_file_fails_loud(tmp_path: Path) -> None:
    with pytest.raises(DumpConfigError, match="cannot read patch overlay"):
        load_patch_overlays((tmp_path / "absent.yaml",))


@pytest.mark.unit
def test_invalid_overlay_shape_fails_loud(tmp_path: Path) -> None:
    overlay = _write(tmp_path / "overlay.yaml", {"unexpected": True})

    with pytest.raises(DumpConfigError, match="patches list"):
        load_patch_overlays((overlay,))


@pytest.mark.unit
def test_render_dump_marks_layer_transitions() -> None:
    document = load_profile_document(_DEFAULT_PROFILE)
    snapshot = compose_profile(document, default_builtin_manifests())

    output = render_dump(snapshot, source_labels=("memstack-default.yaml",))

    assert output.count("# == layer") == 1
    assert "# sources: memstack-default.yaml" in output
