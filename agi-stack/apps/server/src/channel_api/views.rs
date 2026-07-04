use chrono::{DateTime, Utc};
use serde::Serialize;
use serde_json::{Map, Value};

use agistack_adapters_postgres::{
    ChannelConfigRecord, ChannelOutboxRecord, ChannelSessionBindingRecord, ChannelStatusRecord,
};

#[derive(Debug, Clone, Serialize)]
pub(crate) struct ChannelConfigView {
    id: String,
    project_id: String,
    channel_type: String,
    name: String,
    enabled: bool,
    connection_mode: String,
    app_id: Option<String>,
    webhook_url: Option<String>,
    webhook_port: Option<i32>,
    webhook_path: Option<String>,
    domain: Option<String>,
    extra_settings: Option<Value>,
    dm_policy: String,
    group_policy: String,
    allow_from: Option<Value>,
    group_allow_from: Option<Value>,
    rate_limit_per_minute: i32,
    status: String,
    last_error: Option<String>,
    description: Option<String>,
    created_at: String,
    updated_at: Option<String>,
}

impl From<ChannelConfigRecord> for ChannelConfigView {
    fn from(record: ChannelConfigRecord) -> Self {
        Self {
            id: record.id,
            project_id: record.project_id,
            channel_type: record.channel_type,
            name: record.name,
            enabled: record.enabled,
            connection_mode: record.connection_mode,
            app_id: record.app_id,
            webhook_url: record.webhook_url,
            webhook_port: record.webhook_port,
            webhook_path: record.webhook_path,
            domain: record.domain,
            extra_settings: mask_extra_settings(record.extra_settings),
            dm_policy: record.dm_policy,
            group_policy: record.group_policy,
            allow_from: record.allow_from,
            group_allow_from: record.group_allow_from,
            rate_limit_per_minute: record.rate_limit_per_minute,
            status: record.status,
            last_error: record.last_error,
            description: record.description,
            created_at: iso8601(record.created_at),
            updated_at: record.updated_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct ChannelConfigListView {
    pub(crate) items: Vec<ChannelConfigView>,
    pub(crate) total: i64,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct ChannelStatusView {
    config_id: String,
    project_id: String,
    channel_type: String,
    status: String,
    connected: bool,
    last_heartbeat: Option<String>,
    last_error: Option<String>,
    reconnect_attempts: i64,
}

impl From<ChannelStatusRecord> for ChannelStatusView {
    fn from(record: ChannelStatusRecord) -> Self {
        Self {
            config_id: record.config_id,
            project_id: record.project_id,
            channel_type: record.channel_type,
            status: record.status,
            connected: record.connected,
            last_heartbeat: None,
            last_error: record.last_error,
            reconnect_attempts: 0,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct ChannelOutboxItemView {
    id: String,
    channel_config_id: String,
    conversation_id: String,
    chat_id: String,
    status: String,
    attempt_count: i32,
    max_attempts: i32,
    sent_channel_message_id: Option<String>,
    last_error: Option<String>,
    next_retry_at: Option<String>,
    created_at: String,
    updated_at: Option<String>,
}

impl From<ChannelOutboxRecord> for ChannelOutboxItemView {
    fn from(record: ChannelOutboxRecord) -> Self {
        Self {
            id: record.id,
            channel_config_id: record.channel_config_id,
            conversation_id: record.conversation_id,
            chat_id: record.chat_id,
            status: record.status,
            attempt_count: record.attempt_count,
            max_attempts: record.max_attempts,
            sent_channel_message_id: record.sent_channel_message_id,
            last_error: record.last_error,
            next_retry_at: record.next_retry_at.map(iso8601),
            created_at: iso8601(record.created_at),
            updated_at: record.updated_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct ChannelOutboxListView {
    pub(crate) items: Vec<ChannelOutboxItemView>,
    pub(crate) total: i64,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct ChannelSessionBindingItemView {
    id: String,
    channel_config_id: String,
    conversation_id: String,
    channel_type: String,
    chat_id: String,
    chat_type: String,
    thread_id: Option<String>,
    topic_id: Option<String>,
    session_key: String,
    created_at: String,
    updated_at: Option<String>,
}

impl From<ChannelSessionBindingRecord> for ChannelSessionBindingItemView {
    fn from(record: ChannelSessionBindingRecord) -> Self {
        Self {
            id: record.id,
            channel_config_id: record.channel_config_id,
            conversation_id: record.conversation_id,
            channel_type: record.channel_type,
            chat_id: record.chat_id,
            chat_type: record.chat_type,
            thread_id: record.thread_id,
            topic_id: record.topic_id,
            session_key: record.session_key,
            created_at: iso8601(record.created_at),
            updated_at: record.updated_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct ChannelSessionBindingListView {
    pub(crate) items: Vec<ChannelSessionBindingItemView>,
    pub(crate) total: i64,
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(chrono::SecondsFormat::Micros, true)
}

fn mask_extra_settings(settings: Option<Value>) -> Option<Value> {
    settings.map(mask_secret_value)
}

fn mask_secret_value(value: Value) -> Value {
    match value {
        Value::Object(entries) => Value::Object(mask_secret_object(entries)),
        Value::Array(items) => Value::Array(items.into_iter().map(mask_secret_value).collect()),
        other => other,
    }
}

fn mask_secret_object(entries: Map<String, Value>) -> Map<String, Value> {
    entries
        .into_iter()
        .map(|(key, value)| {
            let value = if is_secret_setting_key(&key) {
                Value::String("__MEMSTACK_SECRET_UNCHANGED__".to_string())
            } else {
                mask_secret_value(value)
            };
            (key, value)
        })
        .collect()
}

fn is_secret_setting_key(key: &str) -> bool {
    let normalized = key.to_ascii_lowercase();
    matches!(
        normalized.as_str(),
        "api_key"
            | "app_secret"
            | "access_token"
            | "encrypt_key"
            | "password"
            | "refresh_token"
            | "secret"
            | "token"
            | "verification_token"
    )
}
