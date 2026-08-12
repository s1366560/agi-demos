#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
readonly BCS_ROOT="${REPO_ROOT}/third_party/avernet-bcs"
readonly CARGO_AUDIT_BIN="${CARGO_AUDIT_BIN:-cargo-audit}"
readonly EXPECTED_CARGO_AUDIT_VERSION="0.22.2"
readonly AUDIT_CARGO_HOME="${AVERNET_BCS_AUDIT_CARGO_HOME:-${REPO_ROOT}/.cache/avernet-bcs/cargo-audit-home}"

if ! command -v "${CARGO_AUDIT_BIN}" >/dev/null 2>&1; then
  echo "cargo-audit is required; install the CI-pinned version 0.22.2 in an isolated tool root" >&2
  exit 2
fi

actual_version="$("${CARGO_AUDIT_BIN}" audit --version | awk '{print $2}')"
if [[ "${actual_version}" != "${EXPECTED_CARGO_AUDIT_VERSION}" ]]; then
  echo "cargo-audit ${EXPECTED_CARGO_AUDIT_VERSION} is required; found ${actual_version}" >&2
  exit 2
fi

mkdir -p "${AUDIT_CARGO_HOME}"
export CARGO_HOME="${AUDIT_CARGO_HOME}"

cd "${BCS_ROOT}"
exec "${CARGO_AUDIT_BIN}" audit --deny warnings --file Cargo.lock
