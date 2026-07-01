//! Live-database integration tests for the production Postgres adapter.
//!
//! These are **gated on `DATABASE_URL`**: when it is unset (the default in CI and
//! most dev shells) every test short-circuits to a pass, so `cargo test
//! --workspace` never needs a database to be green. Point `DATABASE_URL` at a
//! Postgres with the `vector` extension available (e.g. the `pgvector/pgvector`
//! image) to exercise the real read/write path against a schema shaped like the
//! Python backend's.
//!
//! The tests create a **minimal subset** of the Python schema (`users`,
//! `tenants`, `projects`, `api_keys`, `memories`, `user_projects`) — only the
//! columns the Rust adapter touches, with the same names/types — then seed and
//! assert round-trips. This proves shared-DB compatibility without standing up
//! the full 110-table Python schema.

use agistack_adapters_postgres::{
    connect, ensure_aux_schema, PgApiKeyStore, PgCheckpointStore, PgMemoryRepository,
    PgProjectStore, PgVectorIndex,
};
use agistack_core::agent::types::{SessionState, SessionStatus};
use agistack_core::model::{Entity, Memory};
use agistack_core::ports::{CheckpointStore, MemoryRepository, VectorIndexPort};
use agistack_adapters_postgres::PgPool;

/// Return a connected pool if `DATABASE_URL` is set, else `None` (skip).
async fn pool_or_skip(test: &str) -> Option<PgPool> {
    match std::env::var("DATABASE_URL") {
        Ok(url) if !url.is_empty() => match connect(&url).await {
            Ok(pool) => Some(pool),
            Err(e) => panic!("DATABASE_URL set but connect failed for {test}: {e}"),
        },
        _ => {
            eprintln!("[skip] {test}: DATABASE_URL unset");
            None
        }
    }
}

/// Create the minimal Python-shaped tables the adapter reads/writes, plus the
/// Rust-owned auxiliary schema. Idempotent (`IF NOT EXISTS`), so tests can share a
/// database. Uses a per-test id prefix to isolate rows.
async fn ensure_python_shaped_tables(pool: &PgPool) {
    for ddl in [
        "CREATE TABLE IF NOT EXISTS users (id text PRIMARY KEY, email text)",
        "CREATE TABLE IF NOT EXISTS tenants (id text PRIMARY KEY, name text)",
        "CREATE TABLE IF NOT EXISTS projects (\
            id text PRIMARY KEY, tenant_id text NOT NULL, name text NOT NULL, \
            owner_id text NOT NULL, is_public boolean DEFAULT false)",
        "CREATE TABLE IF NOT EXISTS user_projects (\
            user_id text NOT NULL, project_id text NOT NULL, \
            PRIMARY KEY (user_id, project_id))",
        "CREATE TABLE IF NOT EXISTS api_keys (\
            id text PRIMARY KEY, key_hash text, name text, user_id text, \
            created_at timestamptz DEFAULT now(), expires_at timestamptz, \
            is_active boolean DEFAULT true, permissions json DEFAULT '[]'::json, \
            last_used_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS memories (\
            id text PRIMARY KEY, project_id text NOT NULL, title varchar(500) NOT NULL, \
            content text NOT NULL, content_type varchar(20) DEFAULT 'text', \
            tags json DEFAULT '[]'::json, entities json DEFAULT '[]'::json, \
            relationships json DEFAULT '[]'::json, version integer DEFAULT 1, \
            author_id text NOT NULL, collaborators json DEFAULT '[]'::json, \
            is_public boolean DEFAULT false, status text DEFAULT 'ENABLED', \
            processing_status text DEFAULT 'PENDING', meta json DEFAULT '{}'::json, \
            task_id text, created_at timestamptz DEFAULT now(), updated_at timestamptz)",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("ddl failed: {ddl}\n{e}"));
    }
    ensure_aux_schema(pool).await.expect("aux schema");
}

fn sample_memory(id: &str, project_id: &str) -> Memory {
    Memory {
        id: id.to_string(),
        project_id: project_id.to_string(),
        title: "Portable core".to_string(),
        content: "Rust core compiles to wasm and native.".to_string(),
        author_id: "u_pg_it".to_string(),
        content_type: "text".to_string(),
        tags: vec!["rust".to_string(), "portable".to_string()],
        entities: vec![Entity {
            name: "Rust".to_string(),
            kind: "language".to_string(),
        }],
        version: 1,
        status: "ENABLED".to_string(),
        created_at_ms: 1_700_000_000_000,
        embedding: None,
    }
}

