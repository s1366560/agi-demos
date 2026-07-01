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

use agistack_adapters_postgres::PgPool;
use agistack_adapters_postgres::{
    connect, ensure_aux_schema, PgApiKeyStore, PgCheckpointStore, PgMemoryRepository,
    PgProjectStore, PgTenantRepository, PgUserStore, PgVectorIndex, TenantLookup,
};
use agistack_core::agent::types::{SessionState, SessionStatus};
use agistack_core::model::{Entity, Memory};
use agistack_core::ports::{CheckpointStore, MemoryRepository, VectorIndexPort};

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
            user_id text NOT NULL, project_id text NOT NULL, role text DEFAULT 'member', \
            PRIMARY KEY (user_id, project_id))",
        "ALTER TABLE user_projects ADD COLUMN IF NOT EXISTS role text DEFAULT 'member'",
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
    let Some(pool) = pool_or_skip("memory_repository_roundtrips_against_shared_schema").await
    else {
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
    let hit = repo
        .search_by_project(project_id, "portable", 10)
        .await
        .unwrap();
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
            .arg(format!(
                "printf '%s' '{raw_key}' | shasum -a 256 | cut -d' ' -f1"
            ))
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

/// Additively extend the minimal `users`/`tenants` tables with the identity
/// columns the P2 adapters read, and create `user_tenants`. `ADD COLUMN IF NOT
/// EXISTS` keeps this idempotent and compatible with the memory/auth tests that
/// created the base tables — it never drops or rewrites existing columns.
async fn ensure_identity_tables(pool: &PgPool) {
    for ddl in [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS hashed_password text",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name text",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_superuser boolean DEFAULT false",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password boolean DEFAULT false",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS slug text",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS description text",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS owner_id text",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS plan text DEFAULT 'free'",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_projects integer DEFAULT 10",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_users integer DEFAULT 5",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_storage bigint DEFAULT 1073741824",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now()",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS updated_at timestamptz",
        "CREATE TABLE IF NOT EXISTS user_tenants (\
            id text PRIMARY KEY, user_id text NOT NULL, tenant_id text NOT NULL, \
            role text DEFAULT 'member', created_at timestamptz DEFAULT now())",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("identity ddl failed: {ddl}\n{e}"));
    }
}

#[tokio::test]
async fn project_store_splits_read_write_and_admin_access() {
    let Some(pool) = pool_or_skip("project_store_splits_read_write_and_admin_access").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;

    for sql in [
        "DELETE FROM user_tenants WHERE user_id IN \
         ('u_owner_authz', 'u_viewer_authz', 'u_admin_authz', 'u_public_authz', 'u_tenant_authz')",
        "DELETE FROM user_projects WHERE user_id IN \
         ('u_owner_authz', 'u_viewer_authz', 'u_admin_authz', 'u_public_authz', 'u_tenant_authz')",
        "DELETE FROM projects WHERE id IN \
         ('p_owned_authz', 'p_viewer_authz', 'p_admin_authz', 'p_public_authz', 'p_tenant_authz')",
        "DELETE FROM tenants WHERE id = 't_authz'",
        "DELETE FROM users WHERE id IN \
         ('u_owner_authz', 'u_viewer_authz', 'u_admin_authz', 'u_public_authz', 'u_tenant_authz')",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    sqlx::query("INSERT INTO tenants (id, name) VALUES ('t_authz', 'T')")
        .execute(&pool)
        .await
        .unwrap();
    for user_id in [
        "u_owner_authz",
        "u_viewer_authz",
        "u_admin_authz",
        "u_public_authz",
        "u_tenant_authz",
    ] {
        sqlx::query("INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, false)")
            .bind(user_id)
            .bind(format!("{user_id}@x"))
            .execute(&pool)
            .await
            .unwrap();
    }
    for (project_id, is_public) in [
        ("p_owned_authz", false),
        ("p_viewer_authz", false),
        ("p_admin_authz", false),
        ("p_public_authz", true),
        ("p_tenant_authz", false),
    ] {
        sqlx::query(
            "INSERT INTO projects (id, tenant_id, name, owner_id, is_public) \
             VALUES ($1, 't_authz', $2, 'u_owner_authz', $3)",
        )
        .bind(project_id)
        .bind(project_id)
        .bind(is_public)
        .execute(&pool)
        .await
        .unwrap();
    }
    for (user_id, project_id, role) in [
        ("u_viewer_authz", "p_viewer_authz", "viewer"),
        ("u_admin_authz", "p_admin_authz", "admin"),
    ] {
        sqlx::query("INSERT INTO user_projects (user_id, project_id, role) VALUES ($1, $2, $3)")
            .bind(user_id)
            .bind(project_id)
            .bind(role)
            .execute(&pool)
            .await
            .unwrap();
    }
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) \
         VALUES ('ut_authz', 'u_tenant_authz', 't_authz', 'owner')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let projects = PgProjectStore::new(pool.clone());

    let owned = projects
        .find_by_id("p_owned_authz")
        .await
        .unwrap()
        .expect("owned project");
    assert!(projects
        .user_can_access("u_owner_authz", &owned)
        .await
        .unwrap());
    assert!(projects
        .user_can_write("u_owner_authz", &owned)
        .await
        .unwrap());
    assert!(projects
        .user_can_admin("u_owner_authz", &owned)
        .await
        .unwrap());

    let viewer = projects
        .find_by_id("p_viewer_authz")
        .await
        .unwrap()
        .expect("viewer project");
    assert!(projects
        .user_can_access("u_viewer_authz", &viewer)
        .await
        .unwrap());
    assert!(!projects
        .user_can_write("u_viewer_authz", &viewer)
        .await
        .unwrap());
    assert!(!projects
        .user_can_admin("u_viewer_authz", &viewer)
        .await
        .unwrap());

    let admin = projects
        .find_by_id("p_admin_authz")
        .await
        .unwrap()
        .expect("admin project");
    assert!(projects
        .user_can_access("u_admin_authz", &admin)
        .await
        .unwrap());
    assert!(projects
        .user_can_write("u_admin_authz", &admin)
        .await
        .unwrap());
    assert!(projects
        .user_can_admin("u_admin_authz", &admin)
        .await
        .unwrap());

    let public = projects
        .find_by_id("p_public_authz")
        .await
        .unwrap()
        .expect("public project");
    assert!(projects
        .user_can_access("u_public_authz", &public)
        .await
        .unwrap());
    assert!(!projects
        .user_can_write("u_public_authz", &public)
        .await
        .unwrap());
    assert!(!projects
        .user_can_admin("u_public_authz", &public)
        .await
        .unwrap());

    let tenant = projects
        .find_by_id("p_tenant_authz")
        .await
        .unwrap()
        .expect("tenant project");
    assert!(projects
        .user_can_admin("u_tenant_authz", &tenant)
        .await
        .unwrap());
}

