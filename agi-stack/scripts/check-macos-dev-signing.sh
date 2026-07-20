#!/bin/sh

set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo "macOS development signing check skipped on $(uname -s)"
  exit 0
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test_root=$(mktemp -d "${TMPDIR:-/tmp}/agistack-dev-signing.XXXXXX")
signing_dir="$test_root/signing"
test_id=$(basename "$test_root")
keychain_path="$HOME/Library/Keychains/$test_id.keychain-db"
binary="$test_root/dev-signing-smoke"
source_file="$test_root/main.c"

remove_test_keychain_from_search_path() {
  set --
  while IFS= read -r listed_keychain; do
    listed_keychain=$(printf '%s' "$listed_keychain" | sed 's/^[[:space:]]*"//; s/"$//')
    if [ -n "$listed_keychain" ] && [ "$listed_keychain" != "$keychain_path" ]; then
      set -- "$@" "$listed_keychain"
    fi
  done <<EOF
$(security list-keychains -d user)
EOF
  security list-keychains -d user -s "$@" >/dev/null 2>&1 || true
}

cleanup() {
  remove_test_keychain_from_search_path
  certificate_path="$signing_dir/development-signing.crt"
  if [ -f "$certificate_path" ]; then
    security remove-trusted-cert "$certificate_path" >/dev/null 2>&1 || true
  fi
  if [ -f "$keychain_path" ]; then
    security delete-keychain "$keychain_path" >/dev/null 2>&1 || true
  fi
  rm -rf "$test_root"
}
trap cleanup EXIT HUP INT TERM

build_binary() {
  return_code=$1
  printf 'int main(void) { return %s; }\n' "$return_code" >"$source_file"
  xcrun clang "$source_file" -o "$binary"
}

designated_requirement() {
  codesign -d -r- "$binary" 2>&1 | sed -n 's/^designated => //p'
}

build_binary 0
AGISTACK_MACOS_DEV_SIGNING_DIR="$signing_dir" \
  AGISTACK_MACOS_DEV_KEYCHAIN_PATH="$keychain_path" \
  "$script_dir/run-macos-dev-signed.sh" "$binary"
first_requirement=$(designated_requirement)

build_binary 0
AGISTACK_MACOS_DEV_SIGNING_DIR="$signing_dir" \
  AGISTACK_MACOS_DEV_KEYCHAIN_PATH="$keychain_path" \
  "$script_dir/run-macos-dev-signed.sh" "$binary"
second_requirement=$(designated_requirement)

if [ -z "$first_requirement" ] || [ "$first_requirement" != "$second_requirement" ]; then
  echo "macOS development signing requirement changed after rebuild" >&2
  exit 1
fi
case "$first_requirement" in
  *'identifier "ai.agistack.desktop"'*) ;;
  *)
    echo "macOS development signing requirement has the wrong identifier" >&2
    exit 1
    ;;
esac

echo "macOS development signing requirement remains stable after rebuild"
