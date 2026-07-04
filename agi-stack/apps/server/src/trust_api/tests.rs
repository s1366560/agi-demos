use agistack_adapters_postgres::{DecisionRecordRecord, TrustPolicyRecord};
use axum::http::StatusCode;
use chrono::{DateTime, Utc};
use serde_json::{json, Value};

use super::*;

fn sample_dt() -> DateTime<Utc> {
    DateTime::<Utc>::from_timestamp_millis(1_700_000_000_000)
        .expect("sample timestamp must be valid")
}

fn sample_policy() -> TrustPolicyRecord {
    TrustPolicyRecord {
        id: "11111111-1111-4111-8111-111111111111".into(),
        tenant_id: "22222222-2222-4222-8222-222222222222".into(),
        workspace_id: "33333333-3333-4333-8333-333333333333".into(),
        agent_instance_id: "44444444-4444-4444-8444-444444444444".into(),
        action_type: "terminal.execute".into(),
        granted_by: "55555555-5555-4555-8555-555555555555".into(),
        grant_type: "always".into(),
        created_at: sample_dt(),
        deleted_at: None,
    }
}

fn sample_decision() -> DecisionRecordRecord {
    DecisionRecordRecord {
        id: "66666666-6666-4666-8666-666666666666".into(),
        tenant_id: "22222222-2222-4222-8222-222222222222".into(),
        workspace_id: "33333333-3333-4333-8333-333333333333".into(),
        agent_instance_id: "44444444-4444-4444-8444-444444444444".into(),
        decision_type: "terminal.execute".into(),
        context_summary: Some("Agent wants to run a shell command.".into()),
        proposal: json!({"command": "cargo test", "cwd": "/workspace"}),
        outcome: "pending".into(),
        reviewer_id: None,
        review_type: None,
        review_comment: None,
        resolved_at: None,
        created_at: sample_dt(),
        updated_at: None,
        deleted_at: None,
    }
}

#[test]
fn trust_policy_response_matches_golden() {
    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/trust_policy_response.json"
    ))
    .expect("trust policy response golden must be valid JSON");
    let actual = serde_json::to_value(TrustPolicyView::from(sample_policy()))
        .expect("trust policy response must serialize");
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn trust_policy_list_matches_golden() {
    let golden: Value =
        serde_json::from_str(include_str!("../../tests/golden/trust_policy_list.json"))
            .expect("trust policy list golden must be valid JSON");
    let actual = serde_json::to_value(TrustPolicyListView {
        items: vec![TrustPolicyView::from(sample_policy())],
    })
    .expect("trust policy list must serialize");
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn trust_check_matches_golden() {
    let golden: Value =
        serde_json::from_str(include_str!("../../tests/golden/trust_check_response.json"))
            .expect("trust check golden must be valid JSON");
    let actual =
        serde_json::to_value(TrustCheckView { trusted: true }).expect("trust check must serialize");
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn decision_record_response_matches_golden() {
    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/decision_record_response.json"
    ))
    .expect("decision record response golden must be valid JSON");
    let actual = serde_json::to_value(DecisionRecordView::from(sample_decision()))
        .expect("decision record response must serialize");
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn decision_record_list_matches_golden() {
    let golden: Value =
        serde_json::from_str(include_str!("../../tests/golden/decision_record_list.json"))
            .expect("decision record list golden must be valid JSON");
    let actual = serde_json::to_value(DecisionRecordListView {
        items: vec![DecisionRecordView::from(sample_decision())],
    })
    .expect("decision record list must serialize");
    agistack_parity::assert_parity(&golden, &actual);
}

#[tokio::test]
async fn dev_resolve_allow_always_creates_policy_and_python_comment() {
    let svc = DevTrustService::new("dev-user");
    let created = svc
        .submit_approval(
            "dev-tenant",
            "dev-user",
            ApprovalRequestCreatePayload {
                workspace_id: "dev-workspace".into(),
                agent_instance_id: "agent-1".into(),
                action_type: "terminal.execute".into(),
                proposal: json!({}),
                context_summary: None,
            },
        )
        .await
        .expect("dev approval creation must succeed");
    let resolved = svc
        .resolve_approval(
            "dev-tenant",
            "dev-user",
            &created.id,
            ApprovalResolvePayload {
                decision: "allow_always".into(),
            },
        )
        .await
        .expect("dev approval resolve must succeed");
    assert_eq!(resolved.outcome, "success");
    assert_eq!(
        resolved.review_comment.as_deref(),
        Some("Allowed always — trust policy created")
    );

    let check = svc
        .check_trust(
            "dev-tenant",
            "dev-user",
            TrustCheckQuery {
                workspace_id: "dev-workspace".into(),
                agent_instance_id: "agent-1".into(),
                action_type: "terminal.execute".into(),
            },
        )
        .await
        .expect("dev trust check must succeed");
    assert!(check.trusted);
}

#[tokio::test]
async fn invalid_resolve_decision_matches_python_404() {
    let svc = DevTrustService::new("dev-user");
    let err = svc
        .resolve_approval(
            "dev-tenant",
            "dev-user",
            "missing",
            ApprovalResolvePayload {
                decision: "bogus".into(),
            },
        )
        .await
        .expect_err("invalid approval resolve should return a 404");
    assert_eq!(err.status, StatusCode::NOT_FOUND);
    assert_eq!(err.detail, "Approval request not found");
}
