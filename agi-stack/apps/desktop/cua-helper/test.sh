#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
./build.sh
test_dir="$(mktemp -d -t memstack-cua-tests)"
trap 'rm -rf "$test_dir"' EXIT
sources=($(rg --files Sources | rg -v '/main.swift$'))
swiftc -swift-version 5 -o "$test_dir/structural-tests" $sources tests/StructuralTests.swift tests/AudioMixingTests.swift tests/AudioCaptureTests.swift tests/ArtifactRetentionTests.swift
codesign --force --sign - --identifier ai.memstack.cua.structural-tests "$test_dir/structural-tests"
"$test_dir/structural-tests"
python3 tests/protocol_test.py
