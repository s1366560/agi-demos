//! P7 tenant audit-log strangler slice.
//!
//! Rust owns tenant-scoped audit list/filter/runtime-hook summary reads. Audit
//! export and write-side logging remain Python-owned.

use std::collections::BTreeMap;
use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::{
        header::{CONTENT_DISPOSITION, CONTENT_TYPE},
        StatusCode,
    },
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;

use agistack_adapters_postgres::{
    AuditLogListQuery as PgAuditLogListQuery, AuditLogRecord, PgAuditLogRepository,
    RuntimeHookAuditQuery as PgRuntimeHookAuditQuery, RuntimeHookAuditSummaryRecord,
};

use crate::auth::Identity;
use crate::AppState;

const AUDIT_EXPORT_LIMIT: i64 = 10_000;
const AUDIT_EXPORT_COLUMNS: &[&str] = &[
    "id",
    "timestamp",
    "actor",
    "action",
    "resource_type",
    "resource_id",
    "tenant_id",
    "details",
    "ip_address",
    "user_agent",
];

pub(crate) type SharedAuditLogs = Arc<dyn AuditLogService>;

#[async_trait]
pub(crate) trait AuditLogService: Send + Sync {
    async fn list_audit_logs(
        &self,
        user_id: &str,
        tenant_id: &str,
        query: ValidatedAuditLogQuery,
    ) -> Result<AuditLogListResponse, AuditApiError>;

    async fn list_runtime_hook_logs(
        &self,
        user_id: &str,
        tenant_id: &str,
        query: ValidatedRuntimeHookAuditQuery,
    ) -> Result<AuditLogListResponse, AuditApiError>;

    async fn summarize_runtime_hook_logs(
        &self,
        user_id: &str,
        tenant_id: &str,
        query: ValidatedRuntimeHookAuditQuery,
    ) -> Result<RuntimeHookAuditSummaryView, AuditApiError>;

    async fn export_audit_logs(
        &self,
        user_id: &str,
        tenant_id: &str,
        query: ValidatedAuditExportQuery,
    ) -> Result<AuditExportResponse, AuditApiError>;
}

pub(crate) struct PgAuditLogService {
    repo: PgAuditLogRepository,
}

