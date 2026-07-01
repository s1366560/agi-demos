//! [`PgVectorIndex`] — the production [`VectorIndexPort`] over pgvector.
//!
//! The Python `memories` table has **no embedding column** (Python keeps vectors
//! in Neo4j/graphiti), so this index lives in the **Rust-owned, additive**
//! `agistack_memory_vectors` table created by [`ensure_aux_schema`]. This keeps
//! the shared-DB strangler invariant: we add a table, we never alter a
//! Python-owned one (plan.md Section 14.5).
//!
//! [`ensure_aux_schema`]: crate::ensure_aux_schema

use async_trait::async_trait;

use agistack_core::ports::{CoreError, CoreResult, ScoredId, VectorIndexPort};

use crate::PgPool;

/// pgvector-backed vector index, scoped per `project_id` (multi-tenancy).
pub struct PgVectorIndex {
    pool: PgPool,
}

impl PgVectorIndex {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

/// Render a vector as a pgvector text literal `[a,b,c]`, bound as text and cast
/// `::vector` in SQL. Avoids a pgvector-specific bind type while staying exact.
fn vector_literal(vector: &[f32]) -> String {
    let mut out = String::with_capacity(vector.len() * 8 + 2);
    out.push('[');
    for (i, v) in vector.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        out.push_str(&v.to_string());
    }
    out.push(']');
    out
}

fn vector_err(e: sqlx::Error) -> CoreError {
    CoreError::Vector(e.to_string())
}

#[async_trait]
impl VectorIndexPort for PgVectorIndex {
    async fn upsert(&self, project_id: &str, id: &str, vector: &[f32]) -> CoreResult<()> {
        let literal = vector_literal(vector);
        sqlx::query(
            "INSERT INTO agistack_memory_vectors (project_id, id, embedding) \
             VALUES ($1, $2, $3::vector) \
             ON CONFLICT (project_id, id) DO UPDATE SET embedding = EXCLUDED.embedding",
        )
        .bind(project_id)
        .bind(id)
        .bind(&literal)
        .execute(&self.pool)
        .await
        .map_err(vector_err)?;
        Ok(())
    }

    async fn query(&self, project_id: &str, vector: &[f32], k: usize) -> CoreResult<Vec<ScoredId>> {
        let literal = vector_literal(vector);
        // `<=>` is pgvector cosine *distance* (0 = identical). Convert to a
        // higher-is-closer score (`1 - distance`) so it matches the in-memory
        // cosine-similarity adapter the rest of the stack expects.
        let rows = sqlx::query_as::<_, (String, f64)>(
            "SELECT id, 1.0 - (embedding <=> $2::vector) AS score \
             FROM agistack_memory_vectors \
             WHERE project_id = $1 \
             ORDER BY embedding <=> $2::vector ASC \
             LIMIT $3",
        )
        .bind(project_id)
        .bind(&literal)
        .bind(k as i64)
        .fetch_all(&self.pool)
        .await
        .map_err(vector_err)?;

        Ok(rows
            .into_iter()
            .map(|(id, score)| ScoredId {
                id,
                score: score as f32,
            })
            .collect())
    }

    async fn remove(&self, project_id: &str, id: &str) -> CoreResult<()> {
        sqlx::query("DELETE FROM agistack_memory_vectors WHERE project_id = $1 AND id = $2")
            .bind(project_id)
            .bind(id)
            .execute(&self.pool)
            .await
            .map_err(vector_err)?;
        Ok(())
    }
}

#[cfg(test)]
mod unit {
    use super::vector_literal;

    #[test]
    fn vector_literal_formats_pgvector_syntax() {
        assert_eq!(vector_literal(&[]), "[]");
        assert_eq!(vector_literal(&[1.0]), "[1]");
        assert_eq!(vector_literal(&[1.0, 2.5, -3.0]), "[1,2.5,-3]");
    }
}
