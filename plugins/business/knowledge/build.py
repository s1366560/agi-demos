"""Build a knowledge package from a published OCI image digest and a compiled device guest."""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from memstack_plugin_sdk.pack import build, stage_contribution

ROOT = Path(__file__).resolve().parent


def release(image: str, wasm: Path, version: str, key: Ed25519PrivateKey) -> bytes:
    """Sign both target manifests against the same package ID and release version."""
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        config = json.loads((ROOT / "package.json").read_bytes())
        config["version"] = version
        (stage / "package.json").write_text(json.dumps(config))
        for target, relative_path in config["targets"].items():
            source = ROOT / relative_path
            staged = stage / relative_path
            staged.parent.mkdir(parents=True)
            spec = json.loads(source.read_bytes())
            if target == "python":
                stage_contribution(source.parent, staged.parent, spec["contribution"])
                (staged.parent / spec["worker"]).write_text(
                    json.dumps(
                        {
                            "schema": "memstack.mcp-oci-worker/1",
                            "image": image,
                            "entrypoint": "/app/project",
                        }
                    )
                )
            elif target == "desktop-sidecar":
                spec["wasm"] = "device.wasm"
                shutil.copyfile(wasm, staged.parent / spec["wasm"])
            else:
                raise ValueError(f"Unknown knowledge target {target!r}")
            staged.write_text(json.dumps(spec))
        return build(stage / "package.json", key)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--wasm", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    signer = serialization.load_pem_private_key(args.key.read_bytes(), password=None)
    if not isinstance(signer, Ed25519PrivateKey):
        parser.error("expected an Ed25519 signing key")
    args.out.write_bytes(release(args.image, args.wasm, args.version, signer))
