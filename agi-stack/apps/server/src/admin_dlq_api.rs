//! P7 admin DLQ read-side strangler slice.
//!
//! Rust owns DLQ list/detail/stat reads plus retry/discard/cleanup mutations.

use std::collections::BTreeMap;
use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use agistack_adapters_postgres::PgAdminAccessRepository;
use agistack_adapters_redis::{
    DlqListQuery as RedisDlqListQuery, DlqMessageRecord, DlqStatsRecord, RedisDlqRepository,
};

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedAdminDlq = Arc<dyn AdminDlqService>;

#[async_trait]
pub(crate) trait AdminDlqService: Send + Sync {
    async fn list_messages(
        &self,
        user_id: &str,
        query: ValidatedDlqListQuery,
    ) -> Result<DlqListResponse, AdminDlqError>;

    async fn get_message(
        &self,
        user_id: &str,
        message_id: &str,
    ) -> Result<DlqMessageResponse, AdminDlqError>;

    async fn stats(&self, user_id: &str) -> Result<DlqStatsResponse, AdminDlqError>;

    async fn discard_message(
        &self,
        user_id: &str,
        message_id: &str,
        reason: &str,
    ) -> Result<DiscardSingleResponse, AdminDlqError>;

    async fn discard_messages(
        &self,
        user_id: &str,
        request: DiscardRequest,
    ) -> Result<DiscardResponse, AdminDlqError>;

    async fn retry_message(
        &self,
        user_id: &str,
        message_id: &str,
    ) -> Result<RetrySingleResponse, AdminDlqError>;

    async fn retry_messages(
        &self,
        user_id: &str,
        request: RetryRequest,
    ) -> Result<RetryResponse, AdminDlqError>;

    async fn cleanup_expired(
        &self,
        user_id: &str,
        older_than_hours: i64,
    ) -> Result<CleanupResponse, AdminDlqError>;

    async fn cleanup_resolved(
        &self,
        user_id: &str,
        older_than_hours: i64,
    ) -> Result<CleanupResponse, AdminDlqError>;
}

#[async_trait]
pub(crate) trait AdminAccessService: Send + Sync {
    async fn user_has_admin_access(&self, user_id: &str) -> Result<bool, AdminDlqError>;
}

struct PgAdminAccessService {
    repo: PgAdminAccessRepository,
}

impl PgAdminAccessService {
    fn new(repo: PgAdminAccessRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl AdminAccessService for PgAdminAccessService {
    async fn user_has_admin_access(&self, user_id: &str) -> Result<bool, AdminDlqError> {
        self.repo
            .user_has_admin_access(user_id)
            .await
            .map_err(AdminDlqError::internal)
    }
}

struct DevAdminAccessService {
    admin_user_id: String,
}

impl DevAdminAccessService {
    fn new(admin_user_id: impl Into<String>) -> Self {
        Self {
            admin_user_id: admin_user_id.into(),
        }
    }
}

#[async_trait]
impl AdminAccessService for DevAdminAccessService {
    async fn user_has_admin_access(&self, user_id: &str) -> Result<bool, AdminDlqError> {
        Ok(user_id == self.admin_user_id)
    }
}

pub(crate) struct RedisAdminDlqService {
    repo: RedisDlqRepository,
    access: Arc<dyn AdminAccessService>,
}

impl RedisAdminDlqService {
    pub(crate) fn new(repo: RedisDlqRepository, access: Arc<dyn AdminAccessService>) -> Self {
        Self { repo, access }
    }
}

#[async_trait]
impl AdminDlqService for RedisAdminDlqService {
    async fn list_messages(
        &self,
        user_id: &str,
        query: ValidatedDlqListQuery,
    ) -> Result<DlqListResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        let redis_query = query.redis_query();
        let total = self
            .repo
            .count_messages(redis_query)
            .await
            .map_err(AdminDlqError::internal)?;
        let messages = self
            .repo
            .list_messages(redis_query)
            .await
            .map_err(AdminDlqError::internal)?;
        DlqListResponse::from_records(messages, total, query.limit, query.offset, Utc::now())
    }

    async fn get_message(
        &self,
        user_id: &str,
        message_id: &str,
    ) -> Result<DlqMessageResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        let record = self
            .repo
            .get_message(message_id)
            .await
            .map_err(AdminDlqError::internal)?
            .ok_or_else(|| AdminDlqError::not_found("DLQ message not found"))?;
        DlqMessageResponse::from_record(record, Utc::now())
    }

