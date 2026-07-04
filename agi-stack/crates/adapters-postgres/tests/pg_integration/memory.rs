use super::support::*;

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
async fn project_sandbox_repository_roundtrips_against_shared_schema() {
    let Some(pool) =
        pool_or_skip("project_sandbox_repository_roundtrips_against_shared_schema").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    sqlx::query(
        "INSERT INTO users (id, email) VALUES ('u_sandbox_pg', 'sandbox@x') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO tenants (id, name) VALUES ('t_sandbox_pg', 'Sandbox T') ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_sandbox_pg', 't_sandbox_pg', 'Sandbox P', 'u_sandbox_pg') \
         ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('p_sandbox_pg_2', 't_sandbox_pg', 'Sandbox P2', 'u_sandbox_pg') \
         ON CONFLICT DO NOTHING",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "DELETE FROM project_sandboxes \
         WHERE project_id IN ('p_sandbox_pg', 'p_sandbox_pg_2') \
            OR sandbox_id IN ('sandbox_pg_1', 'sandbox_pg_2', 'sandbox_pg_3')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let repo = PgProjectSandboxRepository::new(pool.clone());
    let created_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
    let accessed_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 5, 5).unwrap();
    let saved = repo
        .upsert(ProjectSandboxRecord {
            id: "ps_sandbox_pg".to_string(),
            project_id: "p_sandbox_pg".to_string(),
            tenant_id: "t_sandbox_pg".to_string(),
            sandbox_id: "sandbox_pg_1".to_string(),
            sandbox_type: "cloud".to_string(),
            status: "creating".to_string(),
            created_at,
            started_at: None,
            last_accessed_at: accessed_at,
            health_checked_at: None,
            error_message: None,
            metadata_json: json!({ "profile": "lite" }),
            local_config: json!({}),
        })
        .await
        .unwrap();
    assert_eq!(saved.project_id, "p_sandbox_pg");
    assert_eq!(saved.status, "creating");
    assert_eq!(saved.metadata_json["profile"], "lite");

    let fetched = repo
        .find_by_project("p_sandbox_pg")
        .await
        .unwrap()
        .expect("sandbox association present");
    assert_eq!(fetched.sandbox_id, "sandbox_pg_1");
    assert_eq!(fetched.sandbox_type, "cloud");

    let started_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 6, 5).unwrap();
    let updated = repo
        .upsert(ProjectSandboxRecord {
            sandbox_id: "sandbox_pg_2".to_string(),
            status: "running".to_string(),
            started_at: Some(started_at),
            last_accessed_at: started_at,
            health_checked_at: Some(started_at),
            ..fetched
        })
        .await
        .unwrap();
    assert_eq!(updated.sandbox_id, "sandbox_pg_2");
    assert_eq!(updated.status, "running");
    assert_eq!(updated.started_at, Some(started_at));

    let by_sandbox = repo
        .find_by_sandbox("sandbox_pg_2")
        .await
        .unwrap()
        .expect("sandbox lookup present");
    assert_eq!(by_sandbox.project_id, "p_sandbox_pg");

    let second_created_at = Utc.with_ymd_and_hms(2026, 1, 2, 4, 0, 0).unwrap();
    repo.upsert(ProjectSandboxRecord {
        id: "ps_sandbox_pg_2".to_string(),
        project_id: "p_sandbox_pg_2".to_string(),
        tenant_id: "t_sandbox_pg".to_string(),
        sandbox_id: "sandbox_pg_3".to_string(),
        sandbox_type: "cloud".to_string(),
        status: "error".to_string(),
        created_at: second_created_at,
        started_at: None,
        last_accessed_at: second_created_at,
        health_checked_at: Some(second_created_at),
        error_message: Some("boom".to_string()),
        metadata_json: json!({ "profile": "standard" }),
        local_config: json!({}),
    })
    .await
    .unwrap();

    let listed = repo
        .list_by_tenant("t_sandbox_pg", None, 10, 0)
        .await
        .unwrap();
    assert_eq!(
        listed
            .iter()
            .map(|sandbox| sandbox.project_id.as_str())
            .collect::<Vec<_>>(),
        vec!["p_sandbox_pg_2", "p_sandbox_pg"]
    );

    let running = repo
        .list_by_tenant("t_sandbox_pg", Some("running"), 10, 0)
        .await
        .unwrap();
    assert_eq!(running.len(), 1);
    assert_eq!(running[0].sandbox_id, "sandbox_pg_2");

    let page = repo
        .list_by_tenant("t_sandbox_pg", None, 1, 1)
        .await
        .unwrap();
    assert_eq!(page.len(), 1);
    assert_eq!(page[0].project_id, "p_sandbox_pg");

    assert!(repo.delete_by_project("p_sandbox_pg").await.unwrap());
    assert!(repo.delete_by_project("p_sandbox_pg_2").await.unwrap());
    assert!(repo
        .find_by_project("p_sandbox_pg")
        .await
        .unwrap()
        .is_none());
}
