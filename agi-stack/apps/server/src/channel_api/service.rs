use std::sync::Arc;

use async_trait::async_trait;
use serde_json::{json, Map, Value};
use uuid::Uuid;

use agistack_adapters_postgres::{
    ChannelConfigListQuery, ChannelOutboxListQuery, ChannelPageQuery,
    ChannelWebhookEventInsertRecord, ChannelWebhookEventRecord, ChannelWebhookSessionCreateRecord,
    PgChannelRepository,
};

use super::{
    error::ChannelApiError,
    queries::{
        ValidatedChannelConfigQuery, ValidatedChannelOutboxQuery, ValidatedChannelPageQuery,
    },
    views::{
        ChannelConfigListView, ChannelConfigView, ChannelObservabilitySummaryView,
        ChannelOutboxItemView, ChannelOutboxListView, ChannelSessionBindingItemView,
        ChannelSessionBindingListView, ChannelStatusView, ChannelWebhookChallengeView,
        ChannelWebhookIngressView,
    },
    webhook_verifier::{
        feishu_webhook_idempotency_key, verify_feishu_webhook_request, FeishuWebhookHeaders,
        FeishuWebhookSecrets, FeishuWebhookVerification, FeishuWebhookVerificationError,
    },
};

pub(crate) type SharedChannels = Arc<dyn ChannelService>;

#[async_trait]
pub(crate) trait ChannelService: Send + Sync {
    async fn list_project_configs(
        &self,
        user_id: &str,
        project_id: &str,
        query: ValidatedChannelConfigQuery<'_>,
    ) -> Result<ChannelConfigListView, ChannelApiError>;

