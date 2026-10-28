#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
test_dir="$(mktemp -d -t memstack-cua-coverage-tests)"
trap 'rm -rf "$test_dir"' EXIT
swiftc -swift-version 5 -warnings-as-errors -o "$test_dir/coverage-tests" \
    Sources/LockedUseCoverage.swift tests/LockedUseCoverageTests.swift
"$test_dir/coverage-tests"
