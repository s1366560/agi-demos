"""Build a reproducible signed V2 tool bundle from publisher-owned files."""

import argparse
import base64
import io
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import rfc8785
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .compatibility import DEFAULT_RANGE, DESCRIPTOR, build_compatibility
from .contract import ContributionDocument, parse_bound_slot_ui, parse_contribution, sha256_digest
from .package_services import project_services
from .project_http import route_permissions, workspace_permissions

_QUOTAS = {
    "max_wasm_fuel": 1_000_000,
    "max_wasm_memory_bytes": 16 * 1024 * 1024,
    "max_wall_time_ms": 1_000,
    "max_concurrent_calls": 1,
    "max_output_bytes": 65_536,
    "max_network_requests_per_minute": None,
    "max_storage_bytes": None,
    "max_monthly_usd_micros": None,
}


def _quotas(overrides: object, *, worker: bool) -> dict[str, int | None]:
    if not isinstance(overrides, dict) or overrides.keys() - _QUOTAS.keys():
        raise ValueError("unknown package quota")
    defaults = {**_QUOTAS, "max_wall_time_ms": 30_000} if worker else _QUOTAS
    for name, limit in overrides.items():
        if type(limit) is not int or limit <= 0:
            raise ValueError(f"invalid quota for {name}")
        ceiling = defaults[name]
        if ceiling is not None and limit > ceiling:
            raise ValueError(f"quota exceeds the host limit for {name}")
    return {**defaults, **overrides}


def _file(root: Path, relative: str) -> bytes:
    path = PurePosixPath(relative)
    resolved = (root / path).resolve()
    if (
        not relative
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != relative
        or not resolved.is_relative_to(root)
        or not resolved.is_file()
        or resolved.stat().st_size > 8 * 1024 * 1024
    ):
        raise ValueError("asset must be a package-relative file of at most 8 MiB")
    return resolved.read_bytes()


def stage_contribution(source: Path, destination: Path, path: str = "contributions.json") -> None:
    """Copy the contribution and its declared page assets to a clean signing directory."""
    source = source.resolve()
    raw = _file(source, path)
    document = parse_contribution(json.loads(raw))
    assets = {asset.path: asset for page in document.pages for asset in page.assets}
    for name in (path, *(ui.path for ui in document.ui), *assets):
        data = raw if name == path else _file(source, name)
        if name in assets:
            assets[name].verify(data)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _executable(root: Path, spec: dict[str, Any]) -> tuple[str, bytes, str, str, str]:
    if "worker" in spec:
        if "wasm" in spec or spec["target"] != "python" or "contribution" not in spec:
            raise ValueError("workers require a cloud target and signed tool contributions")
        descriptor = json.loads(_file(root, spec["worker"]))
        if not isinstance(descriptor, dict) or set(descriptor) != {"schema", "image", "entrypoint"}:
            raise ValueError("invalid worker descriptor")
        if (
            descriptor["schema"] != "memstack.mcp-oci-worker/1"
            or not isinstance(descriptor["image"], str)
            or not re.fullmatch(r"[^/@\s]+/.+@sha256:[a-f0-9]{64}", descriptor["image"])
            or not isinstance(descriptor["entrypoint"], str)
            or not descriptor["entrypoint"].startswith("/")
        ):
            raise ValueError("worker requires a digest-pinned OCI image and absolute entrypoint")
        return (
            "mcp",
            rfc8785.dumps(descriptor),
            "artifacts/worker.json",
            "mcp.stdio",
            "application/vnd.memstack.mcp-oci-worker.v1+json",
        )
    content = _file(root, spec["wasm"])
    if not content.startswith(b"\0asm"):
        raise ValueError("expected a compiled WebAssembly module")
    if spec["target"] == "desktop-sidecar" and len(content) > 4 * 1024 * 1024:
        raise ValueError("desktop Wasm module exceeds 4 MiB")
    return "wasm", content, "artifacts/tool.wasm", "invoke", "application/wasm"


