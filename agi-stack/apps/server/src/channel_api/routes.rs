use axum::{
    extract::{Path, Query, State},
    routing::get,
    Extension, Json, Router,
};

use crate::{auth::Identity, AppState};

use super::{
    error::ChannelApiError,
    queries::{ChannelConfigQuery, ChannelOutboxQuery, ChannelPageQueryParams},
    views::{
        ChannelConfigListView, ChannelConfigView, ChannelObservabilitySummaryView,
        ChannelOutboxListView, ChannelSessionBindingListView, ChannelStatusView,
    },
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
