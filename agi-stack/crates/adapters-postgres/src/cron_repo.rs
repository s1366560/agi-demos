//! Read-only adapter over Python-owned cron job tables.
//!
//! Rust owns only project-scoped cron job and run reads in this checkpoint.
//! Creation, mutation, scheduling, and manual execution remain Python-owned.

use serde_json::{json, Value};
use sqlx::postgres::PgRow;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const JOB_COLS: &str = "id, project_id, tenant_id, name, description, enabled, \
    delete_after_run, revision, schedule_revision, schedule_type, schedule_config, \
    payload_type, payload_config, \
    delivery_type, delivery_config, conversation_mode, conversation_id, timezone, \
    stagger_seconds, timeout_seconds, max_retries, state, created_by, created_at, updated_at";
const RUN_COLS: &str = "id, job_id, project_id, status, trigger_type, started_at, finished_at, \
    duration_ms, error_message, result_summary, conversation_id";

#[derive(Debug, Clone, Copy)]
pub struct CronJobListQuery<'a> {
    pub project_id: &'a str,
    pub include_disabled: bool,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Clone)]
pub struct CronJobRecord {
    pub id: String,
    pub project_id: String,
    pub tenant_id: String,
    pub name: String,
    pub description: Option<String>,
    pub enabled: bool,
    pub delete_after_run: bool,
    pub revision: i64,
    pub schedule_revision: i64,
    pub schedule_type: String,
    pub schedule_config: Value,
    pub payload_type: String,
    pub payload_config: Value,
    pub delivery_type: String,
    pub delivery_config: Value,
    pub conversation_mode: String,
    pub conversation_id: Option<String>,
    pub timezone: String,
    pub stagger_seconds: i32,
    pub timeout_seconds: i32,
    pub max_retries: i32,
    pub state: Value,
    pub created_by: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone)]
pub struct CronJobRunRecord {
    pub id: String,
    pub job_id: String,
    pub project_id: String,
    pub status: String,
    pub trigger_type: String,
    pub started_at: DateTime<Utc>,
    pub finished_at: Option<DateTime<Utc>>,
    pub duration_ms: Option<i32>,
    pub error_message: Option<String>,
    pub result_summary: Value,
    pub conversation_id: Option<String>,
}

pub struct PgCronRepository {
    pool: PgPool,
}

impl PgCronRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn list_jobs(
        &self,
        query: CronJobListQuery<'_>,
    ) -> CoreResult<(Vec<CronJobRecord>, i64)> {
        let total = self
            .count_jobs(query.project_id, query.include_disabled)
            .await?;
        let rows = if query.include_disabled {
            let sql = format!(
                "SELECT {JOB_COLS} FROM cron_jobs WHERE project_id = $1 \
                 ORDER BY created_at DESC, id ASC LIMIT $2 OFFSET $3"
            );
            sqlx::query(&sql)
                .bind(query.project_id)
                .bind(query.limit)
                .bind(query.offset)
                .fetch_all(&self.pool)
                .await
        } else {
            let sql = format!(
                "SELECT {JOB_COLS} FROM cron_jobs WHERE project_id = $1 AND enabled IS TRUE \
                 ORDER BY created_at DESC, id ASC LIMIT $2 OFFSET $3"
            );
            sqlx::query(&sql)
                .bind(query.project_id)
                .bind(query.limit)
                .bind(query.offset)
                .fetch_all(&self.pool)
                .await
        }
        .map_err(|e| CoreError::Storage(format!("list cron jobs: {e}")))?;

        let records = rows
            .into_iter()
            .map(cron_job_from_row)
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read cron job row: {e}")))?;
        Ok((records, total))
    }

    pub async fn get_job(
        &self,
        project_id: &str,
        job_id: &str,
    ) -> CoreResult<Option<CronJobRecord>> {
        let sql = format!("SELECT {JOB_COLS} FROM cron_jobs WHERE project_id = $1 AND id = $2");
        sqlx::query(&sql)
            .bind(project_id)
            .bind(job_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("get cron job: {e}")))?
            .map(cron_job_from_row)
            .transpose()
            .map_err(|e| CoreError::Storage(format!("read cron job row: {e}")))
    }

    pub async fn list_runs(
        &self,
        project_id: &str,
        job_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<(Vec<CronJobRunRecord>, i64)> {
        let total = sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM cron_job_runs WHERE project_id = $1 AND job_id = $2",
        )
        .bind(project_id)
        .bind(job_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("count cron job runs: {e}")))?;

        let sql = format!(
            "SELECT {RUN_COLS} FROM cron_job_runs WHERE project_id = $1 AND job_id = $2 \
             ORDER BY started_at DESC, id ASC LIMIT $3 OFFSET $4"
        );
        let rows = sqlx::query(&sql)
            .bind(project_id)
            .bind(job_id)
            .bind(limit)
            .bind(offset)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list cron job runs: {e}")))?;

        let records = rows
            .into_iter()
            .map(cron_run_from_row)
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read cron job run row: {e}")))?;
        Ok((records, total))
    }

    async fn count_jobs(&self, project_id: &str, include_disabled: bool) -> CoreResult<i64> {
        let result = if include_disabled {
            sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM cron_jobs WHERE project_id = $1")
                .bind(project_id)
                .fetch_one(&self.pool)
                .await
        } else {
            sqlx::query_scalar::<_, i64>(
                "SELECT COUNT(*) FROM cron_jobs WHERE project_id = $1 AND enabled IS TRUE",
            )
            .bind(project_id)
            .fetch_one(&self.pool)
            .await
        };
        result.map_err(|e| CoreError::Storage(format!("count cron jobs: {e}")))
    }
}

