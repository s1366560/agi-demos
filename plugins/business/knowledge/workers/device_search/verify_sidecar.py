"""Build the release once and exercise signed ABI admission in the desktop Sidecar."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[4]


def main() -> None:
    sys.path.insert(0, str(REPO / "sdk/memstack-plugin-sdk/src"))
    from memstack_plugin_sdk.pack import build

    spec = json.loads((PACKAGE / "plugin.json").read_bytes())
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary)
        target = output / "target"
        subprocess.run(
            [
                "cargo",
                "build",
                "--release",
                "--locked",
                "--target",
                "wasm32-unknown-unknown",
                "--target-dir",
                str(target),
            ],
            cwd=PACKAGE,
            check=True,
        )
        shutil.copy(target / Path(spec["wasm"]).relative_to("target"), output / "guest.wasm")
        signer = Ed25519PrivateKey.generate()
        (output / "public.pem").write_bytes(
            signer.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
        config = output / "plugin.json"
        config.write_text(json.dumps({**spec, "wasm": "guest.wasm"}))
        cloud = {
            "target": "python",
            "tool_name": "query",
            "wasm": "guest.wasm",
            "provenance": spec["provenance"],
        }
        (output / "cloud.json").write_text(json.dumps(cloud))
        family = output / "package.json"
        family.write_text(
            json.dumps(
                {
                    "plugin_id": "memstack-knowledge",
                    "version": spec["version"],
                    "kind": "business",
                    "targets": {"python": "cloud.json", "desktop-sidecar": "plugin.json"},
                }
            )
        )
        (output / "current.mspkg").write_bytes(build(family, signer))
        config.write_text(
            json.dumps(
                {
                    **spec,
                    "wasm": "guest.wasm",
                    "compatibility": {"min_inclusive": "3.0.0", "max_exclusive": "4.0.0"},
                }
            )
        )
        (output / "future.mspkg").write_bytes(build(family, signer))
        subprocess.run(
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                "agistack-desktop-sidecar",
                "publisher_signed_knowledge_guest_at_abi_boundary",
                "--",
                "--ignored",
            ],
            cwd=REPO / "agi-stack",
            env={**os.environ, "MEMSTACK_KNOWLEDGE_QA_RELEASES": str(output)},
            check=True,
        )


if __name__ == "__main__":
    main()
