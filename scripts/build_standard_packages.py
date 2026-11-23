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
        return build(stage / "package.json", signer)


def main() -> None:
    from memstack_plugin_sdk.pack import build

    from plugins.business.agent.release import build_release as build_agent
    from plugins.business.billing.build import build_release as build_billing
    from plugins.business.knowledge.build import release as build_knowledge

    parser = argparse.ArgumentParser(description=__doc__)
    for name in WORKER_CONTEXTS:
        parser.add_argument(
            "--" + name + "-image",
            required=True,
            help="Published OCI image at its immutable digest",
        )
    parser.add_argument("--device-wasm", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    signer = load_pem_private_key(args.key.read_bytes(), password=None)
    if not isinstance(signer, Ed25519PrivateKey):
        parser.error("Expected an Ed25519 publisher key")

    def version(name: str) -> str:
        return str(json.loads((BUSINESS / name / "package.json").read_bytes())["version"])

    archives = {
        "agent": build_agent(args.agent_image, version("agent"), signer),
        "knowledge": build_knowledge(
            args.knowledge_image, args.device_wasm, version("knowledge"), signer
        ),
        "workspace": build(BUSINESS / "workspace/package.json", signer),
        "automation": build_worker(
            BUSINESS / "automation", args.automation_image, "/app/schedule-worker", signer
        ),
        "environments": build_worker(
            BUSINESS / "environments", args.environments_image, "/app/worker", signer
        ),
        "billing": build_billing(
            json.loads((BUSINESS / "billing/plans.json").read_bytes()),
            version=version("billing"),
            signer=signer,
            worker_image=args.billing_image,
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.out.parent) as temporary:
        staged = Path(temporary) / "archives"
        staged.mkdir()
        for name, raw in archives.items():
            (staged / f"memstack-{name}.mspkg").write_bytes(raw)
        staged.rename(args.out)


if __name__ == "__main__":
    main()
