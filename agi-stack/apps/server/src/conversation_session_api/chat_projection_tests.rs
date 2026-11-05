use super::*;
use std::sync::Arc;

fn conversation() -> SessionConversationResponse {
    SessionConversationResponse {
        id: "cloud-chat".into(),
        tenant_id: "tenant".into(),
        project_id: "project".into(),
        workspace_id: None,
        linked_workspace_task_id: None,
        workspace_name: None,
        user_id: "owner".into(),
        title: "Owned cloud fixture".into(),
        summary: None,
        status: "active".into(),
        current_mode: "build".into(),
        conversation_mode: None,
        capability_mode: Some(SessionCapabilityMode::Work),
        message_count: 0,
        participant_agents: vec![],
        coordinator_agent_id: None,
        focused_agent_id: None,
        created_at: DateTime::from_timestamp(1, 0).unwrap(),
        updated_at: None,
    }
}

#[tokio::test]
async fn chat_projection_postgres_reads_nullable_plan_and_exact_owner_scope() {
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
        "CREATE TEMP TABLE agent_plan_versions (LIKE public.agent_plan_versions INCLUDING DEFAULTS)",
        "CREATE TEMP TABLE agent_plan_runs (LIKE public.agent_plan_runs INCLUDING DEFAULTS)",
        "CREATE TEMP TABLE agent_run_authorities (LIKE public.agent_run_authorities INCLUDING DEFAULTS)",
        "INSERT INTO agent_run_authorities (id,tenant_id,project_id,conversation_id,run_kind,idempotency_key,message_id,request_message,status,revision,permission_profile,authorization_snapshot,created_at,updated_at,started_at) VALUES ('chat-run','tenant','project','cloud-chat','chat','rust-chat:message','message','Neutral fixture','running',3,'read_only','{\"source\":\"chat_admission\",\"private\":\"must-not-leak\"}',to_timestamp(2),to_timestamp(3),to_timestamp(2))",
        "INSERT INTO agent_run_authorities (id,tenant_id,project_id,conversation_id,run_kind,idempotency_key,message_id,request_message,status,revision,permission_profile,authorization_snapshot,created_at,updated_at) VALUES ('other-tenant','wrong','project','cloud-chat','chat','other','other','Foreign fixture','running',1,'full_access','{}',to_timestamp(4),to_timestamp(4))",
    ] { sqlx::query(statement).execute(&pool).await.unwrap(); }
    let authority =
        Arc::new(crate::workspace_authority::test_support::FixedWorkspaceAuthority::new(None, &[]));
    let service = PgConversationSessionProjectionService::new(pool.clone(), authority);
    let rows = service.load_runs(&conversation()).await.unwrap();
    assert_eq!(rows.len(), 1);
    let value = serde_json::to_value(&rows[0]).unwrap();
    assert_eq!(value["id"], "chat-run");
    assert_eq!(value["plan_version_id"], Value::Null);
    assert_eq!(value["status"], "running");
    assert_eq!(value["revision"], 3);
    assert_eq!(value["permission_profile"], "read_only");
    assert_eq!(value["started_at"], "1970-01-01T00:00:02Z");
    assert_eq!(
        value["authorization_snapshot"]["plan_version_id"],
        Value::Null
    );
    assert!(!value.to_string().contains("must-not-leak"));
    let mut projection = build_projection(ConversationSessionAuthoritySnapshot {
        conversation: conversation(),
        attempts: vec![],
        runs: rows,
        conversation_tasks: vec![],
        workspace_plan_context: None,
        pending_hitl: vec![],
        has_blocking_hitl: false,
        mutation_authority: SessionMutationAuthority {
            can_send_message: true,
            can_respond_to_hitl: false,
            can_control_execution: false,
        },
        artifact_records: vec![],
        tool_executions: SessionToolExecutionAuthority {
            items: vec![],
            total: 0,
            failed_total: 0,
        },
    })
    .unwrap();
    projection.snapshot_revision = "fixture-cloud-chat-v1".into();
    let fixture: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/rust-cloud-chat-session.json"
    ))
    .unwrap();
    assert_eq!(serde_json::to_value(projection).unwrap(), fixture);
    assert!(service
        .load_plans(&conversation())
        .await
        .unwrap()
        .is_empty());
    sqlx::query("INSERT INTO pg_temp.agent_plan_versions (id,conversation_id,version,status,tasks_json,created_at) VALUES ('draft','cloud-chat',1,'draft','[]',to_timestamp(4))").execute(&pool).await.unwrap();
    let plans = service.load_plans(&conversation()).await.unwrap();
    assert_eq!(plans.len(), 1);
    assert_eq!(plans[0].id, "draft");
    sqlx::query("UPDATE pg_temp.agent_plan_versions SET tasks_json='[{\"id\":\"malformed\"}]'")
        .execute(&pool)
        .await
        .unwrap();
    assert!(service.load_plans(&conversation()).await.is_err());
    sqlx::query(
        "UPDATE pg_temp.agent_run_authorities SET permission_profile='invalid' WHERE id='chat-run'",
    )
    .execute(&pool)
    .await
    .unwrap();
    assert!(service.load_runs(&conversation()).await.is_err());
}
