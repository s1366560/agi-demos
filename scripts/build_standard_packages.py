"""Assemble the six initial project archives from the publishers' pinned worker images."""

import argparse
import json
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

BUSINESS = Path(__file__).resolve().parents[1] / "plugins/business"
WORKER_CONTEXTS = {
    "agent": "agent",
    "knowledge": "knowledge/workers/graph_projection",
    "automation": "automation",
    "environments": "environments",
    "billing": "billing",
}


def build_worker(package: Path, image: str, executable: str, signer: Ed25519PrivateKey) -> bytes:
    from memstack_plugin_sdk.pack import build, stage_contribution

    # Stage only the files referenced by the signed contract, keeping source checkouts immutable.
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        config = json.loads((package / "package.json").read_bytes())
        (stage / "package.json").write_text(json.dumps(config))
        stage_contribution(package, stage, config["contribution"])
        descriptor = {
            "schema": "memstack.mcp-oci-worker/1",
            "image": image,
            "entrypoint": executable,
        }
        (stage / config["worker"]).write_text(json.dumps(descriptor))
        native_root = package / "desktop-sidecar" / "http"
        if (native_root / "plugin.json").is_file():
            native_config = json.loads((native_root / "plugin.json").read_bytes())
            wasm = (native_root / native_config["wasm"]).resolve()
            if not wasm.is_relative_to(native_root.resolve()):
                raise ValueError("Native executable must be inside its package")
            native_config["wasm"] = "native.wasm"
            (stage / "native.wasm").write_bytes(wasm.read_bytes())
            (stage / "native.json").write_text(json.dumps(native_config))
            family = {
                "kind": config["kind"],
                "plugin_id": config["plugin_id"],
                "version": config["version"],
                "targets": {"python": "package.json", "desktop-sidecar": "native.json"},
            }
            (stage / "targets.json").write_text(json.dumps(family))
            return build(stage / "targets.json", signer)
        return build(stage / "package.json", signer)


def build_package(name: str, args: argparse.Namespace, signer: Ed25519PrivateKey) -> bytes:
    root = BUSINESS / name
    if name == "workspace":
        from memstack_plugin_sdk.pack import build

        return build(root / "package.json", signer)

    image = getattr(args, f"{name}_image")
    version = json.loads((root / "package.json").read_bytes())["version"]
    if name == "agent":
        from plugins.business.agent.release import build_release

        return build_release(image, version, signer)
    if name == "knowledge":
        from plugins.business.knowledge.build import release

        return release(image, args.device_wasm, version, signer)
    if name == "billing":
        from plugins.business.billing.build import build_release as build_billing

        return build_billing(
            json.loads((root / "plans.json").read_bytes()),
            version=version,
            signer=signer,
            worker_image=image,
        )
    executable = {"automation": "/app/schedule-worker", "environments": "/app/worker"}[name]
    return build_worker(root, image, executable, signer)


def main() -> None:
    names = ("workspace", *WORKER_CONTEXTS)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", choices=names, help="Build only this package")
    for name in WORKER_CONTEXTS:
        parser.add_argument(
            "--" + name + "-image", help="Published OCI image at its immutable digest"
        )
    parser.add_argument("--device-wasm", type=Path, help="Knowledge device executable")
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    selected = (args.package,) if args.package else names
    for name in selected:
        if name in WORKER_CONTEXTS and not getattr(args, f"{name}_image"):
            parser.error(f"--{name}-image is required for {name}")
    if "knowledge" in selected and not args.device_wasm:
        parser.error("--device-wasm is required for knowledge")
    signer = load_pem_private_key(args.key.read_bytes(), password=None)
    if not isinstance(signer, Ed25519PrivateKey):
        parser.error("Expected an Ed25519 publisher key")

    archives = {name: build_package(name, args, signer) for name in selected}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.out.parent) as temporary:
        staged = Path(temporary) / "archives"
        staged.mkdir()
        for name, raw in archives.items():
            (staged / f"memstack-{name}.mspkg").write_bytes(raw)
        staged.rename(args.out)


if __name__ == "__main__":
    main()
