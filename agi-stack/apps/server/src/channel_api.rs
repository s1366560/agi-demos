//! P5 channel configuration read/status foundation.
//!
//! This module intentionally owns only the database-backed, read-only channel
//! config surface. Plugin runtime management, connection lifecycle, webhook
//! ingress, outbox delivery and channel message routing stay Python-owned until
//! their runtime semantics move as a full vertical slice.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};

use agistack_adapters_postgres::{
    ChannelConfigListQuery, ChannelConfigRecord, ChannelOutboxListQuery, ChannelOutboxRecord,
    ChannelPageQuery, ChannelSessionBindingRecord, ChannelStatusRecord, PgChannelRepository,
};

use crate::{auth::Identity, AppState};

#[cfg(test)]
mod tests;

pub(crate) type SharedChannels = Arc<dyn ChannelService>;

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ChannelConfigQuery {
    channel_type: Option<String>,
    #[serde(default)]
    enabled_only: bool,
    limit: Option<i64>,
    offset: Option<i64>,
}

impl ChannelConfigQuery {
    fn validated(&self) -> Result<ValidatedChannelConfigQuery<'_>, ChannelApiError> {
        let limit = self.limit.unwrap_or(100);
        if !(1..=500).contains(&limit) {
            return Err(ChannelApiError::unprocessable(
                "limit must be greater than or equal to 1 and less than or equal to 500",
            ));
        }
        let offset = self.offset.unwrap_or(0);
        if offset < 0 {
            return Err(ChannelApiError::unprocessable(
                "offset must be greater than or equal to 0",
            ));
        }
        Ok(ValidatedChannelConfigQuery {
            channel_type: self
                .channel_type
                .as_deref()
                .map(str::trim)
                .filter(|value| !value.is_empty()),
            enabled_only: self.enabled_only,
            limit,
            offset,
        })
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct ValidatedChannelConfigQuery<'a> {
    channel_type: Option<&'a str>,
    enabled_only: bool,
    limit: i64,
    offset: i64,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ChannelOutboxQuery {
    #[serde(rename = "status")]
    status_filter: Option<String>,
    limit: Option<i64>,
    offset: Option<i64>,
}

impl ChannelOutboxQuery {
    fn validated(&self) -> Result<ValidatedChannelOutboxQuery<'_>, ChannelApiError> {
        let page = ChannelPageQueryParams {
            limit: self.limit,
            offset: self.offset,
        }
        .validated(200)?;
        let status_filter = self
            .status_filter
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty());
        if let Some(status) = status_filter {
            if !is_valid_outbox_status(status) {
                return Err(ChannelApiError::unprocessable(
                    "status must be one of pending, failed, sent, dead_letter",
                ));
            }
        }
        Ok(ValidatedChannelOutboxQuery {
            status_filter,
            limit: page.limit,
            offset: page.offset,
        })
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct ValidatedChannelOutboxQuery<'a> {
    status_filter: Option<&'a str>,
    limit: i64,
    offset: i64,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ChannelPageQueryParams {
    limit: Option<i64>,
    offset: Option<i64>,
}

impl ChannelPageQueryParams {
    fn validated(&self, max_limit: i64) -> Result<ValidatedChannelPageQuery, ChannelApiError> {
        let limit = self.limit.unwrap_or(50);
        if !(1..=max_limit).contains(&limit) {
            return Err(ChannelApiError::unprocessable(format!(
                "limit must be greater than or equal to 1 and less than or equal to {max_limit}",
            )));
        }
        let offset = self.offset.unwrap_or(0);
        if offset < 0 {
            return Err(ChannelApiError::unprocessable(
                "offset must be greater than or equal to 0",
            ));
        }
        Ok(ValidatedChannelPageQuery { limit, offset })
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct ValidatedChannelPageQuery {
    limit: i64,
    offset: i64,
}

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
    items: Vec<ChannelConfigView>,
    total: i64,
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
    items: Vec<ChannelOutboxItemView>,
    total: i64,
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
    items: Vec<ChannelSessionBindingItemView>,
    total: i64,
}

#[derive(Debug)]
pub(crate) struct ChannelApiError {
    status: StatusCode,
    detail: Value,
}

impl ChannelApiError {
    fn new(status: StatusCode, detail: impl Into<Value>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail.into())
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail.into())
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail.into())
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for ChannelApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

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
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route(
            "/api/v1/channels/projects/:project_id/configs",
            get(list_project_channel_configs),
        )
        .route(
            "/api/v1/channels/configs/:config_id",
            get(get_channel_config),
        )
        .route(
            "/api/v1/channels/configs/:config_id/status",
            get(get_channel_config_status),
        )
        .route(
            "/api/v1/channels/projects/:project_id/observability/outbox",
            get(list_project_channel_outbox),
        )
        .route(
            "/api/v1/channels/projects/:project_id/observability/session-bindings",
            get(list_project_channel_session_bindings),
        )
}

async fn list_project_channel_configs(
    State(state): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Query(query): Query<ChannelConfigQuery>,
) -> Result<Json<ChannelConfigListView>, ChannelApiError> {
    let query = query.validated()?;
    state
        .channels
        .list_project_configs(&identity.user_id, &project_id, query)
        .await
        .map(Json)
}

async fn get_channel_config(
    State(state): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(config_id): Path<String>,
) -> Result<Json<ChannelConfigView>, ChannelApiError> {
    state
        .channels
        .get_config(&identity.user_id, &config_id)
        .await
        .map(Json)
}

async fn get_channel_config_status(
    State(state): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(config_id): Path<String>,
) -> Result<Json<ChannelStatusView>, ChannelApiError> {
    state
        .channels
        .get_status(&identity.user_id, &config_id)
        .await
        .map(Json)
}

async fn list_project_channel_outbox(
    State(state): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Query(query): Query<ChannelOutboxQuery>,
) -> Result<Json<ChannelOutboxListView>, ChannelApiError> {
    let query = query.validated()?;
    state
        .channels
        .list_project_outbox(&identity.user_id, &project_id, query)
        .await
        .map(Json)
}

async fn list_project_channel_session_bindings(
    State(state): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Query(query): Query<ChannelPageQueryParams>,
) -> Result<Json<ChannelSessionBindingListView>, ChannelApiError> {
    let query = query.validated(200)?;
    state
        .channels
        .list_project_session_bindings(&identity.user_id, &project_id, query)
        .await
        .map(Json)
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(chrono::SecondsFormat::Micros, true)
}

fn is_valid_outbox_status(status: &str) -> bool {
    matches!(status, "pending" | "failed" | "sent" | "dead_letter")
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
