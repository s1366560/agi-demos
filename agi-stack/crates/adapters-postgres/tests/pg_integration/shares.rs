use super::support::*;

#[tokio::test]
async fn share_repository_matches_python_memory_shares_lifecycle() {
    let Some(pool) = pool_or_skip("share_repository_matches_python_memory_shares_lifecycle").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    for (id, email) in [
        ("u_share_author", "author@x"),
        ("u_share_target", "target@x"),
        ("u_share_admin", "admin@x"),
    ] {
        sqlx::query("INSERT INTO users (id, email) VALUES ($1, $2) ON CONFLICT DO NOTHING")
            .bind(id)
            .bind(email)
            .execute(&pool)
            .await
            .unwrap();
    }
    sqlx::query(
        "INSERT INTO tenants (id, name) VALUES ('t_share', 'Share T') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_share', 't_share', 'Share P', 'u_share_author') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_projects (user_id, project_id, role) \
         VALUES ('u_share_author', 'p_share', 'owner') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_projects (user_id, project_id, role) \
         VALUES ('u_share_admin', 'p_share', 'admin') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();

    let memory_id = "m_share_pg";
    let share_id = "s_share_pg";
    sqlx::query("DELETE FROM memory_shares WHERE memory_id = $1 OR id = $2")
        .bind(memory_id)
        .bind(share_id)
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM memories WHERE id = $1")
        .bind(memory_id)
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query(
        "INSERT INTO memories \
            (id, project_id, title, content, content_type, tags, entities, relationships, \
             version, author_id, collaborators, is_public, status, processing_status, meta) \
         VALUES \
            ($1, 'p_share', 'Shared memory', 'share content', 'text', \
             '[\"rust\",\"share\"]'::json, '[]'::json, '[]'::json, 1, \
             'u_share_author', '[]'::json, false, 'ENABLED', 'COMPLETED', '{}'::json)",
    )
    .bind(memory_id)
    .execute(&pool)
    .await
    .unwrap();

    let repo = PgShareRepository::new(pool.clone());
    let memory = repo
        .find_memory(memory_id)
        .await
        .unwrap()
        .expect("share memory exists");
    assert_eq!(memory.author_id, "u_share_author");
    assert_eq!(memory.tags, json!(["rust", "share"]));
    assert!(repo.user_exists("u_share_target").await.unwrap());
    assert!(repo.project_exists("p_share").await.unwrap());
    assert!(repo
        .user_can_admin_project("u_share_admin", "p_share")
        .await
        .unwrap());
    assert!(!repo
        .user_can_admin_project("u_share_target", "p_share")
        .await
        .unwrap());

    let created = repo
        .create_share(NewShareRecord {
            id: share_id.into(),
            memory_id: memory_id.into(),
            share_token: "share_pg_token".into(),
            shared_with_user_id: Some("u_share_target".into()),
            shared_with_project_id: None,
            permissions: json!({"view": true, "edit": false}),
            shared_by: "u_share_author".into(),
            expires_at: None,
        })
        .await
        .unwrap();
    assert_eq!(created.memory_id, memory_id);
    assert_eq!(created.share_token.as_deref(), Some("share_pg_token"));
    assert_eq!(created.permissions, json!({"view": true, "edit": false}));
    assert_eq!(created.access_count, 0);
    assert!(repo
        .explicit_target_share_exists(memory_id, "user", "u_share_target")
        .await
        .unwrap());

    let listed = repo.list_for_memory(memory_id).await.unwrap();
    assert!(listed.iter().any(|s| s.id == share_id));
    let by_token = repo
        .find_share_by_token("share_pg_token")
        .await
        .unwrap()
        .expect("share by token");
    assert_eq!(by_token.id, share_id);

    repo.increment_access_count(share_id).await.unwrap();
    let touched = repo
        .find_share_by_id(share_id)
        .await
        .unwrap()
        .expect("share after access");
    assert_eq!(touched.access_count, 1);

    assert!(repo.delete_share(share_id).await.unwrap());
    assert!(repo.find_share_by_id(share_id).await.unwrap().is_none());
}
