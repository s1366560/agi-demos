#!/usr/bin/env python3
"""Generate deterministic CycloneDX inventories from the locked Avernet inputs."""

# pyright: reportImplicitStringConcatenation=false, reportUnusedCallResult=false

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tomllib
import urllib.parse
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENERATOR_NAME = "memstack-avernet-sbom"
GENERATOR_VERSION = "1.0.0"
UPSTREAM_REVISION = "e470fb3d88979b9da8dc11c63f9d9c4b73343c9d"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def source_timestamp() -> str:
    raw_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if raw_epoch is None:
        raise SystemExit("SOURCE_DATE_EPOCH is required for reproducible SBOM generation")
    try:
        epoch = int(raw_epoch)
        timestamp = datetime.fromtimestamp(epoch, tz=UTC)
    except (OverflowError, ValueError) as error:
        raise SystemExit(f"invalid SOURCE_DATE_EPOCH: {error}") from error
    return timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cargo_metadata(bcs_root: Path) -> dict[str, Any]:
    command = [
        str(bcs_root.parents[1] / "scripts" / "avernet-bcs" / "cargo.sh"),
        "metadata",
        "--locked",
        "--format-version",
        "1",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def cargo_checksums(lock_path: Path) -> dict[tuple[str, str, str], str]:
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    checksums: dict[tuple[str, str, str], str] = {}
    for package in lock.get("package", []):
        checksum = package.get("checksum")
        if checksum:
            key = (package["name"], package["version"], package.get("source", ""))
            checksums[key] = checksum
    return checksums


def cargo_purl(name: str, version: str) -> str:
    return f"pkg:cargo/{urllib.parse.quote(name, safe='')}@{version}"


def npm_purl(name: str, version: str) -> str:
    if name.startswith("@") and "/" in name:
        scope, package = name[1:].split("/", 1)
        encoded_name = (
            f"%40{urllib.parse.quote(scope, safe='')}/{urllib.parse.quote(package, safe='')}"
        )
    else:
        encoded_name = urllib.parse.quote(name, safe="")
    return f"pkg:npm/{encoded_name}@{version}"


def component_ref(purl: str, origin: str) -> str:
    suffix = hashlib.sha256(origin.encode()).hexdigest()[:16]
    return f"{purl}#{suffix}"


def cargo_components(bcs_root: Path) -> list[dict[str, Any]]:
    metadata = cargo_metadata(bcs_root)
    checksums = cargo_checksums(bcs_root / "Cargo.lock")
    workspace_members = set(metadata["workspace_members"])
    components: list[dict[str, Any]] = []
    for package in metadata["packages"]:
        name = package["name"]
        version = package["version"]
        source = package.get("source") or "workspace"
        purl = cargo_purl(name, version)
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": component_ref(purl, f"{source}:{package['id']}"),
            "name": name,
            "version": version,
            "purl": purl,
            "properties": [
                {"name": "memstack:source", "value": source},
                {
                    "name": "memstack:workspace-member",
                    "value": str(package["id"] in workspace_members).lower(),
                },
            ],
        }
        if package.get("license"):
            component["licenses"] = [{"expression": package["license"]}]
        checksum = checksums.get((name, version, package.get("source") or ""))
        if checksum:
            component["hashes"] = [{"alg": "SHA-256", "content": checksum}]
        components.append(component)
    return sorted(components, key=lambda component: component["bom-ref"])


def npm_package_name(location: str, package: dict[str, Any], root_name: str) -> str:
    if package.get("name"):
        return str(package["name"])
    if not location:
        return root_name
    marker = "node_modules/"
    if marker not in location:
        raise ValueError(f"cannot derive npm package name from lock path {location!r}")
    return location.rsplit(marker, 1)[1]


def integrity_hash(integrity: str) -> list[dict[str, str]]:
    algorithm, separator, encoded = integrity.partition("-")
    algorithms = {"sha256": "SHA-256", "sha384": "SHA-384", "sha512": "SHA-512"}
    if not separator or algorithm not in algorithms:
        return []
    try:
        content = base64.b64decode(encoded, validate=True).hex()
    except ValueError:
        return []
    return [{"alg": algorithms[algorithm], "content": content}]


