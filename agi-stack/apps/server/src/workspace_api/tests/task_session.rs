use super::super::types::{
    TaskSessionConversationPayload, TaskSessionInitialMessagePayload, WorkspaceCollaborationMode,
    WorkspaceUseCase,
};
use super::super::*;

fn create_payload(idempotency_key: &str) -> CreateTaskSessionPayload {
    CreateTaskSessionPayload {
        idempotency_key: idempotency_key.to_string(),
        workspace: TaskSessionWorkspacePayload::Create {
            name: "Atomic workspace".to_string(),
            description: Some("One transaction".to_string()),
            metadata: Some(Map::from_iter([("source".to_string(), json!("desktop"))])),
            use_case: WorkspaceUseCase::Programming,
            collaboration_mode: WorkspaceCollaborationMode::MultiAgentShared,
            sandbox_code_root: Some("/repo".to_string()),
        },
        conversation: TaskSessionConversationPayload {
            title: "Atomic workspace".to_string(),
            capability_mode: TaskSessionCapabilityMode::Code,
        },
        initial_message: TaskSessionInitialMessagePayload {
            content: "Create the implementation plan".to_string(),
        },
    }
}

#[tokio::test]
async fn dev_task_session_creates_one_bound_plan_session_and_replays_exactly() {
    let service = DevWorkspaceService::new("user-1");
    let payload = create_payload("task-session-1");

    let created = service
        .create_task_session("user-1", "tenant-1", "project-1", payload.clone())
        .await
        .unwrap();
    let replayed = service
        .create_task_session("user-1", "tenant-1", "project-1", payload)
        .await
        .unwrap();

    assert!(!created.replayed);
    assert!(replayed.replayed);
    assert_eq!(created.workspace, replayed.workspace);
    assert_eq!(created.conversation, replayed.conversation);
    assert_eq!(created.initial_message, replayed.initial_message);
    assert_eq!(
        created.conversation["workspace_id"],
        created.workspace["id"]
    );
    assert_eq!(created.conversation["conversation_mode"], "workspace");
    assert_eq!(created.conversation["current_mode"], "plan");
    assert_eq!(
        created.conversation["agent_config"]["capability_mode"],
        "code"
    );
    assert_eq!(
        created.initial_message["workspace_id"],
        created.workspace["id"]
    );

    let state = service.lock_state().unwrap();
    assert_eq!(state.workspaces.len(), 1);
    assert_eq!(state.messages.len(), 1);
    assert_eq!(state.task_session_receipts.len(), 1);
    assert_eq!(state.outbox.len(), 1);
}

#[tokio::test]
async fn dev_task_session_rejects_changed_payload_for_the_same_scoped_key() {
    let service = DevWorkspaceService::new("user-1");
    service
        .create_task_session(
            "user-1",
            "tenant-1",
            "project-1",
            create_payload("task-session-1"),
        )
        .await
        .unwrap();
    let mut changed = create_payload("task-session-1");
    changed.initial_message.content = "A changed objective".to_string();

    let error = service
        .create_task_session("user-1", "tenant-1", "project-1", changed)
        .await
        .unwrap_err();

    assert_eq!(error.status, StatusCode::CONFLICT);
    let state = service.lock_state().unwrap();
    assert_eq!(state.workspaces.len(), 1);
    assert_eq!(state.messages.len(), 1);
    assert_eq!(state.task_session_receipts.len(), 1);
}

#[tokio::test]
async fn dev_task_session_can_bind_an_existing_writable_workspace() {
    let service = DevWorkspaceService::new("user-1");
    let workspace = service
        .create_workspace(
            "user-1",
            "tenant-1",
            "project-1",
            WorkspaceCreatePayload {
                name: "Existing".to_string(),
                description: None,
                metadata: json!({}),
                use_case: Some("general".to_string()),
                collaboration_mode: Some("multi_agent_shared".to_string()),
                autonomy_profile: None,
                sandbox_code_root: None,
            },
        )
        .await
        .unwrap();
    let mut payload = create_payload("task-session-existing");
    payload.workspace = TaskSessionWorkspacePayload::Existing {
        workspace_id: workspace.id.clone(),
    };

    let created = service
        .create_task_session("user-1", "tenant-1", "project-1", payload)
        .await
        .unwrap();

    assert_eq!(created.workspace["id"], workspace.id);
    assert_eq!(service.lock_state().unwrap().workspaces.len(), 1);
}

