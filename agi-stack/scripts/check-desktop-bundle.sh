#!/usr/bin/env bash
set -euo pipefail

ROOT="${AGISTACK_DESKTOP_ROOT:-apps/desktop/src-tauri}"
BUNDLE_ROOT="${AGISTACK_DESKTOP_BUNDLE_ROOT:-$ROOT/target/release/bundle}"
CONFIG="$ROOT/tauri.conf.json"
DIST="$ROOT/../dist/index.html"
EXPECTED_ID="${AGISTACK_DESKTOP_IDENTIFIER:-ai.agistack.desktop}"
EXPECTED_BIN="${AGISTACK_DESKTOP_BIN:-agistack-desktop}"

python3 - "$CONFIG" "$EXPECTED_ID" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
expected_id = sys.argv[2]
config = json.loads(config_path.read_text())
identifier = config.get("identifier")
if identifier != expected_id:
    raise SystemExit(f"unexpected Tauri identifier: {identifier!r}")
if not config.get("bundle", {}).get("active"):
    raise SystemExit("Tauri bundle.active must be true")
frontend_dist = config.get("build", {}).get("frontendDist")
if not frontend_dist:
    raise SystemExit("Tauri build.frontendDist is required")
PY

test -f "$DIST" || {
  echo "missing desktop frontend dist: $DIST" >&2
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
  macos_bin="$app_dir/Contents/MacOS/$EXPECTED_BIN"
  info_plist="$app_dir/Contents/Info.plist"
  test -x "$macos_bin" || {
    echo "macOS bundle binary is missing or not executable: $macos_bin" >&2
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
fi

echo "DESKTOP_BUNDLE_SMOKE_OK bundle_root=$BUNDLE_ROOT"
