#!/usr/bin/env bash
set -euo pipefail

ROOT="${AGISTACK_DESKTOP_ROOT:-apps/desktop}"
BUNDLE_ROOT="${AGISTACK_DESKTOP_BUNDLE_ROOT:-$ROOT/release}"
CONFIG="$ROOT/electron-builder.yml"
EXPECTED_ID="${AGISTACK_DESKTOP_IDENTIFIER:-ai.agistack.desktop}"
EXPECTED_SIDECAR="${AGISTACK_DESKTOP_SIDECAR:-agistack-desktop-sidecar}"

grep -q "^appId: $EXPECTED_ID$" "$CONFIG" || {
  echo "unexpected Electron app identifier in $CONFIG" >&2
  exit 1
}
test -d "$BUNDLE_ROOT" || {
  echo "missing desktop bundle directory: $BUNDLE_ROOT" >&2
  exit 1
}

first_bundle="$(find "$BUNDLE_ROOT" -mindepth 1 -maxdepth 3 -print -quit)"
test -n "$first_bundle" || {
  echo "desktop bundle directory is empty: $BUNDLE_ROOT" >&2
  exit 1
}

app_dir="$(find "$BUNDLE_ROOT" -name '*.app' -type d -print -quit || true)"
if [[ -n "$app_dir" ]]; then
  macos_bin="$(find "$app_dir/Contents/MacOS" -type f -perm -111 -print -quit)"
  sidecar_bin="$app_dir/Contents/Resources/sidecar/$EXPECTED_SIDECAR"
  info_plist="$app_dir/Contents/Info.plist"
  test -n "$macos_bin" || {
    echo "macOS bundle has no executable" >&2
    exit 1
  }
  test -x "$sidecar_bin" || {
    echo "macOS sidecar is missing or not executable: $sidecar_bin" >&2
    exit 1
  }
  test -f "$info_plist" || {
    echo "macOS bundle Info.plist is missing: $info_plist" >&2
    exit 1
  }
  grep -a -q "$EXPECTED_ID" "$info_plist" || {
    echo "macOS bundle Info.plist does not contain identifier $EXPECTED_ID" >&2
    exit 1
  }
  microphone_usage="$(
    /usr/bin/plutil -extract NSMicrophoneUsageDescription raw -o - "$info_plist"
  )"
  test -n "$microphone_usage" || {
    echo "macOS bundle Info.plist has no microphone usage description" >&2
    exit 1
  }
  renderer_helper="$(
    find "$app_dir/Contents/Frameworks" \
      -name '* Helper (Renderer).app' -type d -print -quit
  )"
  test -n "$renderer_helper" || {
    echo "macOS bundle has no Renderer Helper application" >&2
    exit 1
  }
  for entitlement_target in "$app_dir" "$renderer_helper"; do
    entitlements="$(codesign --display --entitlements :- "$entitlement_target" 2>&1)"
    grep -q 'com.apple.security.device.audio-input' <<<"$entitlements" || {
      echo "macOS bundle is missing audio-input entitlement: $entitlement_target" >&2
      exit 1
    }
  done
  codesign --verify --deep --strict "$app_dir"
  codesign --verify --strict "$sidecar_bin"
fi

echo "DESKTOP_BUNDLE_SMOKE_OK bundle_root=$BUNDLE_ROOT"
