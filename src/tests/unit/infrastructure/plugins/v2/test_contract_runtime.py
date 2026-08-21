"""Contract-catalog preflight and runtime enforcement for plugin protocol v2."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.domain.model.plugins.generated_v2 import DataPlaneTargetV2
from src.infrastructure.plugins.v2.protocol import (
    PluginProtocolV2Error,
    canonical_json_v2,
    parse_plugin_manifest_v2,
    parse_profile_snapshot_v2,
)
from src.infrastructure.plugins.v2.runtime import (
    LoaderV2,
    PluginDefinitionV2,
    RuntimeV2Error,
)

_ROOT = Path(__file__).resolve().parents[6]
_CONFORMANCE = json.loads(
    (_ROOT / "shared/fixtures/plugin-contract-conformance.v2.json").read_text(encoding="utf-8")
)


def _snapshot():
    payload = json.loads(
        (_ROOT / "shared/fixtures/platform-plugin-profile.v2.json").read_text(encoding="utf-8")
    )
    return parse_profile_snapshot_v2(payload)


def _catalog(snapshot) -> dict[str, str]:
    return {
        module.module_ref: module.contract_digest
        for manifest in snapshot.manifests
        for module in manifest.modules
        if DataPlaneTargetV2.PYTHON in module.targets
    }


def _definitions(
    snapshot,
    *,
    root_apply,
    consumer_apply,
) -> tuple[PluginDefinitionV2, PluginDefinitionV2]:
    modules = {
        module.module_ref: module for manifest in snapshot.manifests for module in manifest.modules
    }
    return (
        PluginDefinitionV2(
            module_ref="builtin://conformance/root-provider",
            contract_digest=modules["builtin://conformance/root-provider"].contract_digest,
            apply=root_apply,
        ),
        PluginDefinitionV2(
            module_ref="builtin://conformance/session-consumer",
            contract_digest=modules["builtin://conformance/session-consumer"].contract_digest,
            apply=consumer_apply,
        ),
    )


def _apply_pointer(document: object, operation: dict[str, Any]) -> None:
    parts = [
        part.replace("~1", "/").replace("~0", "~") for part in operation["path"].split("/")[1:]
    ]
    parent = document
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    final = parts[-1]
    if operation["operation"] == "remove":
        if isinstance(parent, list):
            parent.pop(int(final))
        else:
            del parent[final]
        return
    value = deepcopy(operation["value"])
    if isinstance(parent, list):
        index = int(final)
        if operation["operation"] == "add":
            parent.insert(index, value)
        else:
            parent[index] = value
    else:
        parent[final] = value


def _mutated_snapshot_payload(case: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(
        (_ROOT / "shared/fixtures/platform-plugin-profile.v2.json").read_text(encoding="utf-8")
    )
    mutation = case["mutation"]
    operations = mutation.get("operations", [mutation])
    for operation in operations:
        _apply_pointer(payload, operation)
    if mutation.get("refresh_contract_digest"):
        for manifest in payload["manifests"]:
            for module in manifest["modules"]:
                module["contract_digest"] = (
                    "sha256:" + hashlib.sha256(canonical_json_v2(module["contract"])).hexdigest()
                )
    digest_payload = {key: value for key, value in payload.items() if key != "digest"}
    payload["digest"] = hashlib.sha256(canonical_json_v2(digest_payload)).hexdigest()
    return payload


def _conformance_definitions(snapshot) -> tuple[PluginDefinitionV2, PluginDefinitionV2]:
    def root_apply(context, _config) -> None:
        context.provide("service:clock", 7)

    def consumer_apply(context, _config) -> None:
        context.require("clock")

    return _definitions(
        snapshot,
        root_apply=root_apply,
        consumer_apply=consumer_apply,
    )


@pytest.mark.unit
@pytest.mark.parametrize("case", _CONFORMANCE["negative_cases"], ids=lambda item: item["name"])
async def test_shared_contract_negative_cases_have_stable_error_codes(
    case: dict[str, Any],
) -> None:
    payload = _mutated_snapshot_payload(case)
    expected = case["expected_error"]
    if expected in {
        "contract_digest_mismatch",
        "invalid_contract_schema",
        "event_contract_mismatch",
    }:
        with pytest.raises(PluginProtocolV2Error) as error:
            parse_profile_snapshot_v2(payload)
        assert error.value.code == expected
        return

    snapshot = parse_profile_snapshot_v2(payload)
    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(
            _conformance_definitions(snapshot),
            target_catalog=_catalog(snapshot),
        ).stage(snapshot)
    assert error.value.code == expected


@pytest.mark.unit
def test_standalone_manifest_rejects_conflicting_event_contracts() -> None:
    case = next(
        item
        for item in _CONFORMANCE["negative_cases"]
        if item["expected_error"] == "event_contract_mismatch"
    )
    payload = _mutated_snapshot_payload(case)

    with pytest.raises(PluginProtocolV2Error) as error:
        parse_plugin_manifest_v2(payload["manifests"][0])

    assert error.value.code == "event_contract_mismatch"


@pytest.mark.unit
async def test_loader_rejects_invalid_config_before_any_apply() -> None:
    snapshot = _snapshot()
    invalid_entry = snapshot.entries[0]
    object.__setattr__(invalid_entry, "config", {"label": ""})
    calls: list[str] = []
    definitions = _definitions(
        snapshot,
        root_apply=lambda _context, _config: calls.append("root"),
        consumer_apply=lambda _context, _config: calls.append("consumer"),
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(definitions, target_catalog=_catalog(snapshot)).stage(snapshot)

    assert error.value.code == "invalid_module_config"
    assert calls == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("inject", "expected_code"),
    [
        ({}, "missing_required_inject"),
        (
            {"clock": "service:clock", "extra": "service:clock"},
            "unexpected_inject",
        ),
        ({"clock": "service:other"}, "inject_service_mismatch"),
    ],
)
async def test_loader_requires_exact_declared_injects(
    inject: dict[str, str],
    expected_code: str,
) -> None:
    snapshot = _snapshot()
    object.__setattr__(snapshot.entries[1], "inject", inject)
    calls: list[str] = []
    definitions = _definitions(
        snapshot,
        root_apply=lambda _context, _config: calls.append("root"),
        consumer_apply=lambda _context, _config: calls.append("consumer"),
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(definitions, target_catalog=_catalog(snapshot)).stage(snapshot)

    assert error.value.code == expected_code
    assert calls == []


@pytest.mark.unit
async def test_loader_rejects_runtime_and_target_catalog_digest_mismatch_before_apply() -> None:
    snapshot = _snapshot()
    calls: list[str] = []
    definitions = list(
        _definitions(
            snapshot,
            root_apply=lambda _context, _config: calls.append("root"),
            consumer_apply=lambda _context, _config: calls.append("consumer"),
        )
    )
    definitions[0] = PluginDefinitionV2(
        module_ref=definitions[0].module_ref,
        contract_digest=f"sha256:{'0' * 64}",
        apply=definitions[0].apply,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(definitions, target_catalog=_catalog(snapshot)).stage(snapshot)

    assert error.value.code == "contract_digest_mismatch"
    assert calls == []

    definitions = list(
        _definitions(
            snapshot,
            root_apply=lambda _context, _config: calls.append("root"),
            consumer_apply=lambda _context, _config: calls.append("consumer"),
        )
    )
    catalog = _catalog(snapshot)
    catalog[definitions[0].module_ref] = f"sha256:{'1' * 64}"

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(definitions, target_catalog=catalog).stage(snapshot)

    assert error.value.code == "contract_digest_mismatch"
    assert calls == []


@pytest.mark.unit
async def test_loader_preserves_explicit_empty_target_catalog() -> None:
    snapshot = _snapshot()
    calls: list[str] = []
    definitions = _definitions(
        snapshot,
        root_apply=lambda _context, _config: calls.append("root"),
        consumer_apply=lambda _context, _config: calls.append("consumer"),
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(definitions, target_catalog={}).stage(snapshot)

    assert error.value.code == "missing_target_catalog"
    assert calls == []


@pytest.mark.unit
async def test_context_enforces_declared_service_operations() -> None:
    snapshot = _snapshot()

    def root_apply(context, _config) -> None:
        context.provide("service:undeclared", object())

    definitions = _definitions(
        snapshot,
        root_apply=root_apply,
        consumer_apply=lambda _context, _config: None,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(definitions, target_catalog=_catalog(snapshot)).stage(snapshot)

    assert error.value.code == "undeclared_provide"


@pytest.mark.unit
async def test_dispatch_uses_contract_mode_and_validates_payload_and_result() -> None:
    snapshot = _snapshot()
    contexts: dict[str, Any] = {}

    def root_apply(context, _config) -> None:
        context.provide("service:clock", 7)
        for event in ("notify", "audit"):
            context.on(event, lambda _value: [3])
            context.on(event, lambda _value: [4])
        context.on("choose", lambda _value: None)
        context.on("choose", lambda _value: "selected")

        async def plus_one(value: int, next_) -> object:
            return await next_(value + 1)

        async def times_two(value: int, next_) -> object:
            return await next_(value * 2)

        context.on("transform", plus_one)
        context.on("transform", times_two)

    def consumer_apply(context, _config) -> None:
        assert context.require("clock") == 7
        contexts["consumer"] = context

    definitions = _definitions(
        snapshot,
        root_apply=root_apply,
        consumer_apply=consumer_apply,
    )
    generation = await LoaderV2(
        definitions,
        target_catalog=_catalog(snapshot),
    ).stage(snapshot)
    context = contexts["consumer"]

    assert await context.dispatch("notify", {}) == ([3], [4])
    assert await context.dispatch("audit", {}) == ([3], [4])
    assert await context.dispatch("choose", None) == "selected"
    assert await context.dispatch("transform", 2) == 6
    with pytest.raises(RuntimeV2Error) as error:
        await context.dispatch("transform", "not-an-integer")
    assert error.value.code == "invalid_event_payload"
    with pytest.raises(RuntimeV2Error) as error:
        await context.dispatch("undeclared-event", {})
    assert error.value.code == "undeclared_event_dispatch"

    await generation.dispose()


@pytest.mark.unit
async def test_context_rejects_undeclared_handler_before_activation() -> None:
    snapshot = _snapshot()

    def root_apply(context, _config) -> None:
        context.provide("service:clock", 7)
        context.on("undeclared-event", lambda _value: None)

    definitions = _definitions(
        snapshot,
        root_apply=root_apply,
        consumer_apply=lambda context, _config: context.require("clock"),
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(definitions, target_catalog=_catalog(snapshot)).stage(snapshot)

    assert error.value.code == "undeclared_event_handler"
