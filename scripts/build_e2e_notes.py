"""Publish two signed versions of the Notes sample for the browser lifecycle test."""

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import wasmtime
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from memstack_plugin_sdk.pack import build

_SAMPLE = Path(__file__).resolve().parents[1] / "samples/optional-business-plugin"


def build_notes(signer: Ed25519PrivateKey, version: str, title: str, result: str) -> bytes:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        ui = json.loads((_SAMPLE / "ui.json").read_bytes())
        ui_bytes = json.dumps({**ui, "title": title}).encode()
        (root / "ui.json").write_bytes(ui_bytes)
        wat = (_SAMPLE / "tool.wat").read_text().replace("ping", result)
        (root / "guest.wasm").write_bytes(wasmtime.wat2wasm(wat))
        tool = {
            "name": "note.ping",
            "description": "Return this release's response.",
            "abi": "invoke",
            "input_schema": {
                "type": "object",
                "required": ["op"],
                "properties": {"op": {"const": "ping"}},
            },
            "output_schema": {
                "type": "object",
                "required": ["ok", "op"],
                "properties": {"ok": {"const": True}, "op": {"const": result}},
            },
            "permissions": ["tools.execute"],
        }
        contribution = {
            "schema": "memstack.plugin.contributions/1",
            "tools": [tool],
            "commands": [
                {
                    "id": "save",
                    "tool": tool["name"],
                    "payload": {"op": "ping"},
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "permissions": ["tools.execute"],
                }
            ],
            "ui": [
                {
                    "slot": "tool_result_renderer",
                    "path": "ui.json",
                    "targets": ["web"],
                    "digest": "sha256:" + hashlib.sha256(ui_bytes).hexdigest(),
                    "permissions": ["ui.slot"],
                }
            ],
        }
        (root / "contributions.json").write_text(json.dumps(contribution))
        metadata = root / "package.json"
        metadata.write_text(
            json.dumps(
                {
                    "plugin_id": "sample.notes",
                    "version": version,
                    "target": "python",
                    "provenance": "repo://qa/notes",
                    "tool_name": "ping",
                    "wasm": "guest.wasm",
                    "contribution": "contributions.json",
                }
            )
        )
        return build(metadata, signer)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    signer = load_pem_private_key(args.key.read_bytes(), password=None)
    if not isinstance(signer, Ed25519PrivateKey):
        parser.error("expected an Ed25519 publisher key")
    args.out.mkdir(exist_ok=True, parents=True)
    for version, title, result in [("1.0.0", "Notes", "ping"), ("1.1.0", "Notes updated", "pong")]:
        (args.out / f"notes-{version}.mspkg").write_bytes(
            build_notes(signer, version, title, result)
        )
