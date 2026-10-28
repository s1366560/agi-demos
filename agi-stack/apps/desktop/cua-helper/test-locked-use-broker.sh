#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
test_dir="$(mktemp -d -t memstack-cua-broker-tests)"
trap 'rm -rf "$test_dir"' EXIT
sources=(Sources/LockedUseBroker.swift Sources/LockedUseBrokerSocket.swift Sources/LockedUseWire.swift)
swiftc -swift-version 5 -warnings-as-errors -D LOCKED_USE_BROKER_TESTS -o "$test_dir/broker-tests" \
    $sources tests/LockedUseBrokerTests.swift
"$test_dir/broker-tests"
