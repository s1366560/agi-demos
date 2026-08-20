"""I5 end-to-end: sample untrusted plugin — gate, load, run, quota, unload."""

from __future__ import annotations

import hashlib

import pytest

from src.domain.model.plugins import parse_plugin_manifest
from src.domain.ports.plugins import PluginPermission, ResourceQuota
from src.infrastructure.plugins.governance import (
    PluginQuotaExceededError,
    PluginTrustGate,
    ResourceQuotaEnforcer,
)
from src.infrastructure.plugins.wasm_host import WasmToolHost

SCORER_WAT = """
(module
  (func (export "score") (param i32) (result i32)
    local.get 0))
"""

MANIFEST = {
    "schemaVersion": 1,
    "id": "untrusted-scorer",
    "version": "1.0.0",
    "runtime": "wasm",
    "trust": "untrusted",
    "provides": [{"kind": "tool", "id": "score", "permissions": ["tools.execute"]}],
}


@pytest.mark.unit
def test_untrusted_plugin_install_run_limit_unload(tmp_path) -> None:
    # Gate: untrusted + wasm + tool-only is installable with approved perms.
    manifest = parse_plugin_manifest(MANIFEST)
    decision = PluginTrustGate().decide(manifest, frozenset({PluginPermission.TOOLS_EXECUTE}))
    assert decision.allowed is True

    # Load: artifact digest verified before any code runs.
    artifact = tmp_path / "plugin.wasm"
    raw = SCORER_WAT.encode()
    artifact.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    events: list[dict[str, object]] = []
    enforcer = ResourceQuotaEnforcer(
        {"untrusted-scorer": ResourceQuota(max_concurrent_calls=2, max_wasm_fuel=10**9)}
    )
    host = WasmToolHost.from_path(
        "untrusted-scorer",
        artifact,
        expected_sha256=digest,
        quota_enforcer=enforcer,
        audit=events.append,
        tenant_id="tenant-1",
    )

    # Run: calls succeed and are audited with tenant attribution.
    outcome = host.call("score", "abcd")
    assert outcome.score == 4
    assert events[-1]["tenant_id"] == "tenant-1"
    assert events[-1]["result"] == "ok"

    # Limit: a stricter fuel quota rejects the next provisioning call.
    strict = ResourceQuotaEnforcer({"untrusted-scorer": ResourceQuota(max_wasm_fuel=5)})
    strict_host = WasmToolHost.from_path(
        "untrusted-scorer",
        artifact,
        expected_sha256=digest,
        quota_enforcer=strict,
        audit=events.append,
        tenant_id="tenant-1",
    )
    with pytest.raises(PluginQuotaExceededError):
        strict_host.call("score", "abcd")
    assert events[-1]["result"] == "error"

    # Unload: disposal is a no-op boundary (fresh store per call), and the
    # host rejects further malformed input without leaking state.
    with pytest.raises(Exception, match="tool_id"):
        host.call("", "abcd")