#[tokio::test]
async fn dev_task_session_replay_rechecks_workspace_access() {
    let service = DevWorkspaceService::new("user-1");
    let payload = create_payload("task-session-revoke");
    service
        .create_task_session("user-1", "tenant-1", "project-1", payload.clone())
        .await
        .unwrap();
    service.lock_state().unwrap().workspace_members.clear();

    let error = service
        .create_task_session("user-1", "tenant-1", "project-1", payload)
        .await
        .unwrap_err();

    assert_eq!(error.status, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn dev_task_session_missing_message_becomes_tombstone_without_recreation() {
    let service = DevWorkspaceService::new("user-1");
    let payload = create_payload("task-session-missing-message");
    let created = service
        .create_task_session("user-1", "tenant-1", "project-1", payload.clone())
        .await
        .unwrap();
    let workspace_id = created.workspace["id"].as_str().unwrap().to_string();
    let message_id = created.initial_message["id"].as_str().unwrap().to_string();
    service.lock_state().unwrap().messages.remove(&message_id);

    for _ in 0..2 {
        let error = service
            .create_task_session("user-1", "tenant-1", "project-1", payload.clone())
            .await
            .unwrap_err();
        assert_eq!(error.status, StatusCode::CONFLICT);
    }

    let state = service.lock_state().unwrap();
    assert_eq!(state.workspaces.len(), 1);
    assert!(state.workspaces.contains_key(&workspace_id));
    assert!(state.messages.is_empty());
    assert_eq!(state.task_session_receipts.len(), 1);
    assert!(state
        .task_session_receipts
        .values()
        .next()
        .expect("task session tombstone")
        .response
        .is_none());
    assert_eq!(state.outbox.len(), 1);
}

#[tokio::test]
async fn dev_workspace_deletion_purges_task_session_receipts() {
    let service = DevWorkspaceService::new("user-1");
    let payload = create_payload("task-session-delete");
    let created = service
        .create_task_session("user-1", "tenant-1", "project-1", payload.clone())
        .await
        .unwrap();
    let workspace_id = created.workspace["id"].as_str().unwrap().to_string();

    service
        .delete_workspace("user-1", "tenant-1", "project-1", &workspace_id)
        .await
        .unwrap();
    assert!(service
        .lock_state()
        .unwrap()
        .task_session_receipts
        .is_empty());

    let recreated = service
        .create_task_session("user-1", "tenant-1", "project-1", payload)
        .await
        .unwrap();
    assert!(!recreated.replayed);
    assert_ne!(recreated.workspace["id"], workspace_id);
}

#[test]
fn task_session_capability_contract_declares_atomic_plan_creation() {
    let capability = TaskSessionCapabilitiesView {
        schema_version: 1,
        atomic_creation: true,
        initial_conversation_mode: "workspace",
        initial_plan_mode: "plan",
    };

    assert_eq!(
        serde_json::to_value(capability).unwrap(),
        json!({
            "schema_version": 1,
            "atomic_creation": true,
            "initial_conversation_mode": "workspace",
            "initial_plan_mode": "plan",
        })
    );
}

#[test]
fn task_session_payload_rejects_unknown_fields_and_invalid_enums() {
    let mut value = serde_json::to_value(create_payload("task-session-1")).unwrap();
    value["unexpected"] = json!(true);
    assert!(serde_json::from_value::<CreateTaskSessionPayload>(value).is_err());

    let mut value = serde_json::to_value(create_payload("task-session-2")).unwrap();
    value["workspace"]["unexpected"] = json!(true);
    assert!(serde_json::from_value::<CreateTaskSessionPayload>(value).is_err());

    let mut value = serde_json::to_value(create_payload("task-session-3")).unwrap();
    value["conversation"]["capability_mode"] = json!("semantic_guess");
    assert!(serde_json::from_value::<CreateTaskSessionPayload>(value).is_err());
}
