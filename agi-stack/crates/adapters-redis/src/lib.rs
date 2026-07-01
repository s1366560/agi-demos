//! Redis Streams adapter for the [`EventStream`] port — the **production**
//! agent-event bus tier (F5).
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

use async_trait::async_trait;
use redis::aio::MultiplexedConnection;
use redis::streams::StreamRangeReply;

use agistack_core::ports::{CoreError, CoreResult, EventStream, StreamEntry};

/// The field name each stream entry stores its opaque payload under. The payload
/// is a self-contained serialized event (JSON) — the core stays decoupled from
/// any concrete event enum, and every adapter stores identical bytes.
const PAYLOAD_FIELD: &str = "data";

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
