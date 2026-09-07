"""Explicit artifact refresh must preserve scope, source ownership and trust."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.refresh_plugin_artifacts_v2 import refresh_declared_artifacts_v2
from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2


def _fixture(root: Path) -> tuple[Path, Path, dict[str, Any]]:
    source = root / "plugins/example.ts"
    source.parent.mkdir()
    source.write_text("export const plugin = 1;\n", encoding="utf-8")
    directory = root / "manifests"
    directory.mkdir()
    path = directory / "example.json"
    module = {
        "module_ref": "builtin://example",
        "entrypoint": "plugin",
        "targets": ["desktop-renderer"],
        "artifact": {
            "source": "repo+typescript://plugins/example.ts",
            "digest": "sha256:" + "0" * 64,
        },
    }
    path.write_text(json.dumps({"modules": [module]}) + "\n", encoding="utf-8")
    return path, source, module


def test_refresh_records_real_bytes_and_changes_only_selected_digest(tmp_path: Path) -> None:
    path, source, module = _fixture(tmp_path)
    changes = refresh_declared_artifacts_v2(
        tmp_path, path.parent, frozenset({"builtin://example"}), check=False
    )
    expected = artifact_digest_v2(source.read_bytes())
    updated = json.loads(path.read_text())["modules"][0]
    assert updated == {**module, "artifact": {**module["artifact"], "digest": expected}}
    assert changes[0]["size_bytes"] == len(source.read_bytes())
    assert changes[0]["digest"] == expected
    assert refresh_declared_artifacts_v2(tmp_path, path.parent, frozenset(), check=True) == []


@pytest.mark.parametrize(
    "check,refs", [(True, frozenset({"builtin://example"})), (False, frozenset())]
)
def test_unselected_or_check_mode_drift_never_writes(
    tmp_path: Path, check: bool, refs: frozenset[str]
) -> None:
    path, _, _ = _fixture(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        refresh_declared_artifacts_v2(tmp_path, path.parent, refs, check=check)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "change",
    [
        {"source": "repo+typescript://../outside.ts"},
        {"source": "repo+typescript:///etc/outside.ts"},
        {"source": "repo+typescript://plugins/./example.ts"},
        {"source": "repo+typescript://plugins/example.py"},
        {"source": "https://example.test/plugin.ts"},
        {"signature": "existing-signature"},
        {"provenance": "existing-attestation"},
    ],
)
def test_unsafe_source_or_trusted_artifact_is_not_refreshed(
    tmp_path: Path, change: dict[str, str]
) -> None:
    path, _, module = _fixture(tmp_path)
    module["artifact"].update(change)
    path.write_text(json.dumps({"modules": [module]}), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        refresh_declared_artifacts_v2(
            tmp_path, path.parent, frozenset({"builtin://example"}), check=False
        )
    assert path.read_bytes() == before


def test_language_mismatch_unknown_ref_and_other_drift_do_not_partially_write(
    tmp_path: Path,
) -> None:
    path, _, module = _fixture(tmp_path)
    module["targets"] = ["python"]
    path.write_text(json.dumps({"modules": [module]}), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="language"):
        refresh_declared_artifacts_v2(
            tmp_path, path.parent, frozenset({"builtin://example"}), check=False
        )
    assert path.read_bytes() == before
    module["targets"] = ["desktop-renderer"]
    path.write_text(json.dumps({"modules": [module]}), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="unknown artifact"):
        refresh_declared_artifacts_v2(
            tmp_path,
            path.parent,
            frozenset({"builtin://example", "builtin://unknown"}),
            check=False,
        )
    assert path.read_bytes() == before
    path.write_text(
        json.dumps({"modules": [module, {**module, "module_ref": "builtin://other"}]}),
        encoding="utf-8",
    )
    before = path.read_bytes()
    with pytest.raises(ValueError, match="builtin://other artifact digest mismatch"):
        refresh_declared_artifacts_v2(
            tmp_path, path.parent, frozenset({"builtin://example"}), check=False
        )
    assert path.read_bytes() == before


def test_symlink_outside_repository_is_rejected(tmp_path: Path) -> None:
    path, source, _ = _fixture(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "-outside.ts")
    outside.write_text("export const external = true;", encoding="utf-8")
    source.unlink()
    source.symlink_to(outside)
    try:
        with pytest.raises(ValueError, match="repository-owned"):
            refresh_declared_artifacts_v2(
                tmp_path, path.parent, frozenset({"builtin://example"}), check=False
            )
    finally:
        outside.unlink()
