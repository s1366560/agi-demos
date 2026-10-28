#!/bin/zsh
set -eo pipefail
cd "$(dirname "$0")"
shared=(../Sources/LockedUseLease.swift ../Sources/LockedUseWire.swift ../Sources/LockedUseSigning.swift ../Sources/LockedUseInputProtection.swift ../Sources/LockedUseCoverage.swift)
activation=(../Sources/LockedUseActivation.swift ../Sources/LockedUseWire.swift)
mkdir -p ../bin/locked-use/MemStackComputerUseAuthorizationPlugin.bundle/Contents/MacOS
if [ "$MEMSTACK_CUA_UNIVERSAL" = "1" ]; then
  for arch in arm64 x86_64; do
    swiftc -swift-version 5 -target "$arch-apple-macos14.4" -O -o "../bin/locked-use/guardian-$arch" $shared Guardian/*.swift
    swiftc -swift-version 5 -target "$arch-apple-macos14.4" -O -o "../bin/locked-use/installer-$arch" $activation Installer/*.swift
  done
  lipo -create ../bin/locked-use/guardian-arm64 ../bin/locked-use/guardian-x86_64 -output ../bin/locked-use/memstack-cua-guardian
  lipo -create ../bin/locked-use/installer-arm64 ../bin/locked-use/installer-x86_64 -output ../bin/locked-use/memstack-cua-lock-installer
  rm ../bin/locked-use/guardian-arm64 ../bin/locked-use/guardian-x86_64 ../bin/locked-use/installer-arm64 ../bin/locked-use/installer-x86_64
  clang -arch arm64 -arch x86_64 -mmacosx-version-min=14.4 -fobjc-arc -bundle -O2 -framework Foundation -framework Security -lbsm AuthorizationPlugin/AuthorizationPlugin.m -o ../bin/locked-use/MemStackComputerUseAuthorizationPlugin.bundle/Contents/MacOS/MemStackComputerUseAuthorizationPlugin
else
  swiftc -swift-version 5 -O -o ../bin/locked-use/memstack-cua-guardian $shared Guardian/*.swift
  swiftc -swift-version 5 -O -o ../bin/locked-use/memstack-cua-lock-installer $activation Installer/*.swift
  clang -fobjc-arc -bundle -O2 -framework Foundation -framework Security -lbsm AuthorizationPlugin/AuthorizationPlugin.m -o ../bin/locked-use/MemStackComputerUseAuthorizationPlugin.bundle/Contents/MacOS/MemStackComputerUseAuthorizationPlugin
fi
cat > ../bin/locked-use/MemStackComputerUseAuthorizationPlugin.bundle/Contents/Info.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>ai.agistack.desktop.cua.authorization-plugin</string>
<key>CFBundleExecutable</key><string>MemStackComputerUseAuthorizationPlugin</string>
<key>CFBundlePackageType</key><string>BNDL</string>
<key>CFBundleVersion</key><string>2</string>
</dict></plist>
PLIST
codesign --force --sign - ../bin/locked-use/MemStackComputerUseAuthorizationPlugin.bundle
codesign --force --sign - --identifier ai.agistack.desktop.cua.guardian ../bin/locked-use/memstack-cua-guardian
codesign --force --sign - --identifier ai.agistack.desktop.cua.lock-installer ../bin/locked-use/memstack-cua-lock-installer
if [[ -n "$MEMSTACK_CUA_CODESIGN_IDENTITY" ]]; then
  codesign --force --options runtime --sign "$MEMSTACK_CUA_CODESIGN_IDENTITY" \
    ../bin/locked-use/MemStackComputerUseAuthorizationPlugin.bundle
  codesign --force --options runtime --sign "$MEMSTACK_CUA_CODESIGN_IDENTITY" \
    --identifier ai.agistack.desktop.cua.guardian ../bin/locked-use/memstack-cua-guardian
  codesign --force --options runtime --sign "$MEMSTACK_CUA_CODESIGN_IDENTITY" \
    --identifier ai.agistack.desktop.cua.lock-installer ../bin/locked-use/memstack-cua-lock-installer
fi
