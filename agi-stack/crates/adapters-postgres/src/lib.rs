//! `agistack-adapters-postgres`: the **production persistence tier**.
//!
//! This is the server-only adapter that lets the Rust core read and write the
//! **same PostgreSQL database the Python backend already owns** — the enabling
//! move for the strangler-fig migration (plan.md Section 14): no data migration,
//! we just route a capability's read/write path from Python to Rust per cutover.
//!
//! ## Two table classes (the shared-DB invariant)
//! 1. **Python-owned tables, read/written verbatim** — [`PgMemoryRepository`]
//!    against `memories`, [`PgApiKeyStore`] against `api_keys`,
//!    [`PgProjectStore`] against `projects`. Column names/types mirror
//!    `src/infrastructure/adapters/secondary/persistence/models.py` exactly.
//! 2. **Rust-owned *additive* auxiliary tables** — created by
//!    [`ensure_aux_schema`], prefixed `agistack_`. The Python `memories` table has
//!    no embedding column (Python keeps vectors in Neo4j/graphiti), so the vector
//!    index lives in its own `agistack_memory_vectors` table; agent checkpoints in
//!    `agistack_checkpoints`. These are purely additive — they never alter a
//!    Python table, so the two backends coexist safely during cutover.
//!
//! ## Portability
//! `sqlx`/`tokio` live **only** in this crate (and the server binary). The core
//! holds the port traits; this adapter is selected at the composition root for
//! the server tier, just like `adapters-device` on device or the in-memory
//! adapters in the browser (ADR-0001). Nothing here leaks into a port signature.

use sha2::{Digest, Sha256};

pub use sqlx::postgres::PgPool;

mod auth_store;
mod checkpoint;
mod memory_repo;
mod tenant_repo;
mod user_store;
mod vector_index;

pub use auth_store::{ApiKeyRecord, PgApiKeyStore, PgProjectStore, ProjectRecord};
pub use checkpoint::PgCheckpointStore;
pub use memory_repo::PgMemoryRepository;
pub use tenant_repo::{PgTenantRepository, TenantLookup, TenantRecord};
pub use user_store::{PgUserStore, UserAuthRecord};
pub use vector_index::PgVectorIndex;

use agistack_core::ports::{CoreError, CoreResult};

/// Open a pooled connection to `database_url` (e.g.
/// `postgres://user:pass@host:5432/db`). Mirrors the Python `POSTGRES_*` DSN; the
/// composition root supplies the URL from the environment.
pub async fn connect(database_url: &str) -> CoreResult<PgPool> {
    sqlx::postgres::PgPoolOptions::new()
        .max_connections(8)
        .connect(database_url)
        .await
        .map_err(|e| CoreError::Storage(format!("postgres connect: {e}")))
}

/// Create the **Rust-owned auxiliary** tables if absent. Strictly additive: it
/// only ever issues `CREATE EXTENSION IF NOT EXISTS` / `CREATE TABLE IF NOT
/// EXISTS` against `agistack_`-prefixed objects, so it can run against the live
/// shared database without disturbing any Python-owned table.
///
/// - `vector` extension + `agistack_memory_vectors` back [`PgVectorIndex`].
/// - `agistack_checkpoints` backs [`PgCheckpointStore`] (agent crash recovery).
pub async fn ensure_aux_schema(pool: &PgPool) -> CoreResult<()> {
    // pgvector. On the `pgvector/pgvector` image the bootstrap superuser can
    // create it; if a managed instance pre-installs it, the IF NOT EXISTS is a
    // no-op. Vectors are kept unbounded-dim (no ANN index) so any embedding width
    // works for the brute-force P1 scan.
    sqlx::query("CREATE EXTENSION IF NOT EXISTS vector")
        .execute(pool)
        .await
        .map_err(|e| CoreError::Storage(format!("ensure vector extension: {e}")))?;

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS agistack_memory_vectors (\
            project_id text NOT NULL, \
            id text NOT NULL, \
            embedding vector NOT NULL, \
            PRIMARY KEY (project_id, id))",
    )
    .execute(pool)
    .await
    .map_err(|e| CoreError::Storage(format!("ensure agistack_memory_vectors: {e}")))?;

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS agistack_checkpoints (\
            session_id text PRIMARY KEY, \
            state jsonb NOT NULL, \
            updated_at timestamptz NOT NULL DEFAULT now())",
    )
    .execute(pool)
    .await
    .map_err(|e| CoreError::Storage(format!("ensure agistack_checkpoints: {e}")))?;

    Ok(())
}

/// SHA-256 hex digest — byte-identical to the Python auth path
/// (`AuthService.hash_api_key` = `hashlib.sha256(key.encode()).hexdigest()`), so
/// a `ms_sk_` key issued by Python verifies here against the same `key_hash`.
pub(crate) fn sha256_hex(input: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(input.as_bytes());
    let digest = hasher.finalize();
    let mut out = String::with_capacity(digest.len() * 2);
    for byte in digest {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

#[cfg(test)]
mod unit {
    use super::sha256_hex;

    #[test]
    fn sha256_matches_python_hexdigest() {
        // Reference vectors from Python `hashlib.sha256(x.encode()).hexdigest()`.
        assert_eq!(
            sha256_hex(""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            sha256_hex("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        // Shape of a real key prefix — just assert determinism + width here.
        let h = sha256_hex("ms_sk_0123456789abcdef");
        assert_eq!(h.len(), 64);
        assert!(h.chars().all(|c| c.is_ascii_hexdigit()));
    }
}
