//! P7 cron job read-side strangler slice.
//!
//! Rust owns only project-scoped cron job list/detail/run history reads. Cron
//! creation, update, deletion, toggle, manual run, and scheduler registration
//! remain Python-owned.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::Deserialize;
use serde::Serialize;
use serde_json::{json, Value};

use agistack_adapters_postgres::{
    CronJobListQuery as PgCronJobListQuery, CronJobRecord, CronJobRunRecord, PgCronRepository,
};

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedCronJobs = Arc<dyn CronJobService>;

#[async_trait]
pub(crate) trait CronJobService: Send + Sync {
    async fn list_jobs(
        &self,
        project_id: &str,
        query: ValidatedCronJobListQuery,
    ) -> Result<CronJobListResponse, CronApiError>;

    async fn get_job(&self, project_id: &str, job_id: &str) -> Result<CronJobView, CronApiError>;

    async fn list_runs(
        &self,
        project_id: &str,
        job_id: &str,
        query: ValidatedCronRunListQuery,
    ) -> Result<CronJobRunListResponse, CronApiError>;
}

pub(crate) struct PgCronJobService {
    repo: PgCronRepository,
}

impl PgCronJobService {
    pub(crate) fn new(repo: PgCronRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl CronJobService for PgCronJobService {
    async fn list_jobs(
        &self,
        project_id: &str,
        query: ValidatedCronJobListQuery,
    ) -> Result<CronJobListResponse, CronApiError> {
        let (records, total) = self
            .repo
            .list_jobs(PgCronJobListQuery {
                project_id,
                include_disabled: query.include_disabled,
                limit: query.limit,
                offset: query.offset,
            })
            .await
            .map_err(CronApiError::internal)?;
        Ok(CronJobListResponse::from_records(records, total))
    }

    async fn get_job(&self, project_id: &str, job_id: &str) -> Result<CronJobView, CronApiError> {
        self.repo
            .get_job(project_id, job_id)
            .await
            .map_err(CronApiError::internal)?
            .map(CronJobView::from)
            .ok_or_else(|| CronApiError::not_found("Cron job not found"))
    }

    async fn list_runs(
        &self,
        project_id: &str,
        job_id: &str,
        query: ValidatedCronRunListQuery,
    ) -> Result<CronJobRunListResponse, CronApiError> {
        if self
            .repo
            .get_job(project_id, job_id)
            .await
            .map_err(CronApiError::internal)?
            .is_none()
        {
            return Err(CronApiError::not_found("Cron job not found"));
        }
        let (records, total) = self
            .repo
            .list_runs(project_id, job_id, query.limit, query.offset)
            .await
            .map_err(CronApiError::internal)?;
        Ok(CronJobRunListResponse::from_records(records, total))
    }
}

#[derive(Default)]
pub(crate) struct DevCronJobService {
    jobs: Vec<CronJobRecord>,
    runs: Vec<CronJobRunRecord>,
}

impl DevCronJobService {
    #[cfg(test)]
    pub(crate) fn new(jobs: Vec<CronJobRecord>, runs: Vec<CronJobRunRecord>) -> Self {
        Self { jobs, runs }
    }
}

#[async_trait]
impl CronJobService for DevCronJobService {
    async fn list_jobs(
        &self,
        project_id: &str,
        query: ValidatedCronJobListQuery,
    ) -> Result<CronJobListResponse, CronApiError> {
        let mut jobs = self
            .jobs
            .iter()
            .filter(|job| job.project_id == project_id)
            .filter(|job| query.include_disabled || job.enabled)
            .cloned()
            .collect::<Vec<_>>();
        sort_jobs(&mut jobs);
        let total = jobs.len() as i64;
        let page = page(jobs, query.limit, query.offset);
        Ok(CronJobListResponse::from_records(page, total))
    }

    async fn get_job(&self, project_id: &str, job_id: &str) -> Result<CronJobView, CronApiError> {
        self.jobs
            .iter()
            .find(|job| job.project_id == project_id && job.id == job_id)
            .cloned()
            .map(CronJobView::from)
            .ok_or_else(|| CronApiError::not_found("Cron job not found"))
    }

    async fn list_runs(
        &self,
        project_id: &str,
        job_id: &str,
        query: ValidatedCronRunListQuery,
    ) -> Result<CronJobRunListResponse, CronApiError> {
        if !self
            .jobs
            .iter()
            .any(|job| job.project_id == project_id && job.id == job_id)
        {
            return Err(CronApiError::not_found("Cron job not found"));
        }
        let mut runs = self
            .runs
            .iter()
            .filter(|run| run.project_id == project_id && run.job_id == job_id)
            .cloned()
            .collect::<Vec<_>>();
        sort_runs(&mut runs);
        let total = runs.len() as i64;
        let page = page(runs, query.limit, query.offset);
        Ok(CronJobRunListResponse::from_records(page, total))
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route(
            "/api/v1/projects/:project_id/cron-jobs",
            get(list_cron_jobs),
        )
        .route(
            "/api/v1/projects/:project_id/cron-jobs/:job_id",
            get(get_cron_job),
        )
        .route(
            "/api/v1/projects/:project_id/cron-jobs/:job_id/runs",
            get(list_cron_job_runs),
        )
}

async fn list_cron_jobs(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Query(query): Query<CronJobListQuery>,
) -> Result<Json<CronJobListResponse>, CronApiError> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let query = query.validated()?;
    let response = app.cron_jobs.list_jobs(&project_id, query).await?;
    Ok(Json(response))
}

async fn get_cron_job(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, job_id)): Path<(String, String)>,
) -> Result<Json<CronJobView>, CronApiError> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let response = app.cron_jobs.get_job(&project_id, &job_id).await?;
    Ok(Json(response))
}

