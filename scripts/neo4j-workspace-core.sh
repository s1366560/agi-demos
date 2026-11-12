#!/bin/sh
# Start the real Workspace Core binary for the Neo4j matched-state gate.
# The process serves the public workspace API. It does not fabricate responses.
set -eu

binary="${WORKSPACE_CORE_BIN:?WORKSPACE_CORE_BIN must point at memstack-workspace-core}"
port="${WORKSPACE_CORE_PORT:-4321}"
runtime_dir="${NEO4J_WORKSPACE_CORE_DIR:-${RUNNER_TEMP:-/tmp}/neo4j-workspace-core}"
database_url="${DATABASE_URL:?DATABASE_URL is required}"

install -d -m 0700 "$runtime_dir" "$runtime_dir/bots" "$runtime_dir/files"
umask 077
cat > "$runtime_dir/bcs-config.toml" << EOF
bind = "127.0.0.1"
port = ${port}
bots_base_dir = "${runtime_dir}/bots"
max_history_per_session = 1000
store_messages = false
strict_container_validation = false
max_groups_as_driver = 20
max_group_members = 20
max_groups_as_member = 100
max_group_messages = 1000
group_chat_delay_min_ms = 0
group_chat_delay_max_ms = 0
bcs_endpoint = "http://127.0.0.1:${port}"
botchat_url = "http://127.0.0.1:8000"
register_path = "/bcn/register"
default_visibility = "protected"
onboard_binding_enabled = false
dingtalk_accounts = []
api_keys = []
allowed_switch_provider_ids = []

[gateway_principal]
issuer = "gateway"
audience = "bcs"
key_id = "bare"
signing_key_env = "AVERNET_SECRET_PRINCIPAL_SIGNING_KEY_VALUE"

[group_session_ws]
signing_key_secret = "workspace-core-group-session-ws-jwt"

[secret]
provider = "env"

[secret.providers.env]
prefix = "BCS_SECRET_"

[auth]
chain = []
require_authentication = true
allow_mock_headers = false

[database]
type = "postgresql"

[database.postgres]
url = "${database_url}"
max_connections = 5
tls_required = false

[cache]
type = "redis"

[cache.redis]
timeout_secs = 5
key_prefix = "workspace-core:"

[cache.redis.connection]
type = "direct"
host = "127.0.0.1"
port = 6379
auth_mode = "disabled"

[leader_election]
enabled = false

[llm]
type = "none"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
model = "disabled"
timeout_ms = 120000
temperature = 0
max_tokens = 4096
structured_output = "json_schema"

[metrics]
enabled = false
mode = "pull"
endpoint_path = "/metrics"

[telemetry]
enabled = false

[logging]
default_level = "warn"
console = true

[user_directory]
enabled = false

[security_gateway]
provider = "noop"

[security.outbound_url]
block_private_networks = false
allow_loopback = true

[session_files]
storage_backend = "local"
multipart_threshold = 104857600
max_file_size = 5368709120
share_link_ttl = 3600

[session_files.backend]
data_dir = "${runtime_dir}/files"

[manifest]
schema_version = 1
EOF

exec "$binary" \
  --config-dir "$runtime_dir/bcs-config.toml" \
  --service-token "${WORKSPACE_CORE_SERVICE_TOKEN:?WORKSPACE_CORE_SERVICE_TOKEN is required}" \
  --agent-registry-url "${WORKSPACE_CORE_AGENT_REGISTRY_URL:-http://127.0.0.1:8000}" \
  --agent-registry-token "${WORKSPACE_CORE_AGENT_REGISTRY_TOKEN:?WORKSPACE_CORE_AGENT_REGISTRY_TOKEN is required}" \
  --provider-webhook-url "${WORKSPACE_CORE_PROVIDER_WEBHOOK_URL:-http://127.0.0.1:8000/internal/v1/workspace-core/provider}" \
  --provider-webhook-token "${WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN:?WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN is required}" \
  --provider-event-token "${WORKSPACE_CORE_PROVIDER_EVENT_TOKEN:?WORKSPACE_CORE_PROVIDER_EVENT_TOKEN is required}" \
  --plan-dispatch-url "${WORKSPACE_CORE_PLAN_DISPATCH_URL:-http://127.0.0.1:8000/internal/v1/workspace-core/plan-dispatch}" \
  --mode cloud