    async fn stats(&self, user_id: &str) -> Result<DlqStatsResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        self.repo
            .stats()
            .await
            .map(DlqStatsResponse::from)
            .map_err(AdminDlqError::internal)
    }

    async fn discard_message(
        &self,
        user_id: &str,
        message_id: &str,
        reason: &str,
    ) -> Result<DiscardSingleResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        let success = self
            .repo
            .discard_message(message_id, reason, &iso8601(Utc::now()))
            .await
            .map_err(AdminDlqError::internal)?
            .ok_or_else(|| AdminDlqError::not_found("DLQ message not found"))?;
        Ok(DiscardSingleResponse {
            message_id: message_id.to_string(),
            success,
            message: if success {
                "Message discarded".to_string()
            } else {
                "Discard failed".to_string()
            },
        })
    }

    async fn discard_messages(
        &self,
        user_id: &str,
        request: DiscardRequest,
    ) -> Result<DiscardResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        let discarded_at = iso8601(Utc::now());
        let results = self
            .repo
            .discard_batch(&request.message_ids, &request.reason, &discarded_at)
            .await
            .map_err(AdminDlqError::internal)?;
        Ok(DiscardResponse::from_results(results))
    }

    async fn retry_message(
        &self,
        user_id: &str,
        message_id: &str,
    ) -> Result<RetrySingleResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        let success = self
            .repo
            .retry_message(message_id)
            .await
            .map_err(AdminDlqError::internal)?
            .ok_or_else(|| AdminDlqError::not_found("DLQ message not found"))?;
        Ok(RetrySingleResponse::from_result(message_id, success))
    }

    async fn retry_messages(
        &self,
        user_id: &str,
        request: RetryRequest,
    ) -> Result<RetryResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        self.repo
            .retry_batch(&request.message_ids)
            .await
            .map(RetryResponse::from_results)
            .map_err(AdminDlqError::internal)
    }

    async fn cleanup_expired(
        &self,
        user_id: &str,
        older_than_hours: i64,
    ) -> Result<CleanupResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        self.repo
            .cleanup_expired(older_than_hours)
            .await
            .map(|cleaned_count| CleanupResponse { cleaned_count })
            .map_err(AdminDlqError::internal)
    }

    async fn cleanup_resolved(
        &self,
        user_id: &str,
        older_than_hours: i64,
    ) -> Result<CleanupResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        self.repo
            .cleanup_resolved(older_than_hours)
            .await
            .map(|cleaned_count| CleanupResponse { cleaned_count })
            .map_err(AdminDlqError::internal)
    }
}

pub(crate) struct DevAdminDlqService {
    messages: Vec<DlqMessageRecord>,
    stats: DlqStatsRecord,
    access: Arc<dyn AdminAccessService>,
}

impl DevAdminDlqService {
    pub(crate) fn empty(admin_user_id: impl Into<String>) -> Self {
        Self {
            messages: Vec::new(),
            stats: empty_stats(),
            access: Arc::new(DevAdminAccessService::new(admin_user_id)),
        }
    }

    #[cfg(test)]
    pub(crate) fn new(
        messages: Vec<DlqMessageRecord>,
        stats: DlqStatsRecord,
        access: Arc<dyn AdminAccessService>,
    ) -> Self {
        Self {
            messages,
            stats,
            access,
        }
    }
}

