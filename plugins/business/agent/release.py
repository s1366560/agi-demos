"""Sign the published Agent operations worker with the MemStack publisher SDK."""

import argparse
import json
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def build_release(image: str, version: str, signer: "Ed25519PrivateKey") -> bytes:
    from memstack_plugin_sdk.pack import build, stage_contribution

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        stage_contribution(Path(__file__).parent, root)
        _ = (root / "worker.json").write_text(
            json.dumps(
                {
                    "schema": "memstack.mcp-oci-worker/1",
                    "image": image,
                    "entrypoint": "/usr/local/bin/memstack-agent-worker",
                }
            ),
            encoding="utf-8",
        )
        config = root / "package.json"
        metadata = json.loads(files(__package__).joinpath("package.json").read_text())
        config.write_text(json.dumps({**metadata, "version": version}), encoding="utf-8")
        return build(config, signer)


def main() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--image", required=True, help="Published registry/repository@sha256 digest"
    )
    _ = parser.add_argument("--version", required=True)
    _ = parser.add_argument("--key", type=Path, required=True)
    _ = parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    signer = load_pem_private_key(args.key.read_bytes(), password=None)
    if not isinstance(signer, Ed25519PrivateKey):
        parser.error("an Ed25519 signing key is required")
    _ = args.out.write_bytes(build_release(args.image, args.version, signer))


if __name__ == "__main__":
    main()