impl PgAuditLogService {
    pub(crate) fn new(repo: PgAuditLogRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl AuditLogService for PgAuditLogService {
    async fn list_audit_logs(
        &self,
        user_id: &str,
        tenant_id: &str,
        query: ValidatedAuditLogQuery,
    ) -> Result<AuditLogListResponse, AuditApiError> {
        require_tenant_access(&self.repo, user_id, tenant_id).await?;
        let (records, total) = self
            .repo
            .list_audit_logs(PgAuditLogListQuery {
                tenant_id,
                action: query.action.as_deref(),
                resource_type: query.resource_type.as_deref(),
                actor: query.actor.as_deref(),
                start_time: query.start_time,
                end_time: query.end_time,
                limit: query.limit,
                offset: query.offset,
            })
            .await
            .map_err(AuditApiError::internal)?;
        Ok(AuditLogListResponse::from_records(
            records,
            total,
            query.limit,
            query.offset,
        ))
    }

    async fn list_runtime_hook_logs(
        &self,
        user_id: &str,
        tenant_id: &str,
        query: ValidatedRuntimeHookAuditQuery,
    ) -> Result<AuditLogListResponse, AuditApiError> {
        require_tenant_access(&self.repo, user_id, tenant_id).await?;
        let (records, total) = self
            .repo
            .list_runtime_hook_logs(pg_runtime_query(tenant_id, &query))
            .await
            .map_err(AuditApiError::internal)?;
        Ok(AuditLogListResponse::from_records(
            records,
            total,
            query.limit,
            query.offset,
        ))
    }

    async fn summarize_runtime_hook_logs(
        &self,
        user_id: &str,
        tenant_id: &str,
        query: ValidatedRuntimeHookAuditQuery,
    ) -> Result<RuntimeHookAuditSummaryView, AuditApiError> {
        require_tenant_access(&self.repo, user_id, tenant_id).await?;
        self.repo
            .summarize_runtime_hook_logs(pg_runtime_query(tenant_id, &query))
            .await
            .map(RuntimeHookAuditSummaryView::from)
            .map_err(AuditApiError::internal)
    }

    async fn export_audit_logs(
        &self,
        user_id: &str,
        tenant_id: &str,
        query: ValidatedAuditExportQuery,
    ) -> Result<AuditExportResponse, AuditApiError> {
        require_tenant_access(&self.repo, user_id, tenant_id).await?;
        let records = if query.is_runtime_hook_export() {
            let runtime_query = query.runtime_hook_query();
            self.repo
                .list_runtime_hook_logs(pg_runtime_query(tenant_id, &runtime_query))
                .await
                .map_err(AuditApiError::internal)?
                .0
        } else {
            self.repo
                .list_audit_logs(PgAuditLogListQuery {
                    tenant_id,
                    action: query.action.as_deref(),
                    resource_type: query.resource_type.as_deref(),
                    actor: query.actor.as_deref(),
                    start_time: query.start_time,
                    end_time: query.end_time,
                    limit: AUDIT_EXPORT_LIMIT,
                    offset: 0,
                })
                .await
                .map_err(AuditApiError::internal)?
                .0
        };
        Ok(AuditExportResponse::from_records(records, query.format))
    }
}

pub(crate) struct DevAuditLogService {
    records: Vec<AuditLogRecord>,
}

impl DevAuditLogService {
    pub(crate) fn new(records: Vec<AuditLogRecord>) -> Self {
        Self { records }
    }
}

impl Default for DevAuditLogService {
    fn default() -> Self {
        Self::new(Vec::new())
    }
}

#[async_trait]
impl AuditLogService for DevAuditLogService {
    async fn list_audit_logs(
        &self,
        _user_id: &str,
        tenant_id: &str,
        query: ValidatedAuditLogQuery,
    ) -> Result<AuditLogListResponse, AuditApiError> {
        let records = filtered_audit_records(&self.records, tenant_id, &query);
        let total = records.len() as i64;
        let page = records
            .into_iter()
            .skip(query.offset as usize)
            .take(query.limit as usize)
            .collect();
        Ok(AuditLogListResponse::from_records(
            page,
            total,
            query.limit,
            query.offset,
        ))
    }

    async fn list_runtime_hook_logs(
        &self,
        _user_id: &str,
        tenant_id: &str,
        query: ValidatedRuntimeHookAuditQuery,
    ) -> Result<AuditLogListResponse, AuditApiError> {
        let records = filtered_runtime_hook_records(&self.records, tenant_id, &query);
        let total = records.len() as i64;
        let page = records
            .into_iter()
            .skip(query.offset as usize)
            .take(query.limit as usize)
            .collect();
        Ok(AuditLogListResponse::from_records(
            page,
            total,
            query.limit,
            query.offset,
        ))
    }

    async fn summarize_runtime_hook_logs(
        &self,
        _user_id: &str,
        tenant_id: &str,
        query: ValidatedRuntimeHookAuditQuery,
    ) -> Result<RuntimeHookAuditSummaryView, AuditApiError> {
        Ok(RuntimeHookAuditSummaryView::from(summarize_runtime_hooks(
            filtered_runtime_hook_records(&self.records, tenant_id, &query),
        )))
    }

    async fn export_audit_logs(
        &self,
        _user_id: &str,
        tenant_id: &str,
        query: ValidatedAuditExportQuery,
    ) -> Result<AuditExportResponse, AuditApiError> {
        let records = if query.is_runtime_hook_export() {
            filtered_runtime_hook_records(&self.records, tenant_id, &query.runtime_hook_query())
        } else {
            filtered_audit_records(&self.records, tenant_id, &query.audit_log_query())
        };
        Ok(AuditExportResponse::from_records(
            records
                .into_iter()
                .take(AUDIT_EXPORT_LIMIT as usize)
                .collect(),
            query.format,
        ))
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route(
            "/api/v1/tenants/:tenant_id/audit-logs",
            get(list_audit_logs),
        )
        .route(
            "/api/v1/tenants/:tenant_id/audit-logs/filter",
            get(list_audit_logs_filtered),
        )
        .route(
            "/api/v1/tenants/:tenant_id/audit-logs/runtime-hooks",
            get(list_runtime_hook_logs),
        )
        .route(
            "/api/v1/tenants/:tenant_id/audit-logs/runtime-hooks/summary",
            get(get_runtime_hook_audit_summary),
        )
        .route(
            "/api/v1/tenants/:tenant_id/audit-logs/export",
            get(export_audit_logs),
        )
}

async fn list_audit_logs(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Query(query): Query<AuditLogPageQuery>,
) -> Result<Json<AuditLogListResponse>, AuditApiError> {
    let query = query.validated_without_filters()?;
    let response = app
        .audit_logs
        .list_audit_logs(&identity.user_id, &tenant_id, query)
        .await?;
    Ok(Json(response))
}

async fn list_audit_logs_filtered(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Query(query): Query<AuditLogFilterQuery>,
) -> Result<Json<AuditLogListResponse>, AuditApiError> {
    let query = query.validated()?;
    let response = app
        .audit_logs
        .list_audit_logs(&identity.user_id, &tenant_id, query)
        .await?;
    Ok(Json(response))
}

async fn list_runtime_hook_logs(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Query(query): Query<RuntimeHookAuditQuery>,
) -> Result<Json<AuditLogListResponse>, AuditApiError> {
    let query = query.validated()?;
    let response = app
        .audit_logs
        .list_runtime_hook_logs(&identity.user_id, &tenant_id, query)
        .await?;
    Ok(Json(response))
}

async fn get_runtime_hook_audit_summary(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Query(query): Query<RuntimeHookAuditQuery>,
) -> Result<Json<RuntimeHookAuditSummaryView>, AuditApiError> {
    let query = query.validated_for_summary()?;
    let response = app
        .audit_logs
        .summarize_runtime_hook_logs(&identity.user_id, &tenant_id, query)
        .await?;
    Ok(Json(response))
}

async fn export_audit_logs(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Query(query): Query<AuditExportQuery>,
) -> Result<Response, AuditApiError> {
    let query = query.validated()?;
    let response = app
        .audit_logs
        .export_audit_logs(&identity.user_id, &tenant_id, query)
        .await?;
    Ok(response.into_response())
}

async fn require_tenant_access(
    repo: &PgAuditLogRepository,
    user_id: &str,
    tenant_id: &str,
) -> Result<(), AuditApiError> {
    if !repo
        .tenant_exists(tenant_id)
        .await
        .map_err(AuditApiError::internal)?
    {
        return Err(AuditApiError::not_found("Tenant not found"));
    }

    if repo
        .user_has_global_admin(user_id)
        .await
        .map_err(AuditApiError::internal)?
    {
        return Ok(());
    }

    if repo
        .tenant_member_role(user_id, tenant_id)
        .await
        .map_err(AuditApiError::internal)?
        .is_some()
    {
        Ok(())
    } else {
        Err(AuditApiError::forbidden("Tenant access required"))
    }
}

fn pg_runtime_query<'a>(
    tenant_id: &'a str,
    query: &'a ValidatedRuntimeHookAuditQuery,
) -> PgRuntimeHookAuditQuery<'a> {
    PgRuntimeHookAuditQuery {
        tenant_id,
        action: query.action.as_deref(),
        hook_name: query.hook_name.as_deref(),
        executor_kind: query.executor_kind.as_deref(),
        hook_family: query.hook_family.as_deref(),
        isolation_mode: query.isolation_mode.as_deref(),
        limit: query.limit,
        offset: query.offset,
    }
}

#[derive(Debug, Clone, Deserialize)]
struct AuditLogPageQuery {
    limit: Option<i64>,
    offset: Option<i64>,
}

impl AuditLogPageQuery {
    fn validated_without_filters(self) -> Result<ValidatedAuditLogQuery, AuditApiError> {
        Ok(ValidatedAuditLogQuery {
            action: None,
            resource_type: None,
            actor: None,
            start_time: None,
            end_time: None,
            limit: validate_limit(self.limit)?,
            offset: validate_offset(self.offset)?,
        })
    }
}

#[derive(Debug, Clone, Deserialize)]
struct AuditLogFilterQuery {
    action: Option<String>,
    resource_type: Option<String>,
    actor: Option<String>,
    start_time: Option<String>,
    end_time: Option<String>,
    limit: Option<i64>,
    offset: Option<i64>,
}

impl AuditLogFilterQuery {
    fn validated(self) -> Result<ValidatedAuditLogQuery, AuditApiError> {
        Ok(ValidatedAuditLogQuery {
            action: non_empty(self.action),
            resource_type: non_empty(self.resource_type),
            actor: non_empty(self.actor),
            start_time: parse_datetime(self.start_time.as_deref(), "start_time")?,
            end_time: parse_datetime(self.end_time.as_deref(), "end_time")?,
            limit: validate_limit(self.limit)?,
            offset: validate_offset(self.offset)?,
        })
    }
}

#[derive(Debug, Clone)]
pub(crate) struct ValidatedAuditLogQuery {
    action: Option<String>,
    resource_type: Option<String>,
    actor: Option<String>,
    start_time: Option<DateTime<Utc>>,
    end_time: Option<DateTime<Utc>>,
    limit: i64,
    offset: i64,
}

#[derive(Debug, Clone, Deserialize)]
struct RuntimeHookAuditQuery {
    action: Option<String>,
    hook_name: Option<String>,
    executor_kind: Option<String>,
    hook_family: Option<String>,
    isolation_mode: Option<String>,
    limit: Option<i64>,
    offset: Option<i64>,
}

impl RuntimeHookAuditQuery {
    fn validated(self) -> Result<ValidatedRuntimeHookAuditQuery, AuditApiError> {
        Ok(ValidatedRuntimeHookAuditQuery {
            action: non_empty(self.action),
            hook_name: non_empty(self.hook_name),
            executor_kind: non_empty(self.executor_kind),
            hook_family: non_empty(self.hook_family),
            isolation_mode: non_empty(self.isolation_mode),
            limit: validate_limit(self.limit)?,
            offset: validate_offset(self.offset)?,
        })
    }

