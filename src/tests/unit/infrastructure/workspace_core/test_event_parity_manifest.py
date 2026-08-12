"""Golden contracts for the complete legacy to Avernet Workspace event bridge."""

from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]
MANIFEST_PATH = REPO_ROOT / "docs/architecture/workspace-core-event-parity-manifest.json"
VERIFIER_PATH = REPO_ROOT / "scripts/workspace-core/verify-event-parity.py"


def _load_verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("workspace_event_parity_verifier", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def _rehash(verifier: ModuleType, manifest: dict[str, Any]) -> None:
    manifest["contractSha256"] = verifier.canonical_contract_hash(manifest)


def test_live_event_manifest_covers_every_legacy_workspace_event() -> None:
    verifier = _load_verifier()

    report = verifier.validate_manifest(_manifest(), repo_root=REPO_ROOT)

    assert report == {
        "ok": True,
        "manifestVersion": "workspace-events-v1",
        "contractSha256": "1c3afd58b335467de1a76c82dada3cd02f005bde4a003eb5e3fa9760f387a0b6",
        "eventCount": 35,
        "authorityCounts": {"avernet-core": 24, "memstack-agent-runtime": 11},
        "terminalMappingCount": 3,
        "terminalSurfaceCount": 4,
    }


def test_full_event_audit_covers_python_web_routing_and_replay_surfaces() -> None:
    verifier = _load_verifier()

    report = verifier.validate_full_event_audit(_manifest(), repo_root=REPO_ROOT)

    assert report["eventCount"] == 166
    assert report["frontendEventCount"] == 164
    assert report["internalEventCount"] == 2
    assert report["webGeneratedEventCount"] == 164
    assert report["webAgentRouteCount"] == 139
    assert report["webWorkspaceRouteCount"] == 25
    assert report["canonicalTimelineRouteCount"] == 48
    assert report["unclassifiedEventCount"] == 0


def test_full_event_audit_fails_when_generated_web_types_are_stale(tmp_path: Path) -> None:
    verifier = _load_verifier()
    generated_path = REPO_ROOT / "web/src/types/generated/eventTypes.ts"
    stale_generated = tmp_path / "eventTypes.ts"
    stale_generated.write_text(
        generated_path.read_text(encoding="utf-8").replace("  | 'run_input_applied'\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(verifier.EventParityError, match="generated Web event coverage mismatch"):
        verifier.validate_full_event_audit(
            _manifest(),
            repo_root=REPO_ROOT,
            generated_event_types_path=stale_generated,
        )


def test_full_event_audit_rejects_generic_default_as_semantic_routing() -> None:
    verifier = _load_verifier()
    manifest = deepcopy(_manifest())
    manifest["fullEventAudit"]["canonicalTimelineRoutes"].remove("cancelled")
    manifest["fullEventAudit"]["genericDefaultRoutes"] = ["cancelled"]
    _rehash(verifier, manifest)

    with pytest.raises(verifier.EventParityError, match="generic default routes are prohibited"):
        verifier.validate_full_event_audit(manifest, repo_root=REPO_ROOT)


def test_event_manifest_fails_closed_when_one_legacy_event_is_omitted() -> None:
    verifier = _load_verifier()
    manifest = deepcopy(_manifest())
    manifest["events"] = manifest["events"][:-1]
    _rehash(verifier, manifest)

    with pytest.raises(verifier.EventParityError, match="coverage mismatch"):
        verifier.validate_manifest(manifest, repo_root=REPO_ROOT)


def test_event_manifest_requires_all_terminal_surfaces_and_exact_state_mapping() -> None:
    verifier = _load_verifier()
    manifest = deepcopy(_manifest())
    manifest["terminalSurfaces"].remove("pipeline_progression")
    _rehash(verifier, manifest)

    with pytest.raises(verifier.EventParityError, match="four durable surfaces"):
        verifier.validate_manifest(manifest, repo_root=REPO_ROOT)

    manifest = deepcopy(_manifest())
    manifest["terminalMappings"][0]["timelineEvent"] = "assistant_message"
    _rehash(verifier, manifest)
    with pytest.raises(verifier.EventParityError, match="terminal mapping drift"):
        verifier.validate_manifest(manifest, repo_root=REPO_ROOT)
