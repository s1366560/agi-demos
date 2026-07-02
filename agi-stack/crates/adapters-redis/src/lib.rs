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
use redis::aio::MultiplexedConnection;
use redis::streams::StreamRangeReply;
use serde::{Deserialize, Serialize};

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
const AGENT_RUNNING_KEY_PREFIX: &str = "agent:running:";
const AGENT_FINISHED_KEY_PREFIX: &str = "agent:finished:";

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

    pub async fn save_preserving_ttl(
        &self,
        device_code: &str,
        grant: &DeviceGrant,
        fallback_ttl_seconds: u64,
    ) -> CoreResult<()> {
        let mut conn = self.conn.clone();
        let ttl: i64 = redis::cmd("TTL")
            .arg(device_code_key(device_code))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        let ttl_seconds = if ttl > 0 {
            ttl as u64
        } else {
            fallback_ttl_seconds
        };
        let payload = serde_json::to_string(grant).map_err(gerr)?;
        let _: () = redis::cmd("SETEX")
            .arg(device_code_key(device_code))
            .arg(ttl_seconds)
            .arg(payload)
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(())
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

    pub async fn agent_running_exists(&self, conversation_id: &str) -> CoreResult<bool> {
        let mut conn = self.conn.clone();
        let exists: i64 = redis::cmd("EXISTS")
            .arg(agent_running_key(conversation_id))
            .query_async(&mut conn)
            .await
            .map_err(gerr)?;
        Ok(exists > 0)
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
