"""Strict offline mapping contract for protocol-v1 desired-state conversion."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import NoReturn, cast

from src.domain.model.plugins.generated_v2 import BundleReferenceV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_v1_migration_repository import (
    digest_payload_v1_to_v2,
)
from src.infrastructure.plugins.v2.protocol import PluginProtocolV2Error, canonical_json_v2
from src.infrastructure.plugins.v2.scope import parse_scope_v2

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_MIGRATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class PluginProtocolV1ToV2MigrationError(ValueError):
    """Stable validation or execution failure for the one-shot conversion."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class PluginProtocolV1ToV2Action(str, Enum):
    ADD_BUNDLE = "add_bundle"
    REPLACE_BUNDLE = "replace_bundle"
    REMOVE_BUNDLE = "remove_bundle"
    RETAIN_BASELINE = "retain_baseline"
    OMIT_INACTIVE = "omit_inactive"


@dataclass(frozen=True, kw_only=True)
class MigrationJudgmentV1ToV2:
    agent_id: str
    tool_name: str
    input_digest: str
    output_digest: str
    rationale: str
    latency_ms: int

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, kw_only=True)
class MigrationDecisionV1ToV2:
    source_row_id: str
    source_row_digest: str
    action: PluginProtocolV1ToV2Action
    target_bundle: BundleReferenceV2 | None
    judgment: MigrationJudgmentV1ToV2

    def target_payload(self) -> dict[str, object] | None:
        if self.target_bundle is None:
            return None
        return bundle_reference_v2_to_payload(self.target_bundle)

    def to_payload(self) -> dict[str, object]:
        return {
            "source_row_id": self.source_row_id,
            "source_row_digest": self.source_row_digest,
            "action": self.action.value,
            "target_bundle": self.target_payload(),
            "judgment": self.judgment.to_payload(),
        }


@dataclass(frozen=True, kw_only=True)
class MigrationTargetHeadV1ToV2:
    scope: ScopeV2
    expected_revision: int | None
    expected_digest: str | None


@dataclass(frozen=True, kw_only=True)
class PluginProtocolV1ToV2MigrationDocument:
    migration_id: str
    source: dict[str, object]
    target_heads: tuple[MigrationTargetHeadV1ToV2, ...]
    decisions: tuple[MigrationDecisionV1ToV2, ...]
    mapping_digest: str


def parse_plugin_v1_to_v2_migration_document(
    payload: object,
) -> PluginProtocolV1ToV2MigrationDocument:
    raw = _object(payload, code="migration_document_invalid", context="mapping document")
    if set(raw) != {
        "schema_version",
        "migration_id",
        "source",
        "target_heads",
        "decisions",
    }:
        _fail("migration_document_invalid", "mapping document fields are not exact")
    if raw["schema_version"] != 1:
        _fail("migration_schema_incompatible", "mapping schema_version must be 1")
    migration_id = _bounded_string(raw["migration_id"], context="migration_id", maximum=128)
    if _MIGRATION_ID_PATTERN.fullmatch(migration_id) is None:
        _fail("migration_id_invalid", "migration_id contains unsupported characters")
    source = _object(raw["source"], code="migration_source_invalid", context="source")
    _ = _digest(source.get("digest"), context="source digest")
    if source.get("schema_version") != 1 or not isinstance(source.get("rows"), list):
        _fail("migration_source_invalid", "source snapshot has an invalid shape")

    target_items = raw["target_heads"]
    if not isinstance(target_items, list):
        _fail("migration_target_heads_invalid", "target_heads must be an array")
    target_heads = tuple(_parse_target_head(item) for item in cast(list[object], target_items))
    target_keys = tuple(_scope_key(item.scope) for item in target_heads)
    if len(target_keys) != len(set(target_keys)):
        _fail("migration_target_heads_invalid", "target_heads repeats a scope")

    decision_items = raw["decisions"]
    if not isinstance(decision_items, list):
        _fail("migration_decisions_invalid", "decisions must be an array")
    decisions = tuple(_parse_decision(item) for item in cast(list[object], decision_items))
    decision_ids = tuple(item.source_row_id for item in decisions)
    if len(decision_ids) != len(set(decision_ids)):
        _fail("migration_decisions_invalid", "decisions repeats a V1 source row")

    return PluginProtocolV1ToV2MigrationDocument(
        migration_id=migration_id,
        source=source,
        target_heads=target_heads,
        decisions=decisions,
        mapping_digest=digest_payload_v1_to_v2(raw),
    )


def plugin_v1_to_v2_decision_output_digest(
    *,
    action: str,
    target_bundle: dict[str, object] | None,
) -> str:
    try:
        parsed_action = PluginProtocolV1ToV2Action(action)
    except ValueError as exc:
        raise PluginProtocolV1ToV2MigrationError(
            "migration_action_invalid",
            "decision action is unsupported",
        ) from exc
    normalized_target = None
    if target_bundle is not None:
        normalized_target = bundle_reference_v2_to_payload(_parse_bundle_reference(target_bundle))
    return digest_payload_v1_to_v2(
        {
            "action": parsed_action.value,
            "target_bundle": normalized_target,
        }
    )


def bundle_reference_v2_to_payload(reference: BundleReferenceV2) -> dict[str, object]:
    return {
        "bundle_id": reference.bundle_id,
        "version": reference.version,
        "digest": reference.digest,
        "source": reference.source,
    }


