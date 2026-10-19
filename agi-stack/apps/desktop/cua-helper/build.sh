#!/bin/zsh
# Build and sign the helper bundle. Staging beside a sidecar is explicit in
# scripts/build-cua-helper.mjs, never a side effect of a protocol test build.
set -eo pipefail

cd "$(dirname "$0")"
mkdir -p bin
if [ "$MEMSTACK_CUA_UNIVERSAL" = "1" ]; then
  swiftc -swift-version 5 -target arm64-apple-macos14.4 -O -o bin/cua-helper-arm64 Sources/*.swift
  swiftc -swift-version 5 -target x86_64-apple-macos14.4 -O -o bin/cua-helper-x86_64 Sources/*.swift
  lipo -create bin/cua-helper-arm64 bin/cua-helper-x86_64 -output bin/cua-helper
  rm bin/cua-helper-arm64 bin/cua-helper-x86_64
else
  swiftc -swift-version 5 -O -o bin/cua-helper Sources/*.swift
fi
./LockedUse/build.sh
codesign --force --sign - --identifier ai.agistack.desktop.cua-helper --entitlements LockedUse/entitlements.plist bin/cua-helper

# Optional: sign with a stable identity so macOS TCC grants (Accessibility,
# Screen Recording) survive rebuilds — ad-hoc binaries change cdhash on every
# rebuild and silently lose their grants. Pick one:
#   security find-identity -v -p codesigning
# export MEMSTACK_CUA_CODESIGN_IDENTITY="Apple Development: you@example.com (ABC123)"
if [ -n "${MEMSTACK_CUA_CODESIGN_IDENTITY:-}" ]; then
  codesign --force --options runtime --identifier ai.agistack.desktop.cua-helper --entitlements LockedUse/entitlements.plist --sign "$MEMSTACK_CUA_CODESIGN_IDENTITY" bin/cua-helper
  echo "signed with: $MEMSTACK_CUA_CODESIGN_IDENTITY"
fi

node ../scripts/bundle-cua-helper.mjs

echo "built: $(pwd)/bin/Memstack Computer Use.app"
