#!/usr/bin/env python3
"""Fail-closed golden gate for the legacy to Avernet Workspace event bridge."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.domain.events.types import (  # noqa: E402
    DELTA_EVENT_TYPES,
    HITL_EVENT_TYPES,
    INTERNAL_EVENT_TYPES,
    TERMINAL_EVENT_TYPES,
    AgentEventType,
)

DEFAULT_MANIFEST = REPO_ROOT / "docs/architecture/workspace-core-event-parity-manifest.json"
_WORKSPACE_EVENT_PREFIXES = (
    "blackboard_",
    "task_execution_",
    "task_recovery_",
    "topology_",
    "workspace_",
)
_TERMINAL_SURFACES = {
    "execution_status",
    "timeline_history",
    "durable_outbox",
    "pipeline_progression",
}
_TERMINAL_STATES = {
    "final": ("complete", "completed", "complete", "workspace.execution.completed", "completed"),
    "error": ("error", "failed", "error", "workspace.execution.failed", "failed"),
    "aborted": ("aborted", "aborted", "cancelled", "workspace.execution.aborted", "aborted"),
}


class EventParityError(RuntimeError):
    """Raised when a frozen event compatibility guarantee no longer holds."""


def canonical_contract_hash(manifest: Mapping[str, Any]) -> str:
    """Hash the semantic manifest while excluding its self-referential hash field."""

    payload = dict(manifest)
    payload.pop("contractSha256", None)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def legacy_workspace_event_names() -> set[str]:
    """Return the complete frozen Workspace subset of the legacy event enum."""

    return {
        event.value for event in AgentEventType if event.value.startswith(_WORKSPACE_EVENT_PREFIXES)
    }


def _manifest_string_set(audit: Mapping[str, Any], key: str) -> set[str]:
    raw = audit.get(key)
    if not isinstance(raw, list) or any(not isinstance(item, str) or not item for item in raw):
        raise EventParityError(f"full event audit {key} must be a string list")
    values = cast("list[str]", raw)
    if len(values) != len(set(values)):
        raise EventParityError(f"full event audit {key} contains duplicates")
    return set(values)


def _audit_source_path(audit: Mapping[str, Any], key: str, *, repo_root: Path) -> Path:
    relative_path = audit.get(key)
    if not isinstance(relative_path, str) or not relative_path:
        raise EventParityError(f"full event audit source {key} is missing")
    source_path = (repo_root / relative_path).resolve()
    try:
        source_path.relative_to(repo_root.resolve())
    except ValueError as error:
        raise EventParityError(f"full event audit source {key} escapes repository") from error
    if not source_path.is_file():
        raise EventParityError(f"full event audit source {key} does not exist")
    return source_path


def _typescript_union_values(source: str, type_name: str) -> set[str]:
    match = re.search(
        rf"export\s+type\s+{re.escape(type_name)}\s*=\s*(.*?);",
        source,
        re.DOTALL,
    )
    if match is None:
        raise EventParityError(f"generated Web type {type_name} is missing")
    return set(re.findall(r"^\s*\|\s*['\"]([^'\"]+)['\"]", match.group(1), re.MULTILINE))


def _typescript_array_values(source: str, constant_name: str) -> set[str]:
    match = re.search(
        rf"{re.escape(constant_name)}(?:\s*:\s*[^=]+)?\s*=\s*\[(.*?)\]",
        source,
        re.DOTALL,
    )
    if match is None:
        raise EventParityError(f"generated Web constant {constant_name} is missing")
    return set(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))


def _python_event_builder_names(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "_EVENT_BUILDERS":
            continue
        if not isinstance(node.value, ast.Dict):
            break
        return {
            key.value
            for key in node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
    raise EventParityError("Agent replay projection builder registry is missing")


def _workspace_route_has_source_evidence(name: str, source: str) -> bool:
    if name.startswith("blackboard_"):
        return "type.startsWith('blackboard_')" in source
    if name.startswith("workspace_task_"):
        return "type.startsWith('workspace_task_')" in source
    return f"type === '{name}'" in source


def _event_classifications() -> tuple[set[str], set[str], set[str], dict[str, set[str]]]:
    all_events = {event.value for event in AgentEventType}
    internal_events = {event.value for event in INTERNAL_EVENT_TYPES}
    return (
        all_events,
        internal_events,
        all_events - internal_events,
        {
            "internalEvents": internal_events,
            "deltaEvents": {event.value for event in DELTA_EVENT_TYPES},
            "terminalEvents": {event.value for event in TERMINAL_EVENT_TYPES},
            "hitlEvents": {event.value for event in HITL_EVENT_TYPES},
        },
    )


def _validate_generated_web_events(
    audit: Mapping[str, Any],
    *,
    repo_root: Path,
    generated_event_types_path: Path | None,
    frontend_events: set[str],
    classifications: Mapping[str, set[str]],
) -> set[str]:
    generated_path = generated_event_types_path or _audit_source_path(
        audit, "generatedWebTypeSource", repo_root=repo_root
    )
    generated_source = generated_path.read_text(encoding="utf-8")
    generated_events = _typescript_union_values(generated_source, "AgentEventType")
    if generated_events != frontend_events:
        missing = sorted(frontend_events - generated_events)
        unexpected = sorted(generated_events - frontend_events)
        raise EventParityError(
            f"generated Web event coverage mismatch: missing={missing}, unexpected={unexpected}"
        )
    generated_classifications = {
        "DELTA_EVENT_TYPES": classifications["deltaEvents"],
        "TERMINAL_EVENT_TYPES": classifications["terminalEvents"],
        "HITL_EVENT_TYPES": classifications["hitlEvents"],
    }
    for constant_name, expected in generated_classifications.items():
        if _typescript_array_values(generated_source, constant_name) != expected:
            raise EventParityError(f"generated Web {constant_name} classification mismatch")
    return generated_events


def _validate_web_route_partition(
    audit: Mapping[str, Any],
    *,
    repo_root: Path,
    frontend_events: set[str],
) -> tuple[set[str], set[str], str]:
    agent_router_source = _audit_source_path(
        audit, "webAgentRouterSource", repo_root=repo_root
    ).read_text(encoding="utf-8")
    agent_route_cases = set(re.findall(r"case\s+['\"]([^'\"]+)['\"]", agent_router_source))
    web_agent_routes = frontend_events & agent_route_cases

    workspace_routes = _manifest_string_set(audit, "webWorkspaceRoutes")
    workspace_router_source = _audit_source_path(
        audit, "webWorkspaceRouterSource", repo_root=repo_root
    ).read_text(encoding="utf-8")
    unsupported_workspace_routes = sorted(
        name
        for name in workspace_routes
        if not _workspace_route_has_source_evidence(name, workspace_router_source)
    )
    if unsupported_workspace_routes:
        raise EventParityError(
            f"Workspace Web router evidence mismatch: {unsupported_workspace_routes}"
        )

    default_branch = agent_router_source.rsplit("default:", maxsplit=1)[-1]
    if "onCanonicalEvent" in default_branch:
        raise EventParityError("generic default routing cannot claim semantic parity")
    return web_agent_routes, workspace_routes, agent_router_source


def _validate_canonical_timeline_routes(
    audit: Mapping[str, Any],
    *,
    repo_root: Path,
    web_agent_routes: set[str],
) -> tuple[set[str], set[str]]:
    canonical_routes = _manifest_string_set(audit, "canonicalTimelineRoutes")
    canonical_source = _audit_source_path(
        audit, "canonicalTimelineSource", repo_root=repo_root
    ).read_text(encoding="utf-8")
    source_canonical_routes = _typescript_array_values(
        canonical_source, "CANONICAL_TIMELINE_EVENT_TYPES"
    )
    if canonical_routes != source_canonical_routes:
        raise EventParityError("canonical timeline route registry mismatch")
    if not canonical_routes <= web_agent_routes:
        raise EventParityError("canonical timeline events are missing explicit Web router cases")

    live_only_routes = _manifest_string_set(audit, "liveOnlyCanonicalRoutes")
    if not live_only_routes <= canonical_routes:
        raise EventParityError("live-only event declarations must be canonical timeline routes")
    replay_builders = _python_event_builder_names(
        _audit_source_path(audit, "replayProjectionSource", repo_root=repo_root)
    )
    replayable_canonical_routes = canonical_routes - live_only_routes
    if not replayable_canonical_routes <= replay_builders:
        raise EventParityError("canonical timeline replay projection is incomplete")
    if live_only_routes & replay_builders:
        raise EventParityError("live-only event declarations unexpectedly have replay builders")
    return canonical_routes, live_only_routes


def _validate_route_coverage(
    frontend_events: set[str],
    web_agent_routes: set[str],
    workspace_routes: set[str],
) -> set[str]:
    classified_frontend_events = web_agent_routes | workspace_routes
    unclassified_events = frontend_events - classified_frontend_events
    unexpected_routes = classified_frontend_events - frontend_events
    overlapping_routes = web_agent_routes & workspace_routes
    if unclassified_events or unexpected_routes or overlapping_routes:
        raise EventParityError(
            "full event routing coverage mismatch: "
            f"missing={sorted(unclassified_events)}, "
            f"unexpected={sorted(unexpected_routes)}, "
            f"overlap={sorted(overlapping_routes)}"
        )
    return unclassified_events


def validate_full_event_audit(
    manifest: Mapping[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    generated_event_types_path: Path | None = None,
) -> dict[str, Any]:
    """Validate every canonical event across Python, Web, routing, and replay surfaces."""

    _validate_manifest_header(manifest)
    audit = manifest.get("fullEventAudit")
    if not isinstance(audit, Mapping):
        raise EventParityError("full event audit contract is missing")

    generic_default_routes = _manifest_string_set(audit, "genericDefaultRoutes")
    if generic_default_routes:
        raise EventParityError("generic default routes are prohibited for semantic parity")

    all_events, internal_events, frontend_events, expected_classifications = (
        _event_classifications()
    )
    for key, expected in expected_classifications.items():
        if _manifest_string_set(audit, key) != expected:
            raise EventParityError(f"full event audit {key} classification mismatch")

    generated_events = _validate_generated_web_events(
        audit,
        repo_root=repo_root,
        generated_event_types_path=generated_event_types_path,
        frontend_events=frontend_events,
        classifications=expected_classifications,
    )
    web_agent_routes, workspace_routes, _agent_router_source = _validate_web_route_partition(
        audit,
        repo_root=repo_root,
        frontend_events=frontend_events,
    )
    canonical_routes, live_only_routes = _validate_canonical_timeline_routes(
        audit,
        repo_root=repo_root,
        web_agent_routes=web_agent_routes,
    )
    unclassified_events = _validate_route_coverage(
        frontend_events,
        web_agent_routes,
        workspace_routes,
    )

    return {
        "ok": True,
        "eventCount": len(all_events),
        "frontendEventCount": len(frontend_events),
        "internalEventCount": len(internal_events),
        "webGeneratedEventCount": len(generated_events),
        "webAgentRouteCount": len(web_agent_routes),
        "webWorkspaceRouteCount": len(workspace_routes),
        "canonicalTimelineRouteCount": len(canonical_routes),
        "liveOnlyCanonicalRouteCount": len(live_only_routes),
        "unclassifiedEventCount": len(unclassified_events),
    }


def _validate_manifest_header(manifest: Mapping[str, Any]) -> str:
    if manifest.get("manifestVersion") != "workspace-events-v1":
        raise EventParityError("unsupported Workspace event manifest version")
    expected_hash = canonical_contract_hash(manifest)
    if manifest.get("contractSha256") != expected_hash:
        raise EventParityError("Workspace event manifest contract hash mismatch")
    return expected_hash


def _validate_envelope_and_delivery(manifest: Mapping[str, Any]) -> None:
    envelope_fields = manifest.get("envelopeRequiredFields")
    required_envelope = {
        "schema_version",
        "event_id",
        "event_type",
        "timestamp",
        "source",
        "correlation_id",
        "payload",
        "metadata",
    }
    if not isinstance(envelope_fields, list) or set(envelope_fields) != required_envelope:
        raise EventParityError("Workspace event envelope field set is incomplete")

    delivery = cast("Mapping[str, Any]", manifest.get("deliveryContract"))
    if (
        delivery.get("sequenceField") != "event_sequence"
        or delivery.get("idempotencyField") != "outbox_id"
        or delivery.get("streamIdentityFields") != ["workspace_id", "stream_name"]
        or not all(delivery.get(name) is True for name in ("ordered", "idempotent", "replayable"))
    ):
        raise EventParityError("Workspace event ordering/idempotency/replay contract is incomplete")

    delivery_evidence = delivery.get("evidence")
    if not isinstance(delivery_evidence, Mapping):
        raise EventParityError("Workspace event delivery evidence is missing")
    for proof in ("publish", "consumeDedup", "crashReplay"):
        item = delivery_evidence.get(proof)
        if not isinstance(item, Mapping):
            raise EventParityError(f"Workspace event delivery evidence is missing {proof}")
        relative_path = item.get("testPath")
        needle = item.get("testContains")
        if not isinstance(relative_path, str) or not isinstance(needle, str) or not needle:
            raise EventParityError(f"Workspace event delivery evidence is invalid for {proof}")
        test_path = (REPO_ROOT / relative_path).resolve()
        try:
            test_path.relative_to(REPO_ROOT.resolve())
        except ValueError as error:
            raise EventParityError(
                f"Workspace event delivery evidence escapes repository for {proof}"
            ) from error
        if not test_path.is_file() or needle not in test_path.read_text(encoding="utf-8"):
            raise EventParityError(
                f"Workspace event delivery evidence no longer proves {proof}"
            )


def _manifest_events(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_events = manifest.get("events")
    if not isinstance(raw_events, list):
        raise EventParityError("Workspace event manifest events must be a list")
    events = [cast("Mapping[str, Any]", item) for item in raw_events]
    names = [item.get("legacyName") for item in events]
    if any(not isinstance(name, str) or not name for name in names):
        raise EventParityError("Workspace event names must be non-empty strings")
    if len(names) != len(set(names)):
        raise EventParityError("Workspace event names must be unique")

    legacy_names = legacy_workspace_event_names()
    manifest_names = set(cast("list[str]", names))
    if manifest_names != legacy_names:
        missing = sorted(legacy_names - manifest_names)
        unexpected = sorted(manifest_names - legacy_names)
        raise EventParityError(
            f"Workspace event coverage mismatch: missing={missing}, unexpected={unexpected}"
        )
    return events


def _validate_event_evidence(event: Mapping[str, Any], *, repo_root: Path, name: str) -> None:
    evidence = event.get("evidence")
    if not isinstance(evidence, Mapping):
        raise EventParityError(f"missing source evidence for {name}")
    relative_path = evidence.get("path")
    needle = evidence.get("contains")
    if not isinstance(relative_path, str) or not isinstance(needle, str) or not needle:
        raise EventParityError(f"invalid source evidence for {name}")
    evidence_path = (repo_root / relative_path).resolve()
    try:
        evidence_path.relative_to(repo_root.resolve())
    except ValueError as error:
        raise EventParityError(f"source evidence escapes repository for {name}") from error
    if not evidence_path.is_file() or needle not in evidence_path.read_text(encoding="utf-8"):
        raise EventParityError(f"source evidence no longer proves {name}")
    legacy_test_path = evidence.get("testPath")
    legacy_test_contains = evidence.get("testContains")
    if legacy_test_path is not None or legacy_test_contains is not None:
        if (
            not isinstance(legacy_test_path, str)
            or not isinstance(legacy_test_contains, str)
            or not legacy_test_contains
        ):
            raise EventParityError(f"invalid transaction test evidence for {name}")
        legacy_path = (repo_root / legacy_test_path).resolve()
        try:
            legacy_path.relative_to(repo_root.resolve())
        except ValueError as error:
            raise EventParityError(
                f"transaction test evidence escapes repository for {name}"
            ) from error
        if (
            not legacy_path.is_file()
            or legacy_test_contains not in legacy_path.read_text(encoding="utf-8")
        ):
            raise EventParityError(f"transaction test evidence no longer proves {name}")
    strict_evidence = evidence.get("evidenceLevel")
    if strict_evidence is None:
        return
    if strict_evidence != "transaction-delivery":
        raise EventParityError(f"invalid evidence level for {name}")
    if event.get("authority") != "avernet-core":
        raise EventParityError(f"transaction-delivery evidence requires Avernet Core for {name}")
    runtime_root = (repo_root / "third_party/avernet-bcs/crates").resolve()
    try:
        evidence_path.relative_to(runtime_root)
    except ValueError as error:
        raise EventParityError(f"Avernet Core evidence must bind runtime source for {name}") from error
    if "/tests/" in evidence_path.as_posix():
        raise EventParityError(f"Avernet Core evidence must bind runtime source for {name}")

    evidence_pairs = (
        ("transaction", "transactionTestPath", "transactionTestContains"),
        ("delivery", "deliveryTestPath", "deliveryTestContains"),
    )
    if any(
        not isinstance(evidence.get(path_key), str)
        or not isinstance(evidence.get(contains_key), str)
        or not evidence.get(contains_key)
        for _, path_key, contains_key in evidence_pairs
    ):
        raise EventParityError(
            f"Avernet Core evidence must include transaction and delivery tests for {name}"
        )
    for evidence_kind, path_key, contains_key in evidence_pairs:
        test_relative_path = cast("str", evidence[path_key])
        test_needle = cast("str", evidence[contains_key])
        test_path = (repo_root / test_relative_path).resolve()
        try:
            test_path.relative_to(repo_root.resolve())
        except ValueError as error:
            raise EventParityError(
                f"{evidence_kind} test evidence escapes repository for {name}"
            ) from error
        if not test_path.is_file() or test_needle not in test_path.read_text(encoding="utf-8"):
            raise EventParityError(
                f"{evidence_kind} test evidence no longer proves {name}"
            )


def _validate_event_contracts(
    events: list[Mapping[str, Any]],
    *,
    repo_root: Path,
) -> dict[str, int]:
    authority_counts: dict[str, int] = {}
    for event in events:
        name = cast("str", event["legacyName"])
        authority = event.get("authority")
        if authority not in {"avernet-core", "memstack-agent-runtime"}:
            raise EventParityError(f"invalid authority for {name}")
        authority_name = cast("str", authority)
        authority_counts[authority_name] = authority_counts.get(authority_name, 0) + 1
        required_payload = event.get("requiredPayload")
        if (
            not isinstance(required_payload, list)
            or not required_payload
            or required_payload[0] != "workspace_id"
            or len(required_payload) != len(set(required_payload))
        ):
            raise EventParityError(f"invalid required payload contract for {name}")
        _validate_event_evidence(event, repo_root=repo_root, name=name)
    return authority_counts


def validate_manifest(
    manifest: Mapping[str, Any], *, repo_root: Path = REPO_ROOT
) -> dict[str, Any]:
    """Validate coverage, source evidence, payload requirements, and delivery invariants."""

    expected_hash = _validate_manifest_header(manifest)
    _validate_envelope_and_delivery(manifest)
    if set(cast("list[str]", manifest.get("terminalSurfaces"))) != _TERMINAL_SURFACES:
        raise EventParityError("terminal event does not bind all four durable surfaces")
    _validate_terminal_mappings(manifest, repo_root=repo_root)
    events = _manifest_events(manifest)
    authority_counts = _validate_event_contracts(events, repo_root=repo_root)

    return {
        "ok": True,
        "manifestVersion": manifest["manifestVersion"],
        "contractSha256": expected_hash,
        "eventCount": len(events),
        "authorityCounts": dict(sorted(authority_counts.items())),
        "terminalMappingCount": len(cast("list[object]", manifest["terminalMappings"])),
        "terminalSurfaceCount": len(_TERMINAL_SURFACES),
    }


def _validate_terminal_mappings(manifest: Mapping[str, Any], *, repo_root: Path) -> None:
    mappings = manifest.get("terminalMappings")
    if not isinstance(mappings, list) or len(mappings) != len(_TERMINAL_STATES):
        raise EventParityError("terminal mapping set is incomplete")
    by_provider_state = {
        cast("str", cast("Mapping[str, Any]", item).get("providerState")): cast(
            "Mapping[str, Any]", item
        )
        for item in mappings
    }
    for state, expected in _TERMINAL_STATES.items():
        item = by_provider_state.get(state)
        if item is None:
            raise EventParityError(f"terminal mapping is missing {state}")
        actual = (
            item.get("executionStatus"),
            item.get("correlationStatus"),
            item.get("timelineEvent"),
            item.get("outboxEvent"),
            item.get("pipelineStatus"),
        )
        if actual != expected:
            raise EventParityError(f"terminal mapping drift for {state}")

    runtime_source = (
        repo_root
        / "third_party/avernet-bcs/crates/bootstrap/memstack-workspace-core/src/runtime.rs"
    ).read_text(encoding="utf-8")
    provider_source = (
        repo_root / "src/infrastructure/workspace_core/agent_runtime_provider.py"
    ).read_text(encoding="utf-8")
    for _, _, timeline_event, outbox_event, _ in _TERMINAL_STATES.values():
        if outbox_event not in runtime_source:
            raise EventParityError(f"Avernet terminal outbox evidence is missing {outbox_event}")
        if timeline_event not in provider_source:
            raise EventParityError(f"Agent terminal history evidence is missing {timeline_event}")


def load_and_validate(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Load one manifest file and return its machine-readable verification summary."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise EventParityError("Workspace event manifest root must be an object")
    manifest = cast("Mapping[str, Any]", raw)
    report = validate_manifest(manifest)
    report["fullEventAudit"] = validate_full_event_audit(manifest)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    try:
        report = load_and_validate(args.manifest)
    except (EventParityError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
