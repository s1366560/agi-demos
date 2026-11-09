"""Executable lifecycle for a signed package that is not a builtin catalog row."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import wasmtime
from memstack_plugin_sdk.contract import parse_contribution, sha256_digest

from src.infrastructure.plugins.v2.plugin_namespace_store_v2 import (
    NamespaceKeyV2,
    NamespaceRecordV2,
    PluginStorageError,
    assert_supported_schema_v2,
)
from src.infrastructure.plugins.v2.scan_evidence_v2 import (
    ScannerReportV2,
    resolve_security_scan_status_v2,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
    SignedOptionalBusinessRuntimeV2,
    SignedPackageBytesV2,
    load_contribution_v2,
)

SAMPLE = Path(__file__).resolve().parents[6] / "samples" / "optional-business-plugin"
PING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["op"],
    "properties": {"op": {"const": "ping"}},
}
PING_OUTPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ok", "op"],
    "properties": {"ok": {"const": True}, "op": {"const": "ping"}},
}


def _package(
    *,
    version: str = "1.0.0",
    approved: frozenset[str] | None = None,
    extra_permission: str | None = None,
    wasm: bytes | None = None,
) -> SignedPackageBytesV2:
    ui = (SAMPLE / "ui.json").read_bytes()
    wat = (SAMPLE / "tool.wat").read_text(encoding="utf-8")
    module = wasm if wasm is not None else wasmtime.wat2wasm(wat)
    permissions = ["tools.execute", "skills.register", "ui.slot", "storage.read", "storage.write"]
    if extra_permission is not None:
        permissions.append(extra_permission)
    contribution = parse_contribution(
        {
            "schema": "memstack.plugin.contributions/1",
            "tools": [
                {
                    "name": "note.ping",
                    "abi": "invoke",
                    "input_schema": PING_SCHEMA,
                    "output_schema": PING_OUTPUT,
                    "permissions": ["tools.execute"],
                }
            ],
            "skills": [
                {
                    "id": "note-skill",
                    "instructions": "Store a short note through the host.",
                    "permissions": ["skills.register"],
                }
            ],
            "ui": [
                {
                    "slot": "tool_result_renderer",
                    "path": "ui.json",
                    "digest": sha256_digest(ui),
                    "targets": ["web", "desktop-renderer"],
                    "permissions": ["ui.slot"],
                }
            ],
            "storage": {"schema_version": 1, "permissions": ["storage.read", "storage.write"]},
        }
    )
    grant = approved if approved is not None else frozenset(permissions)
    return SignedPackageBytesV2(
        plugin_id="sample.notes",
        version=version,
        digest=f"sha256:{version}",
        wasm=module,
        contribution=contribution,
        ui_files={"ui.json": ui},
        approved_permissions=grant,
    )


def _runtime(**kwargs: object) -> SignedOptionalBusinessRuntimeV2:
    runtime = SignedOptionalBusinessRuntimeV2(**kwargs)  # type: ignore[arg-type]
    return runtime


@pytest.mark.unit
def test_sample_package_runs_without_a_builtin_catalog_row() -> None:
    runtime = _runtime()
    package = _package()
    runtime.record(package)
    scope = ScopeBindingV2(tenant_id="tenant-a", project_id="project-a")
    session = runtime.session(package.plugin_id, scope)
    with pytest.raises(OptionalBusinessError, match="not enabled"):
        session.invoke("note.ping", {"op": "ping"})
    runtime.enable(package.plugin_id)
    assert session.invoke("note.ping", {"op": "ping"}) == {"ok": True, "op": "ping"}
    assert session.skills() == ("note-skill",)
    mounted = session.mount_ui("tool_result_renderer", "web")
    assert mounted["title"] == "Notes"
    assert mounted["actions"][0]["id"] == "save"
    session.storage_put("last", {"text": "hello"})
    assert session.storage_get("last") == {"text": "hello"}
    other = runtime.session(
        package.plugin_id, ScopeBindingV2(tenant_id="tenant-b", project_id="project-a")
    )
    assert other.storage_get("last") is None
    projection = runtime.projection(package.plugin_id)
    assert projection.runtime_phase == "active"
    assert projection.ui_mounted is True
    assert projection.desired_enabled is True
    session.dispose_ui()
    assert runtime.projection(package.plugin_id).ui_mounted is False


@pytest.mark.unit
def test_unapproved_permission_never_executes_and_upgrade_keeps_previous() -> None:
    runtime = _runtime()
    package = _package(approved=frozenset({"tools.execute"}))
    with pytest.raises(OptionalBusinessError, match="lacks approval"):
        runtime.record(package)
    granted = _package()
    runtime.record(granted)
    runtime.enable(granted.plugin_id)
    upgraded = _package(version="2.0.0")
    upgraded = SignedPackageBytesV2(
        plugin_id=upgraded.plugin_id,
        version="2.0.0",
        digest="sha256:2.0.0",
        wasm=upgraded.wasm,
        contribution=load_contribution_v2(
            {
                "schema": "memstack.plugin.contributions/1",
                "tools": [
                    {
                        "name": "note.ping",
                        "abi": "invoke",
                        "input_schema": PING_SCHEMA,
                        "output_schema": PING_OUTPUT,
                        "permissions": ["tools.execute", "storage.write"],
                    }
                ],
            }
        ),
        ui_files={},
        approved_permissions=frozenset({"tools.execute"}),
    )
    with pytest.raises(OptionalBusinessError, match="lacks approval"):
        runtime.stage_update(upgraded)
    assert runtime.projection(granted.plugin_id).actual_digest == "sha256:1.0.0"


@pytest.mark.unit
def test_failed_update_and_user_rollback_keep_a_verified_generation() -> None:
    runtime = _runtime()
    first = _package()
    runtime.record(first)
    runtime.enable(first.plugin_id)
    broken = SignedPackageBytesV2(
        plugin_id=first.plugin_id,
        version="2.0.0",
        digest="sha256:2.0.0",
        wasm=b"not-wasm",
        contribution=first.contribution,
        ui_files=first.ui_files,
        approved_permissions=first.approved_permissions,
    )
    with pytest.raises(OptionalBusinessError, match="not a module"):
        runtime.stage_update(broken)
    scope = ScopeBindingV2(tenant_id="tenant-a", project_id="project-a")
    assert runtime.session(first.plugin_id, scope).invoke("note.ping", {"op": "ping"})["ok"] is True
    second = _package(version="1.1.0")
    second = SignedPackageBytesV2(
        plugin_id=second.plugin_id,
        version="1.1.0",
        digest="sha256:1.1.0",
        wasm=second.wasm,
        contribution=second.contribution,
        ui_files=second.ui_files,
        approved_permissions=second.approved_permissions,
    )
    runtime.stage_update(second)
    before = runtime.projection(first.plugin_id).desired_revision
    projection = runtime.rollback(first.plugin_id)
    assert projection.actual_digest == "sha256:1.0.0"
    assert projection.desired_revision == before + 1
    assert runtime.session(first.plugin_id, scope).invoke("note.ping", {"op": "ping"})["op"] == "ping"


@pytest.mark.unit
def test_revoke_disable_uninstall_and_purge_have_distinct_retention() -> None:
    runtime = _runtime()
    package = _package()
    runtime.record(package)
    runtime.enable(package.plugin_id)
    scope = ScopeBindingV2(tenant_id="tenant-a", project_id="project-a")
    session = runtime.session(package.plugin_id, scope)
    session.storage_put("last", {"text": "keep"})
    runtime.revoke(package.plugin_id)
    with pytest.raises(OptionalBusinessError, match="revoked"):
        session.storage_get("last")
    with pytest.raises(OptionalBusinessError, match="revoked|not enabled|not_active"):
        runtime.session(package.plugin_id, scope).invoke("note.ping", {"op": "ping"})
    assert runtime.store.get(
        NamespaceKeyV2(
            plugin_id=package.plugin_id,
            tenant_id="tenant-a",
            project_id="project-a",
            item_key="last",
        )
    )
    runtime2 = _runtime()
    runtime2.record(_package())
    runtime2.enable(package.plugin_id)
    runtime2.session(package.plugin_id, scope).storage_put("last", {"text": "keep"})
    runtime2.disable(package.plugin_id)
    assert runtime2.projection(package.plugin_id).retention == "retained"
    assert runtime2.projection(package.plugin_id).runtime_phase == "inactive"
    runtime2.uninstall(package.plugin_id)
    assert runtime2.projection(package.plugin_id).retention == "retained"
    assert (
        runtime2.store.get(
            NamespaceKeyV2(
                plugin_id=package.plugin_id,
                tenant_id="tenant-a",
                project_id="project-a",
                item_key="last",
            )
        )
        is not None
    )
    assert runtime2.purge(package.plugin_id, scope) == 1
    assert runtime2.projection(package.plugin_id).retention == "purged"


@pytest.mark.unit
def test_expired_lease_blocks_high_risk_calls_and_sync_failure_is_not_revocation() -> None:
    now = datetime(2026, 11, 9, tzinfo=UTC)
    clock = {"at": now}

    runtime = SignedOptionalBusinessRuntimeV2(
        lease=timedelta(seconds=1), clock=lambda: clock["at"]
    )
    package = _package()
    runtime.record(package)
    runtime.enable(package.plugin_id)
    scope = ScopeBindingV2(tenant_id="tenant-a", project_id="project-a")
    session = runtime.session(package.plugin_id, scope)
    session.storage_put("last", {"text": "cached"})
    clock["at"] = now + timedelta(seconds=2)
    runtime.mark_sync(package.plugin_id, "degraded")
    with pytest.raises(OptionalBusinessError, match="lease has expired"):
        session.invoke("note.ping", {"op": "ping"})
    with pytest.raises(OptionalBusinessError, match="lease has expired"):
        session.storage_put("last", {"text": "nope"})
    assert session.storage_get("last") == {"text": "cached"}
    assert runtime.projection(package.plugin_id).sync == "degraded"
    assert runtime.projection(package.plugin_id).runtime_phase == "active"


@pytest.mark.unit
def test_newer_storage_schema_is_not_rewritten() -> None:
    with pytest.raises(PluginStorageError, match="newer"):
        assert_supported_schema_v2(NamespaceRecordV2(schema_version=2, document={"text": "x"}))


@pytest.mark.unit
def test_missing_scanner_is_unknown_and_not_a_pass() -> None:
    assert resolve_security_scan_status_v2(None) == "unknown"
    assert (
        resolve_security_scan_status_v2(ScannerReportV2(verdict="passed", digest="sha256:" + "ab" * 32))
        == "passed"
    )
    assert resolve_security_scan_status_v2(ScannerReportV2(verdict="failed", digest="nope")) == "unknown"


@pytest.mark.unit
def test_ui_digest_mismatch_does_not_mount() -> None:
    runtime = _runtime()
    package = _package()
    package.ui_files["ui.json"] = b'{"schema":"memstack.slot-ui/1","title":"Tampered","actions":[]}'
    runtime.record(package)
    runtime.enable(package.plugin_id)
    with pytest.raises(OptionalBusinessError, match="do not match the signed digest"):
        runtime.session(
            package.plugin_id, ScopeBindingV2(tenant_id="tenant-a", project_id="project-a")
        ).mount_ui("tool_result_renderer", "desktop-renderer")
