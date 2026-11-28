"""Manage the isolated development npm registry for signed MemStack packages."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import bcrypt

from src.infrastructure.plugins.v2.bundle_archive import (
    MAX_BUNDLE_BYTES_V2,
    declared_bundle_permissions_v2,
    parse_bundle_archive_v2,
)

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".cache/plugin-npm"
ORIGIN = "http://127.0.0.1:4873"
PACKAGE_FILE = "package/plugin.mspkg"


class MarketPresentation(TypedDict):
    name: dict[str, str]
    description: dict[str, str]
    icon: str
    targets: list[str]


def _localized(value: object, limit: int) -> dict[str, str]:
    if not isinstance(value, dict) or not value or not value.keys() <= {"en", "zh"}:
        raise ValueError("Provide an English or Chinese market translation")
    if any(
        not isinstance(text, str) or not text.strip() or len(text) > limit
        for text in value.values()
    ):
        raise ValueError("Invalid market translation")
    return dict(value)


def _market_presentation(path: Path, targets: set[str]) -> MarketPresentation | None:
    if not path.exists():
        return None
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value.keys() != {"name", "description", "icon"}:
        raise ValueError("Invalid market presentation")
    icon = value["icon"]
    if not isinstance(icon, str) or not re.fullmatch(r"[a-z0-9-]{1,48}", icon):
        raise ValueError("Expected a market icon identifier")
    return MarketPresentation(
        name=_localized(value["name"], 80),
        description=_localized(value["description"], 320),
        icon=icon,
        targets=sorted(targets),
    )


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    archive: bytes
    market: MarketPresentation | None = None
    scopes: tuple[str, ...] = ("project",)

    @property
    def selector(self) -> str:
        return f"{self.name}@{self.version}"


def signed_package(
    path: Path, public_key: str, metadata_directory: Path = ROOT / "plugins/business"
) -> Package:
    with path.open("rb") as archive:
        raw = archive.read(MAX_BUNDLE_BYTES_V2 + 1)
    verified = parse_bundle_archive_v2(
        raw,
        source=path.name,
        trusted_public_keys=(public_key,),
        require_signature=True,
        approved_permissions=declared_bundle_permissions_v2(raw),
    )
    signed = verified.manifest
    match = re.fullmatch(r"memstack-([a-z0-9][a-z0-9-]*)", signed.bundle_id)
    if (
        not match
        or len(signed.manifests) != 1
        or not all(
            plugin.plugin_id == signed.bundle_id and plugin.version == signed.version
            for plugin in signed.manifests
        )
    ):
        raise ValueError("Expected a signed project package with a matching business identity")
    scopes = {"project"}
    targets = {a.target.value for a in signed.artifacts}
    for artifact in signed.artifacts:
        if artifact.path in {"targets/desktop-capability.json", "targets/desktop-sidecar.mspkg"}:
            targets.add("desktop-sidecar")
        if artifact.path == "contributions.json":
            contribution = json.loads(verified.artifacts[artifact.artifact_id])
            if any(page.get("scope") == "tenant" for page in contribution.get("pages", [])):
                scopes.add("tenant")
            targets.update(t for page in contribution.get("pages", []) for t in page["targets"])
    market = _market_presentation(metadata_directory / match[1] / "market.json", targets)
    return Package(f"@memstack/{match[1]}", signed.version, raw, market, tuple(sorted(scopes)))


def tarball(package: Package) -> bytes:
    manifest: dict[str, object] = {
        "name": package.name,
        "version": package.version,
        "files": ["plugin.mspkg"],
        **({"memstack": {"scopes": package.scopes}} if "tenant" in package.scopes else {}),
        "publishConfig": {"registry": ORIGIN},
    }
    if package.market:
        descriptions = package.market["description"]
        manifest.update(
            {
                "description": descriptions.get("en") or descriptions["zh"],
                "keywords": ["memstack-plugin"],
                "memstack": {"market": package.market, "scopes": package.scopes},
            }
        )
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, content in (
            ("package/package.json", json.dumps(manifest, separators=(",", ":")).encode()),
            (PACKAGE_FILE, package.archive),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return gzip.compress(stream.getvalue(), mtime=0)


def initialize(state: Path) -> None:
    if state.is_dir():
        if not (state / "publishers").is_file() or not (state / "password").is_file():
            raise ValueError(f"Incomplete registry publisher configuration at {state}")
        return
    state.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=state.parent) as temporary:
        stage = Path(temporary) / "registry"
        stage.mkdir(mode=0o700)
        password = secrets.token_urlsafe(36)
        (stage / "password").write_text(password)
        (stage / "password").chmod(0o600)
        digest = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        (stage / "publishers").write_bytes(b"publisher:" + digest + b"\n")
        (stage / "publishers").chmod(0o444)
        stage.rename(state)


def lifecycle(action: str, state: Path) -> None:
    initialize(state)
    compose = ["docker", "compose", "-f", str(ROOT / "docker-compose.npm.yml")]
    env = {**os.environ, "MEMSTACK_NPM_STATE": str(state.resolve())}
    commands = {
        "start": [["up", "-d", "--wait"]],
        "restart": [["restart"], ["up", "-d", "--wait"]],
        "stop": [["stop"]],
    }
    for command in commands[action]:
        subprocess.run([*compose, *command], env=env, check=True)


def npm(args: list[str], tmp: Path, *, missing_ok: bool = False) -> bytes | None:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.lower().startswith("npm_config_") and not k.lower().endswith("_proxy")
    }
    env.update(
        {
            "NPM_CONFIG_USERCONFIG": str(tmp / "npmrc"),
            "NPM_CONFIG_GLOBALCONFIG": str(tmp / "globalrc"),
            "NPM_CONFIG_CACHE": str(tmp / "cache"),
            "NO_PROXY": "localhost,127.0.0.1",
        }
    )
    result = subprocess.run(
        ["npm", *args, "--registry", ORIGIN, "--ignore-scripts", "--json"],
        cwd=tmp,
        env=env,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        if missing_ok and b"E404" in result.stdout + result.stderr:
            return None
        # npm debug output can include authentication-related request information.
        raise RuntimeError(f"npm {args[0]} failed ({result.returncode}) for {args[1]}")
    return result.stdout


def verify(package: Package, directory: Path) -> None:
    dist = npm(["view", package.selector, "dist.integrity"], directory)
    if dist is None:
        raise ValueError(f"Missing {package.selector}")
    packed = npm(["pack", package.selector], directory)
    assert packed is not None
    path = directory / json.loads(packed)[0]["filename"]
    data = path.read_bytes()
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()
    if not hmac.compare_digest(json.loads(dist), integrity):
        raise ValueError(f"Invalid npm integrity for {package.selector}")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        if sorted(archive.getnames()) != ["package/package.json", PACKAGE_FILE]:
            raise ValueError(f"Unexpected file set in {package.selector}")
        manifest = archive.extractfile("package/package.json")
        metadata = json.load(manifest) if manifest is not None else {}
        if (metadata.get("name"), metadata.get("version")) != (package.name, package.version):
            raise ValueError(f"Unexpected package identity in {package.selector}")
        plugin = archive.extractfile(PACKAGE_FILE)
        if plugin is None or not hmac.compare_digest(plugin.read(), package.archive):
            raise ValueError(f"Signed archive differs in {package.selector}")
    path.unlink()
    print(f"{package.selector}  mspkg-sha512={hashlib.sha512(package.archive).hexdigest()}")


def distribute(action: str, packages: list[Package], state: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="memstack-local-npm-") as temporary:
        directory = Path(temporary)
        config = f"registry={ORIGIN}/\n@memstack:registry={ORIGIN}/\n"
        if action == "publish":
            password = (state / "password").read_text()
            auth = base64.b64encode(("publisher:" + password).encode()).decode()
            config += f"//127.0.0.1:4873/:_auth={auth}\n"
        (directory / "npmrc").write_text(config)
        (directory / "npmrc").chmod(0o600)
        (directory / "globalrc").touch()
        for package in packages:
            if (
                action == "publish"
                and npm(["view", package.selector, "version"], directory, missing_ok=True) is None
            ):
                artifact = directory / "release.tgz"
                artifact.write_bytes(tarball(package))
                npm(["publish", artifact.name, "--access", "public"], directory)
            verify(package, directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "restart", "publish", "verify"))
    parser.add_argument("--state", type=Path, default=STATE)
    parser.add_argument("--standard-directory", type=Path, default=ROOT / ".memstack/standard")
    parser.add_argument("--metadata-directory", type=Path, default=ROOT / "plugins/business")
    args = parser.parse_args()
    if args.action in {"publish", "verify"}:
        archives = sorted((args.standard_directory / "archives").glob("*.mspkg"))
        if not archives:
            parser.error("No .mspkg files found in the standard project's archives directory")
        public = (args.standard_directory / "publisher.pem").read_text()
        distribute(
            args.action,
            [signed_package(path, public, args.metadata_directory) for path in archives],
            args.state,
        )
    else:
        lifecycle(args.action, args.state)


if __name__ == "__main__":
    main()
