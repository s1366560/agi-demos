#!/bin/sh

set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: run-macos-dev-signed.sh <binary> [args...]" >&2
  exit 64
fi

if [ "$(uname -s)" != "Darwin" ]; then
  exec "$@"
fi

binary=$1
shift

case "$binary" in
  /*) ;;
  *) binary="$(pwd)/$binary" ;;
esac

if [ ! -f "$binary" ]; then
  echo "macOS development runner could not find binary: $binary" >&2
  exit 66
fi

identity_name="agi-stack Desktop Local Development"
signing_identifier="ai.agistack.desktop"
cache_root=${XDG_CACHE_HOME:-"$HOME/Library/Caches"}
signing_dir=${AGISTACK_MACOS_DEV_SIGNING_DIR:-"$cache_root/ai.agistack.desktop/dev-signing"}
keychain_path=${AGISTACK_MACOS_DEV_KEYCHAIN_PATH:-"$HOME/Library/Keychains/ai.agistack.desktop-dev-signing.keychain-db"}
password_path="$signing_dir/keychain-password"
certificate_path="$signing_dir/development-signing.crt"

ensure_user_keychain_search_path() {
  set --
  keychain_is_listed=0
  while IFS= read -r listed_keychain; do
    listed_keychain=$(printf '%s' "$listed_keychain" | sed 's/^[[:space:]]*"//; s/"$//')
    if [ -n "$listed_keychain" ]; then
      set -- "$@" "$listed_keychain"
      if [ "$listed_keychain" = "$keychain_path" ]; then
        keychain_is_listed=1
      fi
    fi
  done <<EOF
$(security list-keychains -d user)
EOF
  if [ "$keychain_is_listed" -eq 0 ]; then
    security list-keychains -d user -s "$@" "$keychain_path"
  fi
}

mkdir -p "$signing_dir"
chmod 700 "$signing_dir"

if [ ! -f "$password_path" ]; then
  umask 077
  openssl rand -hex 32 >"$password_path"
fi
chmod 600 "$password_path"
keychain_password=$(sed -n '1p' "$password_path")
if [ -z "$keychain_password" ]; then
  echo "macOS development signing keychain password is empty" >&2
  exit 65
fi

if [ ! -f "$keychain_path" ]; then
  security create-keychain -p "$keychain_password" "$keychain_path"
fi
security unlock-keychain -p "$keychain_password" "$keychain_path"
security set-keychain-settings -lut 300 "$keychain_path"

identity_sha=$(
  security find-certificate -c "$identity_name" -Z "$keychain_path" 2>/dev/null \
    | awk '/SHA-1 hash:/{print $3; exit}'
)

if [ -z "$identity_sha" ]; then
  provision_dir=$(mktemp -d "$signing_dir/provision.XXXXXX")
  trap 'rm -rf "$provision_dir"' EXIT HUP INT TERM
  openssl_config="$provision_dir/openssl.cnf"
  private_key="$provision_dir/identity.key"
  archive="$provision_dir/identity.p12"

  {
    echo '[req]'
    echo 'distinguished_name = subject'
    echo 'x509_extensions = extensions'
    echo 'prompt = no'
    echo '[subject]'
    echo "CN = $identity_name"
    echo '[extensions]'
    echo 'basicConstraints = critical, CA:false'
    echo 'keyUsage = critical, digitalSignature'
    echo 'extendedKeyUsage = codeSigning'
    echo 'subjectKeyIdentifier = hash'
    echo 'authorityKeyIdentifier = keyid:always'
  } >"$openssl_config"

  openssl req -new -newkey rsa:2048 -nodes -x509 -days 3650 \
    -config "$openssl_config" \
    -keyout "$private_key" \
    -out "$certificate_path" 2>/dev/null
  openssl pkcs12 -export -legacy \
    -inkey "$private_key" \
    -in "$certificate_path" \
    -name "$identity_name" \
    -passout "pass:$keychain_password" \
    -out "$archive"
  security import "$archive" \
    -k "$keychain_path" \
    -P "$keychain_password" \
    -T /usr/bin/codesign
  security set-key-partition-list \
    -S apple-tool:,apple:,codesign: \
    -s \
    -k "$keychain_password" \
    "$keychain_path" >/dev/null

  identity_sha=$(
    security find-certificate -c "$identity_name" -Z "$keychain_path" \
      | awk '/SHA-1 hash:/{print $3; exit}'
  )
  rm -f "$openssl_config" "$private_key" "$archive"
  rmdir "$provision_dir"
  trap - EXIT HUP INT TERM
fi

if [ -z "$identity_sha" ]; then
  echo "macOS development signing identity is unavailable" >&2
  exit 69
fi

if [ ! -f "$certificate_path" ]; then
  umask 077
  security find-certificate -c "$identity_name" -p "$keychain_path" >"$certificate_path"
fi
if ! security find-identity -v -p codesigning "$keychain_path" \
  | grep -F "$identity_sha" >/dev/null; then
  security add-trusted-cert \
    -r trustRoot \
    -p codeSign \
    -k "$keychain_path" \
    "$certificate_path"
fi
ensure_user_keychain_search_path

codesign --force \
  --sign "$identity_sha" \
  --identifier "$signing_identifier" \
  --keychain "$keychain_path" \
  "$binary"
security lock-keychain "$keychain_path"

if [ "${AGISTACK_MACOS_DEV_SIGN_ONLY:-0}" = "1" ]; then
  exit 0
fi
exec "$binary" "$@"
