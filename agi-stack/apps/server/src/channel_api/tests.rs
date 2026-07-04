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

fn sample_outbox_record() -> ChannelOutboxRecord {
    ChannelOutboxRecord {
        id: "outbox-1".to_string(),
        channel_config_id: "chan-1".to_string(),
        conversation_id: "conv-1".to_string(),
        chat_id: "oc_chat_1".to_string(),
        status: "failed".to_string(),
        attempt_count: 2,
        max_attempts: 3,
        sent_channel_message_id: None,
        last_error: Some("rate limited".to_string()),
        next_retry_at: Some(at(1_700_000_120)),
        created_at: at(1_700_000_000),
        updated_at: Some(at(1_700_000_060)),
    }
}

fn sample_session_binding_record() -> ChannelSessionBindingRecord {
    ChannelSessionBindingRecord {
        id: "binding-1".to_string(),
        channel_config_id: "chan-1".to_string(),
        conversation_id: "conv-1".to_string(),
        channel_type: "feishu".to_string(),
        chat_id: "oc_chat_1".to_string(),
        chat_type: "group".to_string(),
        thread_id: Some("thread-1".to_string()),
        topic_id: None,
        session_key: "feishu:chan-1:group:oc_chat_1".to_string(),
        created_at: at(1_700_000_000),
        updated_at: Some(at(1_700_000_060)),
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
fn channel_outbox_list_matches_golden() {
    let actual = serde_json::to_value(ChannelOutboxListView {
        items: vec![ChannelOutboxItemView::from(sample_outbox_record())],
        total: 1,
    })
    .expect("channel outbox list serializes");
    let golden: Value =
        serde_json::from_str(include_str!("../../tests/golden/channel_outbox_list.json"))
            .expect("golden parses");
    assert_parity(&golden, &actual);
}

#[test]
fn channel_session_binding_list_matches_golden() {
    let actual = serde_json::to_value(ChannelSessionBindingListView {
        items: vec![ChannelSessionBindingItemView::from(
            sample_session_binding_record(),
        )],
        total: 1,
    })
    .expect("channel session binding list serializes");
    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/channel_session_binding_list.json"
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

#[test]
fn channel_outbox_query_rejects_invalid_status_and_pagination() {
    let invalid_status = ChannelOutboxQuery {
        status_filter: Some("queued".to_string()),
        limit: Some(50),
        offset: Some(0),
    };
    assert_eq!(
        invalid_status
            .validated()
            .expect_err("unsupported status rejected")
            .status,
        StatusCode::UNPROCESSABLE_ENTITY
    );

    let high_limit = ChannelOutboxQuery {
        status_filter: Some("pending".to_string()),
        limit: Some(201),
        offset: Some(0),
    };
    assert_eq!(
        high_limit
            .validated()
            .expect_err("limit above max rejected")
            .status,
        StatusCode::UNPROCESSABLE_ENTITY
    );
}

#[test]
fn channel_page_query_rejects_out_of_range_pagination() {
    let negative_offset = ChannelPageQueryParams {
        limit: Some(50),
        offset: Some(-1),
    };
    assert_eq!(
        negative_offset
            .validated(200)
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

    let raw_outbox_query = ChannelOutboxQuery {
        status_filter: Some("failed".to_string()),
        limit: None,
        offset: None,
    };
    let outbox_query = raw_outbox_query.validated().expect("outbox query is valid");
    let outbox = service
        .list_project_outbox("dev-user", "project-1", outbox_query)
        .await
        .expect("dev outbox list succeeds");
    assert!(outbox.items.is_empty());
    assert_eq!(outbox.total, 0);

    let binding_query = ChannelPageQueryParams {
        limit: None,
        offset: None,
    }
    .validated(200)
    .expect("binding query is valid");
    let bindings = service
        .list_project_session_bindings("dev-user", "project-1", binding_query)
        .await
        .expect("dev session binding list succeeds");
    assert!(bindings.items.is_empty());
    assert_eq!(bindings.total, 0);
}
