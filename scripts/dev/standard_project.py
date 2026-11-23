"""Start a checkout-local empty kernel with the six signed official business packages."""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.build_standard_packages import WORKER_CONTEXTS

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / ".memstack/standard"


def initialize(directory: Path) -> None:
    if (directory / "owner.json").is_file():
        return
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory.parent) as temporary:
        stage = Path(temporary) / "state"
        stage.mkdir(mode=0o700)
        signer = Ed25519PrivateKey.generate()
        (stage / "publisher.key").write_bytes(
            signer.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        (stage / "publisher.pem").write_bytes(
            signer.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
        password = secrets.token_urlsafe(32)
        (stage / "postgres-password").write_text(password)
        (stage / "database.env").write_text(
            f"DATABASE_URL=postgresql://memstack:{password}@postgres/memstack\n"
        )
        (stage / "kernel.env").write_text(f"SECRET_KEY={secrets.token_urlsafe(48)}\n")
        owner = {
            "email": "owner@example.org",
            "password": secrets.token_urlsafe(30),
            "tenant_name": "Development",
            "project_name": "Standard",
        }
        (stage / "owner.json").write_text(json.dumps(owner))
        for file in stage.iterdir():
            file.chmod(0o600)
        stage.rename(directory)


def run(command: list[str], env: dict[str, str]) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def prepare_archives(directory: Path, env: dict[str, str]) -> None:
    if (directory / "archives").is_dir():
        return
    registry = "127.0.0.1:" + env.get("STANDARD_REGISTRY_PORT", "5095")
    with tempfile.TemporaryDirectory() as temporary:
        build = Path(temporary)
        images = []
        for name, source in WORKER_CONTEXTS.items():
            tag = f"{registry}/memstack/{name}:dev"
            metadata = build / f"{name}.json"
            run(
                [
                    "docker",
                    "buildx",
                    "build",
                    "--provenance=false",
                    "--push",
                    "--metadata-file",
                    str(metadata),
                    "-t",
                    tag,
                    str(ROOT / "plugins/business" / source),
                ],
                env,
            )
            digest = json.loads(metadata.read_bytes())["containerimage.digest"]
            images += ["--" + name + "-image", tag.rsplit(":", 1)[0] + "@" + digest]
        target = build / "target"
        run(
            [
                "cargo",
                "build",
                "--locked",
                "--release",
                "--target",
                "wasm32-unknown-unknown",
                "--target-dir",
                str(target),
                "--manifest-path",
                "plugins/business/knowledge/workers/device_search/Cargo.toml",
            ],
            env,
        )
        guest = target / "wasm32-unknown-unknown/release/memstack_device_knowledge.wasm"
        run(
            [
                sys.executable,
                "-m",
                "scripts.build_standard_packages",
                "--key",
                str(directory / "publisher.key"),
                "--out",
                str(directory / "archives"),
                "--device-wasm",
                str(guest),
                *images,
            ],
            env,
        )


def compose_project_name(directory: Path) -> str:
    identity = hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:12]
    return "memstack-standard-" + identity


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["init", "start", "stop", "status", "logs", "restart", "reset"]
    )
    args = parser.parse_args()
    directory = Path(os.environ.get("STANDARD_DIRECTORY", str(DEFAULT_DIR))).resolve()
    env = {
        **os.environ,
        "STANDARD_DIRECTORY": str(directory),
        "PYTHONPATH": str(ROOT / "sdk/memstack-plugin-sdk/src"),
    }
    project = compose_project_name(directory)
    compose = [
        "docker",
        "compose",
        "--project-name",
        project,
        "-f",
        "docker-compose.standard.yml",
    ]
    if os.environ.get("STANDARD_NPM_SOURCE") == "1" or (directory / "npm-source.enabled").is_file():
        compose.extend(["-f", "docker-compose.standard.npm.yml"])
    if (
        args.command not in {"init", "start", "restart"}
        and not (directory / "owner.json").is_file()
    ):
        print("This checkout has no initialized standard project.")
        return
    if args.command in {"init", "start", "restart"}:
        initialize(directory)
        run([*compose, "up", "-d", "--wait", "registry"], env)
        prepare_archives(directory, env)
        if args.command != "init":
            run(["corepack", "pnpm", "--dir", "web", "install", "--frozen-lockfile"], env)
            run(["corepack", "pnpm", "--dir", "web", "run", "build:project-packages"], env)
            run([*compose, "up", "-d", "--build", "--wait"], env)
            if args.command == "restart":
                run([*compose, "restart", "api", "web"], env)
                run([*compose, "up", "-d", "--wait"], env)
        print(f"Initial project owner credentials are stored in {directory / 'owner.json'}")
    elif args.command == "reset":
        # Retain publisher keys, identities and deterministic release inputs on the checkout.
        # The registry volume must survive because the installed archives pin its images.
        run([*compose, "rm", "-sf", "api", "web", "redis", "postgres"], env)
        volume = project + "_postgres"
        existing = subprocess.check_output(
            ["docker", "volume", "ls", "--filter", f"name=^{volume}$", "--format", "{{.Name}}"],
            env=env,
            text=True,
        ).splitlines()
        if volume in existing:
            run(["docker", "volume", "rm", volume], env)
    else:
        verb = {"stop": "stop", "status": "ps", "logs": "logs"}[args.command]
        run([*compose, verb], env)


if __name__ == "__main__":
    main()