    async fn get_config(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelConfigView, ChannelApiError>;

    async fn get_status(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError>;

    async fn connect_config(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError>;

    async fn disconnect_config(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError>;

    async fn health_check_config(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError>;

    async fn list_project_outbox(
        &self,
        user_id: &str,
        project_id: &str,
        query: ValidatedChannelOutboxQuery<'_>,
    ) -> Result<ChannelOutboxListView, ChannelApiError>;

    async fn list_project_session_bindings(
        &self,
        user_id: &str,
        project_id: &str,
        query: ValidatedChannelPageQuery,
    ) -> Result<ChannelSessionBindingListView, ChannelApiError>;

    async fn get_project_observability_summary(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<ChannelObservabilitySummaryView, ChannelApiError>;

    async fn ingest_feishu_webhook(
        &self,
        config_id: &str,
        headers: FeishuWebhookHeaders,
        raw_body: Vec<u8>,
        body: Value,
    ) -> Result<ChannelWebhookIngressOutcome, ChannelApiError>;
}

pub(crate) enum ChannelWebhookIngressOutcome {
    Challenge(ChannelWebhookChallengeView),
    Event(Box<ChannelWebhookIngressView>),
}

pub(crate) struct PgChannelService {
    repo: PgChannelRepository,
}

impl PgChannelService {
    pub(crate) fn new(repo: PgChannelRepository) -> Self {
        Self { repo }
    }

    async fn ensure_project_access(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<(), ChannelApiError> {
        if self
            .repo
            .user_has_project_access(user_id, project_id)
            .await
            .map_err(ChannelApiError::internal)?
        {
            Ok(())
        } else {
            Err(ChannelApiError::forbidden("Access denied to project"))
        }
    }

    async fn ensure_project_admin(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<(), ChannelApiError> {
        if self
            .repo
            .user_is_project_admin(user_id, project_id)
            .await
            .map_err(ChannelApiError::internal)?
        {
            Ok(())
        } else {
            Err(ChannelApiError::forbidden("Access denied to project"))
        }
    }
}

#[async_trait]
impl ChannelService for PgChannelService {
    async fn list_project_configs(
        &self,
        user_id: &str,
        project_id: &str,
        query: ValidatedChannelConfigQuery<'_>,
    ) -> Result<ChannelConfigListView, ChannelApiError> {
        self.ensure_project_access(user_id, project_id).await?;
        let rows = self
            .repo
            .list_configs(ChannelConfigListQuery {
                project_id,
                channel_type: query.channel_type,
                enabled_only: query.enabled_only,
                limit: query.limit,
                offset: query.offset,
            })
            .await
            .map_err(ChannelApiError::internal)?;
        let total = self
            .repo
            .count_configs(project_id, query.channel_type, query.enabled_only)
            .await
            .map_err(ChannelApiError::internal)?;
        Ok(ChannelConfigListView {
            items: rows.into_iter().map(ChannelConfigView::from).collect(),
            total,
        })
    }

    async fn get_config(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelConfigView, ChannelApiError> {
        let config = self
            .repo
            .get_config(config_id)
            .await
            .map_err(ChannelApiError::internal)?
            .ok_or_else(|| ChannelApiError::not_found("Configuration not found"))?;
        self.ensure_project_access(user_id, &config.project_id)
            .await?;
        Ok(ChannelConfigView::from(config))
    }

    async fn get_status(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError> {
        let status = self
            .repo
            .get_status(config_id)
            .await
            .map_err(ChannelApiError::internal)?
            .ok_or_else(|| ChannelApiError::not_found("Configuration not found"))?;
        self.ensure_project_access(user_id, &status.project_id)
            .await?;
        Ok(ChannelStatusView::from(status))
    }

    async fn connect_config(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError> {
        let config = self
            .repo
            .get_config(config_id)
            .await
            .map_err(ChannelApiError::internal)?
            .ok_or_else(|| ChannelApiError::not_found("Configuration not found"))?;
        self.ensure_project_admin(user_id, &config.project_id)
            .await?;
        if !config.enabled {
            return Err(ChannelApiError::bad_request(
                "Cannot connect a disabled channel configuration",
            ));
        }
        self.repo
            .update_connection_status(config_id, "connected", None)
            .await
            .map_err(ChannelApiError::internal)?
            .map(ChannelStatusView::from)
            .ok_or_else(|| ChannelApiError::not_found("Configuration not found"))
    }

    async fn disconnect_config(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError> {
        let config = self
            .repo
            .get_config(config_id)
            .await
            .map_err(ChannelApiError::internal)?
            .ok_or_else(|| ChannelApiError::not_found("Configuration not found"))?;
        self.ensure_project_admin(user_id, &config.project_id)
            .await?;
        self.repo
            .update_connection_status(config_id, "disconnected", None)
            .await
            .map_err(ChannelApiError::internal)?
            .map(ChannelStatusView::from)
            .ok_or_else(|| ChannelApiError::not_found("Configuration not found"))
    }

    async fn health_check_config(
        &self,
        user_id: &str,
        config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError> {
        let config = self
            .repo
            .get_config(config_id)
            .await
            .map_err(ChannelApiError::internal)?
            .ok_or_else(|| ChannelApiError::not_found("Configuration not found"))?;
        self.ensure_project_admin(user_id, &config.project_id)
            .await?;
        let (status, last_error) = if config.enabled {
            ("connected", None)
        } else {
            ("disconnected", Some("channel config disabled"))
        };
        self.repo
            .update_connection_status(config_id, status, last_error)
            .await
            .map_err(ChannelApiError::internal)?
            .map(ChannelStatusView::from)
            .ok_or_else(|| ChannelApiError::not_found("Configuration not found"))
    }

    async fn list_project_outbox(
        &self,
        user_id: &str,
        project_id: &str,
        query: ValidatedChannelOutboxQuery<'_>,
    ) -> Result<ChannelOutboxListView, ChannelApiError> {
        self.ensure_project_admin(user_id, project_id).await?;
        let rows = self
            .repo
            .list_outbox(ChannelOutboxListQuery {
                project_id,
                status_filter: query.status_filter,
                limit: query.limit,
                offset: query.offset,
            })
            .await
            .map_err(ChannelApiError::internal)?;
        let total = self
            .repo
            .count_outbox(project_id, query.status_filter)
            .await
            .map_err(ChannelApiError::internal)?;
        Ok(ChannelOutboxListView {
            items: rows.into_iter().map(ChannelOutboxItemView::from).collect(),
            total,
        })
    }

    async fn list_project_session_bindings(
        &self,
        user_id: &str,
        project_id: &str,
        query: ValidatedChannelPageQuery,
    ) -> Result<ChannelSessionBindingListView, ChannelApiError> {
        self.ensure_project_admin(user_id, project_id).await?;
        let rows = self
            .repo
            .list_session_bindings(ChannelPageQuery {
                project_id,
                limit: query.limit,
                offset: query.offset,
            })
            .await
            .map_err(ChannelApiError::internal)?;
        let total = self
            .repo
            .count_session_bindings(project_id)
            .await
            .map_err(ChannelApiError::internal)?;
        Ok(ChannelSessionBindingListView {
            items: rows
                .into_iter()
                .map(ChannelSessionBindingItemView::from)
                .collect(),
            total,
        })
    }

    async fn get_project_observability_summary(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<ChannelObservabilitySummaryView, ChannelApiError> {
        self.ensure_project_admin(user_id, project_id).await?;
        let record = self
            .repo
            .observability_summary(project_id)
            .await
            .map_err(ChannelApiError::internal)?;
        Ok(ChannelObservabilitySummaryView::from(record))
    }

    async fn ingest_feishu_webhook(
        &self,
        config_id: &str,
        headers: FeishuWebhookHeaders,
        raw_body: Vec<u8>,
        body: Value,
    ) -> Result<ChannelWebhookIngressOutcome, ChannelApiError> {
        let config = self
            .repo
            .get_webhook_secrets(config_id)
            .await
            .map_err(ChannelApiError::internal)?
            .ok_or_else(|| ChannelApiError::not_found("Webhook configuration not found"))?;
        if !config.enabled || config.connection_mode != "webhook" || config.channel_type != "feishu"
        {
            return Err(ChannelApiError::not_found(
                "Webhook configuration not found",
            ));
        }

        match verify_feishu_webhook_request(
            FeishuWebhookSecrets::from(&config),
            &headers,
            &raw_body,
            &body,
        )
        .map_err(map_feishu_verification_error)?
        {
            FeishuWebhookVerification::UrlChallenge { challenge } => Ok(
                ChannelWebhookIngressOutcome::Challenge(ChannelWebhookChallengeView { challenge }),
            ),
            FeishuWebhookVerification::Event => {
                let idempotency_key = feishu_webhook_idempotency_key(&headers, &raw_body, &body);
                let event_id = stable_feishu_webhook_event_id(config_id, &idempotency_key);
                let normalized_event_json = normalize_feishu_webhook_event(&body, &idempotency_key);
                let mut ingress = self
                    .repo
                    .record_webhook_event(&ChannelWebhookEventInsertRecord {
                        id: event_id,
                        channel_config_id: config_id.to_string(),
                        idempotency_key,
                        headers_json: headers_json(&headers),
                        raw_event_json: body,
                        normalized_event_json,
                    })
                    .await
                    .map_err(ChannelApiError::internal)?
                    .ok_or_else(|| ChannelApiError::not_found("Webhook configuration not found"))?;
                if ingress.event.status == "received" {
                    let route = channel_webhook_session_route(&ingress.event);
                    let create_record =
                        channel_webhook_session_create_record(&ingress.event, &route);
                    if let Some(routed) = self
                        .repo
                        .route_webhook_event_to_session_binding_or_create(
                            &ingress.event.id,
                            create_record.as_ref(),
                            route.error.as_deref(),
                        )
                        .await
                        .map_err(ChannelApiError::internal)?
                    {
                        ingress.event = routed.event;
                    }
                }
                Ok(ChannelWebhookIngressOutcome::Event(Box::new(
                    ChannelWebhookIngressView::from(ingress),
                )))
            }
        }
    }
}

#[derive(Default)]
pub(crate) struct DevChannelService;

impl DevChannelService {
    pub(crate) fn new() -> Self {
        Self
    }
}

#[async_trait]
impl ChannelService for DevChannelService {
    async fn list_project_configs(
        &self,
        _user_id: &str,
        _project_id: &str,
        _query: ValidatedChannelConfigQuery<'_>,
    ) -> Result<ChannelConfigListView, ChannelApiError> {
        Ok(ChannelConfigListView {
            items: Vec::new(),
            total: 0,
        })
    }

    async fn get_config(
        &self,
        _user_id: &str,
        _config_id: &str,
    ) -> Result<ChannelConfigView, ChannelApiError> {
        Err(ChannelApiError::not_found("Configuration not found"))
    }

    async fn get_status(
        &self,
        _user_id: &str,
        _config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError> {
        Err(ChannelApiError::not_found("Configuration not found"))
    }

    async fn connect_config(
        &self,
        _user_id: &str,
        _config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError> {
        Err(ChannelApiError::not_found("Configuration not found"))
    }

    async fn disconnect_config(
        &self,
        _user_id: &str,
        _config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError> {
        Err(ChannelApiError::not_found("Configuration not found"))
    }

    async fn health_check_config(
        &self,
        _user_id: &str,
        _config_id: &str,
    ) -> Result<ChannelStatusView, ChannelApiError> {
        Err(ChannelApiError::not_found("Configuration not found"))
    }

    async fn list_project_outbox(
        &self,
        _user_id: &str,
        _project_id: &str,
        _query: ValidatedChannelOutboxQuery<'_>,
    ) -> Result<ChannelOutboxListView, ChannelApiError> {
        Ok(ChannelOutboxListView {
            items: Vec::new(),
            total: 0,
        })
    }

    async fn list_project_session_bindings(
        &self,
        _user_id: &str,
        _project_id: &str,
        _query: ValidatedChannelPageQuery,
    ) -> Result<ChannelSessionBindingListView, ChannelApiError> {
        Ok(ChannelSessionBindingListView {
            items: Vec::new(),
            total: 0,
        })
    }

    async fn get_project_observability_summary(
        &self,
        _user_id: &str,
        project_id: &str,
    ) -> Result<ChannelObservabilitySummaryView, ChannelApiError> {
        Ok(ChannelObservabilitySummaryView::empty(project_id))
    }

    async fn ingest_feishu_webhook(
        &self,
        _config_id: &str,
        _headers: FeishuWebhookHeaders,
        _raw_body: Vec<u8>,
        _body: Value,
    ) -> Result<ChannelWebhookIngressOutcome, ChannelApiError> {
        Err(ChannelApiError::service_unavailable(
            "Channel webhook ingress requires Postgres channel runtime",
        ))
    }
}

fn map_feishu_verification_error(error: FeishuWebhookVerificationError) -> ChannelApiError {
    match error {
        FeishuWebhookVerificationError::InvalidJsonObject => {
            ChannelApiError::bad_request("Invalid Feishu webhook JSON payload")
        }
        FeishuWebhookVerificationError::NotConfigured => {
            ChannelApiError::service_unavailable("Feishu webhook verification is not configured")
        }
        FeishuWebhookVerificationError::InvalidToken => {
            ChannelApiError::unauthorized("Invalid Feishu webhook verification token")
        }
        FeishuWebhookVerificationError::MissingSignatureHeaders => {
            ChannelApiError::unauthorized("Missing Feishu webhook signature")
        }
        FeishuWebhookVerificationError::InvalidSignature => {
            ChannelApiError::unauthorized("Invalid Feishu webhook signature")
        }
    }
}

fn stable_feishu_webhook_event_id(config_id: &str, idempotency_key: &str) -> String {
    let name = format!("agistack:channel-webhook:feishu:{config_id}:{idempotency_key}");
    format!(
        "channel_webhook_{}",
        Uuid::new_v5(&Uuid::NAMESPACE_URL, name.as_bytes())
    )
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct ChannelWebhookSessionRoute {
    pub(super) session_key: Option<String>,
    pub(super) error: Option<String>,
    chat_id: Option<String>,
    chat_type: Option<String>,
    thread_id: Option<String>,
    topic_id: Option<String>,
    sender_open_id: Option<String>,
}

pub(super) fn channel_webhook_session_route(
    event: &ChannelWebhookEventRecord,
) -> ChannelWebhookSessionRoute {
    let Some(chat_id) = json_string_at(&event.normalized_event_json, &["chat_id"]) else {
        return ChannelWebhookSessionRoute {
            session_key: None,
            error: Some("missing chat_id".to_string()),
            chat_id: None,
            chat_type: None,
            thread_id: None,
            topic_id: None,
            sender_open_id: None,
        };
    };
    let Some(chat_type) = json_string_at(&event.normalized_event_json, &["chat_type"]) else {
        return ChannelWebhookSessionRoute {
            session_key: None,
            error: Some("missing chat_type".to_string()),
            chat_id: Some(chat_id.to_string()),
            chat_type: None,
            thread_id: None,
            topic_id: None,
            sender_open_id: None,
        };
    };
    let scope = match chat_type {
        "group" => "group",
        "p2p" => "dm",
        other => {
            return ChannelWebhookSessionRoute {
                session_key: None,
                error: Some(format!("unsupported chat_type: {other}")),
                chat_id: Some(chat_id.to_string()),
                chat_type: Some(other.to_string()),
                thread_id: None,
                topic_id: None,
                sender_open_id: None,
            };
        }
    };

    let mut session_key = format!(
        "project:{}:channel:{}:config:{}:{}:{}",
        event.project_id.as_str(),
        event.channel_type.as_str(),
        event.channel_config_id.as_str(),
        scope,
        chat_id
    );
    let topic_id =
        json_string_at(&event.normalized_event_json, &["topic_id"]).map(ToString::to_string);
    if let Some(topic_id) = topic_id.as_deref() {
        session_key.push_str(":topic:");
        session_key.push_str(topic_id);
    }
    let thread_id =
        json_string_at(&event.normalized_event_json, &["thread_id"]).map(ToString::to_string);
    if let Some(thread_id) = thread_id.as_deref() {
        session_key.push_str(":thread:");
        session_key.push_str(thread_id);
    }
    let sender_open_id =
        json_string_at(&event.normalized_event_json, &["sender_open_id"]).map(ToString::to_string);

    ChannelWebhookSessionRoute {
        session_key: Some(session_key),
        error: None,
        chat_id: Some(chat_id.to_string()),
        chat_type: Some(chat_type.to_string()),
        thread_id,
        topic_id,
        sender_open_id,
    }
}

pub(super) fn channel_webhook_session_create_record(
    event: &ChannelWebhookEventRecord,
    route: &ChannelWebhookSessionRoute,
) -> Option<ChannelWebhookSessionCreateRecord> {
    let session_key = route.session_key.as_ref()?;
    let chat_id = route.chat_id.as_ref()?;
    let chat_type = route.chat_type.as_ref()?;
    let conversation_title = channel_webhook_conversation_title(
        &event.channel_type,
        chat_type,
        route.sender_open_id.as_deref().unwrap_or(chat_id),
    );
    Some(ChannelWebhookSessionCreateRecord {
        binding_id: Uuid::new_v4().to_string(),
        conversation_id: Uuid::new_v4().to_string(),
        session_key: session_key.clone(),
        chat_id: chat_id.clone(),
        chat_type: chat_type.clone(),
        thread_id: route.thread_id.clone(),
        topic_id: route.topic_id.clone(),
        conversation_title,
        metadata_json: json!({
            "channel_session_key": session_key,
            "channel_type": event.channel_type.as_str(),
            "channel_config_id": event.channel_config_id.as_str(),
            "chat_id": chat_id,
            "chat_type": chat_type,
            "thread_id": route.thread_id.as_deref(),
            "topic_id": route.topic_id.as_deref(),
            "sender_id": route.sender_open_id.as_deref(),
            "sender_name": route.sender_open_id.as_deref(),
        }),
    })
}

fn channel_webhook_conversation_title(channel_type: &str, chat_type: &str, sender: &str) -> String {
    let channel_name = match channel_type {
        "feishu" => "Feishu".to_string(),
        other => {
            let mut chars = other.chars();
            match chars.next() {
                Some(first) => first.to_uppercase().collect::<String>() + chars.as_str(),
                None => "Channel".to_string(),
            }
        }
    };
    if chat_type == "p2p" {
        format!("{channel_name}: Chat with {sender}")
    } else {
        format!("{channel_name}: Group Chat")
    }
}

fn normalize_feishu_webhook_event(body: &Value, idempotency_key: &str) -> Value {
    let mut normalized = Map::new();
    normalized.insert("provider".to_string(), json!("feishu"));
    normalized.insert("schema_version".to_string(), json!(1));
    normalized.insert("idempotency_key".to_string(), json!(idempotency_key));

    insert_first_string(
        &mut normalized,
        "event_id",
        body,
        &[
            &["event", "header", "event_id"],
            &["header", "event_id"],
            &["event_id"],
        ],
    );
    insert_first_string(
        &mut normalized,
        "event_type",
        body,
        &[
            &["event", "header", "event_type"],
            &["header", "event_type"],
            &["type"],
        ],
    );
    insert_first_string(
        &mut normalized,
        "message_id",
        body,
        &[
            &["event", "message", "message_id"],
            &["event", "message_id"],
            &["message_id"],
        ],
    );
    insert_first_string(
        &mut normalized,
        "chat_id",
        body,
        &[
            &["event", "message", "chat_id"],
            &["event", "chat_id"],
            &["chat_id"],
        ],
    );
    insert_first_string(
        &mut normalized,
        "chat_type",
        body,
        &[
            &["event", "message", "chat_type"],
            &["event", "chat_type"],
            &["chat_type"],
        ],
    );
    insert_first_string(
        &mut normalized,
        "thread_id",
        body,
        &[
            &["event", "message", "thread_id"],
            &["event", "message", "message_thread_id"],
            &["event", "thread_id"],
            &["thread_id"],
        ],
    );
    insert_first_string(
        &mut normalized,
        "topic_id",
        body,
        &[
            &["event", "message", "topic_id"],
            &["event", "topic_id"],
            &["topic_id"],
        ],
    );
    insert_first_string(
        &mut normalized,
        "sender_open_id",
        body,
        &[
            &["event", "sender", "sender_id", "open_id"],
            &["event", "sender", "open_id"],
            &["sender", "sender_id", "open_id"],
        ],
    );

    Value::Object(normalized)
}

fn insert_first_string(
    target: &mut Map<String, Value>,
    key: &str,
    body: &Value,
    paths: &[&[&str]],
) {
    if let Some(value) = paths.iter().find_map(|path| json_string_at(body, path)) {
        target.insert(key.to_string(), json!(value));
    }
}

fn json_string_at<'a>(value: &'a Value, path: &[&str]) -> Option<&'a str> {
    let mut current = value;
    for segment in path {
        current = current.get(*segment)?;
    }
    current.as_str().filter(|value| !value.is_empty())
}

fn headers_json(headers: &FeishuWebhookHeaders) -> Value {
    Value::Object(
        headers
            .iter()
            .map(|(key, value)| (key.clone(), Value::String(value.clone())))
            .collect::<Map<String, Value>>(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_feishu_webhook_event_projects_message_fields() {
        let body = json!({
            "event": {
                "header": {
                    "event_id": "evt-1",
                    "event_type": "im.message.receive_v1"
                },
                "message": {
                    "message_id": "om_msg_1",
                    "chat_id": "oc_chat_1",
                    "chat_type": "group",
                    "thread_id": "thread-1",
                    "topic_id": "topic-1"
                },
                "sender": {
                    "sender_id": {
                        "open_id": "ou_sender_1"
                    }
                }
            }
        });

        let normalized = normalize_feishu_webhook_event(&body, "evt-1");

        assert_eq!(normalized["provider"], "feishu");
        assert_eq!(normalized["schema_version"], 1);
        assert_eq!(normalized["idempotency_key"], "evt-1");
        assert_eq!(normalized["event_id"], "evt-1");
        assert_eq!(normalized["event_type"], "im.message.receive_v1");
        assert_eq!(normalized["message_id"], "om_msg_1");
        assert_eq!(normalized["chat_id"], "oc_chat_1");
        assert_eq!(normalized["chat_type"], "group");
        assert_eq!(normalized["thread_id"], "thread-1");
        assert_eq!(normalized["topic_id"], "topic-1");
        assert_eq!(normalized["sender_open_id"], "ou_sender_1");
    }
}
