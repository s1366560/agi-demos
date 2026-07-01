//! [`PgCheckpointStore`] — the production [`CheckpointStore`] for agent crash
//! recovery (ADR-0005), over the **Rust-owned, additive** `agistack_checkpoints`
//! table created by [`ensure_aux_schema`].
//!
//! [`SessionState`] is fully serde, so a checkpoint is stored as a single `jsonb`
//! document keyed by `session_id` (insert-or-replace). The core is unchanged: on
//! the server this port is Postgres, on device SQLite, in tests in-memory.
//!
//! [`ensure_aux_schema`]: crate::ensure_aux_schema

use async_trait::async_trait;

use agistack_core::agent::types::SessionState;
use agistack_core::ports::{CheckpointStore, CoreError, CoreResult};

use crate::PgPool;

/// `CheckpointStore` backed by the additive `agistack_checkpoints` table.
pub struct PgCheckpointStore {
    pool: PgPool,
}

impl PgCheckpointStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

fn checkpoint_err(e: sqlx::Error) -> CoreError {
    CoreError::Checkpoint(e.to_string())
}

#[async_trait]
impl CheckpointStore for PgCheckpointStore {
    async fn save(&self, state: &SessionState) -> CoreResult<()> {
        let json = serde_json::to_string(state)
            .map_err(|e| CoreError::Checkpoint(format!("encode state: {e}")))?;
        sqlx::query(
            "INSERT INTO agistack_checkpoints (session_id, state, updated_at) \
             VALUES ($1, $2::jsonb, now()) \
             ON CONFLICT (session_id) DO UPDATE SET state = EXCLUDED.state, updated_at = now()",
        )
        .bind(&state.session_id)
        .bind(&json)
        .execute(&self.pool)
        .await
        .map_err(checkpoint_err)?;
        Ok(())
    }

    async fn load(&self, session_id: &str) -> CoreResult<Option<SessionState>> {
        let row = sqlx::query_as::<_, (String,)>(
            "SELECT state::text FROM agistack_checkpoints WHERE session_id = $1",
        )
        .bind(session_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(checkpoint_err)?;

        match row {
            Some((json,)) => {
                let state = serde_json::from_str(&json)
                    .map_err(|e| CoreError::Checkpoint(format!("decode state: {e}")))?;
                Ok(Some(state))
            }
            None => Ok(None),
        }
    }

    async fn delete(&self, session_id: &str) -> CoreResult<()> {
        sqlx::query("DELETE FROM agistack_checkpoints WHERE session_id = $1")
            .bind(session_id)
            .execute(&self.pool)
            .await
            .map_err(checkpoint_err)?;
        Ok(())
    }
}
