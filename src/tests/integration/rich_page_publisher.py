"""Publish the same project page and two distinct executables after building the hosts.

To populate the local registry with both versions, run from the repository root:

    PYTHONPATH=sdk/memstack-plugin-sdk/src uv run python -m src.tests.integration.rich_page_publisher
"""

import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from memstack_plugin_sdk.pack import build
from wasmtime import wat2wasm


def publish_page(
    directory: Path, plugin: str, revision: int, key: Ed25519PrivateKey, *, worker: bool = False
) -> bytes:
    directory.mkdir(parents=True)
    descriptor = {
        "plugin_id": plugin,
        "version": f"1.{revision}.0",
        "kind": "business",
        "targets": {"python": "python.json", "desktop-sidecar": "desktop-sidecar.json"},
    }
    (directory / "package.json").write_text(json.dumps(descriptor))
    for target, tool in (("python", "cloud_label"), ("desktop-sidecar", "device_label")):
        label = f"{target}-{revision}"
        result = json.dumps({"label": label}, separators=(",", ":")).encode()
        literal = "".join(f"\\{byte:02x}" for byte in result)
        wat = f'''(module (memory (export "memory") 2 2)
            (data (i32.const 65536) "{literal}")
            (func (export "invoke") (param i32) (result i32) (i32.const {len(result)})))'''
        (directory / f"{tool}.wasm").write_bytes(wat2wasm(wat))
        target_config = {
            "target": target,
            "tool_name": tool,
            "wasm": f"{tool}.wasm",
            "provenance": "repo://acceptance/label-publisher",
            **({"contribution": "contributions.json"} if target == "python" else {}),
        }
        (directory / f"{target}.json").write_text(json.dumps(target_config))
    title = f"Inventory labels {revision}"
    script = """
(async () => {
  const host = window.memstack;
  const root = document.getElementById('root');
  const heading = document.createElement('h1');
  heading.textContent = TITLE;
  root.append(heading);
  function add(text, call) {
    const button = document.createElement('button');
    button.textContent = text;
    const output = document.createElement('output');
    button.onclick = async () => {
      try { output.textContent = JSON.stringify(await call()); }
      catch (error) { output.textContent = String(error); }
    };
    root.append(button, output);
  }
  add('Cloud label', () => host.invoke('get-label'));
  if ((await host.scope()).target === 'desktop-renderer') {
    add('Device label', () => host.device('device_label', {}));
  }
})();""".replace("TITLE", json.dumps(title)).encode()
    resources = []
    if worker:
        code = f"self.onmessage = () => self.postMessage('worker-{revision}');".encode()
        (directory / "labels.worker.js").write_bytes(code)
        resources.append(
            {"path": "labels.worker.js", "digest": "sha256:" + hashlib.sha256(code).hexdigest()}
        )
        script = script.replace(
            b"  add('Cloud label'",
            b"""  add('Worker label', () => new Promise((resolve, reject) => {
    const worker = new Worker(host.assetUrl('labels.worker.js'));
    worker.onmessage = event => { worker.terminate(); resolve(event.data); };
    worker.onerror = () => { worker.terminate(); reject(new Error('worker_failed')); };
    worker.postMessage(null);
  }));
  add('Cloud label'""",
        )
    (directory / "labels.js").write_bytes(script)
    document = {
        "schema": "memstack.plugin.contributions/1",
        "tools": [
            {
                "name": "cloud_label",
                "abi": "invoke",
                "permissions": ["tools.execute"],
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            }
        ],
        "commands": [
            {
                "id": "get-label",
                "tool": "cloud_label",
                "permissions": ["tools.execute"],
                "payload": {},
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            }
        ],
        "pages": [
            {
                "id": "labels",
                "title": title,
                "routes": [f"/{plugin}/labels"],
                "targets": ["web", "desktop-renderer"],
                "commands": ["get-label"],
                "device_tools": ["device_label"],
                **({"resources": resources} if resources else {}),
                "entry": {
                    "path": "labels.js",
                    "digest": "sha256:" + hashlib.sha256(script).hexdigest(),
                },
            }
        ],
    }
    (directory / "contributions.json").write_text(json.dumps(document))
    return build(directory / "package.json", key)


def main() -> None:
    """Independently build and publish both inventory fixtures to the loopback npm registry."""
    import argparse
    import re
    from tempfile import TemporaryDirectory

    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    from scripts.dev.npm_registry import STATE, distribute, signed_package

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--slug", default="inventory-market-qa")
    parser.add_argument("--publisher-directory", type=Path, default=Path(".memstack/standard"))
    parser.add_argument("--registry-state", type=Path, default=STATE)
    args = parser.parse_args()
    if not re.fullmatch(r"inventory-market-qa(?:-[a-z0-9-]+)?", args.slug):
        parser.error("--slug must identify an inventory-market-qa test package")
    key = load_pem_private_key((args.publisher_directory / "publisher.key").read_bytes(), None)
    if not isinstance(key, Ed25519PrivateKey):
        parser.error("the fixture requires an Ed25519 publisher key")
    public = (args.publisher_directory / "publisher.pem").read_text()
    with TemporaryDirectory(prefix="inventory-market-") as tmp:
        root = Path(tmp)
        metadata = root / args.slug
        metadata.mkdir()
        (metadata / "market.json").write_text(
            json.dumps(
                {
                    "name": {"en": "Inventory labels", "zh": "库存标签"},
                    "description": {
                        "en": "Generate inventory labels in the cloud or on this device.",
                        "zh": "通过云端或本机生成库存标签。",
                    },
                    "icon": "panels-top-left",
                }
            )
        )
        packages = []
        for revision in (1, 2):
            archive = root / f"{revision}.mspkg"
            archive.write_bytes(
                publish_page(
                    root / str(revision), "memstack-" + args.slug, revision, key, worker=args.worker
                )
            )
            packages.append(signed_package(archive, public, root))
        distribute("publish", packages, args.registry_state)


if __name__ == "__main__":
    main()
