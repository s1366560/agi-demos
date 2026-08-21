"""Structural completeness tests for the generated plugin-v2 contract catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_plugin_contract_completeness_v2 import check_repository


def _contract(
    *,
    provides: tuple[str, ...] = (),
    requires: tuple[tuple[str, str], ...] = (),
    handles: tuple[str, ...] = (),
    emits: tuple[str, ...] = (),
) -> dict[str, object]:
    event_schema = {"type": "object", "additionalProperties": False}

    def event(name: str) -> dict[str, object]:
        return {
            "event": name,
            "mode": "serial",
            "payload_schema": event_schema,
            "result_schema": event_schema,
        }

    return {
        "services": {
            "provides": [{"service": service, "version": "1.0.0"} for service in provides],
            "requires": [
                {"alias": alias, "service": service, "version": "1.0.0"}
                for alias, service in requires
            ],
        },
        "events": {
            "emits": [event(name) for name in emits],
            "handles": [event(name) for name in handles],
        },
        "config_schema": {"type": "object", "additionalProperties": False},
    }


def _write_repository(
    root: Path,
    *,
    source: str,
    contract: dict[str, object],
    targets: tuple[str, ...] = ("python",),
    catalog_targets: tuple[str, ...] | None = None,
    entrypoint: str = "src.example.plugin:apply",
    generator_exit_code: int = 0,
) -> None:
    module = {
        "module_ref": "builtin://example/module",
        "entrypoint": entrypoint,
        "artifact": {
            "digest": f"sha256:{'a' * 64}",
            "source": "package://builtin/example",
        },
        "targets": list(targets),
        "contract": contract,
        "contract_digest": f"sha256:{'b' * 64}",
    }
    manifest = {
        "schema_version": 2,
        "plugin_id": "example",
        "version": "1.0.0",
        "runtime": "python-trusted",
        "trust": "builtin",
        "modules": [module],
        "permissions": [],
        "quotas": {},
    }
    catalog_module = {
        "plugin_id": manifest["plugin_id"],
        "plugin_version": manifest["version"],
        "module_ref": module["module_ref"],
        "entrypoint": module["entrypoint"],
        "artifact_digest": module["artifact"]["digest"],
        "targets": list(catalog_targets if catalog_targets is not None else targets),
        "contract": contract,
        "contract_digest": module["contract_digest"],
    }
    catalog = {
        "schema_version": 2,
        "catalog_digest": f"sha256:{'c' * 64}",
        "modules": [catalog_module],
    }

    manifest_path = root / "config/plugin-manifests-v2/example.v2.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    catalog_path = root / "shared/catalogs/plugin-module-catalog.v2.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    source_path = root / "src/example/plugin.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(source, encoding="utf-8")
    generator_path = root / "scripts/generate_plugin_protocol_v2.py"
    generator_path.parent.mkdir(parents=True)
    generator_path.write_text(
        f"raise SystemExit({generator_exit_code})\n",
        encoding="utf-8",
    )


@pytest.mark.unit
def test_declared_context_calls_and_generated_catalog_are_complete(tmp_path: Path) -> None:
    contract = _contract(
        provides=("service:clock",),
        requires=(("database", "service:database"),),
        handles=("event:changed",),
        emits=("event:requested",),
    )
    _write_repository(
        tmp_path,
        contract=contract,
        source="""
CLOCK_SERVICE = "service:clock"
DATABASE_ALIAS = "database"
CHANGED_EVENT = "event:changed"
REQUESTED_EVENT = "event:requested"

def apply(context: ContextV2, _config: object) -> None:
    context.provide(CLOCK_SERVICE, object())
    context.require(DATABASE_ALIAS)
    context.on(CHANGED_EVENT, lambda payload: None)
    context.dispatch(REQUESTED_EVENT, {})
""",
    )

    assert check_repository(tmp_path) == ()


@pytest.mark.unit
def test_statically_imported_string_constant_is_classified(tmp_path: Path) -> None:
    _write_repository(
        tmp_path,
        contract=_contract(requires=(("database", "service:database"),)),
        source="""
from .constants import DATABASE_ALIAS

def apply(context: ContextV2, _config: object) -> None:
    context.require(DATABASE_ALIAS)
""",
    )
    (tmp_path / "src/example/constants.py").write_text(
        'DATABASE_ALIAS = "database"\n',
        encoding="utf-8",
    )

    assert check_repository(tmp_path) == ()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("call", "detail"),
    [
        ('context.provide("service:other", object())', "provide service:other"),
        ('context.require("other")', "require other"),
        ('context.on("event:other", lambda payload: None)', "on event:other"),
        ('context.dispatch("event:other", {})', "dispatch event:other"),
    ],
)
def test_undeclared_context_call_fails(tmp_path: Path, call: str, detail: str) -> None:
    _write_repository(
        tmp_path,
        contract=_contract(),
        source=f"""
def apply(context: ContextV2, _config: object) -> None:
    {call}
