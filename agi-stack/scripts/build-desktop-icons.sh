#!/usr/bin/env bash
set -euo pipefail

SOURCE_ICON="${1:-apps/desktop/src-tauri/icons/icon.png}"
OUTPUT_ICON="${2:-apps/desktop/src-tauri/icons/icon.icns}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  if [[ -f "$OUTPUT_ICON" ]]; then
    exit 0
  fi
  echo "missing desktop icon $OUTPUT_ICON; generating .icns requires macOS iconutil" >&2
  exit 1
fi

command -v sips >/dev/null || {
  echo "sips is required to generate desktop icons" >&2
  exit 1
}
command -v iconutil >/dev/null || {
  echo "iconutil is required to generate desktop icons" >&2
  exit 1
}
test -f "$SOURCE_ICON" || {
  echo "missing source icon: $SOURCE_ICON" >&2
  exit 1
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
iconset="$tmp_dir/AppIcon.iconset"
mkdir -p "$iconset"

make_icon() {
  local name="$1"
  local size="$2"
  sips -z "$size" "$size" "$SOURCE_ICON" --out "$iconset/$name" >/dev/null
}

make_icon "icon_16x16.png" 16
make_icon "icon_16x16@2x.png" 32
make_icon "icon_32x32.png" 32
make_icon "icon_32x32@2x.png" 64
make_icon "icon_128x128.png" 128
make_icon "icon_128x128@2x.png" 256
make_icon "icon_256x256.png" 256
make_icon "icon_256x256@2x.png" 512
make_icon "icon_512x512.png" 512
make_icon "icon_512x512@2x.png" 1024

iconutil -c icns "$iconset" -o "$OUTPUT_ICON"
echo "DESKTOP_ICON_OK $OUTPUT_ICON"
