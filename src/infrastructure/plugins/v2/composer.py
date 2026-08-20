"""Strict v2 profile document parsing and deterministic snapshot composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import yaml

from src.domain.model.plugins.generated_v2 import (
    PluginManifestV2,
    ProfileEntryV2,
    ProfileSnapshotV2,
    QuotaV2,
    RestartPolicyV2,
    ScopeKindV2,
    ScopeV2,
)

from .protocol import PluginProtocolV2Error, build_profile_snapshot_v2

_DOCUMENT_FIELDS = frozenset({"schema_version", "profile", "patches"})
_PROFILE_FIELDS = frozenset({"id", "entries"})
_PATCH_FIELDS = frozenset({"target", "replacement", "remove"})
_ENTRY_FIELDS = frozenset(
    {
        "entry_id",
        "parent_entry_id",
        "plugin_ref",
        "module_ref",
        "enabled",
        "config",
        "inject",
        "isolate",
        "scope",
        "permissions",
        "quotas",
        "restart_policy",
    }
)
_SCOPE_FIELDS = frozenset({"kind", "tenant_id", "project_id", "session_id"})
_QUOTA_FIELDS = frozenset(QuotaV2.__dataclass_fields__)


class ProfileCompositionV2Error(ValueError):
    """A strict v2 profile rejection with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class ProfilePatchV2:
    """A destructive whole-row replacement or removal."""

    target: str
    replacement: ProfileEntryV2 | None = None
    remove: bool = False


@dataclass(frozen=True, kw_only=True)
class ProfileDocumentV2:
    """A parsed v2 profile before manifest and digest validation."""

    profile_id: str
    entries: tuple[ProfileEntryV2, ...]
    patches: tuple[ProfilePatchV2, ...] = ()


def load_profile_document_v2(path: str | Path) -> ProfileDocumentV2:
    """Load one v2 YAML/JSON profile document."""
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        _fail("profile_load_failed", f"failed to load v2 profile {path}: {exc}")
    return parse_profile_document_v2(payload)


def parse_profile_document_v2(payload: object) -> ProfileDocumentV2:
    """Parse only schema v2; unknown fields and v1 inputs fail explicitly."""
    root = _mapping(payload, "profile document")
    if root.get("schema_version") != 2:
        _fail(
            "incompatible_schema_version",
            "profile document schema_version must be 2; v1 is not accepted",
        )
    _reject_unknown(root, _DOCUMENT_FIELDS, "profile document")
    profile = _mapping(root.get("profile"), "profile")
    _reject_unknown(profile, _PROFILE_FIELDS, "profile")
    profile_id = _non_empty_string(profile.get("id"), "profile.id")
    raw_entries = _sequence(profile.get("entries"), "profile.entries")
    entries = tuple(
        _parse_entry(item, f"profile.entries[{index}]") for index, item in enumerate(raw_entries)
    )
    entry_ids = [entry.entry_id for entry in entries]
    if len(entry_ids) != len(set(entry_ids)):
        _fail("duplicate_entry_id", "profile entries must have unique entry_id values")

    raw_patches = _sequence(root.get("patches", []), "patches")
    patches = tuple(_parse_patch(item, index) for index, item in enumerate(raw_patches))
    known = set(entry_ids)
    for patch in patches:
        if patch.target not in known:
            _fail("unknown_patch_target", f"patch targets unknown entry {patch.target}")
        if patch.remove:
            known.remove(patch.target)
        elif patch.replacement is not None and patch.replacement.entry_id != patch.target:
            _fail(
                "patch_entry_id_mismatch",
                f"patch target {patch.target} replacement entry_id must match target",
            )
    return ProfileDocumentV2(profile_id=profile_id, entries=entries, patches=patches)


def compose_profile_v2(
    document: ProfileDocumentV2,
    manifests: Mapping[str, PluginManifestV2],
    *,
    generation: int,
) -> ProfileSnapshotV2:
    """Apply whole-row patches and build one canonical v2 snapshot."""
    rows = list(document.entries)
    positions = {entry.entry_id: index for index, entry in enumerate(rows)}
    for patch in document.patches:
        index = positions[patch.target]
        if patch.remove:
            rows.pop(index)
        else:
            replacement = patch.replacement
            if replacement is None:  # pragma: no cover - parser invariant
                _fail("invalid_patch", f"patch {patch.target} has no replacement")
            rows[index] = replacement
        positions = {entry.entry_id: position for position, entry in enumerate(rows)}

    referenced: dict[str, PluginManifestV2] = {}
    for entry in rows:
        manifest = manifests.get(entry.plugin_ref)
        if manifest is None:
            _fail(
                "missing_manifest",
                f"entry {entry.entry_id} references missing manifest {entry.plugin_ref}",
            )
        undeclared = sorted(set(entry.permissions) - set(manifest.permissions))
        if undeclared:
            _fail(
                "undeclared_entry_permission",
                f"entry {entry.entry_id} requests undeclared permissions: {', '.join(undeclared)}",
            )
        referenced[manifest.plugin_id] = manifest

    try:
        return build_profile_snapshot_v2(
            profile_id=document.profile_id,
            generation=generation,
            manifests=tuple(referenced[key] for key in sorted(referenced)),
            entries=tuple(rows),
        )
    except PluginProtocolV2Error as exc:
        raise ProfileCompositionV2Error(exc.code, str(exc)) from exc