fn cron_job_from_row(row: PgRow) -> Result<CronJobRecord, sqlx::Error> {
    Ok(CronJobRecord {
        id: row.try_get("id")?,
        project_id: row.try_get("project_id")?,
        tenant_id: row.try_get("tenant_id")?,
        name: row.try_get("name")?,
        description: row.try_get("description")?,
        enabled: row.try_get::<Option<bool>, _>("enabled")?.unwrap_or(true),
        delete_after_run: row
            .try_get::<Option<bool>, _>("delete_after_run")?
            .unwrap_or(false),
        revision: row.try_get("revision")?,
        schedule_revision: row.try_get("schedule_revision")?,
        schedule_type: row.try_get("schedule_type")?,
        schedule_config: json_or_default(&row, "schedule_config")?,
        payload_type: row.try_get("payload_type")?,
        payload_config: json_or_default(&row, "payload_config")?,
        delivery_type: row
            .try_get::<Option<String>, _>("delivery_type")?
            .unwrap_or_else(|| "none".to_string()),
        delivery_config: json_or_default(&row, "delivery_config")?,
        conversation_mode: row
            .try_get::<Option<String>, _>("conversation_mode")?
            .unwrap_or_else(|| "reuse".to_string()),
        conversation_id: row.try_get("conversation_id")?,
        timezone: row
            .try_get::<Option<String>, _>("timezone")?
            .unwrap_or_else(|| "UTC".to_string()),
        stagger_seconds: row
            .try_get::<Option<i32>, _>("stagger_seconds")?
            .unwrap_or(0),
        timeout_seconds: row
            .try_get::<Option<i32>, _>("timeout_seconds")?
            .unwrap_or(300),
        max_retries: row.try_get::<Option<i32>, _>("max_retries")?.unwrap_or(3),
        state: json_or_default(&row, "state")?,
        created_by: row.try_get("created_by")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
    })
}

fn cron_run_from_row(row: PgRow) -> Result<CronJobRunRecord, sqlx::Error> {
    Ok(CronJobRunRecord {
        id: row.try_get("id")?,
        job_id: row.try_get("job_id")?,
        project_id: row.try_get("project_id")?,
        status: row.try_get("status")?,
        trigger_type: row
            .try_get::<Option<String>, _>("trigger_type")?
            .unwrap_or_else(|| "scheduled".to_string()),
        started_at: row.try_get("started_at")?,
        finished_at: row.try_get("finished_at")?,
        duration_ms: row.try_get("duration_ms")?,
        error_message: row.try_get("error_message")?,
        result_summary: json_or_default(&row, "result_summary")?,
        conversation_id: row.try_get("conversation_id")?,
    })
}

fn json_or_default(row: &PgRow, column: &str) -> Result<Value, sqlx::Error> {
    row.try_get::<Option<Value>, _>(column)
        .map(|value| value.unwrap_or_else(|| json!({})))
}
