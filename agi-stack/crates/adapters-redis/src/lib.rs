//! Redis Streams adapter for the [`EventStream`] port plus server-only ephemeral
//! grant storage — the **production** Redis tier for F5/P2.
//!
//! This is the server-only sibling of
//! [`agistack_adapters_mem::InMemoryEventStream`]. It stores events in the exact
//! same Redis Streams the Python backend already uses
//! (`agent:events:{conversation_id}`, `MAXLEN` ≈ 1000), so during the strangler
//! migration the Rust server can start *producing* agent events onto a stream
//! that the existing WebSocket bridge keeps consuming — no data migration, flip
//! one producer at a time.
//!
//! ## Semantics (kept byte-parity with the in-memory oracle)
//! - [`RedisEventStream::append`] → `XADD key MAXLEN <n> * data <payload>`.
//!   `MAXLEN` is **exact** (no `~`) so trimming is deterministic — append 5 with
//!   `max_len = 3` retains exactly the last 3, matching the in-memory `Vec`
//!   drain. `max_len == 0` omits `MAXLEN` (unbounded).
//! - [`RedisEventStream::read_after`] → `XRANGE key <start> + COUNT <limit>`.
//!   Empty / `"0"` `after_id` reads from `-` (stream start); otherwise from
//!   `(<after_id>` (exclusive), so callers page forward by echoing back the last
//!   id they saw. Ids are Redis-native (`<ms>-<seq>`) and opaque to callers; they
//!   are never compared across adapters (the parity test compares *payloads*).
//!
//! Everything here is `tokio`-bound and lives strictly outside the core.

use std::collections::BTreeMap;

use async_trait::async_trait;
use chrono::{DateTime, Duration, SecondsFormat, Utc};
use redis::aio::MultiplexedConnection;
use redis::streams::StreamRangeReply;
use serde::{Deserialize, Serialize};
use serde_json::json;

use agistack_core::ports::{CoreError, CoreResult, EventStream, StreamEntry};

/// The field name each stream entry stores its opaque payload under. The payload
/// is a self-contained serialized event (JSON) — the core stays decoupled from
/// any concrete event enum, and every adapter stores identical bytes.
const PAYLOAD_FIELD: &str = "data";
const DEVICE_CODE_KEY_PREFIX: &str = "memstack:device_code:";
const DEVICE_USER_CODE_KEY_PREFIX: &str = "memstack:device_user_code:";
const SANDBOX_HTTP_SERVICE_KEY_PREFIX: &str = "agistack:sandbox:http_services:";
const SANDBOX_PREVIEW_SESSION_KEY_PREFIX: &str = "agistack:sandbox:preview_session:";
const SANDBOX_TERMINAL_SESSION_KEY_PREFIX: &str = "agistack:sandbox:terminal_session:";
const SANDBOX_MCP_UPSTREAM_TOKEN_KEY_PREFIX: &str = "agistack:sandbox:mcp_token:";
const WORKER_LAUNCH_COOLDOWN_KEY_PREFIX: &str = "workspace:worker_launch:cooldown:";
const WORKSPACE_AUTONOMY_COOLDOWN_KEY_PREFIX: &str = "workspace:autonomy:last_trigger:";
const AGENT_RUNNING_KEY_PREFIX: &str = "agent:running:";
const AGENT_FINISHED_KEY_PREFIX: &str = "agent:finished:";
const DLQ_MESSAGE_PREFIX: &str = "dlq:messages:";
const DLQ_PENDING_INDEX: &str = "dlq:index:pending";
const DLQ_ERROR_TYPE_INDEX_PREFIX: &str = "dlq:index:by_error_type:";
const DLQ_EVENT_TYPE_INDEX_PREFIX: &str = "dlq:index:by_event_type:";
const DLQ_STATS_KEY: &str = "dlq:stats";
const UNIFIED_EVENT_STREAM_PREFIX: &str = "events:";
const UNIFIED_EVENT_STREAM_MAX_LEN: usize = 10_000;
const DLQ_RETRY_DELAYS_SECONDS: [i64; 4] = [60, 300, 900, 3600];

/// Open a multiplexed async connection to Redis (e.g. `redis://localhost:6379`).
///
/// The returned [`MultiplexedConnection`] is cheaply cloneable and safe to share
/// across tasks, mirroring how the Python side reuses a connection pool.
pub async fn connect(url: &str) -> CoreResult<RedisEventStream> {
    let client = redis::Client::open(url).map_err(gerr)?;
    let conn = client
        .get_multiplexed_async_connection()
        .await
        .map_err(gerr)?;
    Ok(RedisEventStream { conn })
}

/// Production [`EventStream`] backed by Redis Streams.
#[derive(Clone)]
pub struct RedisEventStream {
    conn: MultiplexedConnection,
}

impl RedisEventStream {
    /// Wrap an already-established multiplexed connection (e.g. one shared with
    /// other Redis-backed adapters).
    pub fn from_connection(conn: MultiplexedConnection) -> Self {
        Self { conn }
    }
}

/// Python-compatible Redis JSON payload for a CLI device-code grant.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeviceGrant {
    pub user_code: String,
    pub status: String,
    pub approved_user_id: Option<String>,
    pub access_token: Option<String>,
}

impl DeviceGrant {
    pub fn pending(user_code: impl Into<String>) -> Self {
        Self {
            user_code: user_code.into(),
            status: "pending".to_string(),
            approved_user_id: None,
            access_token: None,
        }
    }

    pub fn approved(
        user_code: impl Into<String>,
        approved_user_id: impl Into<String>,
        access_token: impl Into<String>,
    ) -> Self {
        Self {
            user_code: user_code.into(),
            status: "approved".to_string(),
            approved_user_id: Some(approved_user_id.into()),
            access_token: Some(access_token.into()),
        }
    }
}

/// Server-only Redis store for Python-compatible device-code grants.
#[derive(Clone)]
pub struct RedisDeviceGrantStore {
    conn: MultiplexedConnection,
}