def _parse_patch(value: object, index: int) -> ProfilePatchV2:
    location = f"patches[{index}]"
    payload = _mapping(value, location)
    _reject_unknown(payload, _PATCH_FIELDS, location)
    target = _non_empty_string(payload.get("target"), f"{location}.target")
    remove = payload.get("remove", False)
    if not isinstance(remove, bool):
        _fail("invalid_patch", f"{location}.remove must be boolean")
    has_replacement = "replacement" in payload
    if int(remove) + int(has_replacement) != 1:
        _fail("invalid_patch", f"{location} must specify exactly one of remove or replacement")
    replacement = (
        _parse_entry(payload["replacement"], f"{location}.replacement") if has_replacement else None
    )
    return ProfilePatchV2(target=target, replacement=replacement, remove=remove)


def _parse_entry(value: object, location: str) -> ProfileEntryV2:
    payload = _mapping(value, location)
    _reject_unknown(payload, _ENTRY_FIELDS, location)
    missing = sorted(_ENTRY_FIELDS - payload.keys())
    if missing:
        _fail("missing_entry_field", f"{location} is missing fields: {', '.join(missing)}")
    try:
        return ProfileEntryV2(
            entry_id=_non_empty_string(payload["entry_id"], f"{location}.entry_id"),
            parent_entry_id=_optional_string(
                payload["parent_entry_id"], f"{location}.parent_entry_id"
            ),
            plugin_ref=_non_empty_string(payload["plugin_ref"], f"{location}.plugin_ref"),
            module_ref=_non_empty_string(payload["module_ref"], f"{location}.module_ref"),
            enabled=_boolean(payload["enabled"], f"{location}.enabled"),
            config=dict(_mapping(payload["config"], f"{location}.config")),
            inject=_string_mapping(payload["inject"], f"{location}.inject"),
            isolate=_string_mapping(payload["isolate"], f"{location}.isolate"),
            scope=_parse_scope(payload["scope"], f"{location}.scope"),
            permissions=_string_tuple(payload["permissions"], f"{location}.permissions"),
            quotas=_parse_quotas(payload["quotas"], f"{location}.quotas"),
            restart_policy=RestartPolicyV2(payload["restart_policy"]),
        )
    except ValueError as exc:
        raise ProfileCompositionV2Error("invalid_entry", f"{location}: {exc}") from exc


def _parse_scope(value: object, location: str) -> ScopeV2:
    payload = _mapping(value, location)
    _reject_unknown(payload, _SCOPE_FIELDS, location)
    try:
        return ScopeV2(
            kind=ScopeKindV2(_non_empty_string(payload.get("kind"), f"{location}.kind")),
            tenant_id=_optional_string(payload.get("tenant_id"), f"{location}.tenant_id"),
            project_id=_optional_string(payload.get("project_id"), f"{location}.project_id"),
            session_id=_optional_string(payload.get("session_id"), f"{location}.session_id"),
        )
    except ValueError as exc:
        raise ProfileCompositionV2Error("invalid_scope", f"{location}: {exc}") from exc


def _parse_quotas(value: object, location: str) -> QuotaV2:
    payload = _mapping(value, location)
    _reject_unknown(payload, _QUOTA_FIELDS, location)
    for key, item in payload.items():
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            _fail("invalid_quota", f"{location}.{key} must be a non-negative integer")
    return QuotaV2(**payload)


def _mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        _fail("invalid_profile_document", f"{location} must be an object")
    return value


def _sequence(value: object, location: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        _fail("invalid_profile_document", f"{location} must be an array")
    return value


def _reject_unknown(payload: Mapping[str, Any], allowed: frozenset[str], location: str) -> None:
    unknown = sorted(payload.keys() - allowed)
    if unknown:
        _fail("unknown_field", f"{location} has unknown fields: {', '.join(unknown)}")


def _non_empty_string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("invalid_string", f"{location} must be a non-empty string")
    return value


def _optional_string(value: object, location: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, location)


def _boolean(value: object, location: str) -> bool:
    if not isinstance(value, bool):
        _fail("invalid_boolean", f"{location} must be boolean")
    return value


def _string_mapping(value: object, location: str) -> dict[str, str]:
    payload = _mapping(value, location)
    result: dict[str, str] = {}
    for key, item in payload.items():
        result[key] = _non_empty_string(item, f"{location}.{key}")
    return result


def _string_tuple(value: object, location: str) -> tuple[str, ...]:
    values = _sequence(value, location)
    return tuple(
        _non_empty_string(item, f"{location}[{index}]") for index, item in enumerate(values)
    )


def _fail(code: str, message: str) -> NoReturn:
    raise ProfileCompositionV2Error(code, message)
