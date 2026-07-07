//! P7 support strangler slice.
//!
//! Rust owns API-v1 and legacy support ticket list/detail/create/update/close.

use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;
use uuid::Uuid;

use agistack_adapters_postgres::{
    ClosedSupportTicketRecord, CreateSupportTicket, PgSupportRepository,
    SupportTicketListQuery as PgSupportTicketListQuery, SupportTicketRecord, UpdateSupportTicket,
};

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedSupport = Arc<dyn SupportService>;

#[async_trait]
pub(crate) trait SupportService: Send + Sync {
    async fn list_tickets(
        &self,
        user_id: &str,
        query: ValidatedSupportTicketListQuery,
    ) -> Result<SupportTicketListResponse, SupportApiError>;

    async fn get_ticket(
        &self,
        user_id: &str,
        ticket_id: &str,
    ) -> Result<SupportTicketView, SupportApiError>;

    async fn create_ticket(
        &self,
        user_id: &str,
        request: CreateSupportTicketRequest,
    ) -> Result<SupportTicketCreateResponse, SupportApiError>;

    async fn update_ticket(
        &self,
        user_id: &str,
        ticket_id: &str,
        request: UpdateSupportTicketRequest,
    ) -> Result<SupportTicketMutationResponse, SupportApiError>;

    async fn close_ticket(
        &self,
        user_id: &str,
        ticket_id: &str,
    ) -> Result<SupportTicketCloseResponse, SupportApiError>;
}

pub(crate) struct PgSupportService {
    repo: PgSupportRepository,
}