impl RedisDeviceGrantStore {
    pub fn from_connection(conn: MultiplexedConnection) -> Self {
        Self { conn }
    }

    pub async fn connect(url: &str) -> CoreResult<Self> {
        let client = redis::Client::open(url).map_err(gerr)?;
        let conn = client
            .get_multiplexed_async_connection()
            .await
            .map_err(gerr)?;
        Ok(Self { conn })
    }

    pub async fn user_code_exists(&self, user_code: &str) -> CoreResult<bool> {
        let mut conn = self.conn.clone();
        let exists: i64 = redis::cmd("EXISTS")
            .arg(device_user_code_key(user_code))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(exists > 0)
    }

    pub async fn create_pending(
        &self,
        device_code: &str,
        grant: &DeviceGrant,
        ttl_seconds: u64,
    ) -> CoreResult<()> {
        let mut conn = self.conn.clone();
        let payload = serde_json::to_string(grant).map_err(gerr)?;
        let _: () = redis::cmd("SETEX")
            .arg(device_code_key(device_code))
            .arg(ttl_seconds)
            .arg(payload)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        let _: () = redis::cmd("SETEX")
            .arg(device_user_code_key(&grant.user_code))
            .arg(ttl_seconds)
            .arg(device_code)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(())
    }

    pub async fn device_code_for_user_code(&self, user_code: &str) -> CoreResult<Option<String>> {
        let mut conn = self.conn.clone();
        let value: Option<String> = redis::cmd("GET")
            .arg(device_user_code_key(user_code))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(value)
    }

    pub async fn get(&self, device_code: &str) -> CoreResult<Option<DeviceGrant>> {
        let mut conn = self.conn.clone();
        let value: Option<String> = redis::cmd("GET")
            .arg(device_code_key(device_code))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        value
            .map(|raw| serde_json::from_str(&raw).map_err(gerr))
            .transpose()
    }

    /// Atomically replace one exact grant while preserving its remaining TTL.
    ///
    /// The comparison happens on decoded fields instead of serialized bytes so
    /// Python and Rust writers can safely transition the same grant even though
    /// their JSON whitespace and object-key ordering differ. A missing,
    /// malformed, or concurrently changed grant is never recreated.
    pub async fn compare_and_set(
        &self,
        device_code: &str,
        expected: &DeviceGrant,
        replacement: &DeviceGrant,
    ) -> CoreResult<bool> {
        if expected.user_code != replacement.user_code {
            return Err(CoreError::Event(
                "device grant CAS cannot change user code".to_string(),
            ));
        }
        self.transition_exact(device_code, expected, Some(replacement), false)
            .await
    }

    /// Atomically replace one exact grant and remove its still-matching
    /// user-code index. Token redemption uses this to make the code single-use.
    pub async fn compare_and_set_and_delete_index(
        &self,
        device_code: &str,
        expected: &DeviceGrant,
        replacement: &DeviceGrant,
    ) -> CoreResult<bool> {
        if expected.user_code != replacement.user_code {
            return Err(CoreError::Event(
                "device grant CAS cannot change user code".to_string(),
            ));
        }
        self.transition_exact(device_code, expected, Some(replacement), true)
            .await
    }

    /// Atomically remove one exact grant and its still-matching user-code
    /// index. A stale reader cannot delete a concurrently approved grant.
    pub async fn compare_and_delete_pair(
        &self,
        device_code: &str,
        expected: &DeviceGrant,
    ) -> CoreResult<bool> {
        self.transition_exact(device_code, expected, None, false)
            .await
    }

    async fn transition_exact(
        &self,
        device_code: &str,
        expected: &DeviceGrant,
        replacement: Option<&DeviceGrant>,
        delete_index_after_set: bool,
    ) -> CoreResult<bool> {
        const TRANSITION_EXACT_GRANT: &str = r#"
local current_raw = redis.call("GET", KEYS[1])
if not current_raw then
    return 0
end

local current_ok, current = pcall(cjson.decode, current_raw)
local expected_ok, expected = pcall(cjson.decode, ARGV[1])
if not current_ok or not expected_ok then
    return redis.error_reply("invalid device grant JSON")
end

local function is_grant(value)
    if type(value) ~= "table"
        or type(value.user_code) ~= "string"
        or type(value.status) ~= "string"
        or value.approved_user_id == nil
        or value.access_token == nil then
        return false
    end
    if value.approved_user_id ~= cjson.null
        and type(value.approved_user_id) ~= "string" then
        return false
    end
    if value.access_token ~= cjson.null
        and type(value.access_token) ~= "string" then
        return false
    end
    for key, _ in pairs(value) do
        if key ~= "user_code"
            and key ~= "status"
            and key ~= "approved_user_id"
            and key ~= "access_token" then
            return false
        end
    end
    return true
end

local function optional_equal(left, right)
    local left_is_null = left == nil or left == cjson.null
    local right_is_null = right == nil or right == cjson.null
    if left_is_null or right_is_null then
        return left_is_null and right_is_null
    end
    return left == right
end

if not is_grant(current) or not is_grant(expected) then
    return redis.error_reply("invalid device grant shape")
end
if current.user_code ~= expected.user_code
    or current.status ~= expected.status
    or not optional_equal(current.approved_user_id, expected.approved_user_id)
    or not optional_equal(current.access_token, expected.access_token) then
    return 0
end

if ARGV[4] == "set" or ARGV[4] == "set_delete_index" then
    redis.call("SET", KEYS[1], ARGV[2], "KEEPTTL")
    if ARGV[4] == "set_delete_index"
        and redis.call("GET", KEYS[2]) == ARGV[3] then
        redis.call("DEL", KEYS[2])
    end
elseif ARGV[4] == "delete" then
    redis.call("DEL", KEYS[1])
    if redis.call("GET", KEYS[2]) == ARGV[3] then
        redis.call("DEL", KEYS[2])
    end
else
    return redis.error_reply("invalid device grant transition")
end
return 1
"#;

        let mut conn = self.conn.clone();
        let expected_payload = serde_json::to_string(expected).map_err(gerr)?;
        let (replacement_payload, operation) = match replacement {
            Some(grant) if delete_index_after_set => (
                serde_json::to_string(grant).map_err(gerr)?,
                "set_delete_index",
            ),
            Some(grant) => (serde_json::to_string(grant).map_err(gerr)?, "set"),
            None => (String::new(), "delete"),
        };
        let changed: i64 = redis::cmd("EVAL")
            .arg(TRANSITION_EXACT_GRANT)
            .arg(2)
            .arg(device_code_key(device_code))
            .arg(device_user_code_key(&expected.user_code))
            .arg(expected_payload)
            .arg(replacement_payload)
            .arg(device_code)
            .arg(operation)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(changed == 1)
    }

