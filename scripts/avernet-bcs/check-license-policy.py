#!/usr/bin/env python3
"""Fail closed when locked Avernet dependencies leave the reviewed license policy."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _locked_package_name(location: str, package: dict[str, Any]) -> str | None:
    if name := package.get("name"):
        return str(name)
    marker = "node_modules/"
    if marker not in location:
        return None
    remainder = location.rsplit(marker, maxsplit=1)[1]
    parts = remainder.split("/")
    if parts[0].startswith("@") and len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def _reviewed_license_expression(
    bcs_root: Path,
    approved: set[str],
    overrides: dict[str, Any],
    package_name: str | None,
    version: str,
    errors: list[str],
) -> str | None:
    coordinate = f"{package_name}@{version}" if package_name is not None else ""
    override = overrides.get(coordinate) if coordinate else None
    if override is None:
        return None

    expression = override.get("expression")
    if expression not in approved:
        errors.append(f"npm override:{coordinate}: unreviewed license expression {expression!r}")
        return None

    relative_license = Path(str(override.get("license_file", "")))
    license_path = (bcs_root / relative_license).resolve()
    if (
        not relative_license.parts
        or relative_license.is_absolute()
        or not license_path.is_relative_to(bcs_root.resolve())
        or not license_path.is_file()
    ):
        errors.append(f"npm override:{coordinate}: reviewed license file is missing")
        return None

    expected_sha256 = override.get("license_sha256")
    actual_sha256 = hashlib.sha256(license_path.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        message = f"npm override:{coordinate}: reviewed license hash differs: "
        message += f"expected={expected_sha256!r} actual={actual_sha256!r}"
        errors.append(message)
        return None

    source = override.get("source")
    if not isinstance(source, str) or not source.startswith("https://"):
        errors.append(f"npm override:{coordinate}: HTTPS source is required")
        return None
    return str(expression)


def _check_npm_lock(
    bcs_root: Path,
    relative_path: str,
    approved: set[str],
    overrides: dict[str, Any],
    enforce_development: bool,
    errors: list[str],
) -> set[str]:
    lock_path = bcs_root / relative_path
    if not lock_path.is_file():
        errors.append(f"npm:{relative_path}: required lockfile is missing")
        return set()
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("lockfileVersion") != 3:
        errors.append(f"npm:{relative_path}: lockfileVersion 3 is required")
        return set()

    lock_root = Path(relative_path).parent
    locked_fixture_paths: set[str] = set()
    for location, package in lock.get("packages", {}).items():
        local_manifest = bcs_root / lock_root / location / "package.json"
        if location and local_manifest.is_file():
            locked_fixture_paths.add(local_manifest.relative_to(bcs_root).as_posix())
        version = package.get("version")
        if not version or (package.get("dev") and not enforce_development):
            continue
        expression = package.get("license")
        coordinate = f"npm:{relative_path}:{location or '<root>'}@{version}"
        if not expression:
            expression = _reviewed_license_expression(
                bcs_root,
                approved,
                overrides,
                _locked_package_name(location, package),
                str(version),
                errors,
            )
            if expression is None:
                errors.append(f"{coordinate}: missing license expression")
        elif expression not in approved:
            errors.append(f"{coordinate}: unreviewed license expression {expression!r}")
    return locked_fixture_paths


def cargo_metadata(repo_root: Path) -> dict[str, Any]:
    command = [
        str(repo_root / "scripts" / "avernet-bcs" / "cargo.sh"),
        "metadata",
        "--locked",
        "--format-version",
        "1",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def check_cargo(repo_root: Path, policy: dict[str, Any], errors: list[str]) -> None:
    approved = set(policy["cargo"]["approved_expressions"])
    for package in cargo_metadata(repo_root)["packages"]:
        expression = package.get("license")
        coordinate = f"cargo:{package['name']}@{package['version']}"
        if not expression:
            errors.append(f"{coordinate}: missing license expression")
        elif expression not in approved:
            errors.append(f"{coordinate}: unreviewed license expression {expression!r}")


def check_npm(bcs_root: Path, policy: dict[str, Any], errors: list[str]) -> None:
    npm_policy = policy["npm"]
    approved = set(npm_policy["approved_expressions"])
    overrides = npm_policy.get("reviewed_license_overrides", {})
    enforce_development = bool(npm_policy["enforce_development_dependencies"])
    required_lockfiles = set(npm_policy["required_lockfiles"])
    actual_lockfiles = {
        path.relative_to(bcs_root).as_posix()
        for path in bcs_root.rglob("package-lock.json")
        if "node_modules" not in path.parts
    }
    if actual_lockfiles != required_lockfiles:
        message = "npm: reviewed lockfile set differs: "
        message += f"expected={sorted(required_lockfiles)!r} actual={sorted(actual_lockfiles)!r}"
        errors.append(message)

    fixture_manifests = set(npm_policy["explicit_test_fixtures"])
    package_manifests = {
        path.relative_to(bcs_root).as_posix()
        for path in bcs_root.rglob("package.json")
        if "node_modules" not in path.parts
    }
    locked_manifests = {str(Path(path).with_name("package.json")) for path in required_lockfiles}
    expected_manifests = locked_manifests | fixture_manifests
    if package_manifests != expected_manifests:
        message = "npm: package manifest coverage differs: "
        message += f"expected={sorted(expected_manifests)!r} actual={sorted(package_manifests)!r}"
        errors.append(message)

    locked_fixture_paths: set[str] = set()
    for relative_path in npm_policy["required_lockfiles"]:
        locked_fixture_paths.update(
            _check_npm_lock(
                bcs_root,
                relative_path,
                approved,
                overrides,
                enforce_development,
                errors,
            )
        )
    missing_fixtures = fixture_manifests - locked_fixture_paths
    if missing_fixtures:
        errors.append(
            f"npm: explicit test fixtures absent from reviewed locks: {sorted(missing_fixtures)!r}"
        )


def check_notices(bcs_root: Path, policy: dict[str, Any], errors: list[str]) -> None:
    for relative_path in policy["required_notices"]:
        notice_path = bcs_root / relative_path
        if not notice_path.is_file() or not notice_path.read_text(encoding="utf-8").strip():
            errors.append(f"notice:{relative_path}: required non-empty file is missing")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    bcs_root = repo_root / "third_party" / "avernet-bcs"
    policy_path = bcs_root / "license-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if policy.get("version") != 1:
        raise SystemExit("unsupported Avernet license policy version")

    errors: list[str] = []
    check_cargo(repo_root, policy, errors)
    check_npm(bcs_root, policy, errors)
    check_notices(bcs_root, policy, errors)
    if errors:
        for error in sorted(errors):
            print(error, file=sys.stderr)
        return 1
    print("Avernet license policy verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
