use super::support::*;

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

#[tokio::test]
async fn api_key_revoke_by_raw_key_is_idempotent_and_isolated() {
    let Some(pool) = pool_or_skip("api_key_revoke_by_raw_key_is_idempotent_and_isolated").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    use sha2::{Digest, Sha256};

    let current_raw_key = "ms_sk_revoke_current_pg";
    let other_raw_key = "ms_sk_revoke_other_pg";
    let current_hash = format!("{:x}", Sha256::digest(current_raw_key.as_bytes()));
    let other_hash = format!("{:x}", Sha256::digest(other_raw_key.as_bytes()));

    let has_full_user_shape = sqlx::query_scalar::<_, bool>(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns \
         WHERE table_schema = current_schema() AND table_name = 'users' \
         AND column_name = 'hashed_password')",
    )
    .fetch_one(&pool)
    .await
    .unwrap();
    if has_full_user_shape {
        sqlx::query(
            "INSERT INTO users (id, email, hashed_password, full_name, is_active, \
             is_superuser, must_change_password, profile) VALUES \
             ('u_revoke', 'revoke@x', 'unused', 'Revoke Test', true, false, false, '{}'::json) \
             ON CONFLICT DO NOTHING",
        )
        .execute(&pool)
        .await
        .unwrap();
    } else {
        sqlx::query(
            "INSERT INTO users (id, email) VALUES ('u_revoke', 'revoke@x') ON CONFLICT DO NOTHING",
        )
        .execute(&pool)
        .await
        .unwrap();
    }
    sqlx::query("DELETE FROM api_keys WHERE id IN ('k_revoke_current', 'k_revoke_other')")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO api_keys (id, key_hash, name, user_id, is_active, permissions) VALUES \
         ('k_revoke_current', $1, 'current', 'u_revoke', true, '[]'::json), \
         ('k_revoke_other', $2, 'other', 'u_revoke', true, '[]'::json)",
    )
    .bind(&current_hash)
    .bind(&other_hash)
    .execute(&pool)
    .await
    .unwrap();

    let keys = PgApiKeyStore::new(pool.clone());
    assert!(keys.revoke_by_raw_key(current_raw_key).await.unwrap());
    assert!(!keys.revoke_by_raw_key(current_raw_key).await.unwrap());
    assert!(keys
        .find_by_raw_key(current_raw_key)
        .await
        .unwrap()
        .is_none());
    assert!(keys.find_by_raw_key(other_raw_key).await.unwrap().is_some());

    sqlx::query("DELETE FROM api_keys WHERE id IN ('k_revoke_current', 'k_revoke_other')")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM users WHERE id = 'u_revoke'")
        .execute(&pool)
        .await
        .unwrap();
}