#[async_trait]
impl AdminDlqService for DevAdminDlqService {
    async fn list_messages(
        &self,
        user_id: &str,
        query: ValidatedDlqListQuery,
    ) -> Result<DlqListResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        let mut messages = self
            .messages
            .iter()
            .filter(|message| {
                query
                    .status
                    .as_deref()
                    .is_none_or(|status| message.status == status)
            })
            .filter(|message| {
                query
                    .event_type
                    .as_deref()
                    .is_none_or(|event_type| message.event_type == event_type)
            })
            .filter(|message| {
                query
                    .error_type
                    .as_deref()
                    .is_none_or(|error_type| message.error_type == error_type)
            })
            .filter(|message| {
                query
                    .routing_key
                    .as_deref()
                    .is_none_or(|routing_key| message.routing_key == routing_key)
            })
            .cloned()
            .collect::<Vec<_>>();
        messages.sort_by(|left, right| right.first_failed_at.cmp(&left.first_failed_at));
        let total = messages.len() as i64;
        let page = messages
            .into_iter()
            .skip(query.offset as usize)
            .take(query.limit as usize)
            .collect();
        DlqListResponse::from_records(page, total, query.limit, query.offset, Utc::now())
    }

    async fn get_message(
        &self,
        user_id: &str,
        message_id: &str,
    ) -> Result<DlqMessageResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        let record = self
            .messages
            .iter()
            .find(|message| message.id == message_id)
            .cloned()
            .ok_or_else(|| AdminDlqError::not_found("DLQ message not found"))?;
        DlqMessageResponse::from_record(record, Utc::now())
    }

    async fn stats(&self, user_id: &str) -> Result<DlqStatsResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        Ok(DlqStatsResponse::from(self.stats.clone()))
    }

    async fn discard_message(
        &self,
        user_id: &str,
        message_id: &str,
        _reason: &str,
    ) -> Result<DiscardSingleResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        if self.messages.iter().any(|message| message.id == message_id) {
            Ok(DiscardSingleResponse {
                message_id: message_id.to_string(),
                success: true,
                message: "Message discarded".to_string(),
            })
        } else {
            Err(AdminDlqError::not_found("DLQ message not found"))
        }
    }

    async fn discard_messages(
        &self,
        user_id: &str,
        request: DiscardRequest,
    ) -> Result<DiscardResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        let results = request
            .message_ids
            .into_iter()
            .map(|message_id| {
                let success = self.messages.iter().any(|message| message.id == message_id);
                (message_id, success)
            })
            .collect();
        Ok(DiscardResponse::from_results(results))
    }

    async fn retry_message(
        &self,
        user_id: &str,
        message_id: &str,
    ) -> Result<RetrySingleResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        let record = self
            .messages
            .iter()
            .find(|message| message.id == message_id)
            .ok_or_else(|| AdminDlqError::not_found("DLQ message not found"))?;
        let success = record.status == "pending" && record.retry_count < record.max_retries;
        if !success {
            return Err(AdminDlqError::internal(format!(
                "Cannot retry: status={}, retries={}/{}",
                record.status, record.retry_count, record.max_retries
            )));
        }
        Ok(RetrySingleResponse::from_result(message_id, success))
    }

    async fn retry_messages(
        &self,
        user_id: &str,
        request: RetryRequest,
    ) -> Result<RetryResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        let results = request
            .message_ids
            .into_iter()
            .map(|message_id| {
                let success = self.messages.iter().any(|message| {
                    message.id == message_id
                        && message.status == "pending"
                        && message.retry_count < message.max_retries
                });
                (message_id, success)
            })
            .collect();
        Ok(RetryResponse::from_results(results))
    }

    async fn cleanup_expired(
        &self,
        user_id: &str,
        _older_than_hours: i64,
    ) -> Result<CleanupResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        Ok(CleanupResponse {
            cleaned_count: self
                .messages
                .iter()
                .filter(|message| message.status == "pending")
                .count() as i64,
        })
    }

    async fn cleanup_resolved(
        &self,
        user_id: &str,
        _older_than_hours: i64,
    ) -> Result<CleanupResponse, AdminDlqError> {
        ensure_admin_access(&*self.access, user_id).await?;
        Ok(CleanupResponse {
            cleaned_count: self
                .messages
                .iter()
                .filter(|message| message.status == "resolved")
                .count() as i64,
        })
    }
}

