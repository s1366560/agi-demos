"""Multi-manifest generation tests for the protocol-v2 contract catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import generate_plugin_protocol_v2 as generator
from scripts.plugin_contract_catalog_v2 import (
    JSON_SCHEMA_DIALECT_V2,
    build_catalog_v2,
    build_event_graph_v2,
    build_service_graph_v2,
    contract_digest_v2,
    validate_manifest_collection_v2,
    validate_python_artifacts_v2,
)
from src.domain.model.plugins.artifact_attestation_v2 import (
    artifact_digest_v2,
    python_artifact_source_v2,
)

_ROOT = Path(__file__).resolve().parents[4]
_SCHEMA_PATH = _ROOT / "shared/schemas/plugins/platform-plugin-protocol.v2.schema.json"


def _event(name: str, *, mode: str = "serial") -> dict[str, object]:
    schema = {
        "$schema": JSON_SCHEMA_DIALECT_V2,
        "type": "object",
        "additionalProperties": False,
    }
    return {
        "event": name,
        "mode": mode,
        "payload_schema": schema,
        "result_schema": schema,
    }


def _contract(
    *,
    provides: tuple[str, ...] = (),
    requires: tuple[tuple[str, str], ...] = (),
    emits: tuple[dict[str, object], ...] = (),
    handles: tuple[dict[str, object], ...] = (),
) -> dict[str, Any]:
    return {
        "services": {
            "provides": [{"service": key, "version": "1.0.0"} for key in provides],
            "requires": [
                {"alias": alias, "service": key, "version": "1.0.0"} for alias, key in requires
            ],
        },
        "events": {"emits": list(emits), "handles": list(handles)},
        "config_schema": {
            "$schema": JSON_SCHEMA_DIALECT_V2,
            "type": "object",
            "additionalProperties": False,
        },
    }


def _module(module_ref: str, contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "module_ref": module_ref,
        "entrypoint": "src.example.plugin:apply",
        "artifact": {
            "digest": f"sha256:{'a' * 64}",
            "source": f"package://tests/{module_ref.rsplit('/', maxsplit=1)[-1]}",
        },
        "targets": ["python"],
        "contract": contract,
        "contract_digest": contract_digest_v2(contract),
    }


def _manifest(
    plugin_id: str,
    *modules: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "plugin_id": plugin_id,
        "version": "1.0.0",
        "runtime": "python-trusted",
        "trust": "builtin",
        "modules": list(modules),
        "permissions": [],
        "quotas": {},
    }


def _cross_manifest_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    event = _event("event:refresh")
    provider = _manifest(
        "alpha-provider",
        _module(
            "builtin://alpha/provider",
            _contract(provides=("service:clock",), handles=(event,)),
        ),
    )
    consumer = _manifest(
        "beta-consumer",
        _module(
            "builtin://beta/consumer",
            _contract(
                requires=(("clock", "service:clock"),),
                emits=(event,),
            ),
        ),
    )
    return provider, consumer


@pytest.mark.unit
def test_catalog_and_graphs_compose_all_manifests_deterministically() -> None:
    provider, consumer = _cross_manifest_pair()

    first = (consumer, provider)
    second = (provider, consumer)

    assert build_catalog_v2(first) == build_catalog_v2(second)
    assert [row["module_ref"] for row in build_catalog_v2(first)["modules"]] == [
        "builtin://alpha/provider",
        "builtin://beta/consumer",
    ]
    assert build_service_graph_v2(first)["edges"] == [
        {
            "alias": "clock",
            "consumer_module_ref": "builtin://beta/consumer",
            "provider_module_ref": "builtin://alpha/provider",
            "service": "service:clock",
            "version": "1.0.0",
        }
    ]
    assert build_event_graph_v2(first)["edges"][0]["emitter_module_ref"] == (
        "builtin://beta/consumer"
    )
    assert build_event_graph_v2(first)["edges"][0]["handler_module_ref"] == (
        "builtin://alpha/provider"
    )


@pytest.mark.unit
def test_manifest_collection_rejects_duplicate_module_ref() -> None:
    provider, _consumer = _cross_manifest_pair()
    duplicate = _manifest(
        "duplicate-provider",
        _module("builtin://alpha/provider", _contract()),
    )
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="duplicate module_ref"):
        validate_manifest_collection_v2((provider, duplicate), schema)
    with pytest.raises(ValueError, match="duplicate module_ref"):
        build_catalog_v2((provider, duplicate))


@pytest.mark.unit
def test_cross_manifest_event_contract_conflict_is_rejected() -> None:
    provider, _consumer = _cross_manifest_pair()
    conflicting = _manifest(
        "conflicting-consumer",
        _module(
            "builtin://conflicting/consumer",
            _contract(emits=(_event("event:refresh", mode="bail"),)),
        ),
    )

    with pytest.raises(ValueError, match="event event:refresh contract conflict"):
        build_event_graph_v2((provider, conflicting))


@pytest.mark.unit
def test_generator_loads_manifest_files_in_filename_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, consumer = _cross_manifest_pair()
    (tmp_path / "z-consumer.v2.json").write_text(json.dumps(consumer), encoding="utf-8")
    (tmp_path / "a-provider.v2.json").write_text(json.dumps(provider), encoding="utf-8")
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    monkeypatch.setattr(generator, "BUILTIN_MANIFEST_DIRECTORY", tmp_path)

    manifests = generator._builtin_manifest(schema, artifact_root=None)

    assert [manifest["plugin_id"] for manifest in manifests] == [
        "alpha-provider",
        "beta-consumer",
    ]


@pytest.mark.unit
def test_python_artifact_validation_binds_manifest_to_raw_entrypoint_bytes(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "src/example/plugin.py"
    source_path.parent.mkdir(parents=True)
    source_bytes = b"def apply(context, config):\n    return None\n"
    source_path.write_bytes(source_bytes)
    manifest = _manifest("artifact-owner", _module("builtin://artifact/owner", _contract()))
    module = manifest["modules"][0]
    module["artifact"] = {
        "digest": artifact_digest_v2(source_bytes),
        "source": python_artifact_source_v2(module["entrypoint"]),
    }

    validate_python_artifacts_v2((manifest,), tmp_path)

    module["artifact"]["digest"] = f"sha256:{'0' * 64}"
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        validate_python_artifacts_v2((manifest,), tmp_path)