async fn list_cron_job_runs(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, job_id)): Path<(String, String)>,
    Query(query): Query<CronRunListQuery>,
) -> Result<Json<CronJobRunListResponse>, CronApiError> {
    ensure_project_access(&app, &identity, &project_id).await?;
    let query = query.validated()?;
    let response = app.cron_jobs.list_runs(&project_id, &job_id, query).await?;
    Ok(Json(response))
}

async fn ensure_project_access(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> Result<(), CronApiError> {
    let allowed = app
        .auth
        .can_access_project(&identity.user_id, project_id)
        .await
        .map_err(CronApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(CronApiError::forbidden("Access denied to project"))
    }
}

#[derive(Debug, Clone, Deserialize)]
struct CronJobListQuery {
    include_disabled: Option<bool>,
    limit: Option<i64>,
    offset: Option<i64>,
}

impl CronJobListQuery {
    fn validated(self) -> Result<ValidatedCronJobListQuery, CronApiError> {
        let limit = validate_non_negative(self.limit.unwrap_or(50), "limit")?;
        let offset = validate_non_negative(self.offset.unwrap_or(0), "offset")?;
        Ok(ValidatedCronJobListQuery {
            include_disabled: self.include_disabled.unwrap_or(false),
            limit,
            offset,
        })
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct ValidatedCronJobListQuery {
    include_disabled: bool,
    limit: i64,
    offset: i64,
}

#[derive(Debug, Clone, Deserialize)]
struct CronRunListQuery {
    limit: Option<i64>,
    offset: Option<i64>,
}

impl CronRunListQuery {
    fn validated(self) -> Result<ValidatedCronRunListQuery, CronApiError> {
        let limit = validate_non_negative(self.limit.unwrap_or(50), "limit")?;
        let offset = validate_non_negative(self.offset.unwrap_or(0), "offset")?;
        Ok(ValidatedCronRunListQuery { limit, offset })
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct ValidatedCronRunListQuery {
    limit: i64,
    offset: i64,
}

fn validate_non_negative(value: i64, field: &str) -> Result<i64, CronApiError> {
    if value < 0 {
        Err(CronApiError::unprocessable(format!(
            "{field} must be greater than or equal to 0"
        )))
    } else {
        Ok(value)
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct CronConfigView {
    kind: String,
    config: Value,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct CronJobView {
    id: String,
    project_id: String,
    tenant_id: String,
    name: String,
    description: Option<String>,
    enabled: bool,
    delete_after_run: bool,
    schedule: CronConfigView,
    payload: CronConfigView,
    delivery: CronConfigView,
    conversation_mode: String,
    conversation_id: Option<String>,
    timezone: String,
    stagger_seconds: i32,
    timeout_seconds: i32,
    max_retries: i32,
    state: Value,
    created_by: Option<String>,
    created_at: String,
    updated_at: Option<String>,
}

impl From<CronJobRecord> for CronJobView {
    fn from(record: CronJobRecord) -> Self {
        Self {
            id: record.id,
            project_id: record.project_id,
            tenant_id: record.tenant_id,
            name: record.name,
            description: record.description,
            enabled: record.enabled,
            delete_after_run: record.delete_after_run,
            schedule: CronConfigView {
                kind: record.schedule_type,
                config: record.schedule_config,
            },
            payload: CronConfigView {
                kind: record.payload_type,
                config: record.payload_config,
            },
            delivery: CronConfigView {
                kind: record.delivery_type,
                config: record.delivery_config,
            },
            conversation_mode: record.conversation_mode,
            conversation_id: record.conversation_id,
            timezone: record.timezone,
            stagger_seconds: record.stagger_seconds,
            timeout_seconds: record.timeout_seconds,
            max_retries: record.max_retries,
            state: record.state,
            created_by: record.created_by,
            created_at: iso8601(record.created_at),
            updated_at: record.updated_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct CronJobListResponse {
    items: Vec<CronJobView>,
    total: i64,
}

impl CronJobListResponse {
    fn from_records(records: Vec<CronJobRecord>, total: i64) -> Self {
        Self {
            items: records.into_iter().map(CronJobView::from).collect(),
            total,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct CronJobRunView {
    id: String,
    job_id: String,
    project_id: String,
    status: String,
    trigger_type: String,
    started_at: String,
    finished_at: Option<String>,
    duration_ms: Option<i32>,
    error_message: Option<String>,
    result_summary: Value,
    conversation_id: Option<String>,
}

impl From<CronJobRunRecord> for CronJobRunView {
    fn from(record: CronJobRunRecord) -> Self {
        Self {
            id: record.id,
            job_id: record.job_id,
            project_id: record.project_id,
            status: record.status,
            trigger_type: record.trigger_type,
            started_at: iso8601(record.started_at),
            finished_at: record.finished_at.map(iso8601),
            duration_ms: record.duration_ms,
            error_message: record.error_message,
            result_summary: record.result_summary,
            conversation_id: record.conversation_id,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct CronJobRunListResponse {
    items: Vec<CronJobRunView>,
    total: i64,
}

impl CronJobRunListResponse {
    fn from_records(records: Vec<CronJobRunRecord>, total: i64) -> Self {
        Self {
            items: records.into_iter().map(CronJobRunView::from).collect(),
            total,
        }
    }
}

fn sort_jobs(records: &mut [CronJobRecord]) {
    records.sort_by(|left, right| {
        right
            .created_at
            .cmp(&left.created_at)
            .then_with(|| left.id.cmp(&right.id))
    });
}

fn sort_runs(records: &mut [CronJobRunRecord]) {
    records.sort_by(|left, right| {
        right
            .started_at
            .cmp(&left.started_at)
            .then_with(|| left.id.cmp(&right.id))
    });
}

fn page<T>(records: Vec<T>, limit: i64, offset: i64) -> Vec<T> {
    records
        .into_iter()
        .skip(offset as usize)
        .take(limit as usize)
        .collect()
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

#[derive(Debug)]
pub(crate) struct CronApiError {
    status: StatusCode,
    detail: String,
}

impl CronApiError {
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

impl IntoResponse for CronApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use serde_json::Value;

    fn cron_job(id: &str, enabled: bool, created_at: DateTime<Utc>) -> CronJobRecord {
        CronJobRecord {
            id: id.to_string(),
            project_id: "project-1".to_string(),
            tenant_id: "tenant-1".to_string(),
            name: format!("Job {id}"),
            description: Some("Nightly maintenance".to_string()),
            enabled,
            delete_after_run: false,
            schedule_type: "cron".to_string(),
            schedule_config: json!({"expr": "0 * * * *", "timezone": "UTC"}),
            payload_type: "agent_turn".to_string(),
            payload_config: json!({"message": "Summarize status", "timeout_seconds": 300}),
            delivery_type: "announce".to_string(),
            delivery_config: json!({"conversation_id": "conversation-1"}),
            conversation_mode: "reuse".to_string(),
            conversation_id: Some("conversation-1".to_string()),
            timezone: "UTC".to_string(),
            stagger_seconds: 5,
            timeout_seconds: 300,
            max_retries: 3,
            state: json!({"last_run_status": "success"}),
            created_by: Some("user-1".to_string()),
            created_at,
            updated_at: Some(Utc.with_ymd_and_hms(2026, 1, 2, 0, 0, 0).unwrap()),
        }
    }

    fn cron_run(id: &str, started_at: DateTime<Utc>) -> CronJobRunRecord {
        CronJobRunRecord {
            id: id.to_string(),
            job_id: "job-1".to_string(),
            project_id: "project-1".to_string(),
            status: "success".to_string(),
            trigger_type: "scheduled".to_string(),
            started_at,
            finished_at: Some(started_at),
            duration_ms: Some(1250),
            error_message: None,
            result_summary: json!({"tokens": 42}),
            conversation_id: Some("conversation-1".to_string()),
        }
    }

    #[test]
    fn cron_job_list_response_matches_python_shape() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/cron_job_list_response.json"))
                .expect("cron job list golden must be valid JSON");
        let response = CronJobListResponse::from_records(
            vec![cron_job(
                "job-1",
                true,
                Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
            )],
            1,
        );

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn cron_job_run_list_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/cron_job_run_list_response.json"
        ))
        .expect("cron job run list golden must be valid JSON");
        let response = CronJobRunListResponse::from_records(
            vec![cron_run(
                "run-1",
                Utc.with_ymd_and_hms(2026, 1, 1, 1, 0, 0).unwrap(),
            )],
            1,
        );

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn cron_queries_default_and_reject_negative_pages() {
        let query = CronJobListQuery {
            include_disabled: None,
            limit: None,
            offset: None,
        }
        .validated()
        .expect("default cron list query is valid");
        assert!(!query.include_disabled);
        assert_eq!(query.limit, 50);
        assert_eq!(query.offset, 0);

        let err = CronRunListQuery {
            limit: Some(-1),
            offset: None,
        }
        .validated()
        .expect_err("negative limit rejected");
        assert_eq!(err.status, StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[tokio::test]
    async fn dev_cron_service_filters_orders_and_pages() {
        let service = DevCronJobService::new(
            vec![
                cron_job(
                    "job-old",
                    true,
                    Utc.with_ymd_and_hms(2026, 1, 1, 0, 0, 0).unwrap(),
                ),
                cron_job(
                    "job-new",
                    true,
                    Utc.with_ymd_and_hms(2026, 1, 2, 0, 0, 0).unwrap(),
                ),
                cron_job(
                    "job-disabled",
                    false,
                    Utc.with_ymd_and_hms(2026, 1, 3, 0, 0, 0).unwrap(),
                ),
                CronJobRecord {
                    project_id: "project-2".to_string(),
                    ..cron_job(
                        "job-other",
                        true,
                        Utc.with_ymd_and_hms(2026, 1, 4, 0, 0, 0).unwrap(),
                    )
                },
            ],
            vec![
                CronJobRunRecord {
                    job_id: "job-new".to_string(),
                    ..cron_run(
                        "run-old",
                        Utc.with_ymd_and_hms(2026, 1, 1, 1, 0, 0).unwrap(),
                    )
                },
                CronJobRunRecord {
                    job_id: "job-new".to_string(),
                    ..cron_run(
                        "run-new",
                        Utc.with_ymd_and_hms(2026, 1, 2, 1, 0, 0).unwrap(),
                    )
                },
            ],
        );

        let jobs = service
            .list_jobs(
                "project-1",
                ValidatedCronJobListQuery {
                    include_disabled: false,
                    limit: 10,
                    offset: 0,
                },
            )
            .await
            .expect("dev list jobs succeeds");
        assert_eq!(jobs.total, 2);
        assert_eq!(jobs.items[0].id, "job-new");

        let runs = service
            .list_runs(
                "project-1",
                "job-new",
                ValidatedCronRunListQuery {
                    limit: 1,
                    offset: 0,
                },
            )
            .await
            .expect("dev list runs succeeds");
        assert_eq!(runs.total, 2);
        assert_eq!(runs.items[0].id, "run-new");

        let err = service
            .get_job("project-1", "missing")
            .await
            .expect_err("missing job returns not found");
        assert_eq!(err.status, StatusCode::NOT_FOUND);
    }
}
