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
        "contractSha256": "38fbd14f097acbb2ad81cda82aba011648f1bcbce5e899b3f9476e7e2501d7cf",
        "eventCount": 35,
        "authorityCounts": {"avernet-core": 28, "memstack-agent-runtime": 7},
        "terminalMappingCount": 3,
        "terminalSurfaceCount": 4,
    }


def test_plan_update_binds_core_runtime_both_databases_and_delivery() -> None:
    event = next(
        item
        for item in _manifest()["events"]
        if item["legacyName"] == "workspace_plan_updated"
    )

    assert event["authority"] == "avernet-core"
    assert event["requiredPayload"] == ["workspace_id", "plan_id", "revision", "action"]
    assert event["evidence"] == {
        "path": "third_party/avernet-bcs/crates/services/memstack-workspace-store/src/plan_authority.rs",
        "contains": 'let event_type = "workspace_plan_updated"',
        "testPath": "third_party/avernet-bcs/crates/services/memstack-workspace-service/tests/plan_authority.rs",
        "testContains": "plan_update_transaction_commits_state_event_compatibility_outbox_and_replays",
        "evidenceLevel": "transaction-delivery",
        "transactionTestPath": "third_party/avernet-bcs/crates/services/memstack-workspace-service/tests/postgres_plan_authority.rs",
        "transactionTestContains": "postgres_plan_update_transaction_commits_state_event_compatibility_outbox_and_replays",
        "deliveryTestPath": "third_party/avernet-bcs/crates/bootstrap/memstack-workspace-core/tests/plan_update_outbox_delivery.rs",
        "deliveryTestContains": "workspace_plan_updated_outbox_publishes_consumer_once_and_replays_after_crash",
    }


def test_recovery_events_bind_core_source_and_transaction_evidence() -> None:
    manifest = _manifest()
    recovery_events = {
        event["legacyName"]: event
        for event in manifest["events"]
        if event["legacyName"]
        in {
            "task_execution_incident_opened",
            "task_execution_session_updated",
            "task_recovery_action_completed",
        }
    }

    assert set(recovery_events) == {
        "task_execution_incident_opened",
        "task_execution_session_updated",
        "task_recovery_action_completed",
    }
    for event in recovery_events.values():
        assert event["authority"] == "avernet-core"
        assert event["evidence"]["path"].endswith("public_tasks.rs")
        assert event["evidence"]["testPath"].endswith("workspace_tasks.rs")
        assert (
            event["evidence"]["testContains"]
            == "recovery_action_commits_ordered_events_and_replays_without_duplicates"
        )


def test_recovery_event_manifest_fails_when_transaction_evidence_is_stale() -> None:
    verifier = _load_verifier()
    manifest = deepcopy(_manifest())
    event = next(
        item
        for item in manifest["events"]
        if item["legacyName"] == "task_execution_session_updated"
    )
    event["evidence"]["testContains"] = "missing_recovery_transaction_contract"
    _rehash(verifier, manifest)

    with pytest.raises(
        verifier.EventParityError,
        match="transaction test evidence no longer proves task_execution_session_updated",
    ):
        verifier.validate_manifest(manifest, repo_root=REPO_ROOT)


def test_avernet_core_events_require_executable_transaction_and_delivery_evidence() -> None:
    verifier = _load_verifier()
    manifest = deepcopy(_manifest())
    event = next(
        item for item in manifest["events"] if item["legacyName"] == "workspace_plan_updated"
    )
    event["authority"] = "avernet-core"
    event["evidence"] = {
        "path": "third_party/avernet-bcs/crates/services/memstack-workspace-store/src/plan_authority.rs",
        "contains": "workspace_plan_updated",
        "evidenceLevel": "transaction-delivery",
    }
    _rehash(verifier, manifest)

    with pytest.raises(
        verifier.EventParityError,
        match="Avernet Core evidence must include transaction and delivery tests",
    ):
        verifier.validate_manifest(manifest, repo_root=REPO_ROOT)


def test_avernet_core_event_evidence_rejects_enum_and_fixture_only_sources() -> None:
    verifier = _load_verifier()
    manifest = deepcopy(_manifest())
    event = next(
        item for item in manifest["events"] if item["legacyName"] == "workspace_plan_updated"
    )
    event["authority"] = "avernet-core"
    event["evidence"] = {
        "path": "third_party/avernet-bcs/crates/bootstrap/memstack-workspace-core/tests/diagnostics_http_contract.rs",
        "contains": "workspace_plan_updated",
        "evidenceLevel": "transaction-delivery",
        "transactionTestPath": "third_party/avernet-bcs/crates/bootstrap/memstack-workspace-core/tests/diagnostics_http_contract.rs",
        "transactionTestContains": "workspace_plan_updated",
        "deliveryTestPath": "third_party/avernet-bcs/crates/bootstrap/memstack-workspace-core/tests/diagnostics_http_contract.rs",
        "deliveryTestContains": "workspace_plan_updated",
    }
    _rehash(verifier, manifest)

    with pytest.raises(verifier.EventParityError, match="must bind runtime source"):
        verifier.validate_manifest(manifest, repo_root=REPO_ROOT)


def test_delivery_contract_requires_publish_consume_dedup_and_crash_replay_tests() -> None:
    verifier = _load_verifier()
    manifest = deepcopy(_manifest())
    manifest["deliveryContract"].setdefault("evidence", {})["crashReplay"] = {
        "testPath": "missing/crash-replay.rs",
        "testContains": "missing_crash_replay",
    }
    manifest["deliveryContract"]["evidence"].pop("crashReplay")
    _rehash(verifier, manifest)

    with pytest.raises(
        verifier.EventParityError,
        match="Workspace event delivery evidence is missing crashReplay",
    ):
        verifier.validate_manifest(manifest, repo_root=REPO_ROOT)


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