def reviewed_npm_lock_paths(bcs_root: Path) -> list[Path]:
    policy = json.loads((bcs_root / "license-policy.json").read_text(encoding="utf-8"))["npm"]
    required = set(policy["required_lockfiles"])
    actual = {
        path.relative_to(bcs_root).as_posix()
        for path in bcs_root.rglob("package-lock.json")
        if "node_modules" not in path.parts
    }
    if actual != required:
        raise SystemExit(
            "reviewed npm lockfile set differs: "
            f"expected={sorted(required)!r} actual={sorted(actual)!r}"
        )

    fixtures = set(policy["explicit_test_fixtures"])
    manifests = {
        path.relative_to(bcs_root).as_posix()
        for path in bcs_root.rglob("package.json")
        if "node_modules" not in path.parts
    }
    locked_manifests = {Path(path).with_name("package.json").as_posix() for path in required}
    expected_manifests = locked_manifests | fixtures
    if manifests != expected_manifests:
        raise SystemExit(
            "npm package manifest coverage differs: "
            f"expected={sorted(expected_manifests)!r} actual={sorted(manifests)!r}"
        )

    covered_fixtures: set[str] = set()
    lock_paths = [bcs_root / path for path in sorted(required)]
    for lock_path in lock_paths:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock_root = lock_path.parent
        for location in lock.get("packages", {}):
            local_manifest = lock_root / location / "package.json"
            if location and local_manifest.is_file():
                covered_fixtures.add(local_manifest.relative_to(bcs_root).as_posix())
    missing_fixtures = fixtures - covered_fixtures
    if missing_fixtures:
        raise SystemExit(
            f"explicit npm test fixtures absent from reviewed locks: {sorted(missing_fixtures)!r}"
        )
    return lock_paths


def npm_components(bcs_root: Path, lock_paths: list[Path]) -> list[dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    if not lock_paths:
        raise SystemExit("no npm lockfiles found below Avernet BCS root")
    for lock_path in lock_paths:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        if lock.get("lockfileVersion") != 3:
            raise SystemExit(f"{lock_path}: npm lockfileVersion 3 is required")
        relative_lock = lock_path.relative_to(bcs_root).as_posix()
        root_name = str(lock.get("name") or lock_path.parent.name)
        for location, package in lock.get("packages", {}).items():
            version = package.get("version")
            if not version:
                continue
            name = npm_package_name(location, package, root_name)
            purl = npm_purl(name, str(version))
            ref = component_ref(purl, relative_lock)
            component: dict[str, Any] = {
                "type": "library",
                "bom-ref": ref,
                "name": name,
                "version": str(version),
                "purl": purl,
                "properties": [
                    {"name": "memstack:lockfile", "value": relative_lock},
                    {
                        "name": "memstack:development",
                        "value": str(bool(package.get("dev"))).lower(),
                    },
                    {
                        "name": "memstack:optional",
                        "value": str(bool(package.get("optional"))).lower(),
                    },
                ],
            }
            if package.get("license"):
                component["licenses"] = [{"expression": str(package["license"])}]
            hashes = integrity_hash(str(package.get("integrity", "")))
            if hashes:
                component["hashes"] = hashes
            components[ref] = component
    return sorted(components.values(), key=lambda component: component["bom-ref"])


def make_bom(
    ecosystem: str, components: list[dict[str, Any]], timestamp: str, seed: str
) -> dict[str, Any]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, seed)}",
        "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": GENERATOR_NAME,
                        "version": GENERATOR_VERSION,
                    }
                ]
            },
            "component": {
                "type": "application",
                "name": f"avernet-bcs-{ecosystem}",
                "version": UPSTREAM_REVISION,
            },
        },
        "components": components,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    bcs_root = repo_root / "third_party" / "avernet-bcs"
    timestamp = source_timestamp()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    cargo_seed = f"cargo:{sha256_file(bcs_root / 'Cargo.lock')}:{timestamp}"
    cargo_bom = make_bom("cargo", cargo_components(bcs_root), timestamp, cargo_seed)
    write_json(args.output_dir / "avernet-bcs.cargo.cdx.json", cargo_bom)

    npm_locks = reviewed_npm_lock_paths(bcs_root)
    npm_seed_material = ":".join(sha256_file(path) for path in npm_locks)
    npm_seed = f"npm:{npm_seed_material}:{timestamp}"
    npm_bom = make_bom("npm", npm_components(bcs_root, npm_locks), timestamp, npm_seed)
    write_json(args.output_dir / "avernet-bcs.npm.cdx.json", npm_bom)
    return 0


if __name__ == "__main__":
    sys.exit(main())
