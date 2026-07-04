use agistack_adapters_postgres::{ShareMemoryRecord, ShareRecord};
use axum::http::StatusCode;
use serde_json::{json, Value};

use super::*;

fn sample_share() -> ShareRecord {
    ShareRecord {
        id: "11111111-1111-4111-8111-111111111111".into(),
        memory_id: "22222222-2222-4222-8222-222222222222".into(),
        share_token: Some("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into()),
        shared_with_user_id: None,
        shared_with_project_id: None,
        permissions: json!({"view": true, "edit": false}),
        shared_by: "33333333-3333-4333-8333-333333333333".into(),
        created_at: sample_dt(),
        expires_at: None,
        access_count: 0,
    }
}

fn sample_memory() -> ShareMemoryRecord {
    ShareMemoryRecord {
        id: "22222222-2222-4222-8222-222222222222".into(),
        project_id: "44444444-4444-4444-8444-444444444444".into(),
        title: "Shared memory".into(),
        content: "Rust serves a Python-compatible share link.".into(),
        author_id: "33333333-3333-4333-8333-333333333333".into(),
        tags: json!(["rust", "share"]),
        created_at: sample_dt(),
        updated_at: None,
    }
}

#[test]
fn share_response_matches_golden() {
    let golden: Value =
        serde_json::from_str(include_str!("../../tests/golden/share_response.json"))
            .expect("share response golden must be valid JSON");
    let actual = serde_json::to_value(ShareView::from(sample_share()))
        .expect("share response must serialize");
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn share_list_matches_golden() {
    let golden: Value = serde_json::from_str(include_str!("../../tests/golden/share_list.json"))
        .expect("share list golden must be valid JSON");
    let actual = serde_json::to_value(ShareList::from_records(vec![sample_share()]))
        .expect("share list must serialize");
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn shared_memory_matches_golden() {
    let golden: Value = serde_json::from_str(include_str!("../../tests/golden/shared_memory.json"))
        .expect("shared memory golden must be valid JSON");
    let actual = serde_json::to_value(shared_memory_view(sample_memory(), sample_share()))
        .expect("shared memory must serialize");
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn target_validation_matches_python_errors() {
    let req: ShareCreatePayload = serde_json::from_value(json!({"target_type": "team"}))
        .expect("test request must deserialize");
    let err = validate_target(&req).expect_err("invalid target type should fail");
    assert_eq!(err.status, StatusCode::BAD_REQUEST);
    assert_eq!(err.detail, "target_type must be 'user' or 'project'");

    let req: ShareCreatePayload = serde_json::from_value(json!({"target_type": "user"}))
        .expect("test request must deserialize");
    let err = validate_target(&req).expect_err("missing permission should fail");
    assert_eq!(err.detail, "permission_level must be 'view' or 'edit'");

    let req: ShareCreatePayload =
        serde_json::from_value(json!({"target_type": "user", "permission_level": "view"}))
            .expect("test request must deserialize");
    let err = validate_target(&req).expect_err("missing target id should fail");
    assert_eq!(err.detail, "target_id is required");
}

#[test]
fn share_can_view_requires_explicit_true() {
    assert!(share_can_view(&json!({"view": true})));
    assert!(!share_can_view(&json!({"view": false})));
    assert!(!share_can_view(&json!({"view": "true"})));
    assert!(!share_can_view(&json!(["view"])));
}