    pub async fn delete_pair(&self, device_code: &str, user_code: &str) -> CoreResult<()> {
        let mut conn = self.conn.clone();
        let _: i64 = redis::cmd("DEL")
            .arg(device_code_key(device_code))
            .arg(device_user_code_key(user_code))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(())
    }
}

/// Redis-persisted sandbox HTTP service registration. This intentionally stays
/// server-only: the portable core never sees Redis, only the server's sandbox
/// orchestration layer maps this JSON record to its HTTP wire types.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SandboxHttpServiceRecord {
    pub service_id: String,
    pub name: String,
    pub source_type: String,
    pub status: String,
    pub service_url: String,
    pub preview_url: String,
    pub ws_preview_url: Option<String>,
    pub sandbox_id: Option<String>,
    pub auto_open: bool,
    pub restart_token: Option<String>,
    pub updated_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SandboxPreviewSessionRecord {
    pub project_id: String,
    pub service_id: String,
    pub expires_at_ms: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SandboxTerminalSessionRecord {
    pub project_id: String,
    pub session_id: String,
    pub cols: u16,
    pub rows: u16,
    pub connected: bool,
    pub last_seen_at_ms: i64,
    pub expires_at_ms: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SandboxMcpUpstreamTokenRecord {
    pub token: String,
    pub project_id: String,
    pub sandbox_id: String,
    pub issued_at_ms: i64,
    pub expires_at_ms: i64,
}

/// Redis-backed registry for P5 sandbox HTTP service control/data-plane state.
#[derive(Clone)]
pub struct RedisSandboxHttpRegistry {
    conn: MultiplexedConnection,
}

impl RedisSandboxHttpRegistry {
    pub fn from_connection(conn: MultiplexedConnection) -> Self {
        Self { conn }
    }

    pub async fn connect(url: &str) -> CoreResult<Self> {
        let client = redis::Client::open(url).map_err(gerr)?;
        let conn = client
            .get_multiplexed_async_connection()
            .await
            .map_err(gerr)?;
        Ok(Self { conn })
    }

    pub async fn upsert_http_service(
        &self,
        project_id: &str,
        service: &SandboxHttpServiceRecord,
    ) -> CoreResult<()> {
        let mut conn = self.conn.clone();
        let payload = serde_json::to_string(service).map_err(gerr)?;
        let _: i64 = redis::cmd("HSET")
            .arg(sandbox_http_services_key(project_id))
            .arg(&service.service_id)
            .arg(payload)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(())
    }

    pub async fn list_http_services(
        &self,
        project_id: &str,
    ) -> CoreResult<Vec<SandboxHttpServiceRecord>> {
        let mut conn = self.conn.clone();
        let raw: BTreeMap<String, String> = redis::cmd("HGETALL")
            .arg(sandbox_http_services_key(project_id))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        raw.into_values()
            .map(|payload| serde_json::from_str(&payload).map_err(gerr))
            .collect()
    }

    pub async fn get_http_service(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> CoreResult<Option<SandboxHttpServiceRecord>> {
        let mut conn = self.conn.clone();
        let raw: Option<String> = redis::cmd("HGET")
            .arg(sandbox_http_services_key(project_id))
            .arg(service_id)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        raw.map(|payload| serde_json::from_str(&payload).map_err(gerr))
            .transpose()
    }

    pub async fn remove_http_service(
        &self,
        project_id: &str,
        service_id: &str,
    ) -> CoreResult<bool> {
        let mut conn = self.conn.clone();
        let removed: i64 = redis::cmd("HDEL")
            .arg(sandbox_http_services_key(project_id))
            .arg(service_id)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(removed > 0)
    }

    pub async fn create_preview_session(
        &self,
        token: &str,
        session: &SandboxPreviewSessionRecord,
        ttl_seconds: u64,
    ) -> CoreResult<()> {
        let mut conn = self.conn.clone();
        let payload = serde_json::to_string(session).map_err(gerr)?;
        let _: () = redis::cmd("SETEX")
            .arg(sandbox_preview_session_key(token))
            .arg(ttl_seconds.max(1))
            .arg(payload)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(())
    }

    pub async fn get_preview_session(
        &self,
        token: &str,
    ) -> CoreResult<Option<SandboxPreviewSessionRecord>> {
        let mut conn = self.conn.clone();
        let raw: Option<String> = redis::cmd("GET")
            .arg(sandbox_preview_session_key(token))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        raw.map(|payload| serde_json::from_str(&payload).map_err(gerr))
            .transpose()
    }

    pub async fn upsert_terminal_session(
        &self,
        session: &SandboxTerminalSessionRecord,
        ttl_seconds: u64,
    ) -> CoreResult<()> {
        let mut conn = self.conn.clone();
        let payload = serde_json::to_string(session).map_err(gerr)?;
        let _: () = redis::cmd("SETEX")
            .arg(sandbox_terminal_session_key(
                &session.project_id,
                &session.session_id,
            ))
            .arg(ttl_seconds.max(1))
            .arg(payload)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(())
    }

    pub async fn get_terminal_session(
        &self,
        project_id: &str,
        session_id: &str,
    ) -> CoreResult<Option<SandboxTerminalSessionRecord>> {
        let mut conn = self.conn.clone();
        let raw: Option<String> = redis::cmd("GET")
            .arg(sandbox_terminal_session_key(project_id, session_id))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        raw.map(|payload| serde_json::from_str(&payload).map_err(gerr))
            .transpose()
    }

    pub async fn remove_terminal_session(
        &self,
        project_id: &str,
        session_id: &str,
    ) -> CoreResult<bool> {
        let mut conn = self.conn.clone();
        let removed: i64 = redis::cmd("DEL")
            .arg(sandbox_terminal_session_key(project_id, session_id))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(removed > 0)
    }

    pub async fn create_mcp_upstream_token(
        &self,
        grant: &SandboxMcpUpstreamTokenRecord,
        ttl_seconds: u64,
    ) -> CoreResult<()> {
        let mut conn = self.conn.clone();
        let payload = serde_json::to_string(grant).map_err(gerr)?;
        let _: () = redis::cmd("SETEX")
            .arg(sandbox_mcp_upstream_token_key(&grant.token))
            .arg(ttl_seconds.max(1))
            .arg(payload)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(())
    }

    pub async fn get_mcp_upstream_token(
        &self,
        token: &str,
    ) -> CoreResult<Option<SandboxMcpUpstreamTokenRecord>> {
        let mut conn = self.conn.clone();
        let raw: Option<String> = redis::cmd("GET")
            .arg(sandbox_mcp_upstream_token_key(token))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        raw.map(|payload| serde_json::from_str(&payload).map_err(gerr))
            .transpose()
    }
}

/// Redis-backed worker-launch process state. It mirrors the Python keys used by
/// `worker_launch.py`: duplicate-launch cooldowns plus per-conversation
/// `agent:running` / `agent:finished` sentinels.
#[derive(Clone)]
pub struct RedisWorkerLaunchStateStore {
    conn: MultiplexedConnection,
}

impl RedisWorkerLaunchStateStore {
    pub fn from_connection(conn: MultiplexedConnection) -> Self {
        Self { conn }
    }

    pub async fn connect(url: &str) -> CoreResult<Self> {
        let client = redis::Client::open(url).map_err(gerr)?;
        let conn = client
            .get_multiplexed_async_connection()
            .await
            .map_err(gerr)?;
        Ok(Self { conn })
    }

    pub async fn claim_worker_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool> {
        let mut conn = self.conn.clone();
        let claimed: Option<String> = redis::cmd("SET")
            .arg(worker_launch_cooldown_key(conversation_id))
            .arg("1")
            .arg("NX")
            .arg("EX")
            .arg(ttl_seconds.max(1))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(claimed.is_some())
    }

    pub async fn refresh_worker_launch_cooldown(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool> {
        let mut conn = self.conn.clone();
        let refreshed: bool = redis::cmd("EXPIRE")
            .arg(worker_launch_cooldown_key(conversation_id))
            .arg(ttl_seconds.max(1))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(refreshed)
    }

    pub async fn agent_finished_message_id(
        &self,
        conversation_id: &str,
    ) -> CoreResult<Option<String>> {
        let mut conn = self.conn.clone();
        let message_id: Option<String> = redis::cmd("GET")
            .arg(agent_finished_key(conversation_id))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(message_id)
    }

    pub async fn agent_running_exists(&self, conversation_id: &str) -> CoreResult<bool> {
        let mut conn = self.conn.clone();
        let exists: i64 = redis::cmd("EXISTS")
            .arg(agent_running_key(conversation_id))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(exists > 0)
    }

    pub async fn refresh_existing_agent_running_marker(
        &self,
        conversation_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<bool> {
        let mut conn = self.conn.clone();
        let finished_exists: i64 = redis::cmd("EXISTS")
            .arg(agent_finished_key(conversation_id))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        if finished_exists > 0 {
            return Ok(false);
        }

        let refreshed: bool = redis::cmd("EXPIRE")
            .arg(agent_running_key(conversation_id))
            .arg(ttl_seconds.max(1))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(refreshed)
    }

    pub async fn clear_reused_worker_session_markers(
        &self,
        conversation_id: &str,
    ) -> CoreResult<()> {
        let mut conn = self.conn.clone();
        let _: i64 = redis::cmd("DEL")
            .arg(agent_finished_key(conversation_id))
            .arg(worker_launch_cooldown_key(conversation_id))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(())
    }
}

/// Redis-backed P6 workspace autonomy tick cooldown state. This mirrors the
/// Python key `workspace:autonomy:last_trigger:{workspace_id}:{root_task_id}`.
#[derive(Clone)]
pub struct RedisWorkspaceAutonomyCooldownStore {
    conn: MultiplexedConnection,
}

impl RedisWorkspaceAutonomyCooldownStore {
    pub fn from_connection(conn: MultiplexedConnection) -> Self {
        Self { conn }
    }

    pub async fn connect(url: &str) -> CoreResult<Self> {
        let client = redis::Client::open(url).map_err(gerr)?;
        let conn = client
            .get_multiplexed_async_connection()
            .await
            .map_err(gerr)?;
        Ok(Self { conn })
    }

    pub async fn is_on_cooldown(&self, workspace_id: &str, root_task_id: &str) -> CoreResult<bool> {
        let mut conn = self.conn.clone();
        let exists: i64 = redis::cmd("EXISTS")
            .arg(workspace_autonomy_cooldown_key(workspace_id, root_task_id))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(exists > 0)
    }

    pub async fn mark_cooldown(
        &self,
        workspace_id: &str,
        root_task_id: &str,
        ttl_seconds: u64,
    ) -> CoreResult<()> {
        let mut conn = self.conn.clone();
        let _: () = redis::cmd("SET")
            .arg(workspace_autonomy_cooldown_key(workspace_id, root_task_id))
            .arg("1")
            .arg("EX")
            .arg(ttl_seconds.max(1))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(())
    }
}

/// Python-compatible read model for `RedisDLQAdapter` messages.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DlqMessageRecord {
    pub id: String,
    pub event_id: String,
    pub event_type: String,
    pub event_data: String,
    pub routing_key: String,
    pub error: String,
    pub error_type: String,
    pub error_traceback: Option<String>,
    pub retry_count: i64,
    pub max_retries: i64,
    pub first_failed_at: String,
    pub last_failed_at: String,
    pub next_retry_at: Option<String>,
    pub status: String,
    pub metadata: serde_json::Value,
}

#[derive(Debug, Clone, Copy)]
pub struct DlqListQuery<'a> {
    pub status: Option<&'a str>,
    pub event_type: Option<&'a str>,
    pub error_type: Option<&'a str>,
    pub routing_key_pattern: Option<&'a str>,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DlqStatsRecord {
    pub total_messages: i64,
    pub pending_count: i64,
    pub retrying_count: i64,
    pub discarded_count: i64,
    pub expired_count: i64,
    pub resolved_count: i64,
    pub oldest_message_age_seconds: f64,
    pub error_type_counts: BTreeMap<String, i64>,
    pub event_type_counts: BTreeMap<String, i64>,
}

/// Server-only read-side adapter for Python's Redis-backed Dead Letter Queue.
#[derive(Clone)]
pub struct RedisDlqRepository {
    conn: MultiplexedConnection,
}

impl RedisDlqRepository {
    pub fn from_connection(conn: MultiplexedConnection) -> Self {
        Self { conn }
    }

    pub async fn connect(url: &str) -> CoreResult<Self> {
        let client = redis::Client::open(url).map_err(gerr)?;
        let conn = client
            .get_multiplexed_async_connection()
            .await
            .map_err(gerr)?;
        Ok(Self { conn })
    }

    pub async fn get_message(&self, message_id: &str) -> CoreResult<Option<DlqMessageRecord>> {
        let mut conn = self.conn.clone();
        let raw: Option<String> = redis::cmd("HGET")
            .arg(dlq_message_key(message_id))
            .arg("data")
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        raw.map(|raw| read_dlq_message(&raw)).transpose()
    }

    pub async fn list_messages(
        &self,
        query: DlqListQuery<'_>,
    ) -> CoreResult<Vec<DlqMessageRecord>> {
        let index_key = dlq_index_key(query.error_type, query.event_type);
        let offset = query.offset.max(0);
        let limit = query.limit.clamp(1, 100);
        let mut conn = self.conn.clone();
        let ids: Vec<String> = redis::cmd("ZREVRANGE")
            .arg(index_key)
            .arg(offset)
            .arg(offset + limit - 1)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;

        let mut messages = Vec::new();
        for id in ids {
            if let Some(message) = self.get_message(&id).await? {
                if message_matches(&message, query.status, query.routing_key_pattern) {
                    messages.push(message);
                }
            }
        }
        Ok(messages)
    }

    pub async fn count_messages(&self, query: DlqListQuery<'_>) -> CoreResult<i64> {
        let index_key = dlq_index_key(query.error_type, query.event_type);
        let mut conn = self.conn.clone();
        let ids: Vec<String> = redis::cmd("ZREVRANGE")
            .arg(index_key)
            .arg(0)
            .arg(-1)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;

        let mut count = 0_i64;
        for id in ids {
            if let Some(message) = self.get_message(&id).await? {
                if message_matches(&message, query.status, query.routing_key_pattern) {
                    count += 1;
                }
            }
        }
        Ok(count)
    }

    pub async fn stats(&self) -> CoreResult<DlqStatsRecord> {
        let mut conn = self.conn.clone();
        let raw: BTreeMap<String, String> = redis::cmd("HGETALL")
            .arg(DLQ_STATS_KEY)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;

        let mut scalar_counts = BTreeMap::new();
        let mut error_type_counts = BTreeMap::new();
        let mut event_type_counts = BTreeMap::new();
        for (key, value) in raw {
            let count = value.parse::<i64>().unwrap_or(0);
            if let Some(error_type) = key.strip_prefix("error:") {
                error_type_counts.insert(error_type.to_string(), count);
            } else if let Some(event_type) = key.strip_prefix("event:") {
                event_type_counts.insert(event_type.to_string(), count);
            } else {
                scalar_counts.insert(key, count);
            }
        }

        let oldest: Vec<(String, f64)> = redis::cmd("ZRANGE")
            .arg(DLQ_PENDING_INDEX)
            .arg(0)
            .arg(0)
            .arg("WITHSCORES")
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        let now_seconds = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_secs_f64())
            .unwrap_or(0.0);
        let oldest_message_age_seconds = oldest
            .first()
            .map(|(_, score)| (now_seconds - *score).max(0.0))
            .unwrap_or(0.0);

        Ok(DlqStatsRecord {
            total_messages: *scalar_counts.get("total_messages").unwrap_or(&0),
            pending_count: *scalar_counts.get("pending_count").unwrap_or(&0),
            retrying_count: *scalar_counts.get("retrying_count").unwrap_or(&0),
            discarded_count: *scalar_counts.get("discarded_count").unwrap_or(&0),
            expired_count: *scalar_counts.get("expired_count").unwrap_or(&0),
            resolved_count: *scalar_counts.get("resolved_count").unwrap_or(&0),
            oldest_message_age_seconds,
            error_type_counts,
            event_type_counts,
        })
    }

    pub async fn discard_message(
        &self,
        message_id: &str,
        reason: &str,
        discarded_at: &str,
    ) -> CoreResult<Option<bool>> {
        let Some(mut message) = self.get_message(message_id).await? else {
            return Ok(None);
        };
        message.status = "discarded".to_string();
        if !message.metadata.is_object() {
            message.metadata = serde_json::json!({});
        }
        if let Some(metadata) = message.metadata.as_object_mut() {
            metadata.insert(
                "discard_reason".to_string(),
                serde_json::Value::String(reason.to_string()),
            );
            metadata.insert(
                "discarded_at".to_string(),
                serde_json::Value::String(discarded_at.to_string()),
            );
        }
        self.write_message(&message).await?;
        self.increment_stat("pending_count", -1).await?;
        self.increment_stat("discarded_count", 1).await?;
        self.remove_from_indexes(&message).await?;
        Ok(Some(true))
    }

    pub async fn discard_batch(
        &self,
        message_ids: &[String],
        reason: &str,
        discarded_at: &str,
    ) -> CoreResult<BTreeMap<String, bool>> {
        let mut results = BTreeMap::new();
        for message_id in message_ids {
            let success = self
                .discard_message(message_id, reason, discarded_at)
                .await?
                .unwrap_or(false);
            results.insert(message_id.clone(), success);
        }
        Ok(results)
    }

    pub async fn retry_message(&self, message_id: &str) -> CoreResult<Option<bool>> {
        let Some(mut message) = self.get_message(message_id).await? else {
            return Ok(None);
        };
        if message.status != "pending" || message.retry_count >= message.max_retries {
            return Err(CoreError::Event(format!(
                "Cannot retry: status={}, retries={}/{}",
                message.status, message.retry_count, message.max_retries
            )));
        }

        let retried_at = Utc::now();
        message.status = "retrying".to_string();
        message.retry_count += 1;
        message.last_failed_at = iso8601_utc(retried_at);
        self.write_message(&message).await?;

        match self.publish_dlq_retry_event(&message, retried_at).await {
            Ok(()) => {
                message.status = "resolved".to_string();
                self.write_message(&message).await?;
                self.increment_stat("pending_count", -1).await?;
                self.increment_stat("resolved_count", 1).await?;
                self.remove_from_indexes(&message).await?;
                Ok(Some(true))
            }
            Err(err) => {
                message.status = "pending".to_string();
                message.error = err.to_string();
                message.error_traceback = Some(format!("Rust DLQ retry publish failed: {err}"));
                message.next_retry_at =
                    next_retry_at(retried_at, message.retry_count, message.max_retries);
                self.write_message(&message).await?;
                Ok(Some(false))
            }
        }
    }

    pub async fn retry_batch(&self, message_ids: &[String]) -> CoreResult<BTreeMap<String, bool>> {
        let mut results = BTreeMap::new();
        for message_id in message_ids {
            let success = match self.retry_message(message_id).await {
                Ok(Some(success)) => success,
                Ok(None) => false,
                Err(CoreError::Event(err)) if err.starts_with("Cannot retry:") => false,
                Err(err) => return Err(err),
            };
            results.insert(message_id.clone(), success);
        }
        Ok(results)
    }

    pub async fn cleanup_expired(&self, older_than_hours: i64) -> CoreResult<i64> {
        let cutoff = unix_now_seconds() - (older_than_hours.max(1) * 3600) as f64;
        let ids = self.pending_ids_older_than(cutoff).await?;
        let mut cleaned = 0_i64;
        for id in ids {
            if let Some(mut message) = self.get_message(&id).await? {
                message.status = "expired".to_string();
                self.write_message(&message).await?;
                self.remove_from_indexes(&message).await?;
                cleaned += 1;
            }
        }
        if cleaned > 0 {
            self.increment_stat("pending_count", -cleaned).await?;
            self.increment_stat("expired_count", cleaned).await?;
        }
        Ok(cleaned)
    }

    pub async fn cleanup_resolved(&self, older_than_hours: i64) -> CoreResult<i64> {
        let cutoff = unix_now_seconds() - (older_than_hours.max(1) * 3600) as f64;
        let ids = self.pending_ids_older_than(cutoff).await?;
        let mut cleaned = 0_i64;
        for id in ids {
            if let Some(message) = self.get_message(&id).await? {
                if message.status == "resolved" {
                    self.delete_message_data(&message.id).await?;
                    self.remove_from_indexes(&message).await?;
                    cleaned += 1;
                }
            }
        }
        if cleaned > 0 {
            self.increment_stat("resolved_count", -cleaned).await?;
        }
        Ok(cleaned)
    }

    async fn publish_dlq_retry_event(
        &self,
        message: &DlqMessageRecord,
        retried_at: DateTime<Utc>,
    ) -> CoreResult<()> {
        let envelope = normalized_dlq_envelope(message, retried_at)?;
        let event_json = serde_json::to_string(&envelope).map_err(gerr)?;
        let stream_key = format!("{UNIFIED_EVENT_STREAM_PREFIX}{}", message.routing_key);
        let event_id = string_field(&envelope, "event_id");
        let event_type = string_field(&envelope, "event_type");
        let schema_version = string_field_with_default(&envelope, "schema_version", "1.0");
        let timestamp = string_field_with_default(&envelope, "timestamp", &iso8601_utc(retried_at));
        let correlation_id = non_empty_string_field(&envelope, "correlation_id");
        let causation_id = non_empty_string_field(&envelope, "causation_id");

        let mut conn = self.conn.clone();
        let mut cmd = redis::cmd("XADD");
        cmd.arg(&stream_key)
            .arg("MAXLEN")
            .arg("~")
            .arg(UNIFIED_EVENT_STREAM_MAX_LEN)
            .arg("*")
            .arg("event_id")
            .arg(event_id)
            .arg("event_type")
            .arg(event_type)
            .arg("schema_version")
            .arg(schema_version)
            .arg(PAYLOAD_FIELD)
            .arg(event_json)
            .arg("timestamp")
            .arg(timestamp)
            .arg("routing_key")
            .arg(&message.routing_key);
        if let Some(correlation_id) = correlation_id {
            cmd.arg("correlation_id").arg(correlation_id);
        }
        if let Some(causation_id) = causation_id {
            cmd.arg("causation_id").arg(causation_id);
        }
        let _: String = cmd.query_async(&mut conn).await.map_err(gerr)?;
        Ok(())
    }

    async fn write_message(&self, message: &DlqMessageRecord) -> CoreResult<()> {
        let payload = serde_json::to_string(message).map_err(gerr)?;
        let mut conn = self.conn.clone();
        let _: i64 = redis::cmd("HSET")
            .arg(dlq_message_key(&message.id))
            .arg("data")
            .arg(payload)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(())
    }

    async fn delete_message_data(&self, message_id: &str) -> CoreResult<()> {
        let mut conn = self.conn.clone();
        let _: i64 = redis::cmd("DEL")
            .arg(dlq_message_key(message_id))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(())
    }

    async fn remove_from_indexes(&self, message: &DlqMessageRecord) -> CoreResult<()> {
        let mut conn = self.conn.clone();
        let _: i64 = redis::cmd("ZREM")
            .arg(DLQ_PENDING_INDEX)
            .arg(&message.id)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        let _: i64 = redis::cmd("ZREM")
            .arg(dlq_error_type_index_key(&message.error_type))
            .arg(&message.id)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        let _: i64 = redis::cmd("ZREM")
            .arg(dlq_event_type_index_key(&message.event_type))
            .arg(&message.id)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(())
    }

    async fn increment_stat(&self, field: &str, delta: i64) -> CoreResult<()> {
        let mut conn = self.conn.clone();
        let _: i64 = redis::cmd("HINCRBY")
            .arg(DLQ_STATS_KEY)
            .arg(field)
            .arg(delta)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(())
    }

    async fn pending_ids_older_than(&self, cutoff: f64) -> CoreResult<Vec<String>> {
        let mut conn = self.conn.clone();
        redis::cmd("ZRANGEBYSCORE")
            .arg(DLQ_PENDING_INDEX)
            .arg("-inf")
            .arg(cutoff)
            .query_async(&mut conn)
            .await
            .map_err(gerr)
    }
}

pub fn dlq_message_key(message_id: &str) -> String {
    format!("{DLQ_MESSAGE_PREFIX}{message_id}")
}

pub fn dlq_pending_index_key() -> &'static str {
    DLQ_PENDING_INDEX
}

pub fn dlq_error_type_index_key(error_type: &str) -> String {
    format!("{DLQ_ERROR_TYPE_INDEX_PREFIX}{error_type}")
}

pub fn dlq_event_type_index_key(event_type: &str) -> String {
    format!("{DLQ_EVENT_TYPE_INDEX_PREFIX}{event_type}")
}

pub fn dlq_stats_key() -> &'static str {
    DLQ_STATS_KEY
}

