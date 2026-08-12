#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
readonly BCS_ROOT="${REPO_ROOT}/third_party/avernet-bcs"
readonly SOURCE_EPOCH="1786291263"
readonly FIRST_OUTPUT="$(mktemp -d)"
readonly SECOND_OUTPUT="$(mktemp -d)"

cleanup() {
  rm -rf "${FIRST_OUTPUT}" "${SECOND_OUTPUT}"
}
trap cleanup EXIT

python3 "${SCRIPT_DIR}/check-license-policy.py"

SOURCE_DATE_EPOCH="${SOURCE_EPOCH}" \
  python3 "${SCRIPT_DIR}/generate-sbom.py" --output-dir "${FIRST_OUTPUT}"
SOURCE_DATE_EPOCH="${SOURCE_EPOCH}" \
  python3 "${SCRIPT_DIR}/generate-sbom.py" --output-dir "${SECOND_OUTPUT}"
diff -ru "${FIRST_OUTPUT}" "${SECOND_OUTPUT}"

python3 - "${BCS_ROOT}" "${FIRST_OUTPUT}" <<'PY'
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

bcs_root = Path(sys.argv[1])
output_root = Path(sys.argv[2])
policy = json.loads((bcs_root / "license-policy.json").read_text(encoding="utf-8"))["npm"]
actual_manifests = {
    path.relative_to(bcs_root).as_posix()
    for path in bcs_root.rglob("package.json")
    if "node_modules" not in path.parts
}
actual_locks = {
    path.relative_to(bcs_root).as_posix()
    for path in bcs_root.rglob("package-lock.json")
    if "node_modules" not in path.parts
}
expected_manifests = {
    "assets/panel/package.json",
    "crates/plugins/openclaw-channel-bcn/package.json",
    "crates/plugins/openclaw-channel-bcn/test/fixtures/openclaw-stub/package.json",
}
expected_locks = {
    "assets/panel/package-lock.json",
    "crates/plugins/openclaw-channel-bcn/package-lock.json",
}
if actual_manifests != expected_manifests or actual_locks != expected_locks:
    raise SystemExit(
        f"npm inventory drift: manifests={sorted(actual_manifests)!r} locks={sorted(actual_locks)!r}"
    )
if set(policy["required_lockfiles"]) != expected_locks:
    raise SystemExit("npm lockfiles are not covered by the reviewed policy")

lock = tomllib.loads((bcs_root / "Cargo.lock").read_text(encoding="utf-8"))
coordinates = {(package["name"], package["version"]) for package in lock["package"]}
banned = {
    ("lru", "0.12.5"),
    ("proc-macro-error2", "2.0.1"),
    ("rkyv", "0.7.46"),
    ("rsa", "0.9.10"),
}
present = sorted(banned & coordinates)
if present:
    raise SystemExit(f"advisory dependency coordinates remain locked: {present}")

expected_timestamp = "2026-08-09T16:01:03Z"
for name in ("avernet-bcs.cargo.cdx.json", "avernet-bcs.npm.cdx.json"):
    bom = json.loads((output_root / name).read_text(encoding="utf-8"))
    if bom.get("bomFormat") != "CycloneDX" or bom.get("specVersion") != "1.6":
        raise SystemExit(f"{name}: invalid CycloneDX envelope")
    if bom.get("metadata", {}).get("timestamp") != expected_timestamp:
        raise SystemExit(f"{name}: SOURCE_DATE_EPOCH was not preserved")
    if not bom.get("components"):
        raise SystemExit(f"{name}: component inventory is empty")
PY

for build_script in \
  "${BCS_ROOT}/crates/bootstrap/bcs/build.rs" \
  "${BCS_ROOT}/crates/tools/bcs-cli/build.rs"; do
  if rg -n 'Command::new\("git"\)|Local::now' "${build_script}"; then
    echo "${build_script}: build provenance must not inspect Git or wall-clock time" >&2
    exit 1
  fi
  rg -q 'MEMSTACK_HOST_GIT_REVISION' "${build_script}"
  rg -q 'AVERNET_UPSTREAM_GIT_REVISION' "${build_script}"
  rg -q 'SOURCE_DATE_EPOCH' "${build_script}"
  rg -q 'e470fb3d88979b9da8dc11c63f9d9c4b73343c9d' "${build_script}"
done

echo "Avernet supply-chain contracts verified"