def _parse_target_head(payload: object) -> MigrationTargetHeadV1ToV2:
    raw = _object(payload, code="migration_target_heads_invalid", context="target head")
    if set(raw) != {"scope", "expected_revision", "expected_digest"}:
        _fail("migration_target_heads_invalid", "target head fields are not exact")
    scope = _parse_scope(raw["scope"])
    revision = raw["expected_revision"]
    digest = raw["expected_digest"]
    if revision is None and digest is None:
        return MigrationTargetHeadV1ToV2(
            scope=scope,
            expected_revision=None,
            expected_digest=None,
        )
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        _fail("migration_target_heads_invalid", "expected_revision must be positive or null")
    return MigrationTargetHeadV1ToV2(
        scope=scope,
        expected_revision=revision,
        expected_digest=_digest(digest, context="expected target digest"),
    )


def _parse_decision(payload: object) -> MigrationDecisionV1ToV2:
    raw = _object(payload, code="migration_decisions_invalid", context="decision")
    if set(raw) != {
        "source_row_id",
        "source_row_digest",
        "action",
        "target_bundle",
        "judgment",
    }:
        _fail("migration_decisions_invalid", "decision fields are not exact")
    source_row_id = _bounded_string(raw["source_row_id"], context="source_row_id", maximum=255)
    source_row_digest = _digest(raw["source_row_digest"], context="source row digest")
    try:
        action = PluginProtocolV1ToV2Action(raw["action"])
    except (TypeError, ValueError) as exc:
        raise PluginProtocolV1ToV2MigrationError(
            "migration_decision_missing",
            "every source row requires one explicit action",
        ) from exc
    target = None
    if raw["target_bundle"] is not None:
        target = _parse_bundle_reference(raw["target_bundle"])
    judgment = _parse_judgment(raw["judgment"])
    expected_output_digest = plugin_v1_to_v2_decision_output_digest(
        action=action.value,
        target_bundle=None if target is None else bundle_reference_v2_to_payload(target),
    )
    if judgment.input_digest != source_row_digest:
        _fail("migration_judgment_invalid", "judgment input_digest differs from its source row")
    if judgment.output_digest != expected_output_digest:
        _fail("migration_judgment_invalid", "judgment output_digest differs from its decision")
    return MigrationDecisionV1ToV2(
        source_row_id=source_row_id,
        source_row_digest=source_row_digest,
        action=action,
        target_bundle=target,
        judgment=judgment,
    )


def _parse_judgment(payload: object) -> MigrationJudgmentV1ToV2:
    raw = _object(payload, code="migration_judgment_invalid", context="judgment")
    expected = {
        "agent_id",
        "tool_name",
        "input_digest",
        "output_digest",
        "rationale",
        "latency_ms",
    }
    if set(raw) != expected:
        _fail("migration_judgment_invalid", "judgment fields are not exact")
    latency = raw["latency_ms"]
    if isinstance(latency, bool) or not isinstance(latency, int) or latency < 0:
        _fail("migration_judgment_invalid", "judgment latency_ms must be non-negative")
    return MigrationJudgmentV1ToV2(
        agent_id=_bounded_string(raw["agent_id"], context="judgment agent_id", maximum=255),
        tool_name=_bounded_string(raw["tool_name"], context="judgment tool_name", maximum=255),
        input_digest=_digest(raw["input_digest"], context="judgment input_digest"),
        output_digest=_digest(raw["output_digest"], context="judgment output_digest"),
        rationale=_bounded_string(
            raw["rationale"], context="judgment rationale", minimum=8, maximum=4000
        ),
        latency_ms=latency,
    )


def _parse_bundle_reference(payload: object) -> BundleReferenceV2:
    raw = _object(
        payload,
        code="migration_target_bundle_invalid",
        context="target bundle",
    )
    if set(raw) != {"bundle_id", "version", "digest", "source"}:
        _fail("migration_target_bundle_invalid", "target Bundle fields are not exact")
    return BundleReferenceV2(
        bundle_id=_bounded_string(raw["bundle_id"], context="bundle_id", maximum=255),
        version=_bounded_string(raw["version"], context="bundle version", maximum=64),
        digest=_digest(raw["digest"], context="bundle digest"),
        source=_bounded_string(raw["source"], context="bundle source", maximum=512),
    )


def _parse_scope(payload: object) -> ScopeV2:
    try:
        return parse_scope_v2(payload)
    except PluginProtocolV2Error as exc:
        raise PluginProtocolV1ToV2MigrationError(
            "migration_target_heads_invalid",
            "mapping scope is invalid",
        ) from exc


def _object(payload: object, *, code: str, context: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        _fail(code, f"{context} must be an object")
    raw = cast(dict[object, object], payload)
    if not all(isinstance(key, str) for key in raw):
        _fail(code, f"{context} contains a non-string field name")
    return cast(dict[str, object], raw)


def _bounded_string(
    value: object,
    *,
    context: str,
    minimum: int = 1,
    maximum: int,
) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        _fail("migration_document_invalid", f"{context} has an invalid length")
    return value


def _digest(value: object, *, context: str) -> str:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        _fail("migration_document_invalid", f"{context} must be a canonical sha256 digest")
    return value


def _scope_key(scope: ScopeV2) -> bytes:
    return canonical_json_v2(
        {
            "kind": scope.kind.value,
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
            "session_id": scope.session_id,
        }
    )


def _fail(code: str, message: str) -> NoReturn:
    raise PluginProtocolV1ToV2MigrationError(code, message)


__all__ = [
    "MigrationDecisionV1ToV2",
    "MigrationTargetHeadV1ToV2",
    "PluginProtocolV1ToV2Action",
    "PluginProtocolV1ToV2MigrationDocument",
    "PluginProtocolV1ToV2MigrationError",
    "bundle_reference_v2_to_payload",
    "parse_plugin_v1_to_v2_migration_document",
    "plugin_v1_to_v2_decision_output_digest",
]