fn dlq_index_key(error_type: Option<&str>, event_type: Option<&str>) -> String {
    if let Some(error_type) = blank_to_none(error_type) {
        dlq_error_type_index_key(error_type)
    } else if let Some(event_type) = blank_to_none(event_type) {
        dlq_event_type_index_key(event_type)
    } else {
        DLQ_PENDING_INDEX.to_string()
    }
}

fn read_dlq_message(raw: &str) -> CoreResult<DlqMessageRecord> {
    let value = serde_json::from_str::<serde_json::Value>(raw).map_err(gerr)?;
    let metadata = value
        .get("metadata")
        .cloned()
        .filter(serde_json::Value::is_object)
        .unwrap_or_else(|| serde_json::json!({}));
    Ok(DlqMessageRecord {
        id: string_field(&value, "id"),
        event_id: string_field(&value, "event_id"),
        event_type: string_field(&value, "event_type"),
        event_data: string_field(&value, "event_data"),
        routing_key: string_field(&value, "routing_key"),
        error: string_field(&value, "error"),
        error_type: string_field(&value, "error_type"),
        error_traceback: optional_string_field(&value, "error_traceback"),
        retry_count: integer_field(&value, "retry_count", 0),
        max_retries: integer_field(&value, "max_retries", 3),
        first_failed_at: string_field(&value, "first_failed_at"),
        last_failed_at: string_field(&value, "last_failed_at"),
        next_retry_at: optional_string_field(&value, "next_retry_at"),
        status: string_field_with_default(&value, "status", "pending"),
        metadata,
    })
}

