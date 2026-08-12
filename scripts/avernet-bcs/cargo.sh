#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
readonly BCS_ROOT="${REPO_ROOT}/third_party/avernet-bcs"
readonly RUST_VERSION="1.91.1"
readonly PROTOC_VERSION="25.3"
readonly TOOL_ROOT="${REPO_ROOT}/.cache/avernet-bcs"
readonly TOOL_CACHE="${TOOL_ROOT}/protoc/${PROTOC_VERSION}"

export RUSTUP_HOME="${AVERNET_BCS_RUSTUP_HOME:-${TOOL_ROOT}/rustup}"
export CARGO_HOME="${AVERNET_BCS_CARGO_HOME:-${TOOL_ROOT}/cargo}"
export CARGO_TARGET_DIR="${AVERNET_BCS_TARGET_DIR:-${TOOL_ROOT}/target}"

platform_key() {
  local os
  local arch
  os="$(uname -s)"
  arch="$(uname -m)"

  case "${os}:${arch}" in
    Darwin:arm64) echo "osx-aarch_64" ;;
    Darwin:x86_64) echo "osx-x86_64" ;;
    Linux:aarch64|Linux:arm64) echo "linux-aarch_64" ;;
    Linux:x86_64|Linux:amd64) echo "linux-x86_64" ;;
    MINGW*:x86_64|MSYS*:x86_64|CYGWIN*:x86_64) echo "win64" ;;
    *)
      echo "unsupported protoc platform: ${os}/${arch}" >&2
      return 1
      ;;
  esac
}

expected_checksum() {
  case "$1" in
    osx-aarch_64) echo "d0fcd6d3b3ef6f22f1c47cc30a80c06727e1eccdddcaf0f4a3be47c070ffd3fe" ;;
    osx-x86_64) echo "247e003b8e115405172eacc50bd19825209d85940728e766f0848eee7c80e2a1" ;;
    linux-aarch_64) echo "9eae1f20f70cccc912d1c318c3929b86aebf5afd4b0f32c196ef682c222ed5ae" ;;
    linux-x86_64) echo "f853e691868d0557425ea290bf7ba6384eef2fa9b04c323afab49a770ba9da80" ;;
    win64) echo "d6b336b852726364313330631656b7f395dde5b1141b169f5c4b8d43cdf01482" ;;
    *) return 1 ;;
  esac
}

install_protoc() {
  local platform
  local install_dir
  local protoc_bin
  local expected
  local temp_dir
  local archive
  local actual
  local protoc_name

  platform="$(platform_key)"
  protoc_name="protoc"
  if [[ "${platform}" == "win64" ]]; then
    protoc_name="protoc.exe"
  fi
  install_dir="${TOOL_CACHE}/${platform}"
  protoc_bin="${install_dir}/bin/${protoc_name}"

  if [[ -x "${protoc_bin}" ]]; then
    printf '%s\n' "${protoc_bin}"
    return
  fi

  command -v curl >/dev/null || { echo "curl is required to install protoc" >&2; return 1; }
  command -v unzip >/dev/null || { echo "unzip is required to install protoc" >&2; return 1; }
  command -v shasum >/dev/null || { echo "shasum is required to verify protoc" >&2; return 1; }

  expected="$(expected_checksum "${platform}")"
  temp_dir="$(mktemp -d)"
  trap 'rm -rf "${temp_dir:?}"' RETURN
  archive="${temp_dir}/protoc.zip"

  curl --fail --location --silent --show-error \
    "https://github.com/protocolbuffers/protobuf/releases/download/v${PROTOC_VERSION}/protoc-${PROTOC_VERSION}-${platform}.zip" \
    --output "${archive}"
  actual="$(shasum -a 256 "${archive}" | awk '{print $1}')"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "protoc archive checksum mismatch for ${platform}" >&2
    return 1
  fi

  mkdir -p "${install_dir}"
  unzip -q "${archive}" -d "${install_dir}"
  [[ -x "${protoc_bin}" ]] || { echo "protoc archive did not contain bin/protoc" >&2; return 1; }
  printf '%s\n' "${protoc_bin}"
}

[[ -f "${BCS_ROOT}/Cargo.toml" ]] || {
  echo "Avernet BCS workspace is missing at ${BCS_ROOT}" >&2
  exit 1
}

command -v rustup >/dev/null || {
  echo "rustup is required to install the isolated BCS toolchain" >&2
  exit 1
}

if ! rustup toolchain list | grep -q "^${RUST_VERSION}-"; then
  rustup toolchain install "${RUST_VERSION}" \
    --profile minimal \
    --component clippy \
    --component rustfmt >&2
fi

readonly PROTOC_BIN="$(install_protoc)"
if [[ "$(platform_key)" == "win64" ]]; then
  command -v cygpath >/dev/null || {
    echo "cygpath is required to run the isolated BCS toolchain on Windows" >&2
    exit 1
  }
  export PROTOC="$(cygpath -w "${PROTOC_BIN}")"
else
  export PROTOC="${PROTOC_BIN}"
fi
export PATH="$(dirname "${PROTOC_BIN}"):${PATH}"

cd "${BCS_ROOT}"
exec rustup run "${RUST_VERSION}" cargo "$@"
