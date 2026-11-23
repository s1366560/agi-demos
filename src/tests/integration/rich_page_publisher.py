"""Publish the same project page and two distinct executables after building the hosts."""

import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from memstack_plugin_sdk.pack import build
from wasmtime import wat2wasm


def publish_page(directory: Path, plugin: str, revision: int, key: Ed25519PrivateKey) -> bytes:
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
                "entry": {
                    "path": "labels.js",
                    "digest": "sha256:" + hashlib.sha256(script).hexdigest(),
                },
            }
        ],
    }
    (directory / "contributions.json").write_text(json.dumps(document))
    return build(directory / "package.json", key)