fn normalized_dlq_envelope(
    message: &DlqMessageRecord,
    fallback_timestamp: DateTime<Utc>,
) -> CoreResult<serde_json::Value> {
    let value = serde_json::from_str::<serde_json::Value>(&message.event_data).map_err(gerr)?;
    let fallback_timestamp = iso8601_utc(fallback_timestamp);
    Ok(json!({
        "schema_version": string_field_with_default(&value, "schema_version", "1.0"),
        "event_id": string_field_with_default(&value, "event_id", &message.event_id),
        "event_type": string_field_with_default(&value, "event_type", &message.event_type),
        "timestamp": string_field_with_default(&value, "timestamp", &fallback_timestamp),
        "source": string_field_with_default(&value, "source", "memstack"),
        "correlation_id": value.get("correlation_id").cloned().unwrap_or(serde_json::Value::Null),
        "causation_id": value.get("causation_id").cloned().unwrap_or(serde_json::Value::Null),
        "payload": value
            .get("payload")
            .cloned()
            .filter(serde_json::Value::is_object)
            .unwrap_or_else(|| json!({})),
        "metadata": value
            .get("metadata")
            .cloned()
            .filter(serde_json::Value::is_object)
            .unwrap_or_else(|| json!({})),
    }))
}

fn message_matches(
    message: &DlqMessageRecord,
    status: Option<&str>,
    routing_key_pattern: Option<&str>,
) -> bool {
    if let Some(status) = blank_to_none(status) {
        if message.status != status {
            return false;
        }
    }
    if let Some(pattern) = blank_to_none(routing_key_pattern) {
        return wildcard_matches(pattern, &message.routing_key);
    }
    true
}