def _collect_contributions(
    root: Path, spec: dict[str, Any], files: dict[str, bytes]
) -> tuple[set[str], ContributionDocument | None]:
    permissions = {"tools.execute"}
    if "contribution" in spec:
        doc = json.loads(_file(root, spec["contribution"]))
    elif spec["target"] == "python":
        doc = {
            "schema": "memstack.plugin.contributions/1",
            "tools": [
                {
                    "name": spec["tool_name"],
                    "abi": "invoke",
                    "permissions": ["tools.execute"],
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                }
            ],
        }
    else:
        return permissions, None
    contribution = parse_contribution(doc)
    for group in (
        contribution.tools,
        contribution.commands,
        contribution.skills,
        contribution.subagents,
        contribution.ui,
    ):
        for item in group:
            permissions.update(item.permissions)
    if contribution.storage:
        permissions.update(contribution.storage.permissions)
    commands = {command.command_id for command in contribution.commands}
    input_commands = frozenset(
        command.command_id for command in contribution.commands if command.accepts_input
    )
    for item in contribution.ui:
        raw = _file(root, item.path)
        if sha256_digest(raw) != item.digest:
            raise ValueError("UI digest differs from the contribution")
        parse_bound_slot_ui(json.loads(raw), item.slot, commands, input_commands)
        files[f"ui/{item.path}"] = raw
    if contribution.pages:
        permissions.add("ui.slot")
    if any(page.voice_authorization for page in contribution.pages):
        permissions.add("ui.media.microphone")
    for page in contribution.pages:
        for asset in page.assets:
            files[f"pages/{asset.path}"] = asset.verify(_file(root, asset.path))
    files["contributions.json"] = rfc8785.dumps(doc)
    return permissions, contribution


def build(config: Path, signer: Ed25519PrivateKey) -> bytes:
    root = config.resolve().parent
    spec = json.loads(config.read_text(encoding="utf-8"))
    if isinstance(spec, dict) and "targets" in spec:
        if set(spec) != {"plugin_id", "version", "kind", "targets"}:
            raise ValueError("invalid multi-target release configuration")
        targets = spec["targets"]
        if not isinstance(targets, dict) or set(targets) != {"python", "desktop-sidecar"}:
            raise ValueError("multi-target releases require cloud and desktop configurations")
        children = {}
        for target, relative in targets.items():
            child = json.loads(_file(root, relative))
            if not isinstance(child, dict) or child.get("target") != target:
                raise ValueError("target configuration mismatch")
            children[target] = {
                **child,
                "plugin_id": spec["plugin_id"],
                "version": spec["version"],
                "kind": spec["kind"],
            }
        native = _build_target(
            (root / targets["desktop-sidecar"]).resolve().parent,
            children["desktop-sidecar"],
            signer,
        )
        return _build_target(
            (root / targets["python"]).resolve().parent,
            children["python"],
            signer,
            device_archive=native,
            device_routes=route_permissions(
                "desktop-sidecar", children["desktop-sidecar"].get("project_http_routes")
            )
            | workspace_permissions(
                "desktop-sidecar", children["desktop-sidecar"].get("workspace_read_operations")
            ),
            device_tool=children["desktop-sidecar"]["tool_name"],
        )
    return _build_target(root, spec, signer)


