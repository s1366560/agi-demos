"""Production profile composition tests for protocol v2."""

from __future__ import annotations

import hashlib
from copy import deepcopy

import pytest
import rfc8785

from src.infrastructure.plugins.v2.composer import (
    ProfileCompositionV2Error,
    compose_profile_v2,
    parse_profile_document_v2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2


def _manifest_payload() -> dict:
    config_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
    }

    def module(module_ref: str, *, provider: bool) -> dict:
        contract = {
            "services": {
                "provides": (
                    [{"service": "service:runtime", "version": "1.0.0"}] if provider else []
                ),
                "requires": (
                    []
                    if provider
                    else [
                        {
                            "alias": "runtime",
                            "service": "service:runtime",
                            "version": "1.0.0",
                        }
                    ]
                ),
            },
            "events": {"emits": [], "handles": []},
            "config_schema": config_schema,
        }
        return {
            "module_ref": module_ref,
            "entrypoint": "runtime:provider" if provider else "runtime:consumer",
            "targets": ["python"],
            "contract": contract,
            "contract_digest": "sha256:" + hashlib.sha256(rfc8785.dumps(contract)).hexdigest(),
            "artifact": {
                "digest": "sha256:" + "a" * 64,
                "source": "package://builtin/runtime-spine",
            },
        }

    return {
        "schema_version": 2,
        "plugin_id": "runtime-spine",
        "version": "1.0.0",
        "runtime": "python-trusted",
        "trust": "builtin",
        "modules": [
            module("builtin://runtime/provider", provider=True),
            module("builtin://runtime/consumer", provider=False),
        ],
        "permissions": ["runtime.read"],
        "quotas": {},
    }


def _entry(
    entry_id: str,
    module_ref: str,
    *,
    parent_entry_id: str | None = None,
    config: dict | None = None,
    inject: dict | None = None,
) -> dict:
    return {
        "entry_id": entry_id,
        "parent_entry_id": parent_entry_id,
        "plugin_ref": "runtime-spine",
        "module_ref": module_ref,
        "enabled": True,
        "config": config or {},
        "inject": inject or {},
        "isolate": {},
        "scope": {"kind": "root"},
        "permissions": [],
        "quotas": {},
        "restart_policy": "hot-generation",
    }


def _document_payload() -> dict:
    return {
        "schema_version": 2,
        "profile": {
            "id": "memstack-default-v2",
            "entries": [
                _entry(
                    "provider",
                    "builtin://runtime/provider",
                    config={"old": True, "nested": {"keep": False}},
                ),
                _entry(
                    "consumer",
                    "builtin://runtime/consumer",
                    parent_entry_id="provider",
                    inject={"runtime": "service:runtime"},
                ),
            ],
        },
        "patches": [],
    }


def test_v2_document_rejects_v1_and_unknown_fields() -> None:
    payload = _document_payload()
    payload["schema_version"] = 1
    with pytest.raises(ProfileCompositionV2Error, match="schema_version must be 2"):
        parse_profile_document_v2(payload)

    payload = _document_payload()
    payload["unexpected"] = True
    with pytest.raises(ProfileCompositionV2Error, match="unknown fields"):
        parse_profile_document_v2(payload)


def test_patch_replaces_the_complete_entry_without_deep_merge() -> None:
    payload = _document_payload()
    replacement = _entry(
        "provider",
        "builtin://runtime/provider",
        config={"new": True},
    )
    payload["patches"] = [{"target": "provider", "replacement": replacement}]

    document = parse_profile_document_v2(payload)
    snapshot = compose_profile_v2(
        document,
        {"runtime-spine": parse_plugin_manifest_v2(_manifest_payload())},
        generation=4,
    )

    assert snapshot.generation == 4
    assert snapshot.entries[0].entry_id == "provider"
    assert snapshot.entries[0].config == {"new": True}
    assert "old" not in snapshot.entries[0].config


def test_patch_remove_preserves_remaining_entry_order() -> None:
    payload = _document_payload()
    payload["patches"] = [{"target": "consumer", "remove": True}]

    snapshot = compose_profile_v2(
        parse_profile_document_v2(payload),
        {"runtime-spine": parse_plugin_manifest_v2(_manifest_payload())},
        generation=1,
    )

    assert [entry.entry_id for entry in snapshot.entries] == ["provider"]


def test_patch_requires_existing_target_and_one_operation() -> None:
    payload = _document_payload()
    payload["patches"] = [{"target": "missing", "remove": True}]
    with pytest.raises(ProfileCompositionV2Error, match="unknown entry missing"):
        parse_profile_document_v2(payload)

    payload = _document_payload()
    payload["patches"] = [
        {
            "target": "provider",
            "remove": True,
            "replacement": _entry("provider", "builtin://runtime/provider"),
        }
    ]
    with pytest.raises(ProfileCompositionV2Error, match="exactly one"):
        parse_profile_document_v2(payload)


def test_composition_rejects_undeclared_entry_permission() -> None:
    payload = _document_payload()
    payload["profile"]["entries"][0]["permissions"] = ["runtime.admin"]

    with pytest.raises(ProfileCompositionV2Error, match="undeclared permissions"):
        compose_profile_v2(
            parse_profile_document_v2(payload),
            {"runtime-spine": parse_plugin_manifest_v2(_manifest_payload())},
            generation=1,
        )


def test_composition_is_deterministic_and_does_not_mutate_input() -> None:
    payload = _document_payload()
    original = deepcopy(payload)
    manifest = parse_plugin_manifest_v2(_manifest_payload())

    first = compose_profile_v2(
        parse_profile_document_v2(payload),
        {"runtime-spine": manifest},
        generation=9,
    )
    second = compose_profile_v2(
        parse_profile_document_v2(payload),
        {"runtime-spine": manifest},
        generation=9,
    )

    assert first == second
    assert payload == original
