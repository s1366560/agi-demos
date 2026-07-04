use super::*;
use agistack_parity::assert_parity;
use chrono::{DateTime, Utc};
use serde_json::Value;

fn at(seconds: i64) -> DateTime<Utc> {
    DateTime::<Utc>::from_timestamp(seconds, 123_000_000).expect("test timestamp must be valid")
}

fn sample_channel_config_record() -> ChannelConfigRecord {
    ChannelConfigRecord {
        id: "chan-1".to_string(),
        project_id: "project-1".to_string(),
        channel_type: "feishu".to_string(),
        name: "Feishu Support".to_string(),
        enabled: true,
        connection_mode: "websocket".to_string(),
        app_id: Some("cli_aabbcc".to_string()),
        webhook_url: Some("https://example.test/hook".to_string()),
        webhook_port: Some(443),
        webhook_path: Some("/webhook/feishu".to_string()),
        domain: Some("feishu".to_string()),
        extra_settings: Some(json!({
            "bot": {
                "token": "encrypted-token",
                "locale": "zh-CN"
            },
            "theme": "default"
        })),
        dm_policy: "open".to_string(),
        group_policy: "allowlist".to_string(),
        allow_from: Some(json!(["ou_user_1"])),
        group_allow_from: Some(json!(["oc_chat_1"])),
        rate_limit_per_minute: 30,
        status: "connected".to_string(),
        last_error: None,
        description: Some("primary project channel".to_string()),
        created_at: at(1_700_000_000),
        updated_at: Some(at(1_700_000_060)),
    }
}

fn sample_status_record() -> ChannelStatusRecord {
    ChannelStatusRecord {
        config_id: "chan-1".to_string(),
        project_id: "project-1".to_string(),
        channel_type: "feishu".to_string(),
        status: "connected".to_string(),
        connected: true,
        last_error: None,
    }
}

#[test]
fn channel_config_response_matches_golden_and_masks_extra_secrets() {
    let actual = serde_json::to_value(ChannelConfigView::from(sample_channel_config_record()))
        .expect("channel config serializes");
    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/channel_config_response.json"
    ))
    .expect("golden parses");
    assert_parity(&golden, &actual);
}

#[test]
fn channel_config_list_matches_golden() {
    let actual = serde_json::to_value(ChannelConfigListView {
        items: vec![ChannelConfigView::from(sample_channel_config_record())],
        total: 1,
    })
    .expect("channel config list serializes");
    let golden: Value =
        serde_json::from_str(include_str!("../../tests/golden/channel_config_list.json"))
            .expect("golden parses");
    assert_parity(&golden, &actual);
}

#[test]
fn channel_status_matches_golden() {
    let actual = serde_json::to_value(ChannelStatusView::from(sample_status_record()))
        .expect("channel status serializes");
    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/channel_status_response.json"
    ))
    .expect("golden parses");
    assert_parity(&golden, &actual);
}

#[test]
fn channel_config_query_rejects_out_of_range_pagination() {
    let low = ChannelConfigQuery {
        channel_type: None,
        enabled_only: false,
        limit: Some(0),
        offset: Some(0),
    };
    assert_eq!(
        low.validated().expect_err("limit=0 rejected").status,
        StatusCode::UNPROCESSABLE_ENTITY
    );

    let negative_offset = ChannelConfigQuery {
        channel_type: None,
        enabled_only: false,
        limit: Some(100),
        offset: Some(-1),
    };
    assert_eq!(
        negative_offset
            .validated()
            .expect_err("negative offset rejected")
            .status,
        StatusCode::UNPROCESSABLE_ENTITY
    );
}

#[tokio::test]
async fn dev_channel_service_lists_empty_configs_and_returns_not_found_for_detail() {
    let service = DevChannelService::new();
    let raw_query = ChannelConfigQuery {
        channel_type: Some(" ".to_string()),
        enabled_only: true,
        limit: None,
        offset: None,
    };
    let query = raw_query.validated().expect("default query is valid");

    let list = service
        .list_project_configs("dev-user", "project-1", query)
        .await
        .expect("dev list succeeds");
    assert!(list.items.is_empty());
    assert_eq!(list.total, 0);

    let err = service
        .get_config("dev-user", "missing")
        .await
        .expect_err("dev detail is missing");
    assert_eq!(err.status, StatusCode::NOT_FOUND);
}
