use axum::Router;
use chrono::{DateTime, Utc};
use serde_json::Value;

use agistack_adapters_postgres::TenantSkillConfigRecord;

use super::*;
use crate::AppState;

fn sample_config_record() -> TenantSkillConfigRecord {
    let at = DateTime::<Utc>::from_timestamp(1_700_000_000, 0)
        .expect("sample tenant skill config timestamp must be valid");
    TenantSkillConfigRecord {
        id: "33333333-3333-4333-8333-333333333333".to_string(),
        tenant_id: "tenant-1".to_string(),
        system_skill_name: "code-review".to_string(),
        action: "override".to_string(),
        override_skill_id: Some("skill-override-1".to_string()),
        created_at: at,
        updated_at: Some(at),
    }
}

#[test]
fn tenant_skill_config_response_matches_golden() {
    let actual = serde_json::to_value(TenantSkillConfigView::from(sample_config_record()))
        .expect("tenant skill config response must serialize");
    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/tenant_skill_config_response.json"
    ))
    .expect("tenant skill config response golden must be valid JSON");
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn tenant_skill_config_list_matches_golden() {
    let actual = serde_json::to_value(TenantSkillConfigListView {
        configs: vec![TenantSkillConfigView::from(sample_config_record())],
        total: 1,
    })
    .expect("tenant skill config list must serialize");
    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/tenant_skill_config_list.json"
    ))
    .expect("tenant skill config list golden must be valid JSON");
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn tenant_skill_status_matches_goldens() {
    let actual = serde_json::to_value(skill_status_view(
        "code-review",
        Some(sample_config_record()),
    ))
    .expect("tenant skill status override response must serialize");
    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/tenant_skill_config_status_overridden.json"
    ))
    .expect("tenant skill status overridden golden must be valid JSON");
    agistack_parity::assert_parity(&golden, &actual);

    let actual = serde_json::to_value(skill_status_view("code-review", None))
        .expect("tenant skill status enabled response must serialize");
    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/tenant_skill_config_status_enabled.json"
    ))
    .expect("tenant skill status enabled golden must be valid JSON");
    agistack_parity::assert_parity(&golden, &actual);
}

#[tokio::test]
async fn dev_service_disable_override_enable_and_delete_roundtrip() {
    let service = DevTenantSkillConfigService::new("tenant-1")
        .with_override_skill("skill-override-1")
        .expect("dev override skill fixture must be accepted");

    let disabled = service
        .disable_skill(
            "u1",
            Some("tenant-1"),
            SystemSkillPayload {
                system_skill_name: "code-review".to_string(),
            },
        )
        .await
        .expect("dev disable must succeed");
    assert_eq!(disabled.action, "disable");
    assert_eq!(disabled.override_skill_id, None);

    let overridden = service
        .override_skill(
            "u1",
            Some("tenant-1"),
            OverrideSkillPayload {
                system_skill_name: "code-review".to_string(),
                override_skill_id: "skill-override-1".to_string(),
            },
        )
        .await
        .expect("dev override must succeed");
    assert_eq!(overridden.action, "override");
    assert_eq!(
        overridden.override_skill_id.as_deref(),
        Some("skill-override-1")
    );

    let status = service
        .skill_status("u1", Some("tenant-1"), "code-review")
        .await
        .expect("dev status after override must succeed");
    assert_eq!(status.status, "overridden");

    service
        .enable_skill(
            "u1",
            Some("tenant-1"),
            SystemSkillPayload {
                system_skill_name: "code-review".to_string(),
            },
        )
        .await
        .expect("dev enable must succeed");
    let status = service
        .skill_status("u1", Some("tenant-1"), "code-review")
        .await
        .expect("dev status after enable must succeed");
    assert_eq!(status.status, "enabled");

    let missing = service
        .delete_config("u1", Some("tenant-1"), "code-review")
        .await;
    assert!(matches!(
        missing,
        Err(TenantSkillConfigApiError {
            status: StatusCode::NOT_FOUND,
            ..
        })
    ));
}

#[test]
fn tenant_skill_config_router_builds() {
    let _router: Router<AppState> = router();
}
