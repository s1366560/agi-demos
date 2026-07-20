#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
signing_runner="$script_dir/run-macos-dev-signed.sh"
cargo_bin=${CARGO:-cargo}

export CARGO_TARGET_AARCH64_APPLE_DARWIN_RUNNER="$signing_runner"
export CARGO_TARGET_X86_64_APPLE_DARWIN_RUNNER="$signing_runner"

exec "$cargo_bin" "$@"
