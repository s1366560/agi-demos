"""Strict structural helpers for protocol-v2 hierarchical scopes."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, cast

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

from .protocol import PluginProtocolV2Error, canonical_json_v2

_SCOPE_FIELDS_V2 = frozenset({"kind", "tenant_id", "project_id", "session_id"})
_SCOPE_ID_FIELDS_V2 = ("tenant_id", "project_id", "session_id")
MAX_SCOPE_ID_LENGTH_V2 = 255


def parse_scope_v2(payload: object) -> ScopeV2:
    """Parse one exact root -> tenant -> project -> session scope."""
    if not isinstance(payload, Mapping):
        raise PluginProtocolV2Error("invalid_scope", "scope must be an object")
    raw = cast(Mapping[str, Any], payload)
    if set(raw) - _SCOPE_FIELDS_V2 or "kind" not in raw:
        raise PluginProtocolV2Error("invalid_scope", "scope has invalid fields")
    try:
        kind = ScopeKindV2(raw["kind"])
    except (TypeError, ValueError) as exc:
        raise PluginProtocolV2Error("invalid_scope", "scope kind is invalid") from exc
    identifiers: dict[str, str | None] = {}
    for field in _SCOPE_ID_FIELDS_V2:
        value = raw.get(field)
        if value is not None and (
            not isinstance(value, str) or not value.strip() or len(value) > MAX_SCOPE_ID_LENGTH_V2
        ):
            raise PluginProtocolV2Error(
                "invalid_scope",
                f"scope {field} must be a non-empty string no longer than 255 characters",
            )
        identifiers[field] = value
    scope = ScopeV2(kind=kind, **identifiers)
    if not _scope_is_consistent_v2(scope):
        raise PluginProtocolV2Error(
            "invalid_scope",
            f"scope identifiers are inconsistent with {kind.value} scope",
        )
    return scope


def validate_scope_v2(scope: ScopeV2) -> ScopeV2:
    """Validate a typed scope and return its canonical representation."""
    try:
        payload = scope_v2_to_payload(scope)
    except (AttributeError, TypeError, ValueError) as exc:
        raise PluginProtocolV2Error("invalid_scope", "scope is invalid") from exc
    return parse_scope_v2(payload)


def scope_v2_to_payload(scope: ScopeV2) -> dict[str, str]:
    """Return the minimal JSON representation of a typed scope."""
    payload = {"kind": scope.kind.value}
    for field in _SCOPE_ID_FIELDS_V2:
        value = getattr(scope, field)
        if value is not None:
            payload[field] = value
    return payload


def scope_key_v2(scope: ScopeV2) -> str:
    """Return an unambiguous fixed-width key for one validated scope."""
    canonical = validate_scope_v2(scope)
    return hashlib.sha256(canonical_json_v2(scope_v2_to_payload(canonical))).hexdigest()


def _scope_is_consistent_v2(scope: ScopeV2) -> bool:
    tenant = scope.tenant_id
    project = scope.project_id
    session = scope.session_id
    return (
        (scope.kind is ScopeKindV2.ROOT and tenant is None and project is None and session is None)
        or (
            scope.kind is ScopeKindV2.TENANT
            and tenant is not None
            and project is None
            and session is None
        )
        or (
            scope.kind is ScopeKindV2.PROJECT
            and tenant is not None
            and project is not None
            and session is None
        )
        or (
            scope.kind is ScopeKindV2.SESSION
            and tenant is not None
            and project is not None
            and session is not None
        )
    )


__all__ = [
    "MAX_SCOPE_ID_LENGTH_V2",
    "parse_scope_v2",
    "scope_key_v2",
    "scope_v2_to_payload",
    "validate_scope_v2",
]