fn wildcard_matches(pattern: &str, value: &str) -> bool {
    let pattern = pattern.as_bytes();
    let value = value.as_bytes();
    let (mut pi, mut vi) = (0_usize, 0_usize);
    let mut star: Option<usize> = None;
    let mut star_match = 0_usize;

    while vi < value.len() {
        if pi < pattern.len() && (pattern[pi] == b'?' || pattern[pi] == value[vi]) {
            pi += 1;
            vi += 1;
        } else if pi < pattern.len() && pattern[pi] == b'*' {
            star = Some(pi);
            star_match = vi;
            pi += 1;
        } else if let Some(star_index) = star {
            pi = star_index + 1;
            star_match += 1;
            vi = star_match;
        } else {
            return false;
        }
    }

    while pi < pattern.len() && pattern[pi] == b'*' {
        pi += 1;
    }
    pi == pattern.len()
}

fn blank_to_none(value: Option<&str>) -> Option<&str> {
    value.and_then(|raw| {
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed)
        }
    })
}

fn string_field(value: &serde_json::Value, field: &str) -> String {
    string_field_with_default(value, field, "")
}

fn string_field_with_default(value: &serde_json::Value, field: &str, default: &str) -> String {
    value
        .get(field)
        .and_then(serde_json::Value::as_str)
        .unwrap_or(default)
        .to_string()
}

