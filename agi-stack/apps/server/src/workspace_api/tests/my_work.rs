use super::*;
use agistack_adapters_postgres::{
    ProjectMyWorkHitlAuthorityRecord, ProjectMyWorkWorkspaceAttemptRecord,
};
use chrono::TimeZone;

fn ts(year: i32, month: u32, day: u32, hour: u32, minute: u32, second: u32) -> DateTime<Utc> {
    Utc.with_ymd_and_hms(year, month, day, hour, minute, second)
        .single()
        .expect("valid timestamp")
}

fn attempt(
    authority_id: &str,
    conversation_id: &str,
    status: &str,
    updated_at: Option<DateTime<Utc>>,
) -> ProjectMyWorkWorkspaceAttemptRecord {
    ProjectMyWorkWorkspaceAttemptRecord {
        authority_id: authority_id.to_string(),
        conversation_id: conversation_id.to_string(),
        workspace_id: "workspace-1".to_string(),
        project_id: "project-1".to_string(),
        title: format!("Task {authority_id}"),
        status: status.to_string(),
        attempt_number: 2,
        conversation_agent_config: Some(json!({"capability_mode": "unknown"})),
        workspace_metadata: json!({"capability_mode": "code"}),
        created_at: ts(2026, 7, 15, 7, 58, 0),
        updated_at,
    }
}

fn hitl(
    authority_id: &str,
    conversation_id: &str,
    request_type: &str,
    expires_at: DateTime<Utc>,
) -> ProjectMyWorkHitlAuthorityRecord {
    ProjectMyWorkHitlAuthorityRecord {
        authority_id: authority_id.to_string(),
        request_type: request_type.to_string(),
        conversation_id: conversation_id.to_string(),
        workspace_id: "workspace-1".to_string(),
        project_id: "project-1".to_string(),
        title: format!("Session {conversation_id}"),
        conversation_agent_config: Some(json!({"capability_mode": "work"})),
        request_metadata: None,
        workspace_metadata: json!({}),
        created_at: ts(2026, 7, 15, 7, 59, 0),
        expires_at,
    }
}

#[test]
fn my_work_projection_maps_only_persisted_attention_authorities() {
    let now = ts(2026, 7, 15, 8, 0, 0);
    let response = project_my_work_response(
        "project-1",
        vec![
            attempt("running", "conversation-running", "running", Some(now)),
            attempt(
                "adjudication",
                "conversation-adjudication",
                "awaiting_leader_adjudication",
                None,
            ),
            attempt("blocked", "conversation-blocked", "blocked", Some(now)),
            attempt("accepted", "conversation-accepted", "accepted", Some(now)),
            attempt("unknown", "conversation-unknown", "custom", Some(now)),
        ],
        Vec::new(),
        now,
    );

    assert_eq!(
        response
            .items
            .iter()
            .map(|item| item.authority_id.as_str())
            .collect::<Vec<_>>(),
        vec!["running", "blocked", "adjudication"]
    );
    let running = &response.items[0];
    assert_eq!(running.id, "workspace_attempt:running");
    assert_eq!(
        running.authority_kind,
        MyWorkAuthorityKind::WorkspaceAttempt
    );
    assert_eq!(running.group, MyWorkGroup::Running);
    assert_eq!(running.status, MyWorkStatus::Running);
    assert_eq!(running.required_action, MyWorkRequiredAction::Observe);
    assert_eq!(running.capability_mode, Some(MyWorkCapabilityMode::Code));
    assert_eq!(running.attempt_number, Some(2));
    assert!(running.run_id.is_none());
    assert!(running.revision.is_none());
    assert!(running.permission_profile.is_none());
    assert!(running.environment.is_none());
    assert!(running.last_heartbeat_at.is_none());

    let blocked = &response.items[1];
    assert_eq!(blocked.group, MyWorkGroup::NeedsInput);
    assert_eq!(blocked.status, MyWorkStatus::Failed);
    assert_eq!(
        blocked.required_action,
        MyWorkRequiredAction::InspectFailure
    );
}

#[test]
fn active_hitl_supersedes_attempt_without_text_inference() {
    let now = ts(2026, 7, 15, 8, 0, 0);
    let mut metadata_override = hitl(
        "metadata-permission",
        "conversation-2",
        "decision",
        now + chrono::Duration::minutes(2),
    );
    metadata_override.request_metadata = Some(json!({"hitl_type": "permission"}));
    let response = project_my_work_response(
        "project-1",
        vec![
            attempt("overridden", "conversation-1", "running", Some(now)),
            attempt("visible", "conversation-3", "pending", Some(now)),
            attempt("unsupported", "conversation-4", "running", Some(now)),
        ],
        vec![
            hitl(
                "permission",
                "conversation-1",
                "permission",
                now + chrono::Duration::minutes(1),
            ),
            metadata_override,
            hitl("expired", "conversation-3", "decision", now),
            hitl(
                "unsupported-hitl",
                "conversation-4",
                "custom",
                now + chrono::Duration::minutes(1),
            ),
        ],
        now,
    );

    let by_id = response
        .items
        .iter()
        .map(|item| (item.authority_id.as_str(), item))
        .collect::<std::collections::HashMap<_, _>>();
    assert_eq!(
        by_id
            .keys()
            .copied()
            .collect::<std::collections::HashSet<_>>(),
        std::collections::HashSet::from([
            "permission",
            "metadata-permission",
            "visible",
            "unsupported",
        ])
    );
    let permission = by_id["permission"];
    assert_eq!(permission.authority_kind, MyWorkAuthorityKind::HitlRequest);
    assert_eq!(permission.group, MyWorkGroup::NeedsApproval);
    assert_eq!(permission.status, MyWorkStatus::NeedsApproval);
    assert_eq!(
        permission.required_action,
        MyWorkRequiredAction::ReviewApproval
    );
    assert_eq!(permission.attempt_number, None);
    assert_eq!(
        by_id["metadata-permission"].required_action,
        MyWorkRequiredAction::ReviewApproval
    );
}

#[test]
fn my_work_response_serializes_the_desktop_contract() {
    let now = ts(2026, 7, 15, 8, 0, 0);
    let response = project_my_work_response(
        "project-1",
        vec![attempt("running", "conversation-1", "running", Some(now))],
        Vec::new(),
        now,
    );

    let payload = serde_json::to_value(response).expect("serialize My Work response");
    assert_eq!(payload["project_id"], "project-1");
    assert_eq!(payload["total"], 1);
    assert_eq!(payload["items"][0]["authority_kind"], "workspace_attempt");
    assert_eq!(payload["items"][0]["group"], "running");
    assert_eq!(payload["items"][0]["required_action"], "observe");
    assert_eq!(payload["items"][0]["capability_mode"], "code");
    assert!(payload["items"][0]["run_id"].is_null());
    assert!(payload["items"][0]["revision"].is_null());
    assert!(payload["items"][0]["permission_profile"].is_null());
    assert!(payload["items"][0]["environment"].is_null());
    assert!(payload["items"][0]["last_heartbeat_at"].is_null());
}