#[tokio::test]
async fn memory_repository_roundtrips_against_shared_schema() {
    let Some(pool) = pool_or_skip("memory_repository_roundtrips_against_shared_schema").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    let project_id = "p_pg_mem";
    // Seed FK-referenced rows so the memories row is valid for Python readers too.
    sqlx::query("INSERT INTO users (id, email) VALUES ('u_pg_it', 'it@x') ON CONFLICT DO NOTHING")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_pg', 'T') ON CONFLICT DO NOTHING")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ($1, 't_pg', 'P', 'u_pg_it') ON CONFLICT DO NOTHING",
    )
    .bind(project_id)
    .execute(&pool)
    .await
    .unwrap();

    let repo = PgMemoryRepository::new(pool.clone());
    let id = "m_pg_1";
    sqlx::query("DELETE FROM memories WHERE id = $1")
        .bind(id)
        .execute(&pool)
        .await
        .unwrap();

    // save -> find_by_id
    repo.save(sample_memory(id, project_id)).await.unwrap();
    let fetched = repo.find_by_id(id).await.unwrap().expect("memory present");
    assert_eq!(fetched.title, "Portable core");
    assert_eq!(fetched.tags, vec!["rust", "portable"]);
    assert_eq!(fetched.entities.len(), 1);
    assert_eq!(fetched.entities[0].name, "Rust");
    assert_eq!(fetched.project_id, project_id);

    // list_by_project
    let listed = repo.list_by_project(project_id, 10, 0).await.unwrap();
    assert!(listed.iter().any(|m| m.id == id));

    // search_by_project (ILIKE) — hit and miss
    let hit = repo.search_by_project(project_id, "portable", 10).await.unwrap();
    assert!(hit.iter().any(|m| m.id == id));
    let miss = repo
        .search_by_project(project_id, "no_such_token_zzz", 10)
        .await
        .unwrap();
    assert!(!miss.iter().any(|m| m.id == id));

    // count_by_project override — efficient SELECT count(*) with the same ILIKE
    // filter as search. Unfiltered count includes the row; a matching search
    // counts it; a non-matching search excludes it.
    let total = repo.count_by_project(project_id, None).await.unwrap();
    assert!(total >= 1, "unfiltered count should see the saved memory");
    let count_hit = repo
        .count_by_project(project_id, Some("portable"))
        .await
        .unwrap();
    assert!(count_hit >= 1, "search count should match the saved memory");
    let count_miss = repo
        .count_by_project(project_id, Some("no_such_token_zzz"))
        .await
        .unwrap();
    assert_eq!(count_miss, 0, "non-matching search count is zero");

    // The row is byte-compatible with what Python expects: assert the DB-required
    // columns the core doesn't model were populated with valid defaults.
    let (relationships, is_public, proc_status): (String, bool, String) = sqlx::query_as(
        "SELECT relationships::text, is_public, processing_status FROM memories WHERE id = $1",
    )
    .bind(id)
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(relationships, "[]");
    assert!(!is_public);
    assert_eq!(proc_status, "COMPLETED");

    // delete
    assert!(repo.delete(id).await.unwrap());
    assert!(repo.find_by_id(id).await.unwrap().is_none());
}