fn optional_string_field(value: &serde_json::Value, field: &str) -> Option<String> {
    value
        .get(field)
        .and_then(serde_json::Value::as_str)
        .map(ToOwned::to_owned)
}

fn non_empty_string_field(value: &serde_json::Value, field: &str) -> Option<String> {
    optional_string_field(value, field).filter(|value| !value.is_empty())
}

fn integer_field(value: &serde_json::Value, field: &str, default: i64) -> i64 {
    value
        .get(field)
        .and_then(serde_json::Value::as_i64)
        .unwrap_or(default)
}

fn iso8601_utc(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::AutoSi, true)
}

fn next_retry_at(retried_at: DateTime<Utc>, retry_count: i64, max_retries: i64) -> Option<String> {
    if retry_count >= max_retries {
        return None;
    }
    let index = retry_count.clamp(0, DLQ_RETRY_DELAYS_SECONDS.len() as i64 - 1) as usize;
    Some(iso8601_utc(
        retried_at + Duration::seconds(DLQ_RETRY_DELAYS_SECONDS[index]),
    ))
}

fn unix_now_seconds() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_secs_f64())
        .unwrap_or(0.0)
}

pub fn device_code_key(device_code: &str) -> String {
    format!("{DEVICE_CODE_KEY_PREFIX}{device_code}")
}

