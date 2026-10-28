#!/bin/sh
# Ensure protocol-v2 grants, optionally launching a command with the validated pair.
# Default development mode can provision through the repository bootstrap and
# stays a graceful no-op when the backend/provisioning is unavailable. Reuse-only
# mode never invokes bootstrap and fails closed before launching on any failure.
# Grant files are parsed as data, not sourced; credentials never enter log/argv.
#
# Overrides:
#   AGISTACK_DESKTOP_GRANTS_API_BASE   requested API origin (default http://localhost:8000)
#   AGISTACK_DESKTOP_GRANTS_DIR        directory (default agi-stack/.local/desktop-grants)
#                                    relative paths are based on agi-stack
#   AGISTACK_DESKTOP_GRANTS_FORCE=1    reprovision in default development mode
#   AGISTACK_DESKTOP_GRANTS_REUSE_ONLY=1  require the existing pair; never provision
#   AGISTACK_DESKTOP_GRANTS_LOCAL_ONLY=1  skip grant files, HTTP and bootstrap
# Usage: ensure-desktop-grants.sh [-- command [args...]]
set +x
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AGISTACK_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(CDPATH= cd -- "$AGISTACK_ROOT/.." && pwd)
API_BASE=${AGISTACK_DESKTOP_GRANTS_API_BASE:-http://localhost:8000}
API_BASE=${API_BASE%/}
GRANT_DIR=${AGISTACK_DESKTOP_GRANTS_DIR:-$AGISTACK_ROOT/.local/desktop-grants}
case "$GRANT_DIR" in /*) ;; *) GRANT_DIR="$AGISTACK_ROOT/$GRANT_DIR" ;; esac
ENV_FILE="$GRANT_DIR/grants.env"
METADATA_FILE="$GRANT_DIR/grants.metadata.json"
REUSE_ONLY=${AGISTACK_DESKTOP_GRANTS_REUSE_ONLY:-0}
LOCAL_ONLY=${AGISTACK_DESKTOP_GRANTS_LOCAL_ONLY:-0}
LOAD_GRANTS=0

note() { printf '%s\n' "ensure-desktop-grants: $1" >&2; }
fail() { note "$1"; exit 1; }
if [ "$#" -gt 0 ]; then
    [ "$1" = "--" ] || fail 'expected -- before the launch command'
    shift
    [ "$#" -gt 0 ] || fail 'missing launch command'
fi
case "$REUSE_ONLY" in 0 | 1) ;; *) fail 'reuse-only must be 0 or 1' ;; esac
case "$LOCAL_ONLY" in 0 | 1) ;; *) fail 'local-only must be 0 or 1' ;; esac
if [ "$LOCAL_ONLY" = 1 ] && { [ "$REUSE_ONLY" = 1 ] || [ "${AGISTACK_DESKTOP_GRANTS_FORCE:-0}" = 1 ]; }; then
    fail 'local-only conflicts with reuse-only or forced provisioning'
fi
if [ "$REUSE_ONLY" = 1 ] && [ "${AGISTACK_DESKTOP_GRANTS_FORCE:-0}" = 1 ]; then
    fail 'reuse-only conflicts with forced provisioning'
fi

finish() {
    # Ignore inherited/stale credentials when this invocation has not validated
    # the configured file. Use the parsed snapshot, never source the file again.
    unset AGISTACK_PLUGIN_DATA_PLANE_CREDENTIAL_V2 AGISTACK_PLUGIN_DATA_PLANE_API_BASE_URL_V2
    unset AGISTACK_PLUGIN_DATA_PLANE_ACK_PARTICIPATION_V2
    unset AGISTACK_PLUGIN_RENDERER_DATA_PLANE_CREDENTIAL_V2 AGISTACK_PLUGIN_RENDERER_DATA_PLANE_API_BASE_URL_V2
    unset AGISTACK_PLUGIN_RENDERER_DATA_PLANE_ACK_PARTICIPATION_V2
    if [ "$LOAD_GRANTS" = 1 ]; then
        export AGISTACK_PLUGIN_DATA_PLANE_CREDENTIAL_V2="$SIDECAR_CREDENTIAL"
        export AGISTACK_PLUGIN_DATA_PLANE_API_BASE_URL_V2="$API_BASE"
        export AGISTACK_PLUGIN_DATA_PLANE_ACK_PARTICIPATION_V2="$SIDECAR_ACK"
        export AGISTACK_PLUGIN_RENDERER_DATA_PLANE_CREDENTIAL_V2="$RENDERER_CREDENTIAL"
        export AGISTACK_PLUGIN_RENDERER_DATA_PLANE_API_BASE_URL_V2="$API_BASE"
        export AGISTACK_PLUGIN_RENDERER_DATA_PLANE_ACK_PARTICIPATION_V2="$RENDERER_ACK"
    fi
    if [ "$#" -gt 0 ]; then exec "$@"; fi
    exit 0
}

# Explicit local-only startup makes no grant-file or backend access. finish
# clears all six inherited grant variables; product authorization stays intact.
if [ "$LOCAL_ONLY" = 1 ]; then
    note 'local-only startup; desktop grant import and provisioning disabled'
    finish "$@"
fi

valid_origin() {
    case "$1" in http://* | https://*) authority=${1#*://} ;; *) return 1 ;; esac
    case "$authority" in '' | *[!a-zA-Z0-9.:\[\]-]*) return 1 ;; esac
    case "$authority" in
        \[*\]*)
            host=${authority%%]*}; host=${host#\[}; port=${authority#*]}
            case "$host" in '' | *[!a-fA-F0-9:.]* ) return 1 ;; esac
            case "$host" in *:*) ;; *) return 1 ;; esac
            ;;
        *\[* | *\]*) return 1 ;;
        *) host=${authority%%:*}; port=${authority#"$host"}
            [ -n "$host" ] || return 1 ;;
    esac
    if [ -n "$port" ]; then
        case "$port" in :*) port=${port#:} ;; *) return 1 ;; esac
        case "$port" in '' | *[!0-9]*) return 1 ;; esac
        [ "$port" -ge 1 ] 2>/dev/null && [ "$port" -le 65535 ] 2>/dev/null || return 1
    fi
    case "$1" in
        http://*) case "$host" in localhost | 127.0.0.1 | ::1) ;; *) return 1 ;; esac ;;
    esac
}

valid_credential() {
    [ "${#1}" = 70 ] || return 1
    case "$1" in ms_dp_*) suffix=${1#ms_dp_} ;; *) return 1 ;; esac
    case "$suffix" in *[!a-f0-9]*) return 1 ;; esac
}

load_grants() {
    [ -f "$1" ] && [ -r "$1" ] || return 1
    SIDECAR_CREDENTIAL= SIDECAR_ORIGIN= SIDECAR_ACK=
    RENDERER_CREDENTIAL= RENDERER_ORIGIN= RENDERER_ACK=
    seen=' '
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in '' | \#*) continue ;; export\ *=*) assignment=${line#export } ;; *) return 1 ;; esac
        key=${assignment%%=*}; value=${assignment#*=}
        case "$seen" in *" $key "*) return 1 ;; esac
        seen="$seen$key "
        # Bootstrap uses shlex.quote; no expansion/evaluation is permitted.
        case "$value" in \"*\") value=${value#\"}; value=${value%\"} ;; \'*\') value=${value#\'}; value=${value%\'} ;; esac
        case "$key" in
            AGISTACK_PLUGIN_DATA_PLANE_CREDENTIAL_V2) SIDECAR_CREDENTIAL=$value ;;
            AGISTACK_PLUGIN_DATA_PLANE_API_BASE_URL_V2) SIDECAR_ORIGIN=${value%/} ;;
            AGISTACK_PLUGIN_DATA_PLANE_ACK_PARTICIPATION_V2) SIDECAR_ACK=$value ;;
            AGISTACK_PLUGIN_RENDERER_DATA_PLANE_CREDENTIAL_V2) RENDERER_CREDENTIAL=$value ;;
            AGISTACK_PLUGIN_RENDERER_DATA_PLANE_API_BASE_URL_V2) RENDERER_ORIGIN=${value%/} ;;
            AGISTACK_PLUGIN_RENDERER_DATA_PLANE_ACK_PARTICIPATION_V2) RENDERER_ACK=$value ;;
            *) return 1 ;;
        esac
    done < "$1"
    valid_credential "$SIDECAR_CREDENTIAL" && valid_credential "$RENDERER_CREDENTIAL" || return 1
    [ "$SIDECAR_CREDENTIAL" != "$RENDERER_CREDENTIAL" ] || return 1
    [ "$SIDECAR_ORIGIN" = "$API_BASE" ] && [ "$RENDERER_ORIGIN" = "$API_BASE" ] || return 1
    case "$SIDECAR_ACK:$RENDERER_ACK" in true:true | true:false | false:true | false:false) ;; *) return 1 ;; esac
}

probe_grants() {
    # GET authenticates each credential, but is not a role-introspection endpoint.
    for credential in "$SIDECAR_CREDENTIAL" "$RENDERER_CREDENTIAL"; do
        probe=$(printf 'header = "Authorization: Bearer %s"\n' "$credential" |
            curl -q --config - -s -o /dev/null -w '%{http_code}' --max-time 5 \
                --noproxy '*' --proto '=http,https' \
                "$API_BASE/api/v1/platform-plugins/v2/distribution" 2>/dev/null) || return 1
        case "$probe" in 200 | 404) ;; *) return 1 ;; esac
    done
}

if ! valid_origin "$API_BASE"; then
    [ "$REUSE_ONLY" != 1 ] || fail 'reuse-only requires a valid API origin'
    note 'invalid API origin; continuing without desktop grants'
    finish "$@"
fi
STORED_VALID=0
if load_grants "$ENV_FILE"; then STORED_VALID=1; fi
if [ "$REUSE_ONLY" = 1 ] && [ "$STORED_VALID" != 1 ]; then
    fail 'reuse-only requires a valid existing grant pair for the requested origin'
fi
if ! curl -q -fsS -o /dev/null --max-time 3 --noproxy '*' --proto '=http,https' "$API_BASE/docs" 2>/dev/null; then
    [ "$REUSE_ONLY" != 1 ] || fail 'reuse-only backend is unreachable'
    note 'local backend unreachable; skipping desktop grant provisioning'
    finish "$@"
fi
if [ "${AGISTACK_DESKTOP_GRANTS_FORCE:-0}" != 1 ] && [ "$STORED_VALID" = 1 ] && probe_grants; then
    LOAD_GRANTS=1
    note 'existing desktop grant pair is valid; reusing configured grants'
    finish "$@"
fi
[ "$REUSE_ONLY" != 1 ] || fail 'reuse-only grant pair was rejected; no provisioning attempted'

# Default development mode retains the existing repository bootstrap behavior.
umask 077
if ! mkdir -p "$GRANT_DIR"; then
    note 'grant directory unavailable; continuing without desktop grants'
    finish "$@"
fi
TMP_ENV="$GRANT_DIR/.grants.env.tmp.$$"
TMP_METADATA="$GRANT_DIR/.grants.metadata.json.tmp.$$"
trap 'rm -f "$TMP_ENV" "$TMP_METADATA"' 0
rm -f "$TMP_ENV" "$TMP_METADATA"
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
    PYTHON_BIN='uv run python'
fi
if (
    cd "$REPO_ROOT" && PYTHONPATH=. $PYTHON_BIN scripts/bootstrap-local-desktop-grants.py \
        --api-base "$API_BASE" --output "$TMP_ENV" --metadata-output "$TMP_METADATA" >/dev/null 2>&1
) && [ -f "$TMP_METADATA" ] && load_grants "$TMP_ENV" &&
    chmod 600 "$TMP_ENV" "$TMP_METADATA" &&
    mv -f "$TMP_ENV" "$ENV_FILE" && mv -f "$TMP_METADATA" "$METADATA_FILE"; then
    LOAD_GRANTS=1
    note 'provisioned fresh desktop grants into the configured directory'
else
    note 'provisioning failed; continuing without desktop grants (cloud mode stays gated)'
fi
rm -f "$TMP_ENV" "$TMP_METADATA"
trap - 0
finish "$@"
