use sqlx::types::chrono::{TimeZone, Utc};

use super::*;
use crate::workspace_repo::{TaskSessionCapabilityMode, TaskSessionConversationRecord};

#[test]
fn task_session_validation_enforces_canonical_hash_and_text() {
    let mut record = sample_record();
    assert!(validate_record(&record).is_ok());

    record.payload_hash = "not-a-sha256".to_string();
    assert_eq!(
        validate_record(&record),
        Err(TaskSessionRepositoryError::InvalidInput)
    );

    record = sample_record();
    record.conversation.title = " title with outer whitespace ".to_string();
    assert_eq!(
        validate_record(&record),
        Err(TaskSessionRepositoryError::InvalidInput)
    );
}

#[test]
fn authorization_queries_lock_tenant_before_project_and_membership() {
    assert_eq!(
        AUTHORIZATION_LOCK_QUERIES.map(|(scope, _)| scope),
        ["tenant", "project", "user_project"]
    );
    assert!(LOCK_TENANT_SCOPE_SQL.contains("FROM tenants"));
    assert!(LOCK_PROJECT_SCOPE_SQL.contains("FROM projects"));
    assert!(LOCK_PROJECT_SCOPE_SQL.contains("tenant_id = $2"));
    assert!(LOCK_PROJECT_MEMBERSHIP_SQL.contains("FROM user_projects"));
    assert!(AUTHORIZATION_LOCK_QUERIES
        .iter()
        .all(|(_, query)| query.ends_with("FOR SHARE")));
}

#[test]
fn receipt_queries_share_one_four_parameter_scope() {
    for query in [LOAD_RECEIPT_SQL, LOCK_RECEIPT_SQL] {
        for parameter in ["$1", "$2", "$3", "$4"] {
            assert_eq!(query.matches(parameter).count(), 1, "query: {query}");
        }
        assert!(!query.contains("$5"), "query: {query}");
    }
    assert!(!LOAD_RECEIPT_SQL.contains("FOR SHARE"));
    assert!(LOCK_RECEIPT_SQL.ends_with("FOR SHARE"));
}

#[test]
fn receipt_snapshot_requires_exact_resource_ids() {
    let snapshot = sample_snapshot();
    let replayed = outcome_from_receipt(
        snapshot.clone(),
        "workspace",
        "conversation",
        "message",
        "tenant",
        "project",
    )
    .expect("matching non-null resource identifiers preserve the response snapshot");
    assert!(replayed.replayed);
    assert_eq!(replayed.workspace, snapshot["workspace"]);

    let mismatch = outcome_from_receipt(
        snapshot,
        "different-workspace",
        "conversation",
        "message",
        "tenant",
        "project",
    );
    assert!(matches!(
        mismatch,
        Err(TaskSessionRepositoryError::Storage(_))
    ));
}

#[test]
fn replay_requires_locked_receipt_to_match_initial_row() {
    let initial = sample_receipt_row();
    let matching = require_unchanged_receipt(&initial, Some(initial.clone()))
        .expect("identical locked receipt is stable");
    assert_eq!(matching, initial);

    let mut changed = initial.clone();
    changed.4 = Json(json!({ "changed": true }));
    assert_eq!(
        require_unchanged_receipt(&initial, Some(changed)),
        Err(TaskSessionRepositoryError::IdempotencyConflict)
    );
    assert_eq!(
        require_unchanged_receipt(&initial, None),
        Err(TaskSessionRepositoryError::IdempotencyConflict)
    );
}

#[test]
fn tombstoned_receipt_is_a_controlled_idempotency_conflict() {
    let mut tombstone = sample_receipt_row();
    tombstone.2 = None;
    tombstone.3 = None;
    tombstone.4 = Json(json!({ "tombstone": true }));
    assert_eq!(
        require_replayable_receipt(tombstone),
        Err(TaskSessionRepositoryError::IdempotencyConflict)
    );

    let live = require_replayable_receipt(sample_receipt_row())
        .expect("a live receipt remains replayable");
    assert_eq!(live.2, "conversation");
    assert_eq!(live.3, "message");
}

#[test]
fn project_write_access_accepts_member_and_editor_but_rejects_viewer() {
    for role in ["owner", "admin", "member", "editor"] {
        assert!(has_project_write_role(&[role.to_string()]), "role: {role}");
    }
    for role in ["viewer", "unknown"] {
        assert!(!has_project_write_role(&[role.to_string()]), "role: {role}");
    }
    assert!(has_project_write_role(&[
        "viewer".to_string(),
        "editor".to_string(),
    ]));
}

#[test]
fn workspace_write_access_rejects_member_and_viewer() {
    for role in ["owner", "admin", "editor"] {
        assert!(
            has_workspace_write_role(&[role.to_string()]),
            "role: {role}"
        );
    }
    for role in ["member", "viewer", "unknown"] {
        assert!(
            !has_workspace_write_role(&[role.to_string()]),
            "role: {role}"
        );
    }
}

#[test]
fn repository_error_display_redacts_storage_details() {
    let error = TaskSessionRepositoryError::Storage("sensitive database detail".to_string());
    assert_eq!(error.to_string(), "task session storage failed");
}

fn sample_record() -> CreateTaskSessionRecord {
    let created_at = Utc
        .with_ymd_and_hms(2026, 7, 19, 0, 0, 0)
        .single()
        .expect("valid test timestamp");
    CreateTaskSessionRecord {
        receipt_id: "receipt".to_string(),
        actor_user_id: "user".to_string(),
        tenant_id: "tenant".to_string(),
        project_id: "project".to_string(),
        idempotency_key: "key".to_string(),
        payload_hash: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            .to_string(),
        workspace: TaskSessionWorkspaceRecord::Create {
            workspace: Box::new(WorkspaceRecord {
                id: "workspace".to_string(),
                tenant_id: "tenant".to_string(),
                project_id: "project".to_string(),
                name: "Workspace".to_string(),
                description: None,
                created_by: "user".to_string(),
                is_archived: false,
                metadata_json: json!({}),
                office_status: "inactive".to_string(),
                hex_layout_config_json: json!({}),
                default_blocking_categories_json: Vec::new(),
                created_at,
                updated_at: None,
            }),
            owner_member_id: "member".to_string(),
        },
        conversation: TaskSessionConversationRecord {
            id: "conversation".to_string(),
            title: "Conversation".to_string(),
            capability_mode: TaskSessionCapabilityMode::Work,
        },
        initial_message_id: "message".to_string(),
        initial_message_content: "Start work".to_string(),
        blackboard_outbox_id: "outbox".to_string(),
        created_at,
    }
}

fn sample_snapshot() -> Value {
    json!({
        "workspace": {
            "id": "workspace",
            "tenant_id": "tenant",
            "project_id": "project",
        },
        "conversation": {
            "id": "conversation",
            "tenant_id": "tenant",
            "project_id": "project",
            "workspace_id": "workspace",
            "conversation_mode": "workspace",
            "current_mode": "plan",
            "agent_config": { "selected_agent_id": "builtin:all-access" },
        },
        "initial_message": {
            "id": "message",
            "workspace_id": "workspace",
            "sender_type": "human",
        },
    })
}

fn sample_receipt_row() -> ReceiptRow {
    (
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_string(),
        "workspace".to_string(),
        Some("conversation".to_string()),
        Some("message".to_string()),
        Json(sample_snapshot()),
    )
}