pub(crate) async fn build_admin_dlq_service(
    pool: Option<agistack_adapters_postgres::PgPool>,
) -> SharedAdminDlq {
    let access: Arc<dyn AdminAccessService> = match pool {
        Some(pool) => Arc::new(PgAdminAccessService::new(PgAdminAccessRepository::new(
            pool,
        ))),
        None => Arc::new(DevAdminAccessService::new("dev-user")),
    };

    match std::env::var("REDIS_URL") {
        Ok(url) if !url.is_empty() => match RedisDlqRepository::connect(&url).await {
            Ok(repo) => {
                eprintln!("[agistack] admin DLQ reads: Redis via REDIS_URL");
                Arc::new(RedisAdminDlqService::new(repo, access))
            }
            Err(err) => {
                eprintln!(
                    "[agistack] admin DLQ reads: Redis unavailable ({err}); falling back to empty dev DLQ"
                );
                Arc::new(DevAdminDlqService::empty("dev-user"))
            }
        },
        _ => {
            eprintln!("[agistack] admin DLQ reads: empty dev DLQ");
            Arc::new(DevAdminDlqService::empty("dev-user"))
        }
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/admin/dlq/messages", get(list_messages))
        .route("/api/v1/admin/dlq/messages/", get(list_messages))
        .route("/api/v1/admin/dlq/messages/retry", post(retry_messages))
        .route("/api/v1/admin/dlq/messages/discard", post(discard_messages))
        .route(
            "/api/v1/admin/dlq/messages/:message_id/retry",
            post(retry_message),
        )
        .route(
            "/api/v1/admin/dlq/messages/:message_id",
            get(get_message).delete(discard_message),
        )
        .route("/api/v1/admin/dlq/cleanup/expired", post(cleanup_expired))
        .route("/api/v1/admin/dlq/cleanup/resolved", post(cleanup_resolved))
        .route("/api/v1/admin/dlq/stats", get(stats))
        .route("/api/v1/admin/dlq/stats/", get(stats))
}

async fn list_messages(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<DlqListQuery>,
) -> Result<Json<DlqListResponse>, AdminDlqError> {
    let response = app
        .admin_dlq
        .list_messages(&identity.user_id, query.validated()?)
        .await?;
    Ok(Json(response))
}

async fn get_message(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(message_id): Path<String>,
) -> Result<Json<DlqMessageResponse>, AdminDlqError> {
    Ok(Json(
        app.admin_dlq
            .get_message(&identity.user_id, &message_id)
            .await?,
    ))
}

async fn stats(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
) -> Result<Json<DlqStatsResponse>, AdminDlqError> {
    Ok(Json(app.admin_dlq.stats(&identity.user_id).await?))
}

async fn discard_message(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(message_id): Path<String>,
    Query(query): Query<DiscardMessageQuery>,
) -> Result<Json<DiscardSingleResponse>, AdminDlqError> {
    let reason = validate_reason(query.reason)?;
    Ok(Json(
        app.admin_dlq
            .discard_message(&identity.user_id, &message_id, &reason)
            .await?,
    ))
}

async fn discard_messages(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(request): Json<DiscardRequest>,
) -> Result<Json<DiscardResponse>, AdminDlqError> {
    let request = request.validated()?;
    Ok(Json(
        app.admin_dlq
            .discard_messages(&identity.user_id, request)
            .await?,
    ))
}

async fn retry_message(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(message_id): Path<String>,
) -> Result<Json<RetrySingleResponse>, AdminDlqError> {
    Ok(Json(
        app.admin_dlq
            .retry_message(&identity.user_id, &message_id)
            .await?,
    ))
}

async fn retry_messages(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(request): Json<RetryRequest>,
) -> Result<Json<RetryResponse>, AdminDlqError> {
    let request = request.validated()?;
    Ok(Json(
        app.admin_dlq
            .retry_messages(&identity.user_id, request)
            .await?,
    ))
}

async fn cleanup_expired(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<CleanupExpiredQuery>,
) -> Result<Json<CleanupResponse>, AdminDlqError> {
    Ok(Json(
        app.admin_dlq
            .cleanup_expired(&identity.user_id, query.validated()?)
            .await?,
    ))
}

async fn cleanup_resolved(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<CleanupResolvedQuery>,
) -> Result<Json<CleanupResponse>, AdminDlqError> {
    Ok(Json(
        app.admin_dlq
            .cleanup_resolved(&identity.user_id, query.validated()?)
            .await?,
    ))
}

async fn ensure_admin_access(
    access: &dyn AdminAccessService,
    user_id: &str,
) -> Result<(), AdminDlqError> {
    if access.user_has_admin_access(user_id).await? {
        Ok(())
    } else {
        Err(AdminDlqError::forbidden("Admin access required"))
    }
}

#[derive(Debug, Clone, Deserialize)]
struct DlqListQuery {
    #[serde(rename = "status")]
    filter_status: Option<String>,
    event_type: Option<String>,
    error_type: Option<String>,
    routing_key: Option<String>,
    limit: Option<i64>,
    offset: Option<i64>,
}

impl DlqListQuery {
    fn validated(self) -> Result<ValidatedDlqListQuery, AdminDlqError> {
        let status = self
            .filter_status
            .map(|status| validate_status(&status))
            .transpose()?;
        let limit = self.limit.unwrap_or(50);
        if !(1..=100).contains(&limit) {
            return Err(AdminDlqError::unprocessable(
                "limit must be greater than or equal to 1 and less than or equal to 100",
            ));
        }
        let offset = self.offset.unwrap_or(0);
        if offset < 0 {
            return Err(AdminDlqError::unprocessable(
                "offset must be greater than or equal to 0",
            ));
        }
        Ok(ValidatedDlqListQuery {
            status,
            event_type: blank_to_none(self.event_type),
            error_type: blank_to_none(self.error_type),
            routing_key: blank_to_none(self.routing_key),
            limit,
            offset,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ValidatedDlqListQuery {
    status: Option<String>,
    event_type: Option<String>,
    error_type: Option<String>,
    routing_key: Option<String>,
    limit: i64,
    offset: i64,
}

impl ValidatedDlqListQuery {
    fn redis_query(&self) -> RedisDlqListQuery<'_> {
        RedisDlqListQuery {
            status: self.status.as_deref(),
            event_type: self.event_type.as_deref(),
            error_type: self.error_type.as_deref(),
            routing_key_pattern: self.routing_key.as_deref(),
            limit: self.limit,
            offset: self.offset,
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
struct DiscardMessageQuery {
    reason: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct DiscardRequest {
    message_ids: Vec<String>,
    reason: String,
}

impl DiscardRequest {
    fn validated(self) -> Result<Self, AdminDlqError> {
        validate_message_ids(&self.message_ids)?;
        let reason = validate_reason(self.reason)?;
        Ok(Self {
            message_ids: self.message_ids,
            reason,
        })
    }
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct RetryRequest {
    message_ids: Vec<String>,
}

impl RetryRequest {
    fn validated(self) -> Result<Self, AdminDlqError> {
        validate_message_ids(&self.message_ids)?;
        Ok(self)
    }
}

#[derive(Debug, Clone, Deserialize)]
struct CleanupExpiredQuery {
    older_than_hours: Option<i64>,
}

impl CleanupExpiredQuery {
    fn validated(self) -> Result<i64, AdminDlqError> {
        validate_hours(self.older_than_hours.unwrap_or(168), 1, 720)
    }
}

#[derive(Debug, Clone, Deserialize)]
struct CleanupResolvedQuery {
    older_than_hours: Option<i64>,
}

impl CleanupResolvedQuery {
    fn validated(self) -> Result<i64, AdminDlqError> {
        validate_hours(self.older_than_hours.unwrap_or(24), 1, 168)
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct DlqMessageResponse {
    id: String,
    event_id: String,
    event_type: String,
    event_data: String,
    routing_key: String,
    error: String,
    error_type: String,
    error_traceback: Option<String>,
    retry_count: i64,
    max_retries: i64,
    first_failed_at: String,
    last_failed_at: String,
    next_retry_at: Option<String>,
    status: String,
    metadata: Value,
    can_retry: bool,
    age_seconds: f64,
}

impl DlqMessageResponse {
    fn from_record(record: DlqMessageRecord, now: DateTime<Utc>) -> Result<Self, AdminDlqError> {
        let first_failed_at = parse_python_time(&record.first_failed_at)?;
        let last_failed_at = parse_python_time(&record.last_failed_at)?;
        let next_retry_at = record
            .next_retry_at
            .as_deref()
            .map(parse_python_time)
            .transpose()?;
        Ok(Self {
            id: record.id,
            event_id: record.event_id,
            event_type: record.event_type,
            event_data: record.event_data,
            routing_key: record.routing_key,
            error: record.error,
            error_type: record.error_type,
            error_traceback: record.error_traceback,
            retry_count: record.retry_count,
            max_retries: record.max_retries,
            first_failed_at: iso8601(first_failed_at),
            last_failed_at: iso8601(last_failed_at),
            next_retry_at: next_retry_at.map(iso8601),
            can_retry: record.status == "pending" && record.retry_count < record.max_retries,
            age_seconds: (now - first_failed_at).num_milliseconds().max(0) as f64 / 1000.0,
            status: record.status,
            metadata: record.metadata,
        })
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct DlqListResponse {
    messages: Vec<DlqMessageResponse>,
    total: i64,
    limit: i64,
    offset: i64,
}

impl DlqListResponse {
    fn from_records(
        records: Vec<DlqMessageRecord>,
        total: i64,
        limit: i64,
        offset: i64,
        now: DateTime<Utc>,
    ) -> Result<Self, AdminDlqError> {
        Ok(Self {
            messages: records
                .into_iter()
                .map(|record| DlqMessageResponse::from_record(record, now))
                .collect::<Result<Vec<_>, _>>()?,
            total,
            limit,
            offset,
        })
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct DlqStatsResponse {
    total_messages: i64,
    pending_count: i64,
    retrying_count: i64,
    discarded_count: i64,
    expired_count: i64,
    resolved_count: i64,
    oldest_message_age_seconds: f64,
    error_type_counts: BTreeMap<String, i64>,
    event_type_counts: BTreeMap<String, i64>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub(crate) struct DiscardSingleResponse {
    message_id: String,
    success: bool,
    message: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub(crate) struct RetrySingleResponse {
    message_id: String,
    success: bool,
    message: String,
}

impl RetrySingleResponse {
    fn from_result(message_id: &str, success: bool) -> Self {
        Self {
            message_id: message_id.to_string(),
            success,
            message: if success {
                "Retry initiated".to_string()
            } else {
                "Retry failed".to_string()
            },
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub(crate) struct DiscardResponse {
    results: BTreeMap<String, bool>,
    success_count: i64,
    failure_count: i64,
}

impl DiscardResponse {
    fn from_results(results: BTreeMap<String, bool>) -> Self {
        let success_count = results.values().filter(|success| **success).count() as i64;
        let failure_count = results.len() as i64 - success_count;
        Self {
            results,
            success_count,
            failure_count,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub(crate) struct RetryResponse {
    results: BTreeMap<String, bool>,
    success_count: i64,
    failure_count: i64,
}

impl RetryResponse {
    fn from_results(results: BTreeMap<String, bool>) -> Self {
        let success_count = results.values().filter(|success| **success).count() as i64;
        let failure_count = results.len() as i64 - success_count;
        Self {
            results,
            success_count,
            failure_count,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub(crate) struct CleanupResponse {
    cleaned_count: i64,
}

impl From<DlqStatsRecord> for DlqStatsResponse {
    fn from(record: DlqStatsRecord) -> Self {
        Self {
            total_messages: record.total_messages,
            pending_count: record.pending_count,
            retrying_count: record.retrying_count,
            discarded_count: record.discarded_count,
            expired_count: record.expired_count,
            resolved_count: record.resolved_count,
            oldest_message_age_seconds: record.oldest_message_age_seconds,
            error_type_counts: record.error_type_counts,
            event_type_counts: record.event_type_counts,
        }
    }
}

fn validate_status(value: &str) -> Result<String, AdminDlqError> {
    let trimmed = value.trim();
    if matches!(
        trimmed,
        "pending" | "retrying" | "discarded" | "expired" | "resolved"
    ) {
        Ok(trimmed.to_string())
    } else {
        Err(AdminDlqError::bad_request("Invalid DLQ status"))
    }
}

fn validate_message_ids(message_ids: &[String]) -> Result<(), AdminDlqError> {
    if (1..=100).contains(&message_ids.len()) {
        Ok(())
    } else {
        Err(AdminDlqError::unprocessable(
            "message_ids must contain between 1 and 100 items",
        ))
    }
}

fn validate_reason(value: String) -> Result<String, AdminDlqError> {
    let trimmed = value.trim();
    if (1..=500).contains(&trimmed.chars().count()) {
        Ok(trimmed.to_string())
    } else {
        Err(AdminDlqError::unprocessable(
            "reason must contain between 1 and 500 characters",
        ))
    }
}

fn validate_hours(value: i64, min: i64, max: i64) -> Result<i64, AdminDlqError> {
    if (min..=max).contains(&value) {
        Ok(value)
    } else {
        Err(AdminDlqError::unprocessable(format!(
            "older_than_hours must be greater than or equal to {min} and less than or equal to {max}"
        )))
    }
}

fn blank_to_none(value: Option<String>) -> Option<String> {
    value.and_then(|raw| {
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        }
    })
}

fn parse_python_time(value: &str) -> Result<DateTime<Utc>, AdminDlqError> {
    DateTime::parse_from_rfc3339(value)
        .map(|value| value.with_timezone(&Utc))
        .map_err(|e| AdminDlqError::internal(format!("parse DLQ timestamp: {e}")))
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::AutoSi, true)
}

fn empty_stats() -> DlqStatsRecord {
    DlqStatsRecord {
        total_messages: 0,
        pending_count: 0,
        retrying_count: 0,
        discarded_count: 0,
        expired_count: 0,
        resolved_count: 0,
        oldest_message_age_seconds: 0.0,
        error_type_counts: BTreeMap::new(),
        event_type_counts: BTreeMap::new(),
    }
}

#[derive(Debug)]
pub(crate) struct AdminDlqError {
    status: StatusCode,
    detail: String,
}

impl AdminDlqError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
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

impl IntoResponse for AdminDlqError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    struct TestAccess(bool);

    #[async_trait]
    impl AdminAccessService for TestAccess {
        async fn user_has_admin_access(&self, _user_id: &str) -> Result<bool, AdminDlqError> {
            Ok(self.0)
        }
    }

    fn message(id: &str, status: &str, retry_count: i64) -> DlqMessageRecord {
        DlqMessageRecord {
            id: id.to_string(),
            event_id: "event-1".to_string(),
            event_type: "agent.failed".to_string(),
            event_data: "{\"type\":\"agent.failed\"}".to_string(),
            routing_key: "agent.events.failed".to_string(),
            error: "boom".to_string(),
            error_type: "RuntimeError".to_string(),
            error_traceback: Some("traceback".to_string()),
            retry_count,
            max_retries: 3,
            first_failed_at: "2026-01-02T03:04:05+00:00".to_string(),
            last_failed_at: "2026-01-02T03:05:05+00:00".to_string(),
            next_retry_at: Some("2026-01-02T03:06:05+00:00".to_string()),
            status: status.to_string(),
            metadata: json!({"consumer": "events"}),
        }
    }

    fn stats_record() -> DlqStatsRecord {
        DlqStatsRecord {
            total_messages: 2,
            pending_count: 1,
            retrying_count: 0,
            discarded_count: 0,
            expired_count: 0,
            resolved_count: 1,
            oldest_message_age_seconds: 42.0,
            error_type_counts: BTreeMap::from([("RuntimeError".to_string(), 2)]),
            event_type_counts: BTreeMap::from([("agent.failed".to_string(), 2)]),
        }
    }

    #[tokio::test]
    async fn dev_service_lists_details_stats_and_enforces_admin() {
        let service = DevAdminDlqService::new(
            vec![
                message("dlq-1", "pending", 1),
                message("dlq-2", "resolved", 3),
            ],
            stats_record(),
            Arc::new(TestAccess(true)),
        );
        let list = service
            .list_messages(
                "admin-user",
                ValidatedDlqListQuery {
                    status: Some("pending".to_string()),
                    event_type: None,
                    error_type: None,
                    routing_key: None,
                    limit: 50,
                    offset: 0,
                },
            )
            .await
            .expect("list messages");
        assert_eq!(list.total, 1);
        assert_eq!(list.messages[0].id, "dlq-1");
        assert!(list.messages[0].can_retry);

        let detail = service
            .get_message("admin-user", "dlq-2")
            .await
            .expect("get message");
        assert!(!detail.can_retry);
        let stats = service.stats("admin-user").await.expect("stats");
        assert_eq!(stats.total_messages, 2);
        let discarded = service
            .discard_message("admin-user", "dlq-1", "operator decision")
            .await
            .expect("discard message");
        assert_eq!(discarded.message, "Message discarded");
        let batch = service
            .discard_messages(
                "admin-user",
                DiscardRequest {
                    message_ids: vec!["dlq-1".to_string(), "dlq-missing".to_string()],
                    reason: "operator decision".to_string(),
                },
            )
            .await
            .expect("discard batch");
        assert_eq!(batch.success_count, 1);
        assert_eq!(batch.failure_count, 1);
        let retry = service
            .retry_message("admin-user", "dlq-1")
            .await
            .expect("retry message");
        assert_eq!(retry.message, "Retry initiated");
        let retry_batch = service
            .retry_messages(
                "admin-user",
                RetryRequest {
                    message_ids: vec!["dlq-1".to_string(), "dlq-2".to_string()],
                },
            )
            .await
            .expect("retry batch");
        assert_eq!(retry_batch.success_count, 1);
        assert_eq!(retry_batch.failure_count, 1);
        assert_eq!(
            service
                .cleanup_expired("admin-user", 168)
                .await
                .expect("cleanup expired")
                .cleaned_count,
            1
        );
        assert_eq!(
            service
                .cleanup_resolved("admin-user", 24)
                .await
                .expect("cleanup resolved")
                .cleaned_count,
            1
        );

        let denied =
            DevAdminDlqService::new(Vec::new(), empty_stats(), Arc::new(TestAccess(false)))
                .stats("user")
                .await
                .expect_err("non-admin rejected");
        assert_eq!(denied.status, StatusCode::FORBIDDEN);
    }

    #[test]
    fn invalid_status_matches_python_error() {
        let err = DlqListQuery {
            filter_status: Some("lost".to_string()),
            event_type: None,
            error_type: None,
            routing_key: None,
            limit: None,
            offset: None,
        }
        .validated()
        .expect_err("invalid status");
        assert_eq!(err.status, StatusCode::BAD_REQUEST);
        assert_eq!(err.detail, "Invalid DLQ status");
    }

    #[test]
    fn discard_request_validation_matches_bounds() {
        let empty = DiscardRequest {
            message_ids: Vec::new(),
            reason: "operator".to_string(),
        }
        .validated()
        .expect_err("empty ids rejected");
        assert_eq!(empty.status, StatusCode::UNPROCESSABLE_ENTITY);

        let blank_reason = validate_reason("   ".to_string()).expect_err("blank reason rejected");
        assert_eq!(blank_reason.status, StatusCode::UNPROCESSABLE_ENTITY);
        let empty_retry = RetryRequest {
            message_ids: Vec::new(),
        }
        .validated()
        .expect_err("empty retry ids rejected");
        assert_eq!(empty_retry.status, StatusCode::UNPROCESSABLE_ENTITY);
        let bad_hours = validate_hours(721, 1, 720).expect_err("hours bound rejected");
        assert_eq!(bad_hours.status, StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[test]
    fn dlq_list_response_matches_golden() {
        let now = Utc.with_ymd_and_hms(2026, 1, 2, 3, 10, 5).unwrap();
        let value = serde_json::to_value(
            DlqListResponse::from_records(vec![message("dlq-1", "pending", 1)], 1, 50, 0, now)
                .expect("render list"),
        )
        .expect("serialize list");
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/admin_dlq_list_response.json"))
                .expect("DLQ list golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn dlq_stats_response_matches_golden() {
        let value =
            serde_json::to_value(DlqStatsResponse::from(stats_record())).expect("serialize stats");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/admin_dlq_stats_response.json"
        ))
        .expect("DLQ stats golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn dlq_discard_response_matches_golden() {
        let value = serde_json::to_value(DiscardResponse::from_results(BTreeMap::from([
            ("dlq-1".to_string(), true),
            ("dlq-missing".to_string(), false),
        ])))
        .expect("serialize discard response");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/admin_dlq_discard_response.json"
        ))
        .expect("DLQ discard golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn dlq_retry_response_matches_golden() {
        let value = serde_json::to_value(RetrySingleResponse::from_result("dlq-1", true))
            .expect("serialize retry response");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/admin_dlq_retry_response.json"
        ))
        .expect("DLQ retry golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn dlq_retry_batch_response_matches_golden() {
        let value = serde_json::to_value(RetryResponse::from_results(BTreeMap::from([
            ("dlq-1".to_string(), true),
            ("dlq-missing".to_string(), false),
        ])))
        .expect("serialize retry batch response");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/admin_dlq_retry_batch_response.json"
        ))
        .expect("DLQ retry batch golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn dlq_cleanup_response_matches_golden() {
        let value = serde_json::to_value(CleanupResponse { cleaned_count: 2 })
            .expect("serialize cleanup response");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/admin_dlq_cleanup_response.json"
        ))
        .expect("DLQ cleanup golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }
}
