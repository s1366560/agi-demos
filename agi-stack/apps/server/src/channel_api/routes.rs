use axum::{
    body::Bytes,
    extract::{Path, Query, State},
    http::HeaderMap,
    routing::{get, post},
    Extension, Json, Router,
};
use serde_json::{json, Value};

use crate::{auth::Identity, AppState};

use super::{
    error::ChannelApiError,
    queries::{ChannelConfigQuery, ChannelOutboxQuery, ChannelPageQueryParams},
    service::ChannelWebhookIngressOutcome,
    views::{
        ChannelConfigListView, ChannelConfigView, ChannelObservabilitySummaryView,
        ChannelOutboxListView, ChannelSessionBindingListView, ChannelStatusView,
    },
    webhook_verifier::FeishuWebhookHeaders,
};

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
            "/api/v1/channels/configs/:config_id/connect",
            post(connect_channel_config),
        )
        .route(
            "/api/v1/channels/configs/:config_id/disconnect",
            post(disconnect_channel_config),
        )
        .route(
            "/api/v1/channels/configs/:config_id/health-check",
            post(health_check_channel_config),
        )
        .route(
            "/api/v1/channels/projects/:project_id/observability/outbox",
            get(list_project_channel_outbox),
        )
        .route(
            "/api/v1/channels/projects/:project_id/observability/summary",
            get(get_project_channel_observability_summary),
        )
        .route(
            "/api/v1/channels/projects/:project_id/observability/session-bindings",
            get(list_project_channel_session_bindings),
        )
}

pub(crate) fn router_public() -> Router<AppState> {
    Router::new().route(
        "/api/v1/channels/configs/:config_id/webhook/feishu",
        post(ingest_feishu_webhook),
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

async fn ingest_feishu_webhook(
    State(state): State<AppState>,
    Path(config_id): Path<String>,
    headers: HeaderMap,
    raw_body: Bytes,
) -> Result<Json<Value>, ChannelApiError> {
    let body = serde_json::from_slice::<Value>(&raw_body)
        .map_err(|_| ChannelApiError::bad_request("Invalid Feishu webhook JSON payload"))?;
    let headers = header_map_to_webhook_headers(&headers);
    match state
        .channels
        .ingest_feishu_webhook(&config_id, headers, raw_body.to_vec(), body)
        .await?
    {
        ChannelWebhookIngressOutcome::Challenge(view) => serde_json::to_value(view),
        ChannelWebhookIngressOutcome::Event(mut view) => {
            view.routed_event_id = publish_channel_webhook_event(&state, &view).await?;
            serde_json::to_value(view)
        }
    }
    .map(Json)
    .map_err(ChannelApiError::internal)
}

const CHANNEL_WEBHOOK_EVENT_STREAM_MAX_LEN: usize = 1_000;

async fn publish_channel_webhook_event(
    state: &AppState,
    view: &super::views::ChannelWebhookIngressView,
) -> Result<Option<String>, ChannelApiError> {
    if !view.inserted {
        return Ok(None);
    }
    let payload = channel_webhook_event_payload(view);
    state
        .events
        .append(
            &channel_webhook_event_topic(&view.project_id),
            &payload.to_string(),
            CHANNEL_WEBHOOK_EVENT_STREAM_MAX_LEN,
        )
        .await
        .map(Some)
        .map_err(ChannelApiError::internal)
}

pub(super) fn channel_webhook_event_payload(
    view: &super::views::ChannelWebhookIngressView,
) -> Value {
    let mut payload = json!({
        "type": "channel_webhook_message_received",
        "provider": view.normalized_event.get("provider").and_then(Value::as_str).unwrap_or("unknown"),
        "project_id": view.project_id.as_str(),
        "channel_config_id": view.channel_config_id.as_str(),
        "channel_event_id": view.event_id.as_str(),
        "idempotency_key": view.idempotency_key.as_str(),
        "status": view.status.as_str(),
        "routing_key": format!(
            "channel:{}:{}",
            view.channel_config_id.as_str(),
            view.idempotency_key.as_str()
        ),
        "normalized_event": view.normalized_event.clone(),
    });
    if let Value::Object(payload) = &mut payload {
        if let Some(route_session_key) = view.route_session_key.as_deref() {
            payload.insert("route_session_key".to_string(), json!(route_session_key));
        }
        if let Some(session_binding_id) = view.session_binding_id.as_deref() {
            payload.insert("session_binding_id".to_string(), json!(session_binding_id));
        }
        if let Some(conversation_id) = view.conversation_id.as_deref() {
            payload.insert("conversation_id".to_string(), json!(conversation_id));
        }
    }
    payload
}

fn channel_webhook_event_topic(project_id: &str) -> String {
    format!("channel:events:{project_id}")
}

fn header_map_to_webhook_headers(headers: &HeaderMap) -> FeishuWebhookHeaders {
    headers
        .iter()
        .filter_map(|(name, value)| {
            value
                .to_str()
                .ok()
                .map(|value| (name.as_str().to_string(), value.to_string()))
        })
        .collect()
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

async fn connect_channel_config(
    State(state): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(config_id): Path<String>,
) -> Result<Json<ChannelStatusView>, ChannelApiError> {
    state
        .channels
        .connect_config(&identity.user_id, &config_id)
        .await
        .map(Json)
}

async fn disconnect_channel_config(
    State(state): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(config_id): Path<String>,
) -> Result<Json<ChannelStatusView>, ChannelApiError> {
    state
        .channels
        .disconnect_config(&identity.user_id, &config_id)
        .await
        .map(Json)
}

async fn health_check_channel_config(
    State(state): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(config_id): Path<String>,
) -> Result<Json<ChannelStatusView>, ChannelApiError> {
    state
        .channels
        .health_check_config(&identity.user_id, &config_id)
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

async fn get_project_channel_observability_summary(
    State(state): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> Result<Json<ChannelObservabilitySummaryView>, ChannelApiError> {
    state
        .channels
        .get_project_observability_summary(&identity.user_id, &project_id)
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
