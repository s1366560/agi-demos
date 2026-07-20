use super::plan_snapshot::build_plan_snapshot;
use super::*;
use agistack_parity::compare;
use axum::Router;
use serde::Serialize;

fn canonical_workspace() -> WorkspaceRecord {
    WorkspaceRecord {
        id: "ws-00000000-0000-4000-8000-000000000001".to_string(),
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        name: "Core Workspace".to_string(),
        description: Some("Shared P6 surface".to_string()),
        created_by: "user-1".to_string(),
        is_archived: false,
        metadata_json: json!({
            "workspace_use_case": "programming",
            "workspace_type": "software_development",
            "collaboration_mode": "multi_agent_shared",
            "agent_conversation_mode": "multi_agent_shared",
            "autonomy_profile": {"workspace_type": "software_development"}
        }),
        office_status: "inactive".to_string(),
        hex_layout_config_json: json!({}),
        default_blocking_categories_json: Vec::new(),
        created_at: "2026-01-02T03:04:05Z".parse().unwrap(),
        updated_at: None,
    }
}

fn assert_golden<T: Serialize>(actual: &T, golden: Value) {
    let actual = serde_json::to_value(actual).unwrap();
    let report = compare(&golden, &actual);
    assert!(report.is_match(), "{report:#?}\nactual={actual:#}");
}

mod accept_review;
mod autonomy;
mod chat_mentions;
mod goldens;
mod my_work;
mod task_session;
mod workspace_lifecycle;

#[test]
fn workspace_router_builds() {
    let _router: Router<AppState> = router();
}