def _build_target(
    root: Path,
    spec: dict[str, Any],
    signer: Ed25519PrivateKey,
    *,
    device_archive: bytes | None = None,
    device_routes: set[str] | None = None,
    device_tool: str | None = None,
) -> bytes:
    if not isinstance(spec, dict) or spec.keys() - {
        "kind",
        "plugin_id",
        "version",
        "target",
        "tool_name",
        "wasm",
        "worker",
        "contribution",
        "quotas",
        "provenance",
        "compatibility",
        "services",
        "device_capability",
        "project_http_routes",
        "workspace_read_operations",
    }:
        raise ValueError("unknown package configuration field")
    plugin, version, target, tool = (
        spec[k] for k in ("plugin_id", "version", "target", "tool_name")
    )
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", plugin)
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9.-]+)?", version)
        or target not in {"python", "desktop-sidecar"}
        or not re.fullmatch(r"[a-zA-Z0-9_]+", tool)
        or len(f"wasm__{plugin}__{tool}") > 64
    ):
        raise ValueError("invalid plugin identity, target, version or tool name")
    worker = "worker" in spec
    quotas = _quotas(spec.get("quotas", {}), worker=worker)
    provenance = spec.get("provenance")
    if (target == "desktop-sidecar" or worker) and (
        not isinstance(provenance, str) or not provenance.strip()
    ):
        raise ValueError("desktop and worker packages require a publisher provenance reference")
    runtime, content, executable_path, abi, media_type = _executable(root, spec)
    files = {
        executable_path: content,
        DESCRIPTOR: build_compatibility(spec.get("compatibility", DEFAULT_RANGE)),
    }
    if "kind" in spec:
        if spec["kind"] not in ("adapter", "business"):
            raise ValueError("package kind must be adapter or business")
        files["release-kind.json"] = rfc8785.dumps({"kind": spec["kind"]})
    device_path = "targets/desktop-sidecar.mspkg"
    if device_archive is not None:
        files[device_path] = device_archive
    permissions, contribution = _collect_contributions(root, spec, files)
    permissions.update(
        workspace_permissions(target, spec.get("workspace_read_operations")),
        route_permissions(target, spec.get("project_http_routes")),
        device_routes or (),
    )
    if "device_capability" in spec:
        from .device_capability import attach_device_capability

        device_tool = attach_device_capability(
            spec["device_capability"], files, permissions, target, device_archive
        )
    if contribution and contribution.pages:
        from .rich_pages import validate_device_tools

        validate_device_tools(contribution.pages, device_tool)
    approved = sorted(permissions)
    native = target == "desktop-sidecar"
    catalog = "service:tool-set-catalog"
    services: dict[str, list[dict[str, Any]]] = {
        "provides": [{"service": "service:wasm-tool-set", "version": "1.0.0"}] if native else [],
        "requires": []
        if native
        else [{"alias": "catalog", "service": catalog, "version": "1.0.0", "contributes": True}],
    }
    bindings = project_services(
        spec.get("services", {}),
        plugin=plugin,
        target=target,
        worker=worker,
        tools=contribution.tools if contribution else (),
    )
    services["provides"].extend(
        {"service": row.service, "version": row.version} for row in bindings.provides
    )
    services["requires"].extend(
        {"alias": row.alias, "service": row.service, "version": row.version, "contributes": False}
        for row in bindings.requires
    )
    contract: dict[str, Any] = {
        "services": services,
        "events": {"emits": [], "handles": []},
        "config_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"tool_name": {"const": tool}},
            "required": ["tool_name"],
            "additionalProperties": False,
        },
    }
    reference = f"{runtime}://{plugin}/{abi}"
    module = {
        "module_ref": reference,
        "entrypoint": abi,
        "targets": [target],
        "artifact": {
            "digest": sha256_digest(content),
            "source": f"bundle://{plugin}/{executable_path}",
            "signature": None,
            "provenance": None,
        },
        "contract": contract,
        "contract_digest": sha256_digest(rfc8785.dumps(contract)),
    }
    manifest = {
        "schema_version": 2,
        "plugin_id": plugin,
        "version": version,
        "runtime": runtime,
        "trust": "signed",
        "modules": [module],
        "permissions": approved,
        "quotas": quotas.copy(),
    }
    scope = {"kind": "root", "tenant_id": None, "project_id": None, "session_id": None}
    entry = {
        "entry_id": plugin,
        "parent_entry_id": None,
        "plugin_ref": plugin,
        "module_ref": reference,
        "enabled": True,
        "config": {"tool_name": tool},
        "inject": {row["alias"]: row["service"] for row in services["requires"]},
        "isolate": {},
        "scope": scope,
        "permissions": approved,
        "quotas": quotas.copy(),
        "restart_policy": "process-boundary" if worker else "hot-generation",
    }
    layer = {
        "layer_id": plugin,
        "kind": "bundle",
        "scope": scope,
        "entries": [entry],
        "replacements": [],
        "disabled_entry_ids": [],
    }
    artifacts = [
        {
            "artifact_id": f"asset-{i}",
            "target": "desktop-sidecar" if path == device_path else target,
            "path": path,
            "digest": sha256_digest(raw),
            "size_bytes": len(raw),
            "media_type": (
                "application/vnd.memstack.target-package"
                if path == device_path
                else media_type
                if path == executable_path
                else "text/javascript"
                if path.startswith("pages/") and path.endswith(".js")
                else "text/css"
                if path.startswith("pages/") and path.endswith(".css")
                else "application/json"
            ),
        }
        for i, (path, raw) in enumerate(sorted(files.items()))
    ]
    bundle: dict[str, Any] = {
        "schema_version": 2,
        "bundle_id": plugin,
        "version": version,
        "manifests": [manifest],
        "layers": [layer],
        "artifacts": artifacts,
        "provenance": spec.get("provenance"),
    }
    digest = sha256_digest(rfc8785.dumps(bundle))
    bundle.update(
        digest=digest,
        signature=base64.b64encode(signer.sign(digest.encode("ascii"))).decode("ascii"),
    )
    # Optional quotas hash as explicit null in the canonical model and are omitted on the wire.
    for owner in (manifest, entry):
        owner["quotas"] = {k: v for k, v in quotas.items() if v is not None}
    files["bundle.json"] = rfc8785.dumps(bundle)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path, raw in sorted(files.items()):
            archive.writestr(zipfile.ZipInfo(path), raw)
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--key", type=Path, required=True, help="Ed25519 PKCS#8 PEM key file")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    key = serialization.load_pem_private_key(args.key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        parser.error("an Ed25519 signing key is required")
    content = build(args.config, key)
    with tempfile.NamedTemporaryFile(dir=args.out.parent, delete=False) as temporary:
        try:
            temporary.write(content)
            temporary.close()
            os.replace(temporary.name, args.out)
        finally:
            Path(temporary.name).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