    fn validated_for_summary(self) -> Result<ValidatedRuntimeHookAuditQuery, AuditApiError> {
        Ok(ValidatedRuntimeHookAuditQuery {
            action: non_empty(self.action),
            hook_name: non_empty(self.hook_name),
            executor_kind: non_empty(self.executor_kind),
            hook_family: non_empty(self.hook_family),
            isolation_mode: non_empty(self.isolation_mode),
            limit: 50,
            offset: 0,
        })
    }
}

#[derive(Debug, Clone)]
pub(crate) struct ValidatedRuntimeHookAuditQuery {
    action: Option<String>,
    hook_name: Option<String>,
    executor_kind: Option<String>,
    hook_family: Option<String>,
    isolation_mode: Option<String>,
    limit: i64,
    offset: i64,
}

#[derive(Debug, Clone, Deserialize)]
struct AuditExportQuery {
    #[serde(default, rename = "format")]
    format: Option<String>,
    action: Option<String>,
    resource_type: Option<String>,
    actor: Option<String>,
    hook_name: Option<String>,
    executor_kind: Option<String>,
    hook_family: Option<String>,
    isolation_mode: Option<String>,
    start_time: Option<String>,
    end_time: Option<String>,
}

impl AuditExportQuery {
    fn validated(self) -> Result<ValidatedAuditExportQuery, AuditApiError> {
        Ok(ValidatedAuditExportQuery {
            format: AuditExportFormat::parse(self.format.as_deref())?,
            action: non_empty(self.action),
            resource_type: non_empty(self.resource_type),
            actor: non_empty(self.actor),
            hook_name: non_empty(self.hook_name),
            executor_kind: non_empty(self.executor_kind),
            hook_family: non_empty(self.hook_family),
            isolation_mode: non_empty(self.isolation_mode),
            start_time: parse_datetime(self.start_time.as_deref(), "start_time")?,
            end_time: parse_datetime(self.end_time.as_deref(), "end_time")?,
        })
    }
}

#[derive(Debug, Clone)]
pub(crate) struct ValidatedAuditExportQuery {
    format: AuditExportFormat,
    action: Option<String>,
    resource_type: Option<String>,
    actor: Option<String>,
    hook_name: Option<String>,
    executor_kind: Option<String>,
    hook_family: Option<String>,
    isolation_mode: Option<String>,
    start_time: Option<DateTime<Utc>>,
    end_time: Option<DateTime<Utc>>,
}

impl ValidatedAuditExportQuery {
    fn is_runtime_hook_export(&self) -> bool {
        self.hook_name.is_some()
            || self.executor_kind.is_some()
            || self.hook_family.is_some()
            || self.isolation_mode.is_some()
            || self
                .action
                .as_deref()
                .is_some_and(|action| action.starts_with("runtime_hook."))
    }

