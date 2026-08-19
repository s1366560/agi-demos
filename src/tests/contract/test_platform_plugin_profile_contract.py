"""Cross-runtime contract: Python composition output vs shared golden file.

The golden file at ``shared/fixtures/platform-plugin-profile.v1.json`` is the
canonical JSON the Rust data planes parse. Regenerate it after intentional
profile or manifest changes with:

    uv run python scripts/dump_plugin_profile.py --format json \
        > shared/fixtures/platform-plugin-profile.v1.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.infrastructure.plugins.builtin_manifests import default_builtin_manifests
from src.infrastructure.plugins.dump_config import load_profile_document
from src.infrastructure.plugins.profile import compose_profile

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PROFILE = _REPO_ROOT / "config" / "plugin-profiles" / "memstack-default.yaml"
_GOLDEN = _REPO_ROOT / "shared" / "fixtures" / "platform-plugin-profile.v1.json"


@pytest.mark.contract
def test_default_profile_composition_matches_shared_golden() -> None:
    document = load_profile_document(_DEFAULT_PROFILE)
    snapshot = compose_profile(document, default_builtin_manifests())

    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    composed = json.loads(snapshot.to_json())

    assert composed == golden, (
        "platform profile drifted from the shared contract; regenerate with "
        "`uv run python scripts/dump_plugin_profile.py --format json > "
        "shared/fixtures/platform-plugin-profile.v1.json`"
    )


@pytest.mark.contract
def test_golden_file_satisfies_cross_runtime_invariants() -> None:
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))

    assert golden["schema_version"] == 1
    assert golden["profile_id"] == "memstack-default"
    digest = golden["digest"]
    assert len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest)
    for row in golden["plugins"]:
        assert row["schema_version"] == 1
        assert row["trust"] in {"builtin", "signed", "tenant-approved", "untrusted"}
        if row["runtime"] == "python-trusted":
            assert row["trust"] != "untrusted"
        for capability in row["provides"]:
            assert capability["kind"] and capability["id"] and capability["contract"]
