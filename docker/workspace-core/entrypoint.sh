#!/bin/sh
set -eu

require_env() {
    name="$1"
    value="$(printenv "$name" 2>/dev/null || true)"
    if [ -z "$value" ]; then
        echo "Workspace Core startup requires $name" >&2
        exit 78
    fi
}

require_env "WORKSPACE_CORE_DATABASE_URL"
require_env "WORKSPACE_CORE_SERVICE_TOKEN"
require_env "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN"
require_env "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN"
require_env "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN"
require_env "AVERNET_SECRET_PRINCIPAL_SIGNING_KEY_VALUE"
require_env "BCS_SECRET_WORKSPACE_CORE_GROUP_SESSION_WS_JWT"

config_path="/etc/memstack-workspace-core/bcs-config.toml"
umask 077
envsubst '${WORKSPACE_CORE_DATABASE_URL}' \
    < /usr/local/share/memstack-workspace-core/bcs-config.toml.template \
    > "$config_path"

exec /usr/local/bin/memstack-workspace-core --config-dir "$config_path"