    fn audit_log_query(&self) -> ValidatedAuditLogQuery {
        ValidatedAuditLogQuery {
            action: self.action.clone(),
            resource_type: self.resource_type.clone(),
            actor: self.actor.clone(),
            start_time: self.start_time,
            end_time: self.end_time,
            limit: AUDIT_EXPORT_LIMIT,
            offset: 0,
        }
    }

    fn runtime_hook_query(&self) -> ValidatedRuntimeHookAuditQuery {
        ValidatedRuntimeHookAuditQuery {
            action: self.action.clone(),
            hook_name: self.hook_name.clone(),
            executor_kind: self.executor_kind.clone(),
            hook_family: self.hook_family.clone(),
            isolation_mode: self.isolation_mode.clone(),
            limit: AUDIT_EXPORT_LIMIT,
            offset: 0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum AuditExportFormat {
    Csv,
    Json,
}

impl AuditExportFormat {
    fn parse(value: Option<&str>) -> Result<Self, AuditApiError> {
        match value.unwrap_or("csv") {
            "csv" => Ok(Self::Csv),
            "json" => Ok(Self::Json),
            _ => Err(AuditApiError::unprocessable("format must be csv or json")),
        }
    }

    fn extension(self) -> &'static str {
        match self {
            Self::Csv => "csv",
            Self::Json => "json",
        }
    }

    fn content_type(self) -> &'static str {
        match self {
            Self::Csv => "text/csv; charset=utf-8",
            Self::Json => "application/json",
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct AuditEntryView {
    id: String,
    timestamp: String,
    actor: Option<String>,
    action: String,
    resource_type: String,
    resource_id: Option<String>,
    tenant_id: Option<String>,
    details: serde_json::Value,
    ip_address: Option<String>,
    user_agent: Option<String>,
}

impl From<AuditLogRecord> for AuditEntryView {
    fn from(record: AuditLogRecord) -> Self {
        Self {
            id: record.id,
            timestamp: iso8601(record.timestamp),
            actor: record.actor,
            action: record.action,
            resource_type: record.resource_type,
            resource_id: record.resource_id,
            tenant_id: record.tenant_id,
            details: record.details_json,
            ip_address: record.ip_address,
            user_agent: record.user_agent,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct AuditLogListResponse {
    items: Vec<AuditEntryView>,
    total: i64,
    limit: i64,
    offset: i64,
}

impl AuditLogListResponse {
    fn from_records(records: Vec<AuditLogRecord>, total: i64, limit: i64, offset: i64) -> Self {
        Self {
            items: records.into_iter().map(AuditEntryView::from).collect(),
            total,
            limit,
            offset,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct RuntimeHookAuditSummaryView {
    total: i64,
    action_counts: BTreeMap<String, i64>,
    executor_counts: BTreeMap<String, i64>,
    family_counts: BTreeMap<String, i64>,
    isolation_mode_counts: BTreeMap<String, i64>,
    latest_timestamp: Option<String>,
}

impl From<RuntimeHookAuditSummaryRecord> for RuntimeHookAuditSummaryView {
    fn from(record: RuntimeHookAuditSummaryRecord) -> Self {
        Self {
            total: record.total,
            action_counts: record.action_counts,
            executor_counts: record.executor_counts,
            family_counts: record.family_counts,
            isolation_mode_counts: record.isolation_mode_counts,
            latest_timestamp: record.latest_timestamp.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct AuditExportRow {
    id: String,
    timestamp: String,
    actor: String,
    action: String,
    resource_type: String,
    resource_id: String,
    tenant_id: String,
    details: String,
    ip_address: String,
    user_agent: String,
}

impl From<AuditLogRecord> for AuditExportRow {
    fn from(record: AuditLogRecord) -> Self {
        Self {
            id: record.id,
            timestamp: python_iso8601(record.timestamp),
            actor: record.actor.unwrap_or_default(),
            action: record.action,
            resource_type: record.resource_type,
            resource_id: record.resource_id.unwrap_or_default(),
            tenant_id: record.tenant_id.unwrap_or_default(),
            details: python_json_dumps(&record.details_json),
            ip_address: record.ip_address.unwrap_or_default(),
            user_agent: record.user_agent.unwrap_or_default(),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct AuditExportResponse {
    format: AuditExportFormat,
    body: String,
}

impl AuditExportResponse {
    fn from_records(records: Vec<AuditLogRecord>, format: AuditExportFormat) -> Self {
        let rows = records
            .into_iter()
            .map(AuditExportRow::from)
            .collect::<Vec<_>>();
        let body = match format {
            AuditExportFormat::Csv => render_audit_csv(&rows),
            AuditExportFormat::Json => {
                serde_json::to_string_pretty(&rows).expect("audit export rows serialize")
            }
        };
        Self { format, body }
    }
}

impl IntoResponse for AuditExportResponse {
    fn into_response(self) -> Response {
        let disposition = format!(
            "attachment; filename=\"audit-logs.{}\"",
            self.format.extension()
        );
        Response::builder()
            .status(StatusCode::OK)
            .header(CONTENT_TYPE, self.format.content_type())
            .header(CONTENT_DISPOSITION, disposition)
            .body(self.body.into())
            .expect("audit export response is valid")
    }
}

fn render_audit_csv(rows: &[AuditExportRow]) -> String {
    let mut out = String::new();
    out.push_str(&AUDIT_EXPORT_COLUMNS.join(","));
    out.push_str("\r\n");
    for row in rows {
        let values = [
            row.id.as_str(),
            row.timestamp.as_str(),
            row.actor.as_str(),
            row.action.as_str(),
            row.resource_type.as_str(),
            row.resource_id.as_str(),
            row.tenant_id.as_str(),
            row.details.as_str(),
            row.ip_address.as_str(),
            row.user_agent.as_str(),
        ];
        out.push_str(
            &values
                .into_iter()
                .map(csv_escape)
                .collect::<Vec<_>>()
                .join(","),
        );
        out.push_str("\r\n");
    }
    out
}

fn csv_escape(value: &str) -> String {
    if value.contains([',', '"', '\n', '\r']) {
        format!("\"{}\"", value.replace('"', "\"\""))
    } else {
        value.to_string()
    }
}

fn python_json_dumps(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::Null => "null".to_string(),
        serde_json::Value::Bool(value) => value.to_string(),
        serde_json::Value::Number(value) => value.to_string(),
        serde_json::Value::String(value) => {
            serde_json::to_string(value).expect("JSON string serializes")
        }
        serde_json::Value::Array(values) => format!(
            "[{}]",
            values
                .iter()
                .map(python_json_dumps)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        serde_json::Value::Object(map) => {
            let mut entries = map.iter().collect::<Vec<_>>();
            entries.sort_by_key(|(key, _)| *key);
            format!(
                "{{{}}}",
                entries
                    .into_iter()
                    .map(|(key, value)| {
                        format!(
                            "{}: {}",
                            serde_json::to_string(key).expect("JSON object key serializes"),
                            python_json_dumps(value)
                        )
                    })
                    .collect::<Vec<_>>()
                    .join(", ")
            )
        }
    }
}

fn filtered_audit_records(
    records: &[AuditLogRecord],
    tenant_id: &str,
    query: &ValidatedAuditLogQuery,
) -> Vec<AuditLogRecord> {
    let mut records = records
        .iter()
        .filter(|record| record.tenant_id.as_deref().is_none_or(|id| id == tenant_id))
        .filter(|record| query.action.as_deref().is_none_or(|v| record.action == v))
        .filter(|record| {
            query
                .resource_type
                .as_deref()
                .is_none_or(|v| record.resource_type == v)
        })
        .filter(|record| {
            query
                .actor
                .as_deref()
                .is_none_or(|v| record.actor.as_deref() == Some(v))
        })
        .filter(|record| {
            query
                .start_time
                .is_none_or(|start| record.timestamp >= start)
        })
        .filter(|record| query.end_time.is_none_or(|end| record.timestamp <= end))
        .cloned()
        .collect::<Vec<_>>();
    records.sort_by(|left, right| {
        right
            .timestamp
            .cmp(&left.timestamp)
            .then_with(|| left.id.cmp(&right.id))
    });
    records
}

fn filtered_runtime_hook_records(
    records: &[AuditLogRecord],
    tenant_id: &str,
    query: &ValidatedRuntimeHookAuditQuery,
) -> Vec<AuditLogRecord> {
    let mut records = records
        .iter()
        .filter(|record| record.tenant_id.as_deref().is_none_or(|id| id == tenant_id))
        .filter(|record| record.action.starts_with("runtime_hook."))
        .filter(|record| record.resource_type == "runtime_hook")
        .filter(|record| query.action.as_deref().is_none_or(|v| record.action == v))
        .filter(|record| {
            detail_eq(
                &record.details_json,
                "hook_name",
                query.hook_name.as_deref(),
            )
        })
        .filter(|record| {
            detail_eq(
                &record.details_json,
                "executor_kind",
                query.executor_kind.as_deref(),
            )
        })
        .filter(|record| {
            detail_eq(
                &record.details_json,
                "hook_family",
                query.hook_family.as_deref(),
            )
        })
        .filter(|record| {
            detail_eq(
                &record.details_json,
                "isolation_mode",
                query.isolation_mode.as_deref(),
            )
        })
        .cloned()
        .collect::<Vec<_>>();
    records.sort_by(|left, right| {
        right
            .timestamp
            .cmp(&left.timestamp)
            .then_with(|| left.id.cmp(&right.id))
    });
    records
}

fn summarize_runtime_hooks(records: Vec<AuditLogRecord>) -> RuntimeHookAuditSummaryRecord {
    let mut action_counts = BTreeMap::new();
    let mut executor_counts = BTreeMap::new();
    let mut family_counts = BTreeMap::new();
    let mut isolation_mode_counts = BTreeMap::new();
    let mut latest_timestamp = None;

    for record in &records {
        increment(&mut action_counts, &record.action);
        increment(
            &mut executor_counts,
            detail_string(&record.details_json, "executor_kind").as_str(),
        );
        increment(
            &mut family_counts,
            detail_string(&record.details_json, "hook_family").as_str(),
        );
        increment(
            &mut isolation_mode_counts,
            detail_string(&record.details_json, "isolation_mode").as_str(),
        );
        latest_timestamp = latest_timestamp.max(Some(record.timestamp));
    }

    RuntimeHookAuditSummaryRecord {
        total: records.len() as i64,
        action_counts,
        executor_counts,
        family_counts,
        isolation_mode_counts,
        latest_timestamp,
    }
}

fn increment(counts: &mut BTreeMap<String, i64>, key: &str) {
    *counts.entry(key.to_string()).or_insert(0) += 1;
}

fn detail_eq(details: &serde_json::Value, key: &str, expected: Option<&str>) -> bool {
    expected.is_none_or(|expected| {
        details
            .get(key)
            .and_then(serde_json::Value::as_str)
            .is_some_and(|actual| actual == expected)
    })
}

fn detail_string(details: &serde_json::Value, key: &str) -> String {
    details
        .get(key)
        .and_then(serde_json::Value::as_str)
        .unwrap_or("unknown")
        .to_string()
}

fn non_empty(value: Option<String>) -> Option<String> {
    value.filter(|value| !value.is_empty())
}

fn validate_limit(value: Option<i64>) -> Result<i64, AuditApiError> {
    let limit = value.unwrap_or(50);
    if !(1..=200).contains(&limit) {
        return Err(AuditApiError::unprocessable(
            "limit must be greater than or equal to 1 and less than or equal to 200",
        ));
    }
    Ok(limit)
}

fn validate_offset(value: Option<i64>) -> Result<i64, AuditApiError> {
    let offset = value.unwrap_or(0);
    if offset < 0 {
        return Err(AuditApiError::unprocessable(
            "offset must be greater than or equal to 0",
        ));
    }
    Ok(offset)
}

fn parse_datetime(
    value: Option<&str>,
    field: &str,
) -> Result<Option<DateTime<Utc>>, AuditApiError> {
    let Some(value) = value else {
        return Ok(None);
    };
    chrono::DateTime::parse_from_rfc3339(value)
        .map(|datetime| Some(datetime.with_timezone(&Utc)))
        .map_err(|_| AuditApiError::unprocessable(format!("{field} must be a valid datetime")))
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn python_iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::AutoSi, false)
}

#[derive(Debug)]
pub(crate) struct AuditApiError {
    status: StatusCode,
    detail: String,
}

impl AuditApiError {
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

impl IntoResponse for AuditApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use serde_json::Value;

    fn audit_record(
        id: &str,
        action: &str,
        resource_type: &str,
        tenant_id: Option<&str>,
        timestamp: DateTime<Utc>,
    ) -> AuditLogRecord {
        AuditLogRecord {
            id: id.to_string(),
            timestamp,
            actor: Some("user-1".to_string()),
            action: action.to_string(),
            resource_type: resource_type.to_string(),
            resource_id: Some("resource-1".to_string()),
            tenant_id: tenant_id.map(ToOwned::to_owned),
            details_json: json!({
                "hook_name": "pre_tool",
                "executor_kind": "sandbox",
                "hook_family": "tool",
                "isolation_mode": "container"
            }),
            ip_address: Some("127.0.0.1".to_string()),
            user_agent: Some("pytest".to_string()),
        }
    }

    #[test]
    fn audit_log_list_response_matches_python_shape() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/audit_log_list_response.json"))
                .expect("audit log list golden must be valid JSON");
        let response = AuditLogListResponse::from_records(
            vec![audit_record(
                "audit-1",
                "runtime_hook.completed",
                "runtime_hook",
                Some("tenant-1"),
                Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
            )],
            1,
            50,
            0,
        );

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn runtime_hook_summary_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/audit_runtime_hook_summary_response.json"
        ))
        .expect("runtime hook summary golden must be valid JSON");
        let summary = RuntimeHookAuditSummaryView::from(summarize_runtime_hooks(vec![
            audit_record(
                "audit-1",
                "runtime_hook.completed",
                "runtime_hook",
                Some("tenant-1"),
                Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
            ),
            audit_record(
                "audit-2",
                "runtime_hook.failed",
                "runtime_hook",
                Some("tenant-1"),
                Utc.with_ymd_and_hms(2026, 1, 2, 0, 0, 0).unwrap(),
            ),
        ]));

        let value = serde_json::to_value(summary).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn audit_export_json_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/audit_export_json_response.json"
        ))
        .expect("audit export JSON golden must be valid JSON");
        let response = AuditExportResponse::from_records(
            vec![audit_record(
                "audit-1",
                "runtime_hook.completed",
                "runtime_hook",
                Some("tenant-1"),
                Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
            )],
            AuditExportFormat::Json,
        );
        let value: Value =
            serde_json::from_str(&response.body).expect("export response is valid JSON");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn audit_export_csv_matches_python_dialect() {
        let response = AuditExportResponse::from_records(
            vec![audit_record(
                "audit-1",
                "runtime_hook.completed",
                "runtime_hook",
                Some("tenant-1"),
                Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
            )],
            AuditExportFormat::Csv,
        );

        assert_eq!(
            response.body,
            concat!(
                "id,timestamp,actor,action,resource_type,resource_id,tenant_id,details,ip_address,user_agent\r\n",
                "audit-1,2026-01-01T00:00:00+00:00,user-1,runtime_hook.completed,runtime_hook,resource-1,tenant-1,",
                "\"{\"\"executor_kind\"\": \"\"sandbox\"\", \"\"hook_family\"\": \"\"tool\"\", \"\"hook_name\"\": \"\"pre_tool\"\", \"\"isolation_mode\"\": \"\"container\"\"}\",",
                "127.0.0.1,pytest\r\n"
            )
        );
    }

    #[test]
    fn audit_query_defaults_and_validates_like_python() {
        let query = AuditLogPageQuery {
            limit: None,
            offset: None,
        }
        .validated_without_filters()
        .expect("query is valid");
        assert_eq!(query.limit, 50);
        assert_eq!(query.offset, 0);

        let err = AuditLogPageQuery {
            limit: Some(0),
            offset: Some(0),
        }
        .validated_without_filters()
        .expect_err("limit below minimum rejected");
        assert_eq!(err.status, StatusCode::UNPROCESSABLE_ENTITY);

        let err = AuditLogFilterQuery {
            action: None,
            resource_type: None,
            actor: None,
            start_time: Some("not-a-date".to_string()),
            end_time: None,
            limit: Some(50),
            offset: Some(0),
        }
        .validated()
        .expect_err("invalid datetime rejected");
        assert_eq!(err.status, StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[test]
    fn audit_export_query_defaults_and_detects_runtime_scope() {
        let query = AuditExportQuery {
            format: None,
            action: Some("runtime_hook.completed".to_string()),
            resource_type: Some("memory".to_string()),
            actor: None,
            hook_name: None,
            executor_kind: None,
            hook_family: None,
            isolation_mode: None,
            start_time: None,
            end_time: None,
        }
        .validated()
        .expect("export query is valid");
        assert_eq!(query.format, AuditExportFormat::Csv);
        assert!(query.is_runtime_hook_export());
        assert_eq!(query.runtime_hook_query().limit, AUDIT_EXPORT_LIMIT);

        let err = AuditExportQuery {
            format: Some("xml".to_string()),
            action: None,
            resource_type: None,
            actor: None,
            hook_name: None,
            executor_kind: None,
            hook_family: None,
            isolation_mode: None,
            start_time: None,
            end_time: None,
        }
        .validated()
        .expect_err("unsupported format rejected");
        assert_eq!(err.status, StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[tokio::test]
    async fn dev_runtime_hook_filters_and_summarizes_tenant_scope() {
        let service = DevAuditLogService::new(vec![
            audit_record(
                "audit-new",
                "runtime_hook.completed",
                "runtime_hook",
                Some("tenant-1"),
                Utc.with_ymd_and_hms(2026, 1, 3, 0, 0, 0).unwrap(),
            ),
            audit_record(
                "audit-old",
                "runtime_hook.completed",
                "runtime_hook",
                Some("tenant-1"),
                Utc.with_ymd_and_hms(2026, 1, 2, 0, 0, 0).unwrap(),
            ),
            audit_record(
                "audit-other",
                "runtime_hook.completed",
                "runtime_hook",
                Some("tenant-2"),
                Utc.with_ymd_and_hms(2026, 1, 4, 0, 0, 0).unwrap(),
            ),
            audit_record(
                "audit-memory",
                "memory.created",
                "memory",
                Some("tenant-1"),
                Utc.with_ymd_and_hms(2026, 1, 5, 0, 0, 0).unwrap(),
            ),
        ]);
        let query = RuntimeHookAuditQuery {
            action: Some("runtime_hook.completed".to_string()),
            hook_name: Some("pre_tool".to_string()),
            executor_kind: Some("sandbox".to_string()),
            hook_family: None,
            isolation_mode: None,
            limit: Some(1),
            offset: Some(0),
        }
        .validated()
        .expect("runtime hook query is valid");

        let list = service
            .list_runtime_hook_logs("user-1", "tenant-1", query.clone())
            .await
            .expect("runtime hook list succeeds");
        assert_eq!(list.total, 2);
        assert_eq!(list.items.len(), 1);
        assert_eq!(list.items[0].id, "audit-new");

        let summary = service
            .summarize_runtime_hook_logs("user-1", "tenant-1", query)
            .await
            .expect("runtime hook summary succeeds");
        assert_eq!(summary.total, 2);
        assert_eq!(
            summary.action_counts["runtime_hook.completed"], 2,
            "summary counts all filtered rows, not just first page"
        );

        let export_query = AuditExportQuery {
            format: Some("json".to_string()),
            action: Some("runtime_hook.completed".to_string()),
            resource_type: None,
            actor: None,
            hook_name: Some("pre_tool".to_string()),
            executor_kind: Some("sandbox".to_string()),
            hook_family: None,
            isolation_mode: None,
            start_time: None,
            end_time: None,
        }
        .validated()
        .expect("export query is valid");
        let export = service
            .export_audit_logs("user-1", "tenant-1", export_query)
            .await
            .expect("runtime hook export succeeds");
        let rows: Value = serde_json::from_str(&export.body).expect("export is valid JSON");
        assert_eq!(
            rows.as_array().expect("export rows are array").len(),
            2,
            "runtime export ignores non-runtime and other-tenant rows"
        );
    }
}
