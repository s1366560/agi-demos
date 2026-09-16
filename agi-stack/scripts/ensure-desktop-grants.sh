#!/bin/sh
# Ensure protocol-v2 desktop data-plane grants exist for the local backend.
#
# Cloud mode renderer delivery needs a dedicated renderer data-plane credential
# that the Electron main process imports once at startup from
# AGISTACK_PLUGIN_RENDERER_DATA_PLANE_CREDENTIAL_V2 (plus base URL / ack flag).
# This script mints that grant (and the sidecar grant) through the development
# only bootstrap scripts/bootstrap-local-desktop-grants.py and stores exports in
# a mode-0600 env file that `make run-desktop` sources before launch.
#
# Graceful no-op (exit 0) when the local backend is unreachable or provisioning
# fails: local mode keeps working, cloud mode simply stays gated. Never prints
# secret material.
#
# Overrides:
#   AGISTACK_DESKTOP_GRANTS_API_BASE  backend origin (default http://localhost:8000)
#   AGISTACK_DESKTOP_GRANTS_DIR       output directory (default agi-stack/.local/desktop-grants)
#   AGISTACK_DESKTOP_GRANTS_FORCE=1   reprovision even if the stored grant is valid
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AGISTACK_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(CDPATH= cd -- "$AGISTACK_ROOT/.." && pwd)

API_BASE=${AGISTACK_DESKTOP_GRANTS_API_BASE:-http://localhost:8000}
API_BASE=${API_BASE%/}
GRANT_DIR=${AGISTACK_DESKTOP_GRANTS_DIR:-$AGISTACK_ROOT/.local/desktop-grants}
ENV_FILE="$GRANT_DIR/grants.env"
METADATA_FILE="$GRANT_DIR/grants.metadata.json"

note() { printf '%s\n' "ensure-desktop-grants: $1" >&2; }

# 1. Local backend reachable? Otherwise stay a no-op.
if ! curl -fsS -o /dev/null --max-time 3 "$API_BASE/docs" 2>/dev/null; then
    note "local backend $API_BASE unreachable; skipping desktop grant provisioning"
    exit 0
fi

# 2. Reuse the stored grant while the backend still accepts it. The
#    distribution endpoint answers 200 with a publication and 404 when the
#    credential authenticated but nothing is published yet; both prove validity.
if [ "${AGISTACK_DESKTOP_GRANTS_FORCE:-0}" != "1" ] && [ -f "$ENV_FILE" ]; then
    probe=$(
        set -u
        . "$ENV_FILE"
        curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
            -H "Authorization: Bearer ${AGISTACK_PLUGIN_RENDERER_DATA_PLANE_CREDENTIAL_V2:-}" \
            "$API_BASE/api/v1/platform-plugins/v2/distribution" 2>/dev/null
    )
    case "$probe" in
        200 | 404)
            note "existing desktop grants still valid; reusing $ENV_FILE"
            exit 0
            ;;
        *)
            note "stored desktop grant rejected (HTTP ${probe:-000}); reprovisioning"
            ;;
    esac
fi

# 3. Mint fresh grants into temporary files, then atomically replace the old
#    ones so a failed run never destroys a previously working grant.
mkdir -p "$GRANT_DIR"
TMP_ENV="$GRANT_DIR/.grants.env.tmp.$$"
TMP_METADATA="$GRANT_DIR/.grants.metadata.json.tmp.$$"
rm -f "$TMP_ENV" "$TMP_METADATA"

if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
    PYTHON_BIN="uv run python"
fi

if (
    cd "$REPO_ROOT" && PYTHONPATH=. $PYTHON_BIN \
        scripts/bootstrap-local-desktop-grants.py \
        --api-base "$API_BASE" \
        --output "$TMP_ENV" \
        --metadata-output "$TMP_METADATA" >/dev/null
); then
    chmod 600 "$TMP_ENV" "$TMP_METADATA"
    mv -f "$TMP_ENV" "$ENV_FILE"
    mv -f "$TMP_METADATA" "$METADATA_FILE"
    note "provisioned fresh desktop grants into $ENV_FILE"
else
    rm -f "$TMP_ENV" "$TMP_METADATA"
    note "provisioning failed; continuing without desktop grants (cloud mode stays gated)"
fi
exit 0