/// P2 login vertical: prove the store-level round-trip against the shared schema.
/// 1. `find_auth_by_email` returns the Python-shaped auth record.
/// 2. `insert_api_key` (mint on login) writes a key that `find_by_raw_key` then
///    resolves — this exercises the exact SHA-256 digest parity the two sides
///    share (mint hashes the plaintext; auth hashes the presented raw key).
/// 3. `PgTenantRepository` scopes tenant reads by membership (count/list/get with
///    404-then-403 ordering).
#[tokio::test]
async fn login_and_tenant_reads_roundtrip_against_shared_schema() {
    let Some(pool) = pool_or_skip("login_and_tenant_reads_roundtrip_against_shared_schema").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;

    // Clean any prior run for a deterministic assertion set.
    for sql in [
        "DELETE FROM user_tenants WHERE user_id = 'u_p2'",
        "DELETE FROM api_keys WHERE user_id = 'u_p2'",
        "DELETE FROM tenants WHERE id IN ('t_p2_member', 't_p2_other')",
        "DELETE FROM users WHERE id = 'u_p2'",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    // A user with a Python-stored bcrypt hash (the real `userpassword` vector).
    let stored_hash = "$2b$12$7zqrguT7EVNDjaBFQ03ITe6Q5Y1YiOL6Vu45Q6rjaLF3VfNYU/VD6";
    sqlx::query(
        "INSERT INTO users (id, email, full_name, hashed_password, is_active, is_superuser, \
         must_change_password) VALUES ('u_p2', 'p2@memstack.ai', 'P2 User', $1, true, false, false)",
    )
    .bind(stored_hash)
    .execute(&pool)
    .await
    .unwrap();

    let users = PgUserStore::new(pool.clone());

    // (1) Auth lookup returns the shaped record.
    let rec = users
        .find_auth_by_email("p2@memstack.ai")
        .await
        .unwrap()
        .expect("user found");
    assert_eq!(rec.id, "u_p2");
    assert_eq!(rec.hashed_password, stored_hash);
    assert!(rec.is_active);
    assert!(!rec.is_superuser);
    assert!(users
        .find_auth_by_email("missing@x")
        .await
        .unwrap()
        .is_none());

    // (2) Mint a key exactly as login does, then resolve it via the auth store.
    let raw_key = "ms_sk_p2_login_session_key_0000000000000000000000000000000000000000";
    users
        .insert_api_key(
            "k_p2",
            raw_key,
            "Login Session p2@memstack.ai",
            "u_p2",
            None,
            &["read".to_string(), "write".to_string()],
        )
        .await
        .unwrap();
    let keys = PgApiKeyStore::new(pool.clone());
    let resolved = keys
        .find_by_raw_key(raw_key)
        .await
        .unwrap()
        .expect("minted key resolves");
    assert_eq!(resolved.user_id, "u_p2");
    assert!(resolved.is_usable_at(1_700_000_000_000));

    // (3) Tenant membership scoping.
    sqlx::query(
        "INSERT INTO tenants (id, name, slug, owner_id) \
         VALUES ('t_p2_member', 'Member Tenant', 'member-tenant', 'u_p2')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenants (id, name, slug, owner_id) \
         VALUES ('t_p2_other', 'Other Tenant', 'other-tenant', 'u_other')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) \
         VALUES ('ut_p2', 'u_p2', 't_p2_member', 'admin')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let tenants = PgTenantRepository::new(pool.clone());
    assert_eq!(tenants.count_for_user("u_p2", None).await.unwrap(), 1);
    let page = tenants.list_for_user("u_p2", None, 0, 20).await.unwrap();
    assert_eq!(page.len(), 1);
    assert_eq!(page[0].id, "t_p2_member");
    assert_eq!(page[0].slug, "member-tenant");

    // Found (member), by id and by slug.
    assert!(matches!(
        tenants.get_for_user("u_p2", "t_p2_member").await.unwrap(),
        TenantLookup::Found(t) if t.id == "t_p2_member"
    ));
    assert!(matches!(
        tenants.get_for_user("u_p2", "member-tenant").await.unwrap(),
        TenantLookup::Found(_)
    ));
    // Exists but no membership -> Forbidden (403), not NotFound.
    assert!(matches!(
        tenants.get_for_user("u_p2", "t_p2_other").await.unwrap(),
        TenantLookup::Forbidden
    ));
    // Does not exist -> NotFound (404).
    assert!(matches!(
        tenants.get_for_user("u_p2", "t_nope").await.unwrap(),
        TenantLookup::NotFound
    ));
}
