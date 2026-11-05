use super::*;
use crate::auth::DevAuthenticator;
use axum::{
    body::{to_bytes, Body},
    http::Request,
    middleware,
};
use tower::ServiceExt;

async fn get(app: AppState, id: &str, project: &str) -> (StatusCode, Value) {
    let response = router()
        .layer(middleware::from_fn_with_state(
            app.clone(),
            crate::auth::require_api_key,
        ))
        .with_state(app)
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/v1/agent/conversations/{id}?project_id={project}"
                ))
                .header("Authorization", "Bearer ms_sk_fixture")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

#[tokio::test]
async fn conversation_detail_http_preserves_scope_and_rejects_other_owner() {
    let mut app = crate::prod_api::unit::test_state();
    let conversation = app
        .agent_conversations
        .create_conversation(
            "dev-user",
            serde_json::from_value(json!({"project_id":"dev-project","title":"Owned fixture"}))
                .unwrap(),
        )
        .await
        .unwrap();
    let id = conversation.id.clone();
    let (status, value) = get(app.clone(), &id, "dev-project").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(value["id"], id);
    assert_eq!(value["user_id"], "dev-user");
    assert_eq!(value["tenant_id"], "dev-tenant");
    assert_eq!(value["project_id"], "dev-project");
    assert_eq!(value["workspace_id"], Value::Null);
    assert_eq!(
        get(app.clone(), &id, "other-project").await.0,
        StatusCode::NOT_FOUND
    );
    assert_eq!(
        get(app.clone(), "missing", "dev-project").await.0,
        StatusCode::NOT_FOUND
    );
    app.auth = Arc::new(DevAuthenticator::new("other-user"));
    assert_eq!(get(app, &id, "dev-project").await.0, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn conversation_detail_postgres_uses_live_membership_and_core_authority() {
    let Ok(url) = std::env::var("AGISTACK_TEST_DATABASE_URL") else {
        return;
    };
    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(1)
        .max_lifetime(None)
        .idle_timeout(None)
        .connect(&url)
        .await
        .unwrap();
    for statement in [
        "CREATE TEMP TABLE conversations (LIKE public.conversations INCLUDING DEFAULTS)",
        "CREATE TEMP TABLE projects (id text PRIMARY KEY, tenant_id text)",
        "CREATE TEMP TABLE user_projects (user_id text, project_id text)",
        "CREATE TEMP TABLE user_tenants (user_id text, tenant_id text, role text)",
        "INSERT INTO projects VALUES ('dev-project','dev-tenant'),('other-project','dev-tenant')",
        "INSERT INTO user_projects VALUES ('dev-user','dev-project'),('other-user','dev-project')",
        "INSERT INTO user_tenants VALUES ('dev-user','dev-tenant','member'),('other-user','dev-tenant','member')",
        "INSERT INTO conversations (id,project_id,tenant_id,user_id,title,status,current_mode,merge_strategy,agent_config,meta,message_count,created_at,updated_at,participant_agents) VALUES ('owned-detail','dev-project','dev-tenant','dev-user','Owned fixture','active','build','result_only','{}','{}',0,NOW(),NOW(),'[]')",
    ] { sqlx::query(statement).execute(&pool).await.unwrap(); }
    let mut app = crate::prod_api::unit::test_state();
    let authority =
        Arc::new(crate::workspace_authority::test_support::FixedWorkspaceAuthority::new(None, &[]));
    app.agent_conversations = Arc::new(PgAgentConversationService::new(
        PgAgentConversationRepository::new(pool.clone()),
        PgAgentExecutionEventRepository::new(pool.clone()),
        PgHitlRequestRepository::new(pool.clone()),
        PgConversationSessionProjectionService::new(pool.clone(), authority.clone()),
        authority,
    ));
    assert_eq!(
        get(app.clone(), "owned-detail", "dev-project").await.0,
        StatusCode::OK
    );
    assert_eq!(
        get(app.clone(), "owned-detail", "other-project").await.0,
        StatusCode::NOT_FOUND
    );
    app.auth = Arc::new(DevAuthenticator::new("other-user"));
    assert_eq!(
        get(app.clone(), "owned-detail", "dev-project").await.0,
        StatusCode::FORBIDDEN
    );
    app.auth = Arc::new(DevAuthenticator::new("dev-user"));
    sqlx::query("DELETE FROM pg_temp.user_projects WHERE user_id='dev-user'")
        .execute(&pool)
        .await
        .unwrap();
    assert_eq!(
        get(app.clone(), "owned-detail", "dev-project").await.0,
        StatusCode::FORBIDDEN
    );
    sqlx::query("INSERT INTO pg_temp.user_projects VALUES ('dev-user','dev-project')")
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("UPDATE pg_temp.conversations SET workspace_id='revoked-workspace'")
        .execute(&pool)
        .await
        .unwrap();
    assert_eq!(
        get(app, "owned-detail", "dev-project").await.0,
        StatusCode::FORBIDDEN
    );
}