pub fn device_user_code_key(user_code: &str) -> String {
    format!("{DEVICE_USER_CODE_KEY_PREFIX}{user_code}")
}

pub fn sandbox_http_services_key(project_id: &str) -> String {
    format!("{SANDBOX_HTTP_SERVICE_KEY_PREFIX}{project_id}")
}

pub fn sandbox_preview_session_key(token: &str) -> String {
    format!("{SANDBOX_PREVIEW_SESSION_KEY_PREFIX}{token}")
}

pub fn sandbox_terminal_session_key(project_id: &str, session_id: &str) -> String {
    format!("{SANDBOX_TERMINAL_SESSION_KEY_PREFIX}{project_id}:{session_id}")
}

pub fn sandbox_mcp_upstream_token_key(token: &str) -> String {
    format!("{SANDBOX_MCP_UPSTREAM_TOKEN_KEY_PREFIX}{token}")
}

pub fn worker_launch_cooldown_key(conversation_id: &str) -> String {
    format!("{WORKER_LAUNCH_COOLDOWN_KEY_PREFIX}{conversation_id}")
}

pub fn workspace_autonomy_cooldown_key(workspace_id: &str, root_task_id: &str) -> String {
    format!("{WORKSPACE_AUTONOMY_COOLDOWN_KEY_PREFIX}{workspace_id}:{root_task_id}")
}

pub fn agent_running_key(conversation_id: &str) -> String {
    format!("{AGENT_RUNNING_KEY_PREFIX}{conversation_id}")
}

pub fn agent_finished_key(conversation_id: &str) -> String {
    format!("{AGENT_FINISHED_KEY_PREFIX}{conversation_id}")
}

/// Map any Redis error to the port-level [`CoreError::Event`], keeping the
/// concrete `redis` type out of the core contract.
fn gerr<E: std::fmt::Display>(e: E) -> CoreError {
    CoreError::Event(e.to_string())
}

#[async_trait]
impl EventStream for RedisEventStream {
    async fn append(&self, topic: &str, payload: &str, max_len: usize) -> CoreResult<String> {
        let mut conn = self.conn.clone();
        let mut cmd = redis::cmd("XADD");
        cmd.arg(topic);
        if max_len > 0 {
            // Exact trim (no `~`) → deterministic "keep last N", parity with the
            // in-memory oracle's front-drain.
            cmd.arg("MAXLEN").arg(max_len);
        }
        cmd.arg("*").arg(PAYLOAD_FIELD).arg(payload);
        let id: String = cmd.query_async(&mut conn).await.map_err(gerr)?;
        Ok(id)
    }

    async fn read_after(
        &self,
        topic: &str,
        after_id: &str,
        limit: usize,
    ) -> CoreResult<Vec<StreamEntry>> {
        let mut conn = self.conn.clone();
        // Empty / "0" → from the very start (`-`); otherwise exclusive after the
        // given id (`(<id>`), so paging never re-yields the last-seen entry.
        let start = if after_id.is_empty() || after_id == "0" {
            "-".to_string()
        } else {
            format!("({after_id}")
        };
        let reply: StreamRangeReply = redis::cmd("XRANGE")
            .arg(topic)
            .arg(&start)
            .arg("+")
            .arg("COUNT")
            .arg(limit)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;

        let mut out = Vec::with_capacity(reply.ids.len());
        for entry in reply.ids {
            let payload = entry.get::<String>(PAYLOAD_FIELD).ok_or_else(|| {
                CoreError::Event(format!(
                    "stream entry {} missing '{PAYLOAD_FIELD}' field",
                    entry.id
                ))
            })?;
            out.push(StreamEntry {
                id: entry.id,
                payload,
            });
        }
        Ok(out)
    }
}