impl PgSupportService {
    pub(crate) fn new(repo: PgSupportRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl SupportService for PgSupportService {
    async fn list_tickets(
        &self,
        user_id: &str,
        query: ValidatedSupportTicketListQuery,
    ) -> Result<SupportTicketListResponse, SupportApiError> {
        if let Some(tenant_id) = query.tenant_id.as_deref() {
            require_support_tenant_access(&self.repo, user_id, tenant_id).await?;
        }
        let (tickets, total) = self
            .repo
            .list_tickets(PgSupportTicketListQuery {
                user_id,
                tenant_id: query.tenant_id.as_deref(),
                status: query.status.as_deref(),
                limit: query.limit,
                offset: query.offset,
            })
            .await
            .map_err(SupportApiError::internal)?;
        Ok(SupportTicketListResponse::from_records(
            tickets,
            total,
            query.limit,
            query.offset,
        ))
    }

    async fn get_ticket(
        &self,
        user_id: &str,
        ticket_id: &str,
    ) -> Result<SupportTicketView, SupportApiError> {
        self.repo
            .get_ticket(user_id, ticket_id)
            .await
            .map_err(SupportApiError::internal)?
            .map(SupportTicketView::from)
            .ok_or_else(|| SupportApiError::not_found("Ticket not found"))
    }

    async fn create_ticket(
        &self,
        user_id: &str,
        request: CreateSupportTicketRequest,
    ) -> Result<SupportTicketCreateResponse, SupportApiError> {
        if let Some(tenant_id) = request.tenant_id.as_deref() {
            require_support_tenant_access(&self.repo, user_id, tenant_id).await?;
        }
        let id = Uuid::new_v4().to_string();
        self.repo
            .create_ticket(CreateSupportTicket {
                id: &id,
                tenant_id: request.tenant_id.as_deref(),
                user_id,
                subject: &request.subject,
                message: &request.message,
                priority: request.priority.as_deref().unwrap_or("medium"),
            })
            .await
            .map_err(SupportApiError::internal)
            .map(SupportTicketCreateResponse::from)
    }

    async fn update_ticket(
        &self,
        user_id: &str,
        ticket_id: &str,
        request: UpdateSupportTicketRequest,
    ) -> Result<SupportTicketMutationResponse, SupportApiError> {
        self.repo
            .update_ticket(
                user_id,
                ticket_id,
                UpdateSupportTicket {
                    subject: request.subject.as_deref(),
                    message: request.message.as_deref(),
                    priority: request.priority.as_deref(),
                },
            )
            .await
            .map_err(SupportApiError::internal)?
            .map(SupportTicketMutationResponse::from)
            .ok_or_else(|| SupportApiError::not_found("Ticket not found"))
    }

    async fn close_ticket(
        &self,
        user_id: &str,
        ticket_id: &str,
    ) -> Result<SupportTicketCloseResponse, SupportApiError> {
        self.repo
            .close_ticket(user_id, ticket_id)
            .await
            .map_err(SupportApiError::internal)?
            .map(SupportTicketCloseResponse::from)
            .ok_or_else(|| SupportApiError::not_found("Ticket not found"))
    }
}

pub(crate) struct DevSupportService {
    tickets: Mutex<Vec<SupportTicketRecord>>,
}

impl DevSupportService {
    pub(crate) fn new(tickets: Vec<SupportTicketRecord>) -> Self {
        Self {
            tickets: Mutex::new(tickets),
        }
    }
}

impl Default for DevSupportService {
    fn default() -> Self {
        Self::new(Vec::new())
    }
}

#[async_trait]
impl SupportService for DevSupportService {
    async fn list_tickets(
        &self,
        user_id: &str,
        query: ValidatedSupportTicketListQuery,
    ) -> Result<SupportTicketListResponse, SupportApiError> {
        let tickets = self
            .tickets
            .lock()
            .map_err(|_| SupportApiError::internal("support ticket store lock poisoned"))?;
        let mut tickets = tickets
            .iter()
            .filter(|ticket| ticket.user_id == user_id)
            .filter(|ticket| {
                query
                    .tenant_id
                    .as_deref()
                    .is_none_or(|tenant_id| ticket.tenant_id.as_deref() == Some(tenant_id))
            })
            .filter(|ticket| {
                query
                    .status
                    .as_deref()
                    .is_none_or(|status| ticket.status == status)
            })
            .cloned()
            .collect::<Vec<_>>();
        tickets.sort_by(|left, right| {
            right
                .created_at
                .cmp(&left.created_at)
                .then_with(|| left.id.cmp(&right.id))
        });
        let total = tickets.len() as i64;
        let page = tickets
            .into_iter()
            .skip(query.offset as usize)
            .take(query.limit as usize)
            .collect();
        Ok(SupportTicketListResponse::from_records(
            page,
            total,
            query.limit,
            query.offset,
        ))
    }

    async fn get_ticket(
        &self,
        user_id: &str,
        ticket_id: &str,
    ) -> Result<SupportTicketView, SupportApiError> {
        let tickets = self
            .tickets
            .lock()
            .map_err(|_| SupportApiError::internal("support ticket store lock poisoned"))?;
        tickets
            .iter()
            .find(|ticket| ticket.user_id == user_id && ticket.id == ticket_id)
            .cloned()
            .map(SupportTicketView::from)
            .ok_or_else(|| SupportApiError::not_found("Ticket not found"))
    }

    async fn create_ticket(
        &self,
        user_id: &str,
        request: CreateSupportTicketRequest,
    ) -> Result<SupportTicketCreateResponse, SupportApiError> {
        let now = Utc::now();
        let record = SupportTicketRecord {
            id: Uuid::new_v4().to_string(),
            tenant_id: request.tenant_id,
            user_id: user_id.to_string(),
            subject: request.subject,
            message: request.message,
            priority: request.priority.unwrap_or_else(|| "medium".to_string()),
            status: "open".to_string(),
            created_at: now,
            updated_at: now,
            resolved_at: None,
        };
        self.tickets
            .lock()
            .map_err(|_| SupportApiError::internal("support ticket store lock poisoned"))?
            .push(record.clone());
        Ok(SupportTicketCreateResponse::from(record))
    }

    async fn update_ticket(
        &self,
        user_id: &str,
        ticket_id: &str,
        request: UpdateSupportTicketRequest,
    ) -> Result<SupportTicketMutationResponse, SupportApiError> {
        let mut tickets = self
            .tickets
            .lock()
            .map_err(|_| SupportApiError::internal("support ticket store lock poisoned"))?;
        let ticket = tickets
            .iter_mut()
            .find(|ticket| ticket.user_id == user_id && ticket.id == ticket_id)
            .ok_or_else(|| SupportApiError::not_found("Ticket not found"))?;
        if let Some(subject) = request.subject {
            ticket.subject = subject;
        }
        if let Some(message) = request.message {
            ticket.message = message;
        }
        if let Some(priority) = request.priority {
            ticket.priority = priority;
        }
        if ticket.status != "closed" {
            ticket.updated_at = Utc::now();
        }
        Ok(SupportTicketMutationResponse::from(ticket.clone()))
    }

    async fn close_ticket(
        &self,
        user_id: &str,
        ticket_id: &str,
    ) -> Result<SupportTicketCloseResponse, SupportApiError> {
        let mut tickets = self
            .tickets
            .lock()
            .map_err(|_| SupportApiError::internal("support ticket store lock poisoned"))?;
        let ticket = tickets
            .iter_mut()
            .find(|ticket| ticket.user_id == user_id && ticket.id == ticket_id)
            .ok_or_else(|| SupportApiError::not_found("Ticket not found"))?;
        let now = Utc::now();
        ticket.status = "closed".to_string();
        ticket.updated_at = now;
        ticket.resolved_at = Some(now);
        Ok(SupportTicketCloseResponse {
            id: ticket.id.clone(),
            status: ticket.status.clone(),
            resolved_at: iso8601(now),
        })
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route(
            "/api/v1/support/tickets",
            get(list_tickets).post(create_ticket),
        )
        .route(
            "/api/v1/support/tickets/:ticket_id",
            get(get_ticket).put(update_ticket),
        )
        .route(
            "/api/v1/support/tickets/:ticket_id/close",
            post(close_ticket),
        )
        .route("/support/tickets", get(list_tickets).post(create_ticket))
        .route(
            "/support/tickets/:ticket_id",
            get(get_ticket).put(update_ticket),
        )
        .route("/support/tickets/:ticket_id/close", post(close_ticket))
}

async fn list_tickets(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<SupportTicketListQuery>,
) -> Result<Json<SupportTicketListResponse>, SupportApiError> {
    let response = app
        .support
        .list_tickets(&identity.user_id, query.validated()?)
        .await?;
    Ok(Json(response))
}

async fn get_ticket(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(ticket_id): Path<String>,
) -> Result<Json<SupportTicketView>, SupportApiError> {
    let response = app
        .support
        .get_ticket(&identity.user_id, &ticket_id)
        .await?;
    Ok(Json(response))
}

async fn create_ticket(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(request): Json<CreateSupportTicketRequest>,
) -> Result<Json<SupportTicketCreateResponse>, SupportApiError> {
    let response = app
        .support
        .create_ticket(&identity.user_id, request)
        .await?;
    Ok(Json(response))
}

async fn update_ticket(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(ticket_id): Path<String>,
    Json(request): Json<UpdateSupportTicketRequest>,
) -> Result<Json<SupportTicketMutationResponse>, SupportApiError> {
    let response = app
        .support
        .update_ticket(&identity.user_id, &ticket_id, request)
        .await?;
    Ok(Json(response))
}

async fn close_ticket(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(ticket_id): Path<String>,
) -> Result<Json<SupportTicketCloseResponse>, SupportApiError> {
    let response = app
        .support
        .close_ticket(&identity.user_id, &ticket_id)
        .await?;
    Ok(Json(response))
}

async fn require_support_tenant_access(
    repo: &PgSupportRepository,
    user_id: &str,
    tenant_id: &str,
) -> Result<(), SupportApiError> {
    if repo
        .user_is_superuser(user_id)
        .await
        .map_err(SupportApiError::internal)?
    {
        return Ok(());
    }
    if repo
        .user_has_tenant_membership(user_id, tenant_id)
        .await
        .map_err(SupportApiError::internal)?
    {
        Ok(())
    } else {
        Err(SupportApiError::forbidden("Access denied"))
    }
}

#[derive(Debug, Clone, Deserialize)]
struct SupportTicketListQuery {
    tenant_id: Option<String>,
    status: Option<String>,
    limit: Option<i64>,
    offset: Option<i64>,
}

impl SupportTicketListQuery {
    fn validated(self) -> Result<ValidatedSupportTicketListQuery, SupportApiError> {
        let limit = self.limit.unwrap_or(25);
        if !(1..=100).contains(&limit) {
            return Err(SupportApiError::unprocessable(
                "limit must be greater than or equal to 1 and less than or equal to 100",
            ));
        }
        let offset = self.offset.unwrap_or(0);
        if offset < 0 {
            return Err(SupportApiError::unprocessable(
                "offset must be greater than or equal to 0",
            ));
        }
        Ok(ValidatedSupportTicketListQuery {
            tenant_id: non_empty(self.tenant_id),
            status: non_empty(self.status),
            limit,
            offset,
        })
    }
}

fn non_empty(value: Option<String>) -> Option<String> {
    value.filter(|value| !value.is_empty())
}

#[derive(Debug, Clone)]
pub(crate) struct ValidatedSupportTicketListQuery {
    tenant_id: Option<String>,
    status: Option<String>,
    limit: i64,
    offset: i64,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct CreateSupportTicketRequest {
    tenant_id: Option<String>,
    subject: String,
    message: String,
    priority: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct UpdateSupportTicketRequest {
    subject: Option<String>,
    message: Option<String>,
    priority: Option<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct SupportTicketView {
    id: String,
    tenant_id: Option<String>,
    subject: String,
    message: String,
    priority: String,
    status: String,
    created_at: String,
    updated_at: String,
    resolved_at: Option<String>,
}

impl From<SupportTicketRecord> for SupportTicketView {
    fn from(record: SupportTicketRecord) -> Self {
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            subject: record.subject,
            message: record.message,
            priority: record.priority,
            status: record.status,
            created_at: iso8601(record.created_at),
            updated_at: iso8601(record.updated_at),
            resolved_at: record.resolved_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct SupportTicketCreateResponse {
    id: String,
    subject: String,
    message: String,
    priority: String,
    status: String,
    created_at: String,
    updated_at: String,
}

impl From<SupportTicketRecord> for SupportTicketCreateResponse {
    fn from(record: SupportTicketRecord) -> Self {
        Self {
            id: record.id,
            subject: record.subject,
            message: record.message,
            priority: record.priority,
            status: record.status,
            created_at: iso8601(record.created_at),
            updated_at: iso8601(record.updated_at),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct SupportTicketMutationResponse {
    id: String,
    subject: String,
    message: String,
    priority: String,
    status: String,
    created_at: String,
    updated_at: String,
    resolved_at: Option<String>,
}

impl From<SupportTicketRecord> for SupportTicketMutationResponse {
    fn from(record: SupportTicketRecord) -> Self {
        Self {
            id: record.id,
            subject: record.subject,
            message: record.message,
            priority: record.priority,
            status: record.status,
            created_at: iso8601(record.created_at),
            updated_at: iso8601(record.updated_at),
            resolved_at: record.resolved_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct SupportTicketCloseResponse {
    id: String,
    status: String,
    resolved_at: String,
}

impl From<ClosedSupportTicketRecord> for SupportTicketCloseResponse {
    fn from(record: ClosedSupportTicketRecord) -> Self {
        Self {
            id: record.id,
            status: record.status,
            resolved_at: iso8601(record.resolved_at),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct SupportTicketListResponse {
    tickets: Vec<SupportTicketView>,
    total: i64,
    limit: i64,
    offset: i64,
    has_more: bool,
}

impl SupportTicketListResponse {
    fn from_records(
        records: Vec<SupportTicketRecord>,
        total: i64,
        limit: i64,
        offset: i64,
    ) -> Self {
        let returned = records.len() as i64;
        Self {
            tickets: records.into_iter().map(SupportTicketView::from).collect(),
            total,
            limit,
            offset,
            has_more: offset + returned < total,
        }
    }
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

#[derive(Debug)]
pub(crate) struct SupportApiError {
    status: StatusCode,
    detail: String,
}

impl SupportApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for SupportApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use serde_json::Value;

    fn ticket(id: &str, user_id: &str, created_at: DateTime<Utc>) -> SupportTicketRecord {
        SupportTicketRecord {
            id: id.to_string(),
            tenant_id: Some("tenant-1".to_string()),
            user_id: user_id.to_string(),
            subject: "Cannot access workspace".to_string(),
            message: "Workspace returns a permission error".to_string(),
            priority: "high".to_string(),
            status: "open".to_string(),
            created_at,
            updated_at: Utc.with_ymd_and_hms(2026, 1, 2, 0, 0, 0).unwrap(),
            resolved_at: None,
        }
    }

    #[test]
    fn support_ticket_list_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/support_ticket_list_response.json"
        ))
        .expect("support ticket list golden must be valid JSON");
        let response = SupportTicketListResponse::from_records(
            vec![ticket(
                "ticket-1",
                "user-1",
                Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
            )],
            2,
            1,
            0,
        );

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn support_ticket_detail_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/support_ticket_detail_response.json"
        ))
        .expect("support ticket detail golden must be valid JSON");
        let response = SupportTicketView::from(ticket(
            "ticket-1",
            "user-1",
            Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
        ));

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn support_ticket_create_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/support_ticket_create_response.json"
        ))
        .expect("support ticket create golden must be valid JSON");
        let response = SupportTicketCreateResponse::from(ticket(
            "ticket-1",
            "user-1",
            Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
        ));

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn support_ticket_update_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/support_ticket_update_response.json"
        ))
        .expect("support ticket update golden must be valid JSON");
        let response = SupportTicketMutationResponse::from(ticket(
            "ticket-1",
            "user-1",
            Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
        ));

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn support_ticket_close_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/support_ticket_close_response.json"
        ))
        .expect("support ticket close golden must be valid JSON");
        let response = SupportTicketCloseResponse::from(ClosedSupportTicketRecord {
            id: "ticket-1".to_string(),
            status: "closed".to_string(),
            resolved_at: Utc.with_ymd_and_hms(2026, 1, 3, 0, 0, 0).unwrap(),
        });

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn support_ticket_query_defaults_and_validates_like_python() {
        let query = SupportTicketListQuery {
            tenant_id: Some(String::new()),
            status: Some(String::new()),
            limit: None,
            offset: None,
        }
        .validated()
        .expect("query is valid");
        assert!(query.tenant_id.is_none());
        assert!(query.status.is_none());
        assert_eq!(query.limit, 25);
        assert_eq!(query.offset, 0);

        let err = SupportTicketListQuery {
            tenant_id: None,
            status: None,
            limit: Some(101),
            offset: Some(0),
        }
        .validated()
        .expect_err("limit above max rejected");
        assert_eq!(err.status, StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[tokio::test]
    async fn dev_support_service_filters_orders_and_paginates() {
        let service = DevSupportService::new(vec![
            ticket(
                "ticket-old",
                "user-1",
                Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
            ),
            ticket(
                "ticket-new",
                "user-1",
                Utc.with_ymd_and_hms(2026, 1, 2, 0, 0, 0).unwrap(),
            ),
            ticket(
                "ticket-other-user",
                "user-2",
                Utc.with_ymd_and_hms(2026, 1, 3, 0, 0, 0).unwrap(),
            ),
        ]);
        let query = SupportTicketListQuery {
            tenant_id: Some("tenant-1".to_string()),
            status: Some("open".to_string()),
            limit: Some(1),
            offset: Some(0),
        }
        .validated()
        .expect("query is valid");

        let response = service
            .list_tickets("user-1", query)
            .await
            .expect("dev service succeeds");

        assert_eq!(response.total, 2);
        assert!(response.has_more);
        assert_eq!(response.tickets.len(), 1);
        assert_eq!(response.tickets[0].id, "ticket-new");

        let detail = service
            .get_ticket("user-1", "ticket-new")
            .await
            .expect("detail succeeds");
        assert_eq!(detail.id, "ticket-new");

        let err = service
            .get_ticket("user-1", "ticket-other-user")
            .await
            .expect_err("other user's ticket is hidden");
        assert_eq!(err.status, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn dev_support_service_creates_updates_and_closes_tickets() {
        let service = DevSupportService::default();
        let created = service
            .create_ticket(
                "user-1",
                CreateSupportTicketRequest {
                    tenant_id: Some("tenant-1".to_string()),
                    subject: "Test Issue".to_string(),
                    message: "This is a test issue".to_string(),
                    priority: None,
                },
            )
            .await
            .expect("create succeeds");
        assert_eq!(created.priority, "medium");
        assert_eq!(created.status, "open");

        let updated = service
            .update_ticket(
                "user-1",
                &created.id,
                UpdateSupportTicketRequest {
                    subject: Some("Updated Issue".to_string()),
                    message: None,
                    priority: Some("high".to_string()),
                },
            )
            .await
            .expect("update succeeds");
        assert_eq!(updated.subject, "Updated Issue");
        assert_eq!(updated.priority, "high");

        let closed = service
            .close_ticket("user-1", &created.id)
            .await
            .expect("close succeeds");
        assert_eq!(closed.id, created.id);
        assert_eq!(closed.status, "closed");
    }
}
