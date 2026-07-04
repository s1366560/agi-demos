use super::support::*;

#[tokio::test]
async fn hitl_request_repository_matches_python_response_lifecycle() {
    let Some(pool) =
        pool_or_skip("hitl_request_repository_matches_python_response_lifecycle").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_identity_tables(&pool).await;
    ensure_hitl_tables(&pool).await;

    for sql in [
        "DELETE FROM hitl_requests WHERE id LIKE 'hitl_repo_%'",
        "DELETE FROM conversations WHERE id LIKE 'hitl_repo_%'",
        "DELETE FROM user_projects WHERE project_id = 'hitl_repo_project'",
        "DELETE FROM user_tenants WHERE tenant_id = 'hitl_repo_tenant'",
        "DELETE FROM projects WHERE id = 'hitl_repo_project'",
        "DELETE FROM tenants WHERE id = 'hitl_repo_tenant'",
        "DELETE FROM users WHERE id IN ('hitl_repo_user', 'hitl_repo_other')",
    ] {
        sqlx::query(sql).execute(&pool).await.unwrap();
    }

    sqlx::query("INSERT INTO tenants (id, name) VALUES ('hitl_repo_tenant', 'HITL')")
        .execute(&pool)
        .await
        .unwrap();
    for user_id in ["hitl_repo_user", "hitl_repo_other"] {
        sqlx::query("INSERT INTO users (id, email) VALUES ($1, $2)")
            .bind(user_id)
            .bind(format!("{user_id}@example.com"))
            .execute(&pool)
            .await
            .unwrap();
    }
    sqlx::query(
        "INSERT INTO user_tenants (id, user_id, tenant_id, role) \
         VALUES ('hitl_repo_ut_user', 'hitl_repo_user', 'hitl_repo_tenant', 'member')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id) \
         VALUES ('hitl_repo_project', 'hitl_repo_tenant', 'HITL Project', 'hitl_repo_user')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO user_projects (user_id, project_id, role) \
         VALUES ('hitl_repo_user', 'hitl_repo_project', 'member')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO conversations (id, project_id, tenant_id, user_id, title) \
         VALUES ('hitl_repo_conversation', 'hitl_repo_project', 'hitl_repo_tenant', \
                 'hitl_repo_user', 'HITL conversation')",
    )
    .execute(&pool)
    .await
    .unwrap();

    let now = Utc::now();
    sqlx::query(
        "INSERT INTO hitl_requests \
         (id, request_type, conversation_id, message_id, tenant_id, project_id, user_id, \
          question, request_metadata, status, expires_at) \
         VALUES \
         ('hitl_repo_pending', 'clarification', 'hitl_repo_conversation', 'hitl_repo_message', \
          'hitl_repo_tenant', 'hitl_repo_project', 'hitl_repo_user', 'Continue?', \
          '{\"agent_mode\":\"default\"}'::json, 'pending', $1), \
         ('hitl_repo_expired', 'decision', 'hitl_repo_conversation', NULL, \
          'hitl_repo_tenant', 'hitl_repo_project', 'hitl_repo_user', 'Pick one', \
          NULL, 'pending', $2)",
    )
    .bind(ts(2099, 1, 1, 0, 0, 0))
    .bind(ts(2000, 1, 1, 0, 0, 0))
    .execute(&pool)
    .await
    .unwrap();

    let repo = PgHitlRequestRepository::new(pool.clone());
    let request = repo
        .get_by_id("hitl_repo_pending")
        .await
        .unwrap()
        .expect("pending HITL request");
    assert_eq!(request.request_type, "clarification");
    assert_eq!(request.conversation_id, "hitl_repo_conversation");
    assert_eq!(request.message_id.as_deref(), Some("hitl_repo_message"));
    assert!(!request.is_expired_at(now));

    assert!(repo
        .user_has_tenant_access("hitl_repo_user", "hitl_repo_tenant")
        .await
        .unwrap());
    assert!(!repo
        .user_has_tenant_access("hitl_repo_other", "hitl_repo_tenant")
        .await
        .unwrap());
    assert!(repo
        .user_has_project_access("hitl_repo_user", "hitl_repo_project")
        .await
        .unwrap());
    assert!(repo
        .user_has_conversation_access(
            "hitl_repo_user",
            "hitl_repo_tenant",
            "hitl_repo_conversation",
        )
        .await
        .unwrap());
    assert!(!repo
        .user_has_conversation_access(
            "hitl_repo_other",
            "hitl_repo_tenant",
            "hitl_repo_conversation",
        )
        .await
        .unwrap());

    assert!(repo
        .update_response(
            "hitl_repo_pending",
            "yes",
            Some(&json!({"source": "integration"})),
            now,
        )
        .await
        .unwrap());
    assert!(!repo
        .update_response("hitl_repo_pending", "again", None, now)
        .await
        .unwrap());

    let answered = repo
        .get_by_id("hitl_repo_pending")
        .await
        .unwrap()
        .expect("answered HITL request");
    assert_eq!(answered.status, "answered");
    let (response, metadata): (Option<String>, Option<serde_json::Value>) = sqlx::query_as(
        "SELECT response, response_metadata FROM hitl_requests WHERE id = 'hitl_repo_pending'",
    )
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(response.as_deref(), Some("yes"));
    assert_eq!(metadata.unwrap()["source"], "integration");

    let expired = repo
        .get_by_id("hitl_repo_expired")
        .await
        .unwrap()
        .expect("expired HITL request");
    assert!(expired.is_expired_at(now));
    assert!(repo.mark_timeout("hitl_repo_expired").await.unwrap());
    let timed_out = repo
        .get_by_id("hitl_repo_expired")
        .await
        .unwrap()
        .expect("timed out HITL request");
    assert_eq!(timed_out.status, "timeout");
}
