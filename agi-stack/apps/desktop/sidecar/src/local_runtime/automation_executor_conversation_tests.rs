use super::*;
use agistack_adapters_device::SqliteCheckpointStore;
use chrono::{Duration, Utc};
use uuid::Uuid;

#[tokio::test]
async fn fresh_runs_ignore_saved_binding_but_recovery_and_reuse_keep_their_conversation() {
    let root = std::env::temp_dir().join(format!("automation-conversation-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).unwrap();
    let state = LocalRuntimeState::new(
        root.clone(),
        LocalToolHost::new(&root).unwrap(),
        Arc::new(SqliteCheckpointStore::in_memory().unwrap()),
        "conversation-test-token".into(),
        session_store::DesktopSessionStore::in_memory().unwrap(),
    )
    .unwrap();
    state
        .mock_llm_enabled
        .store(1, std::sync::atomic::Ordering::Release);
    let mut claim = AutomationOperationClaim {
        operation_id: "operation".into(),
        run_id: "first-run".into(),
        tenant_id: "local".into(),
        project_id: "local-project".into(),
        job_id: "job".into(),
        actor_user_id: "local-user".into(),
        runtime_execution_id: "first-run".into(),
        conversation_id: None,
        job_snapshot: json!({"name":"Fresh", "conversation_mode":"fresh",
            "conversation_id":"deleted-old-binding", "workspace_id":"local-workspace"}),
        attempts: 1,
        max_retries: 0,
        deadline_at: Utc::now() + Duration::seconds(60),
        worker_id: "worker".into(),
        lease_token: "lease".into(),
        fence_token: 1,
    };
    let first = automation_conversation(&state, &claim).await.unwrap();
    assert_eq!(first.id, "local-automation-conversation-first-run");
    assert_eq!(first.workspace_id.as_deref(), Some("local-workspace"));
    // A crash/provider failure can occur after insertion but before run history
    // records the conversation. Retrying the same run must reuse that row.
    assert_eq!(
        automation_conversation(&state, &claim).await.unwrap().id,
        first.id
    );
    claim.run_id = "second-run".into();
    let second = automation_conversation(&state, &claim).await.unwrap();
    assert_ne!(first.id, second.id);
    claim.conversation_id = Some(first.id.clone());
    assert_eq!(
        automation_conversation(&state, &claim).await.unwrap().id,
        first.id
    );
    claim.conversation_id = None;
    claim.job_snapshot["conversation_mode"] = json!("reuse");
    claim.job_snapshot["conversation_id"] = json!(first.id);
    assert_eq!(
        automation_conversation(&state, &claim).await.unwrap().id,
        first.id
    );
    claim.project_id = "other-project".into();
    assert_eq!(
        automation_conversation(&state, &claim).await.unwrap_err(),
        "local_automation_conversation_scope_mismatch"
    );
    drop(state);
    std::fs::remove_dir_all(root).unwrap();
}