""",
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["undeclared_context_call"]
    assert detail in issues[0].detail


@pytest.mark.unit
def test_dynamic_context_call_is_unclassified_and_fails(tmp_path: Path) -> None:
    _write_repository(
        tmp_path,
        contract=_contract(provides=("service:clock",)),
        source="""
def apply(context: ContextV2, _config: object) -> None:
    service = "service:clock"
    context.provide(service, object())
""",
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["unclassified_context_call"]
    assert "provide" in issues[0].detail


@pytest.mark.unit
def test_factory_entrypoint_follows_static_apply_reference(tmp_path: Path) -> None:
    _write_repository(
        tmp_path,
        contract=_contract(),
        entrypoint="src.example.plugin:definition",
        source="""
def _apply(context: ContextV2, _config: object) -> None:
    context.provide("service:undeclared", object())

def definition() -> PluginDefinitionV2:
    return PluginDefinitionV2(module_ref="builtin://example/module", apply=_apply)
""",
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["undeclared_context_call"]
    assert "provide service:undeclared" in issues[0].detail


@pytest.mark.unit
def test_apply_reachable_local_helper_is_checked(tmp_path: Path) -> None:
    _write_repository(
        tmp_path,
        contract=_contract(),
        source="""
def _register(context: ContextV2) -> None:
    context.provide("service:undeclared", object())

def apply(context: ContextV2, _config: object) -> None:
    _register(context)
""",
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["undeclared_context_call"]
    assert "provide service:undeclared" in issues[0].detail


@pytest.mark.unit
def test_operation_context_dispatch_requires_global_emitter_contract(tmp_path: Path) -> None:
    _write_repository(
        tmp_path,
        contract=_contract(),
        source="def apply(context: ContextV2, _config: object) -> None:\n    pass\n",
    )
    consumer_path = tmp_path / "src/example/consumer.py"
    consumer_path.write_text(
        """
async def publish(operation: OperationContextV2) -> None:
    await operation.dispatch("event:undeclared", {})
""",
        encoding="utf-8",
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["undeclared_operation_event"]
    assert "event:undeclared" in issues[0].detail
    assert issues[0].path == "src/example/consumer.py"


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        """
async def publish() -> None:
    operation = current_operation_context_v2()
    await operation.dispatch("event:undeclared", {})
""",
        """
async def publish() -> None:
    await current_operation_context_v2().dispatch("event:undeclared", {})
""",
        """
async def publish() -> None:
    async with pin_operation_context_v2() as operation:
        await operation.dispatch("event:undeclared", {})
""",
        """
async def publish() -> None:
    async with pin_agent_turn_operation_v2() as operation:
        await operation.dispatch("event:undeclared", {})
""",
    ],
)
def test_operation_context_factory_dispatch_is_checked(tmp_path: Path, source: str) -> None:
    _write_repository(
        tmp_path,
        contract=_contract(),
        source="def apply(context: ContextV2, _config: object) -> None:\n    pass\n",
    )
    consumer_path = tmp_path / "src/example/consumer.py"
    consumer_path.write_text(source, encoding="utf-8")

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["undeclared_operation_event"]


@pytest.mark.unit
def test_dynamic_operation_context_event_is_unclassified(tmp_path: Path) -> None:
    _write_repository(
        tmp_path,
        contract=_contract(emits=("event:declared",)),
        source="def apply(context: ContextV2, _config: object) -> None:\n    pass\n",
    )
    consumer_path = tmp_path / "src/example/consumer.py"
    consumer_path.write_text(
        """
async def publish(operation: OperationContextV2, event: str) -> None:
    await operation.dispatch(event, {})
""",
        encoding="utf-8",
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["unclassified_operation_event"]


@pytest.mark.unit
def test_operation_context_dispatch_accepts_declared_global_emitter(tmp_path: Path) -> None:
    _write_repository(
        tmp_path,
        contract=_contract(emits=("event:declared",)),
        source="def apply(context: ContextV2, _config: object) -> None:\n    pass\n",
    )
    consumer_path = tmp_path / "src/example/consumer.py"
    consumer_path.write_text(
        """
async def publish(operation: OperationContextV2) -> None:
    await operation.dispatch("event:declared", {})
""",
        encoding="utf-8",
    )

    assert check_repository(tmp_path) == ()


@pytest.mark.unit
def test_manifest_target_must_exist_in_generated_catalog(tmp_path: Path) -> None:
    _write_repository(
        tmp_path,
        contract=_contract(),
        source="def apply(context: ContextV2, _config: object) -> None:\n    pass\n",
        catalog_targets=("web",),
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["missing_target_catalog"]
    assert "python" in issues[0].detail


@pytest.mark.unit
def test_stale_generator_output_fails_completeness_gate(tmp_path: Path) -> None:
    _write_repository(
        tmp_path,
        contract=_contract(),
        source="def apply(context: ContextV2, _config: object) -> None:\n    pass\n",
        generator_exit_code=1,
    )

    issues = check_repository(tmp_path)

    assert [issue.code for issue in issues] == ["generated_outputs_stale"]
