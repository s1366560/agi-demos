#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
./build.sh
test_dir="$(mktemp -d -t memstack-cua-tests)"
trap 'rm -rf "$test_dir"' EXIT
sources=($(rg --files Sources | rg -v '/main.swift$'))
swiftc -swift-version 5 -o "$test_dir/structural-tests" $sources LockedUse/Installer/InstallTransaction.swift LockedUse/Installer/ProtectedPath.swift tests/StructuralTests.swift tests/AudioMixingTests.swift tests/AudioCaptureTests.swift tests/MeetingAudioTests.swift tests/ArtifactRetentionTests.swift tests/InputOutputTests.swift tests/WindowIdentityTests.swift tests/LockedUseTests.swift tests/LockedUseUnlockTests.swift tests/LockedUseInstallerTests.swift tests/LockedUseActivationTests.swift
codesign --force --sign - --identifier ai.memstack.cua.structural-tests "$test_dir/structural-tests"
"$test_dir/structural-tests"
python3 tests/protocol_test.py
./test-locked-use-broker.sh
./test-locked-use-coverage.sh
