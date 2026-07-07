//! P7 observability/events strangler slice.
//!
//! The Python `/api/v1/events` router still owns filter/export/write siblings.
//! Rust owns only exact event list and type-discovery read paths in this
//! checkpoint.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;

use agistack_adapters_postgres::{
    PgEventLogRepository, TenantEventLogListQuery, TenantEventLogRecord,
};

use crate::auth::Identity;
use crate::identity::IdentityError;
use crate::AppState;

pub(crate) type SharedEventLogs = Arc<dyn EventLogService>;

#[async_trait]
pub(crate) trait EventLogService: Send + Sync {
    async fn list_events(
        &self,
        query: ValidatedEventListQuery,
    ) -> Result<EventLogListResponse, EventsApiError>;

    async fn list_event_types(&self, tenant_id: &str) -> Result<Vec<String>, EventsApiError>;
}

pub(crate) struct PgEventLogService {
    repo: PgEventLogRepository,
}

impl PgEventLogService {
    pub(crate) fn new(repo: PgEventLogRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl EventLogService for PgEventLogService {
    async fn list_events(
        &self,
        query: ValidatedEventListQuery,
    ) -> Result<EventLogListResponse, EventsApiError> {
        let page = query.page;
        let page_size = query.page_size;
        let (records, total) = self
            .repo
            .list_events(TenantEventLogListQuery {
                tenant_id: &query.tenant_id,
                event_type: query.event_type.as_deref(),
                date_from: query.date_from,
                date_to: query.date_to,
                page,
                page_size,
            })
            .await
            .map_err(EventsApiError::internal)?;
        Ok(EventLogListResponse {
            items: records.into_iter().map(EventLogView::from).collect(),
            total,
            page,
            page_size,
        })
    }

    async fn list_event_types(&self, tenant_id: &str) -> Result<Vec<String>, EventsApiError> {
        self.repo
            .list_event_types(tenant_id)
            .await
            .map_err(EventsApiError::internal)
    }
}

pub(crate) struct DevEventLogService {
    event_types: Vec<String>,
}

impl DevEventLogService {
    pub(crate) fn new(event_types: Vec<String>) -> Self {
        Self { event_types }
    }
}

impl Default for DevEventLogService {
    fn default() -> Self {
        Self::new(Vec::new())
    }
}

#[async_trait]
impl EventLogService for DevEventLogService {
    async fn list_events(
        &self,
        query: ValidatedEventListQuery,
    ) -> Result<EventLogListResponse, EventsApiError> {
        Ok(EventLogListResponse {
            items: Vec::new(),
            total: 0,
            page: query.page,
            page_size: query.page_size,
        })
    }

    async fn list_event_types(&self, _tenant_id: &str) -> Result<Vec<String>, EventsApiError> {
        Ok(self.event_types.clone())
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/events", get(list_events))
        .route("/api/v1/events/types", get(list_event_types))
}

async fn list_events(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<EventListQuery>,
) -> Result<Json<EventLogListResponse>, EventsApiError> {
    let tenant_id = selected_tenant_id(&app, &identity.user_id, query.tenant_id.as_deref()).await?;
    let query = query.validated(tenant_id)?;
    let response = app.event_logs.list_events(query).await?;
    Ok(Json(response))
}

async fn list_event_types(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<EventTypesQuery>,
) -> Result<Json<Vec<String>>, EventsApiError> {
    let tenant_id = selected_tenant_id(&app, &identity.user_id, query.tenant_id.as_deref()).await?;
    let event_types = app.event_logs.list_event_types(&tenant_id).await?;
    Ok(Json(event_types))
}

#[derive(Debug, Clone, Deserialize)]
struct EventTypesQuery {
    tenant_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct EventListQuery {
    tenant_id: Option<String>,
    event_type: Option<String>,
    date_from: Option<String>,
    date_to: Option<String>,
    page: Option<i64>,
    page_size: Option<i64>,
}

impl EventListQuery {
    fn validated(self, tenant_id: String) -> Result<ValidatedEventListQuery, EventsApiError> {
        let page = self.page.unwrap_or(1);
        if page < 1 {
            return Err(EventsApiError::unprocessable(
                "page must be greater than or equal to 1",
            ));
        }
        let page_size = self.page_size.unwrap_or(20);
        if !(1..=100).contains(&page_size) {
            return Err(EventsApiError::unprocessable(
                "page_size must be greater than or equal to 1 and less than or equal to 100",
            ));
        }
        Ok(ValidatedEventListQuery {
            tenant_id,
            event_type: self.event_type,
            date_from: parse_datetime(self.date_from.as_deref(), "date_from")?,
            date_to: parse_datetime(self.date_to.as_deref(), "date_to")?,
            page,
            page_size,
        })
    }
}

#[derive(Debug, Clone)]
pub(crate) struct ValidatedEventListQuery {
    tenant_id: String,
    event_type: Option<String>,
    date_from: Option<DateTime<Utc>>,
    date_to: Option<DateTime<Utc>>,
    page: i64,
    page_size: i64,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct EventLogView {
    id: String,
    tenant_id: String,
    event_type: String,
    message: String,
    source: String,
    metadata: serde_json::Value,
    created_at: String,
}

impl From<TenantEventLogRecord> for EventLogView {
    fn from(record: TenantEventLogRecord) -> Self {
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            event_type: record.event_type,
            message: record.message,
            source: record.source,
            metadata: record.metadata_json,
            created_at: iso8601(record.created_at),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct EventLogListResponse {
    items: Vec<EventLogView>,
    total: i64,
    page: i64,
    page_size: i64,
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn parse_datetime(
    value: Option<&str>,
    field: &str,
) -> Result<Option<DateTime<Utc>>, EventsApiError> {
    let Some(value) = value else {
        return Ok(None);
    };
    chrono::DateTime::parse_from_rfc3339(value)
        .map(|datetime| Some(datetime.with_timezone(&Utc)))
        .map_err(|_| EventsApiError::unprocessable(format!("{field} must be a valid datetime")))
}

async fn selected_tenant_id(
    app: &AppState,
    user_id: &str,
    selected_tenant_id: Option<&str>,
) -> Result<String, EventsApiError> {
    if let Some(tenant_id) = selected_tenant_id {
        if tenant_id.is_empty() {
            return Err(EventsApiError::unprocessable(
                "tenant_id must be at least 1 character",
            ));
        }
        app.identity
            .get_tenant(user_id, tenant_id)
            .await
            .map_err(EventsApiError::from_identity)?;
        return Ok(tenant_id.to_string());
    }

    let page = app
        .identity
        .list_tenants(user_id, None, 1, 1)
        .await
        .map_err(EventsApiError::from_identity)?;
    page.tenants
        .into_iter()
        .next()
        .map(|tenant| tenant.id)
        .ok_or_else(|| {
            EventsApiError::bad_request(
                "User does not belong to any tenant. Please contact administrator.",
            )
        })
}

#[derive(Debug)]
pub(crate) struct EventsApiError {
    status: StatusCode,
    detail: String,
}

impl EventsApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }

    fn from_identity(error: IdentityError) -> Self {
        Self::new(error.status, error.detail)
    }
}

impl IntoResponse for EventsApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use serde_json::Value;

    #[test]
    fn event_list_response_matches_python_shape() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/event_list_response.json"))
                .expect("event list golden must be valid JSON");
        let response = EventLogListResponse {
            items: vec![EventLogView {
                id: "event-1".to_string(),
                tenant_id: "tenant-1".to_string(),
                event_type: "gene.installed".to_string(),
                message: "Gene installed".to_string(),
                source: "gene-market".to_string(),
                metadata: json!({"gene_id": "gene-1"}),
                created_at: iso8601(Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap()),
            }],
            total: 1,
            page: 2,
            page_size: 10,
        };

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn event_list_query_defaults_and_validates_like_python() {
        let query = EventListQuery {
            tenant_id: None,
            event_type: Some("gene.installed".to_string()),
            date_from: Some("2026-01-01T00:00:00Z".to_string()),
            date_to: None,
            page: None,
            page_size: None,
        }
        .validated("tenant-1".to_string())
        .expect("query is valid");

        assert_eq!(query.tenant_id, "tenant-1");
        assert_eq!(query.event_type.as_deref(), Some("gene.installed"));
        assert!(query.date_from.is_some());
        assert_eq!(query.page, 1);
        assert_eq!(query.page_size, 20);

        let err = EventListQuery {
            tenant_id: None,
            event_type: None,
            date_from: None,
            date_to: None,
            page: Some(0),
            page_size: Some(20),
        }
        .validated("tenant-1".to_string())
        .expect_err("page below minimum rejected");
        assert_eq!(err.status, StatusCode::UNPROCESSABLE_ENTITY);

        let err = EventListQuery {
            tenant_id: None,
            event_type: None,
            date_from: Some("not-a-date".to_string()),
            date_to: None,
            page: Some(1),
            page_size: Some(20),
        }
        .validated("tenant-1".to_string())
        .expect_err("invalid datetime rejected");
        assert_eq!(err.status, StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[tokio::test]
    async fn dev_event_types_match_python_response_shape() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/event_types_response.json"))
                .expect("event types golden must be valid JSON");
        let service = DevEventLogService::new(vec![
            "gene.installed".to_string(),
            "workspace.message.created".to_string(),
        ]);

        let value = serde_json::to_value(
            service
                .list_event_types("tenant-1")
                .await
                .expect("dev service succeeds"),
        )
        .expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }
}
