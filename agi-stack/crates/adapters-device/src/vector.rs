//! SQLite [`VectorIndexPort`] — the on-device ANN tier (`01-portable-core.md` §3).
//!
//! A production device build would use the `sqlite-vec` extension for indexed
//! search; here we store embeddings as JSON and do a project-scoped brute-force
//! cosine scan. That keeps the adapter dependency-light and identical in
//! behaviour to [`agistack_adapters_mem::InMemoryVectorIndex`], while still
//! proving the *durable* device path (vectors survive a reopen).

use std::sync::Mutex;

use async_trait::async_trait;
use rusqlite::{params, Connection};

use agistack_core::ports::{CoreError, CoreResult, ScoredId, VectorIndexPort};

pub struct SqliteVectorIndex {
    conn: Mutex<Connection>,
}

impl SqliteVectorIndex {
    pub fn open(path: &str) -> CoreResult<Self> {
        Self::init(Connection::open(path).map_err(to_vec)?)
    }

    pub fn in_memory() -> CoreResult<Self> {
        Self::init(Connection::open_in_memory().map_err(to_vec)?)
    }

    fn init(conn: Connection) -> CoreResult<Self> {
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS vectors (
                project_id TEXT NOT NULL,
                id TEXT NOT NULL,
                embedding TEXT NOT NULL,
                PRIMARY KEY (project_id, id)
            );",
        )
        .map_err(to_vec)?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }
}

fn to_vec<E: std::fmt::Display>(e: E) -> CoreError {
    CoreError::Vector(e.to_string())
}

/// Cosine similarity (higher = closer); 0 for mismatched or zero-norm vectors.
fn cosine(a: &[f32], b: &[f32]) -> f32 {
    if a.len() != b.len() {
        return 0.0;
    }
    let dot: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
    let na: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let nb: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    if na == 0.0 || nb == 0.0 {
        0.0
    } else {
        dot / (na * nb)
    }
}

#[async_trait]
impl VectorIndexPort for SqliteVectorIndex {
    async fn upsert(&self, project_id: &str, id: &str, vector: &[f32]) -> CoreResult<()> {
        let json = serde_json::to_string(vector).map_err(to_vec)?;
        let conn = self.conn.lock().map_err(to_vec)?;
        conn.execute(
            "INSERT OR REPLACE INTO vectors (project_id, id, embedding) VALUES (?1, ?2, ?3)",
            params![project_id, id, json],
        )
        .map_err(to_vec)?;
        Ok(())
    }

    async fn query(&self, project_id: &str, vector: &[f32], k: usize) -> CoreResult<Vec<ScoredId>> {
        let conn = self.conn.lock().map_err(to_vec)?;
        let mut stmt = conn
            .prepare("SELECT id, embedding FROM vectors WHERE project_id = ?1")
            .map_err(to_vec)?;
        let rows = stmt
            .query_map(params![project_id], |r| {
                let id: String = r.get(0)?;
                let emb: String = r.get(1)?;
                Ok((id, emb))
            })
            .map_err(to_vec)?;

        let mut scored: Vec<ScoredId> = Vec::new();
        for row in rows {
            let (id, emb_json) = row.map_err(to_vec)?;
            let emb: Vec<f32> = serde_json::from_str(&emb_json).map_err(to_vec)?;
            scored.push(ScoredId {
                id,
                score: cosine(vector, &emb),
            });
        }
        scored.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| a.id.cmp(&b.id))
        });
        scored.truncate(k);
        Ok(scored)
    }

    async fn remove(&self, project_id: &str, id: &str) -> CoreResult<()> {
        let conn = self.conn.lock().map_err(to_vec)?;
        conn.execute(
            "DELETE FROM vectors WHERE project_id = ?1 AND id = ?2",
            params![project_id, id],
        )
        .map_err(to_vec)?;
        Ok(())
    }
}