#[tokio::test]
async fn vector_index_roundtrips_and_scopes_by_project() {
    let Some(pool) = pool_or_skip("vector_index_roundtrips_and_scopes_by_project").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    let index = PgVectorIndex::new(pool.clone());

    let (pa, pb) = ("p_vec_a", "p_vec_b");
    for p in [pa, pb] {
        sqlx::query("DELETE FROM agistack_memory_vectors WHERE project_id = $1")
            .bind(p)
            .execute(&pool)
            .await
            .unwrap();
    }

    index.upsert(pa, "v1", &[1.0, 0.0, 0.0]).await.unwrap();
    index.upsert(pa, "v2", &[0.0, 1.0, 0.0]).await.unwrap();
    // Same id/vector in a *different* project — must never leak across scope.
    index.upsert(pb, "v1", &[1.0, 0.0, 0.0]).await.unwrap();

    let hits = index.query(pa, &[0.9, 0.1, 0.0], 2).await.unwrap();
    assert_eq!(hits.len(), 2);
    assert_eq!(hits[0].id, "v1", "nearest should be v1");
    assert!(hits[0].score > hits[1].score);

    // Project scoping: querying pb only ever returns pb's ids.
    let pb_hits = index.query(pb, &[1.0, 0.0, 0.0], 10).await.unwrap();
    assert_eq!(pb_hits.len(), 1);
    assert_eq!(pb_hits[0].id, "v1");

    index.remove(pa, "v1").await.unwrap();
    let after = index.query(pa, &[1.0, 0.0, 0.0], 10).await.unwrap();
    assert!(!after.iter().any(|h| h.id == "v1"));
}

#[tokio::test]
async fn checkpoint_store_roundtrips_session_state() {
    let Some(pool) = pool_or_skip("checkpoint_store_roundtrips_session_state").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    let store = PgCheckpointStore::new(pool.clone());

    let sid = "s_pg_ckpt";
    store.delete(sid).await.unwrap();
    assert!(store.load(sid).await.unwrap().is_none());

    let mut state = SessionState::new(sid, "achieve the goal", Some("p_ckpt"));
    state.round = 3;
    state.status = SessionStatus::Running;
    store.save(&state).await.unwrap();

    let loaded = store.load(sid).await.unwrap().expect("checkpoint present");
    assert_eq!(loaded.session_id, sid);
    assert_eq!(loaded.goal, "achieve the goal");
    assert_eq!(loaded.round, 3);

    store.delete(sid).await.unwrap();
    assert!(store.load(sid).await.unwrap().is_none());
}

#[tokio::test]
async fn api_key_and_project_stores_verify_and_scope() {
    let Some(pool) = pool_or_skip("api_key_and_project_stores_verify_and_scope").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    // Seed a user, project, and an api_keys row whose key_hash is the SHA-256 of a
    // known raw key — exactly how Python stores it.
    sqlx::query("INSERT INTO users (id, email) VALUES ('u_auth', 'a@x') ON CONFLICT DO NOTHING")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_auth', 'T') ON CONFLICT DO NOTHING")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_auth', 't_auth', 'P', 'u_auth') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();

    // sha256("ms_sk_testkey_pg") computed by Python's hashlib.sha256(...).hexdigest().
    let raw_key = "ms_sk_testkey_pg";
    let key_hash = {
        use std::process::Command;
        // Derive via openssl to avoid hardcoding; falls back to a known constant.
        let out = Command::new("sh")
            .arg("-c")
            .arg(format!("printf '%s' '{raw_key}' | shasum -a 256 | cut -d' ' -f1"))
            .output();
        match out {
            Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).trim().to_string(),
            _ => String::new(),
        }
    };
    assert!(!key_hash.is_empty(), "could not compute sha256 for test");

    sqlx::query("DELETE FROM api_keys WHERE id = 'k_auth'")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO api_keys (id, key_hash, name, user_id, is_active) \
         VALUES ('k_auth', $1, 'test', 'u_auth', true)",
    )
    .bind(&key_hash)
    .execute(&pool)
    .await
    .unwrap();

    let keys = PgApiKeyStore::new(pool.clone());
    let now_ms = 1_700_000_000_000;

    // Correct key resolves to the user and is usable.
    let rec = keys
        .find_by_raw_key(raw_key)
        .await
        .unwrap()
        .expect("key found");
    assert_eq!(rec.user_id, "u_auth");
    assert!(rec.is_usable_at(now_ms));

    // Wrong key resolves to nothing.
    assert!(keys.find_by_raw_key("ms_sk_wrong").await.unwrap().is_none());

    // Project scope + access.
    let projects = PgProjectStore::new(pool.clone());
    let proj = projects
        .find_by_id("p_auth")
        .await
        .unwrap()
        .expect("project found");
    assert_eq!(proj.tenant_id, "t_auth");
    assert!(projects.user_can_access("u_auth", &proj).await.unwrap()); // owner
    assert!(!projects.user_can_access("u_other", &proj).await.unwrap()); // no membership
}
