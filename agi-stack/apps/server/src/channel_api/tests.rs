use super::views::{ChannelOutboxItemView, ChannelSessionBindingItemView};
use super::*;
use agistack_adapters_postgres::{
    ChannelConfigRecord, ChannelObservabilitySummaryRecord, ChannelOutboxRecord,
    ChannelSessionBindingRecord, ChannelStatusRecord, ChannelWebhookEventRecord,
    ChannelWebhookIngressRecord,
};
use agistack_parity::assert_parity;
use axum::http::StatusCode;
use chrono::{DateTime, Utc};
use serde_json::{json, Value};

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

fn sample_disconnected_status_record() -> ChannelStatusRecord {
    ChannelStatusRecord {
        config_id: "chan-1".to_string(),
        project_id: "project-1".to_string(),
        channel_type: "feishu".to_string(),
        status: "disconnected".to_string(),
        connected: false,
        last_error: None,
    }
}

fn sample_outbox_record() -> ChannelOutboxRecord {
    ChannelOutboxRecord {
        id: "outbox-1".to_string(),
        project_id: "project-1".to_string(),
        channel_config_id: "chan-1".to_string(),
        channel_type: Some("feishu".to_string()),
        webhook_url: Some("https://example.test/hook".to_string()),
        domain: Some("feishu".to_string()),
        conversation_id: "conv-1".to_string(),
        chat_id: "oc_chat_1".to_string(),
        content_text: "hello from workspace".to_string(),
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

fn sample_observability_summary_record() -> ChannelObservabilitySummaryRecord {
    ChannelObservabilitySummaryRecord {
        project_id: "project-1".to_string(),
        session_bindings_total: 1,
        outbox_total: 2,
        outbox_by_status: [
            ("failed".to_string(), 1_i64),
            ("pending".to_string(), 1_i64),
        ]
        .into_iter()
        .collect(),
        latest_delivery_error: Some("rate limited".to_string()),
    }
}

fn sample_webhook_ingress_record() -> ChannelWebhookIngressRecord {
    ChannelWebhookIngressRecord {
        inserted: true,
        event: ChannelWebhookEventRecord {
            id: "channel_webhook_11111111-1111-5111-8111-111111111111".to_string(),
            project_id: "project-1".to_string(),
            channel_config_id: "chan-1".to_string(),
            channel_type: "feishu".to_string(),
            idempotency_key: "evt-1".to_string(),
            headers_json: json!({"x-lark-request-id": "req-1"}),
            raw_event_json: json!({"event": {"header": {"event_id": "evt-1"}}}),
            normalized_event_json: json!({
                "provider": "feishu",
                "schema_version": 1,
                "idempotency_key": "evt-1",
                "event_id": "evt-1"
            }),
            status: "received".to_string(),
            route_error: None,
            route_session_key: None,
            route_binding_id: None,
            route_conversation_id: None,
            received_at: at(1_700_000_000),
            routed_at: None,
        },
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
fn channel_disconnected_status_matches_golden() {
    let actual = serde_json::to_value(ChannelStatusView::from(sample_disconnected_status_record()))
        .expect("channel disconnected status serializes");
    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/channel_disconnected_status_response.json"
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
fn channel_observability_summary_matches_golden() {
    let actual = serde_json::to_value(ChannelObservabilitySummaryView::from(
        sample_observability_summary_record(),
    ))
    .expect("channel observability summary serializes");
    let golden: Value = serde_json::from_str(include_str!(
        "../../tests/golden/channel_observability_summary.json"
    ))
    .expect("golden parses");
    assert_parity(&golden, &actual);
}

#[test]
fn channel_webhook_challenge_matches_golden() {
    let actual = serde_json::to_value(ChannelWebhookChallengeView {
        challenge: "challenge-value".to_string(),
    })
    .expect("channel webhook challenge serializes");
    let golden = serde_json::from_str(include_str!(
        "../../tests/golden/channel_webhook_challenge.json"
    ))
    .expect("golden parses");
    assert_parity(&golden, &actual);
}

#[test]
fn channel_webhook_ingress_matches_golden() {
    let actual = serde_json::to_value(ChannelWebhookIngressView::from(
        sample_webhook_ingress_record(),
    ))
    .expect("channel webhook ingress serializes");
    let golden = serde_json::from_str(include_str!(
        "../../tests/golden/channel_webhook_ingress.json"
    ))
    .expect("golden parses");
    assert_parity(&golden, &actual);
}

#[test]
fn channel_webhook_event_payload_routes_normalized_message_to_project_stream() {
    let view = ChannelWebhookIngressView::from(sample_webhook_ingress_record());
    let payload = super::routes::channel_webhook_event_payload(&view);

    assert_eq!(payload["type"], "channel_webhook_message_received");
    assert_eq!(payload["project_id"], "project-1");
    assert_eq!(payload["channel_config_id"], "chan-1");
    assert_eq!(
        payload["channel_event_id"],
        "channel_webhook_11111111-1111-5111-8111-111111111111"
    );
    assert_eq!(payload["idempotency_key"], "evt-1");
    assert_eq!(payload["routing_key"], "channel:chan-1:evt-1");
    assert_eq!(payload["normalized_event"]["provider"], "feishu");
}

#[test]
fn channel_webhook_session_route_matches_python_session_key_shape() {
    let mut record = sample_webhook_ingress_record().event;
    record.normalized_event_json = json!({
        "provider": "feishu",
        "schema_version": 1,
        "chat_id": "oc_chat_1",
        "chat_type": "group",
        "topic_id": "topic-1",
        "thread_id": "thread-1"
    });

    let route = super::service::channel_webhook_session_route(&record);

    assert_eq!(
        route.session_key.as_deref(),
        Some("project:project-1:channel:feishu:config:chan-1:group:oc_chat_1:topic:topic-1:thread:thread-1")
    );
    assert_eq!(route.error, None);
}

#[test]
fn channel_webhook_session_create_record_matches_python_conversation_shape() {
    let mut record = sample_webhook_ingress_record().event;
    record.normalized_event_json = json!({
        "provider": "feishu",
        "schema_version": 1,
        "chat_id": "ou_dm_chat",
        "chat_type": "p2p",
        "thread_id": "thread-1",
        "sender_open_id": "ou_sender_1"
    });

    let route = super::service::channel_webhook_session_route(&record);
    let create_record = super::service::channel_webhook_session_create_record(&record, &route)
        .expect("valid route produces create record");

    assert_eq!(
        create_record.session_key,
        "project:project-1:channel:feishu:config:chan-1:dm:ou_dm_chat:thread:thread-1"
    );
    assert_eq!(create_record.chat_id, "ou_dm_chat");
    assert_eq!(create_record.chat_type, "p2p");
    assert_eq!(create_record.thread_id.as_deref(), Some("thread-1"));
    assert_eq!(
        create_record.conversation_title,
        "Feishu: Chat with ou_sender_1"
    );
    assert_eq!(
        create_record.metadata_json["channel_session_key"],
        create_record.session_key
    );
    assert_eq!(create_record.metadata_json["channel_type"], "feishu");
    assert_eq!(create_record.metadata_json["chat_type"], "p2p");
    assert_eq!(create_record.metadata_json["sender_id"], "ou_sender_1");
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

    let summary = service
        .get_project_observability_summary("dev-user", "project-1")
        .await
        .expect("dev observability summary succeeds");
    let summary_json = serde_json::to_value(summary).expect("dev summary serializes");
    assert_eq!(summary_json["project_id"], "project-1");
    assert_eq!(summary_json["session_bindings_total"], 0);
    assert_eq!(summary_json["outbox_total"], 0);
    assert_eq!(summary_json["active_connections"], 0);
    assert_eq!(summary_json["connected_config_ids"], json!([]));
}
