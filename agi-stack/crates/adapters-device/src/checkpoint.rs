//! SQLite [`CheckpointStore`] — durable agent crash recovery on device
//! (ADR-0005). The whole [`SessionState`] is serialized to JSON in one row keyed
//! by `session_id`; `save` is insert-or-replace, so each round boundary durably
//! overwrites the prior checkpoint. Surviving a process kill is the point: a
//! restart loads this row and resumes without re-running completed tool calls.

use std::sync::Mutex;

use async_trait::async_trait;
use rusqlite::{params, Connection, OptionalExtension};

use agistack_core::agent::types::SessionState;
use agistack_core::ports::{CheckpointStore, CoreError, CoreResult};

pub struct SqliteCheckpointStore {
    conn: Mutex<Connection>,
}

impl SqliteCheckpointStore {
    pub fn open(path: &str) -> CoreResult<Self> {
        Self::init(Connection::open(path).map_err(to_ckpt)?)
    }

    pub fn in_memory() -> CoreResult<Self> {
        Self::init(Connection::open_in_memory().map_err(to_ckpt)?)
    }

    fn init(conn: Connection) -> CoreResult<Self> {
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS checkpoints (
                session_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                updated_round INTEGER NOT NULL
            );",
        )
        .map_err(to_ckpt)?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }
}

fn to_ckpt<E: std::fmt::Display>(e: E) -> CoreError {
    CoreError::Checkpoint(e.to_string())
}

#[async_trait]
impl CheckpointStore for SqliteCheckpointStore {
    async fn save(&self, state: &SessionState) -> CoreResult<()> {
        let json = serde_json::to_string(state).map_err(to_ckpt)?;
        let conn = self.conn.lock().map_err(to_ckpt)?;
        conn.execute(
            "INSERT OR REPLACE INTO checkpoints (session_id, state, updated_round)
             VALUES (?1, ?2, ?3)",
            params![state.session_id, json, state.round as i64],
        )
        .map_err(to_ckpt)?;
        Ok(())
    }

    async fn load(&self, session_id: &str) -> CoreResult<Option<SessionState>> {
        let conn = self.conn.lock().map_err(to_ckpt)?;
        let json: Option<String> = conn
            .query_row(
                "SELECT state FROM checkpoints WHERE session_id = ?1",
                params![session_id],
                |r| r.get(0),
            )
            .optional()
            .map_err(to_ckpt)?;
        match json {
            Some(j) => Ok(Some(serde_json::from_str(&j).map_err(to_ckpt)?)),
            None => Ok(None),
        }
    }

    async fn delete(&self, session_id: &str) -> CoreResult<()> {
        let conn = self.conn.lock().map_err(to_ckpt)?;
        conn.execute(
            "DELETE FROM checkpoints WHERE session_id = ?1",
            params![session_id],
        )
        .map_err(to_ckpt)?;
        Ok(())
    }
}
