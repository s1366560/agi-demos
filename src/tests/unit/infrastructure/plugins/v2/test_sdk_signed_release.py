"""A publisher can release an unknown module without importing a host or rebuilding it."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import wasmtime
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.infrastructure.plugins.v2.bundle_archive import read_bundle_archive_v2

SDK = Path(__file__).resolve().parents[6] / "sdk/memstack-plugin-sdk/src"


@pytest.mark.parametrize("target", ["python", "desktop-sidecar"])
def test_independent_publisher_builds_reproducible_signed_release(tmp_path, target):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    (tmp_path / "key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (tmp_path / "guest.wasm").write_bytes(
        wasmtime.wat2wasm(
            '(module (memory (export "memory") 2) (data (i32.const 65536) "{}") '
            '(func (export "invoke") (param i32) (result i32) i32.const 2))'
        )
    )
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "plugin_id": "qa.new",
                "version": "2.0.1",
                "target": target,
                "provenance": "repo://qa/independent-publisher",
                "tool_name": "read_value",
                "wasm": "guest.wasm",
            }
        )
    )
    args = [
        sys.executable,
        "-m",
        "memstack_plugin_sdk.pack",
        "package.json",
        "--key",
        "key.pem",
        "--out",
        "release.mspkg",
    ]

    def build():
        subprocess.run(
            args,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": str(SDK)},
            check=True,
            capture_output=True,
        )
        return (tmp_path / "release.mspkg").read_bytes()

    assert build() == build()
    verified = read_bundle_archive_v2(
        tmp_path / "release.mspkg",
        trusted_public_keys=[public.decode()],
        approved_permissions=frozenset({"tools.execute"}),
        require_signature=True,
    )
    compatibility = next(
        asset for asset in verified.manifest.artifacts if asset.path == "compatibility.json"
    )
    assert json.loads(verified.artifacts[compatibility.artifact_id]) == {
        "schema": "memstack.host-compatibility/1",
        "min_inclusive": "2.0.0",
        "max_exclusive": "3.0.0",
    }
    manifest = verified.manifest.manifests[0]
    assert (manifest.plugin_id, manifest.version, manifest.modules[0].entrypoint) == (
        "qa.new",
        "2.0.1",
        "invoke",
    )
    assert manifest.modules[0].targets == (target,)
    if target == "python":
        from dataclasses import replace

        from src.infrastructure.plugins.v2.project_package_execution import invoke_project_tool
        from src.infrastructure.plugins.v2.project_plugin_package import (
            _check_host_contract,
            admit_package,
        )
        from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
            OptionalBusinessError,
            ScopeBindingV2,
        )

        module = manifest.modules[0]
        required = module.contract.services.requires[0]
        scope = ScopeBindingV2(tenant_id="t", project_id="p")
        package = admit_package(build(), (public.decode(),), frozenset({"tools.execute"}), scope)
        assert asyncio.run(invoke_project_tool(package, scope, "read_value", {})) == {}
        for name, value in (("service", "service:not-installed"), ("version", "3.0.0")):
            incompatible = replace(
                module.contract.services, requires=(replace(required, **{name: value}),)
            )
            with pytest.raises(OptionalBusinessError, match="unsupported host service"):
                _check_host_contract(
                    manifest,
                    replace(module, contract=replace(module.contract, services=incompatible)),
                    package.contribution,
                )


def test_device_package_requires_a_signed_provenance_reference(tmp_path):
    from memstack_plugin_sdk.pack import build

    config = tmp_path / "package.json"
    config.write_text(
        json.dumps(
            {
                "plugin_id": "qa.device",
                "version": "1.0.0",
                "target": "desktop-sidecar",
                "tool_name": "query",
                "wasm": "guest.wasm",
            }
        )
    )
    with pytest.raises(ValueError, match="provenance"):
        build(config, Ed25519PrivateKey.generate())


def test_settings_page_only_accepts_actions_that_renderers_can_dispatch():
    from memstack_plugin_sdk.contract import ContractError, parse_bound_slot_ui

    page = {"schema": "memstack.slot-ui/1", "title": "Project"}
    assert parse_bound_slot_ui(page, "settings_page", set()).actions == ()
    for action in ("UNSUPPORTED", "a" * 65, "missing-command"):
        with pytest.raises(ContractError, match="action"):
            parse_bound_slot_ui(
                {**page, "actions": [{"id": action, "label": "Open"}]}, "settings_page", {"open"}
            )
    valid = parse_bound_slot_ui(
        {**page, "actions": [{"id": "open", "label": "Open"}]}, "settings_page", {"open"}
    )
    assert valid.actions == (("open", "Open"),)
    form = {
        **page,
        "actions": [{"id": "open", "label": "Open", "input": {"label": "Options", "initial": {}}}],
    }
    with pytest.raises(ContractError, match="input-enabled"):
        parse_bound_slot_ui(form, "settings_page", {"open"})
    assert (
        parse_bound_slot_ui(form, "settings_page", {"open"}, frozenset({"open"})).actions
        == valid.actions
    )


@pytest.mark.parametrize(
    "lower,upper",
    [
        ("2.0", "3.0.0"),
        ("2.0.00", "3.0.0"),
        ("2.0.0", "2.0.0"),
        ("3.0.0", "2.0.0"),
        ("2.0.0", "3.0.4294967296"),
        ("1.0.0", "2.0.0-beta"),
    ],
)
def test_invalid_abi_ranges_cannot_be_signed(lower, upper):
    from memstack_plugin_sdk.compatibility import build_compatibility

    with pytest.raises(ValueError, match="host ABI"):
        build_compatibility({"min_inclusive": lower, "max_exclusive": upper})


def test_legacy_packages_only_bind_fixed_v2_host_abi():
    from memstack_plugin_sdk.compatibility import require_compatible

    require_compatible(None)
    with pytest.raises(ValueError, match="legacy host ABI"):
        require_compatible(None, (2, 1, 0))
    with pytest.raises(ValueError, match="duplicate host ABI"):
        require_compatible(
            b'{"schema":"memstack.host-compatibility/1","min_inclusive":"1.0.0","min_inclusive":"2.0.0","max_exclusive":"3.0.0"}'
        )


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        ("dependencies", "contribution_unknown"),
        ("runtime_hooks", "contribution_unknown"),
        ("workflows", "executor_unavailable"),
    ],
)
def test_sdk_rejects_unknown_and_unavailable_contribution_sections(section, expected):
    from memstack_plugin_sdk.contract import CONTRIBUTION_SCHEMA, ContractError, parse_contribution

    with pytest.raises(ContractError) as caught:
        parse_contribution({"schema": CONTRIBUTION_SCHEMA, section: []})
    assert caught.value.code == expected


@pytest.mark.parametrize(
    "upload_location",
    [
        "https://other.example/v2/team/app/blobs/uploads/id",
        "/v2/another/app/blobs/uploads/id",
        None,
    ],
)
def test_registry_upload_keeps_credentials_on_target_repository(upload_location):
    import httpx
    from memstack_plugin_sdk.publish import _upload

    calls = []

    def transport(request):
        calls.append((request.method, request.url.host))
        if request.method == "HEAD":
            return httpx.Response(404)
        headers = {"Location": upload_location} if upload_location else {}
        return httpx.Response(202, headers=headers)

    with (
        httpx.Client(
            transport=httpx.MockTransport(transport), headers={"Authorization": "Bearer test"}
        ) as client,
        pytest.raises(ValueError, match="upload location"),
    ):
        _upload(client, "https://registry.example/v2/team/app", "sha256:" + "0" * 64, b"x")
    assert calls == [("HEAD", "registry.example"), ("POST", "registry.example")]


def test_multi_target_release_uses_one_signed_identity(tmp_path):
    from memstack_plugin_sdk.pack import build

    from src.infrastructure.plugins.v2.project_plugin_package import admit_package

    signer = Ed25519PrivateKey.generate()
    key = (
        signer.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    root = {"plugin_id": "qa.family", "version": "2.1.0", "kind": "business", "targets": {}}
    for target in ("python", "desktop-sidecar"):
        directory = tmp_path / target
        directory.mkdir()
        (directory / "tool.wasm").write_bytes(wasmtime.wat2wasm("(module)"))
        config = directory / "plugin.json"
        config.write_text(
            json.dumps(
                {
                    "tool_name": "probe",
                    "wasm": "tool.wasm",
                    "target": target,
                    "provenance": "repo://qa",
                }
            )
        )
        root["targets"][target] = str(config.relative_to(tmp_path))
    spec = tmp_path / "package.json"
    spec.write_text(json.dumps(root))
    raw = build(spec, signer)
    assert raw == build(spec, signer)
    from scripts.package_release_counts import release_counts

    artifact = tmp_path / "release.mspkg"
    artifact.write_bytes(raw)
    counts = release_counts([artifact], (key,))
    assert (counts["business"], counts["adapter"], counts["modules"]) == (1, 0, 2)
    assert counts["artifacts"] > counts["modules"]
    with pytest.raises(ValueError, match="multiple releases"):
        release_counts([artifact, artifact], (key,))
    package = admit_package(raw, (key,), frozenset({"tools.execute"}), None)
    assert (package.plugin_id, package.kind, package.targets) == (
        "qa.family",
        "business",
        ("python", "desktop-sidecar"),
    )
    (tmp_path / "desktop-sidecar/tool.wasm").write_bytes(wasmtime.wat2wasm("(module (func))"))
    changed = admit_package(build(spec, signer), (key,), frozenset({"tools.execute"}), None)
    assert changed.digest != package.digest
    assert changed.wasm == package.wasm
    native_spec = tmp_path / root["targets"]["desktop-sidecar"]
    config = json.loads(native_spec.read_bytes())
    config["project_http_routes"] = {"GET": ["sandbox"], "POST": ["sandbox/desktop"]}
    config["workspace_read_operations"] = ["text"]
    native_spec.write_text(json.dumps(config))
    routed = build(spec, signer)
    route_grants = frozenset({"desktop.http.get.sandbox", "desktop.http.post.sandbox.desktop"})
    route_grants |= {"device.workspace.read.text"}
    approved = route_grants | {"tools.execute"}
    assert admit_package(routed, (key,), approved, None).approved_permissions == approved
    for required in route_grants:
        with pytest.raises(ValueError, match="lacks approval"):
            admit_package(routed, (key,), approved - {required}, None)



def test_rich_release_binds_page_to_same_signed_device_tool(tmp_path):
    import hashlib

    from memstack_plugin_sdk.pack import build

    from src.infrastructure.plugins.v2.project_plugin_package import admit_package

    key = Ed25519PrivateKey.generate()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    targets = {}
    for target in ("python", "desktop-sidecar"):
        folder = tmp_path / target
        folder.mkdir()
        (folder / "guest.wasm").write_bytes(wasmtime.wat2wasm("(module)"))
        spec = {
            "target": target,
            "tool_name": "read_notes",
            "wasm": "guest.wasm",
            "provenance": "repo://qa/notes",
        }
        if target == "python":
            spec["contribution"] = "contributions.json"
        (folder / "spec.json").write_text(json.dumps(spec))
        targets[target] = f"{target}/spec.json"
    root = tmp_path / "package.json"
    root.write_text(
        json.dumps(
            {
                "plugin_id": "unknown.notes",
                "version": "1.0.0",
                "kind": "business",
                "targets": targets,
            }
        )
    )
    raw = b"console.log('notes')"
    (tmp_path / "python/app.js").write_bytes(raw)
    page = {
        "id": "notes",
        "title": "Notes",
        "routes": ["/notes"],
        "targets": ["web", "desktop-renderer"],
        "entry": {"path": "app.js", "digest": "sha256:" + hashlib.sha256(raw).hexdigest()},
        "device_tools": ["read_notes"],
    }
    doc = {
        "schema": "memstack.plugin.contributions/1",
        "tools": [
            {
                "name": "read_notes",
                "abi": "invoke",
                "input_schema": {},
                "output_schema": {},
                "permissions": ["tools.execute"],
            }
        ],
        "pages": [page],
    }
    contribution = tmp_path / "python/contributions.json"
    contribution.write_text(json.dumps(doc))
    signed = build(root, key)
    permissions = frozenset({"tools.execute", "ui.slot"})
    candidate = admit_package(signed, (public,), permissions, None)
    assert candidate.contribution.pages[0].device_tools == ("read_notes",)
    with pytest.raises(ValueError, match="lacks approval for ui.slot"):
        admit_package(signed, (public,), frozenset({"tools.execute"}), None)
    page["device_tools"] = ["another_tool"]
    contribution.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="undeclared device tool"):
        build(root, key)
