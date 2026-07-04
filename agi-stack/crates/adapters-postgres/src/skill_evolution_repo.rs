//! Repository for Python-owned skill evolution tables.
//!
//! The skill evolution plugin stores capture sessions and review jobs in
//! `skill_evolution_sessions` and `skill_evolution_jobs`. Rust reads and
//! updates those rows verbatim for the P5 strangler skill-evolution endpoints;
//! it does not create or alter the Python-owned schema.
//!
//! Rust-side run admission uses the additive `agistack_skill_evolution_runs`
//! queue created by `ensure_aux_schema`, so manual run scheduling can be
//! persisted without polluting Python's review-job table.

use std::collections::HashMap;

use serde_json::Value;
use sqlx::postgres::PgRow;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::{Postgres, QueryBuilder, Row};

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const JOB_COLS: &str = "id, tenant_id, project_id, skill_name, action, status, rationale, \
    candidate_content, session_ids, skill_version_id, created_at, applied_at";
const RUN_COLS: &str = "id, tenant_id, project_id, skill_name, reason, status, attempts, \
    worker_id, started_at, completed_at, last_error, result_json, created_at, updated_at";

#[derive(Debug, Clone, Default, PartialEq)]
pub struct SkillEvolutionOverviewStatsRecord {
    pub total_sessions: i64,
    pub skill_sessions: i64,
    pub no_skill_sessions: i64,
    pub unprocessed_sessions: i64,
    pub processed_sessions: i64,
    pub scored_sessions: i64,
    pub successful_sessions: i64,
    pub avg_score: Option<f64>,
    pub total_jobs: i64,
    pub pending_jobs: i64,
    pub applied_jobs: i64,
    pub skipped_jobs: i64,
    pub rejected_jobs: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SkillEvolutionSkillSummaryRecord {
    pub skill_id: Option<String>,
    pub project_id: Option<String>,
    pub skill_name: String,
    pub session_count: i64,
    pub success_count: i64,
    pub unprocessed_count: i64,
    pub scored_count: i64,
    pub avg_score: Option<f64>,
    pub latest_session_at: Option<DateTime<Utc>>,
    pub job_count: i64,
    pub pending_job_count: i64,
    pub latest_job_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SkillEvolutionSessionRecord {
    pub id: String,
    pub skill_name: String,
    pub conversation_id: String,
    pub project_id: Option<String>,
    pub user_query: String,
    pub summary: Option<String>,
    pub judge_scores: Option<Value>,
    pub overall_score: Option<f64>,
    pub success: bool,
    pub execution_time_ms: i64,
    pub tool_call_count: i64,
    pub processed: bool,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SkillEvolutionPipelineSessionRecord {
    pub id: String,
    pub skill_name: String,
    pub conversation_id: String,
    pub project_id: Option<String>,
    pub user_query: String,
    pub trajectory: Option<Value>,
    pub summary: Option<String>,
    pub judge_scores: Option<Value>,
    pub overall_score: Option<f64>,
    pub success: bool,
    pub execution_time_ms: i64,
    pub tool_call_count: i64,
    pub processed: bool,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SkillEvolutionSessionGroupRecord {
    pub skill_name: String,
    pub project_id: Option<String>,
    pub session_count: i64,
    pub avg_score: f64,
    pub success_count: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SkillEvolutionJobRecord {
    pub id: String,
    pub tenant_id: String,
    pub project_id: Option<String>,
    pub skill_name: String,
    pub action: String,
    pub status: String,
    pub rationale: Option<String>,
    pub candidate_content: Option<String>,
    pub session_ids: Vec<String>,
    pub skill_version_id: Option<String>,
    pub created_at: DateTime<Utc>,
    pub applied_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SkillEvolutionRunRecord {
    pub id: String,
    pub tenant_id: String,
    pub project_id: Option<String>,
    pub skill_name: Option<String>,
    pub reason: String,
    pub status: String,
    pub attempts: i32,
    pub worker_id: Option<String>,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub last_error: Option<String>,
    pub result_json: Option<Value>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone)]
pub struct PgSkillEvolutionRepository {
    pool: PgPool,
}

impl PgSkillEvolutionRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn accessible_project_ids(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> CoreResult<Vec<String>> {
        let rows = sqlx::query_as::<_, (String,)>(
            "SELECT DISTINCT up.project_id \
             FROM user_projects up \
             JOIN projects p ON p.id = up.project_id \
             WHERE up.user_id = $1 AND p.tenant_id = $2 \
             ORDER BY up.project_id ASC",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        Ok(rows.into_iter().map(|(project_id,)| project_id).collect())
    }

    pub async fn overview_stats(
        &self,
        tenant_id: &str,
        project_ids: &[String],
    ) -> CoreResult<SkillEvolutionOverviewStatsRecord> {
        let mut sessions = QueryBuilder::new(
            "SELECT \
                count(id) AS total_sessions, \
                count(*) FILTER (WHERE skill_name <> '__no_skill__') AS skill_sessions, \
                count(*) FILTER (WHERE skill_name = '__no_skill__') AS no_skill_sessions, \
                count(*) FILTER (WHERE skill_name <> '__no_skill__' AND processed = false) AS unprocessed_sessions, \
                count(*) FILTER (WHERE skill_name <> '__no_skill__' AND processed = true) AS processed_sessions, \
                count(*) FILTER (WHERE skill_name <> '__no_skill__' AND overall_score IS NOT NULL) AS scored_sessions, \
                count(*) FILTER (WHERE success = true) AS successful_sessions, \
                avg(overall_score) FILTER (WHERE skill_name <> '__no_skill__') AS avg_score \
             FROM skill_evolution_sessions WHERE tenant_id = ",
        );
        sessions.push_bind(tenant_id);
        push_project_access_filter(&mut sessions, "project_id", project_ids);
        let session_row = sessions
            .build()
            .fetch_one(&self.pool)
            .await
            .map_err(storage)?;

        let mut jobs = QueryBuilder::new(
            "SELECT \
                count(id) AS total_jobs, \
                count(*) FILTER (WHERE status = 'pending_review') AS pending_jobs, \
                count(*) FILTER (WHERE status = 'applied') AS applied_jobs, \
                count(*) FILTER (WHERE status = 'skipped') AS skipped_jobs, \
                count(*) FILTER (WHERE status = 'rejected') AS rejected_jobs \
             FROM skill_evolution_jobs WHERE tenant_id = ",
        );
        jobs.push_bind(tenant_id);
        push_project_access_filter(&mut jobs, "project_id", project_ids);
        let job_row = jobs.build().fetch_one(&self.pool).await.map_err(storage)?;

        Ok(SkillEvolutionOverviewStatsRecord {
            total_sessions: session_row.try_get("total_sessions").map_err(storage)?,
            skill_sessions: session_row.try_get("skill_sessions").map_err(storage)?,
            no_skill_sessions: session_row.try_get("no_skill_sessions").map_err(storage)?,
            unprocessed_sessions: session_row
                .try_get("unprocessed_sessions")
                .map_err(storage)?,
            processed_sessions: session_row.try_get("processed_sessions").map_err(storage)?,
            scored_sessions: session_row.try_get("scored_sessions").map_err(storage)?,
            successful_sessions: session_row
                .try_get("successful_sessions")
                .map_err(storage)?,
            avg_score: session_row.try_get("avg_score").map_err(storage)?,
            total_jobs: job_row.try_get("total_jobs").map_err(storage)?,
            pending_jobs: job_row.try_get("pending_jobs").map_err(storage)?,
            applied_jobs: job_row.try_get("applied_jobs").map_err(storage)?,
            skipped_jobs: job_row.try_get("skipped_jobs").map_err(storage)?,
            rejected_jobs: job_row.try_get("rejected_jobs").map_err(storage)?,
        })
    }

    pub async fn skill_session_summaries(
        &self,
        tenant_id: &str,
        project_ids: &[String],
        limit: i64,
    ) -> CoreResult<Vec<SkillEvolutionSkillSummaryRecord>> {
        let job_counts = self.job_counts_by_skill(tenant_id, project_ids).await?;
        let mut sessions = QueryBuilder::new(
            "SELECT \
                min(skills.id) AS skill_id, \
                sessions.project_id AS project_id, \
                sessions.skill_name AS skill_name, \
                count(sessions.id) AS session_count, \
                count(*) FILTER (WHERE sessions.success = true) AS success_count, \
                count(*) FILTER (WHERE sessions.processed = false) AS unprocessed_count, \
                count(*) FILTER (WHERE sessions.overall_score IS NOT NULL) AS scored_count, \
                avg(sessions.overall_score) AS avg_score, \
                max(sessions.created_at) AS latest_session_at \
             FROM skill_evolution_sessions sessions \
             LEFT JOIN skills ON skills.tenant_id = ",
        );
        sessions.push_bind(tenant_id);
        sessions.push(
            " AND skills.name = sessions.skill_name \
              AND coalesce(skills.project_id, '') = coalesce(sessions.project_id, '') \
             WHERE sessions.tenant_id = ",
        );
        sessions.push_bind(tenant_id);
        sessions.push(" AND sessions.skill_name <> '__no_skill__'");
        push_project_access_filter(&mut sessions, "sessions.project_id", project_ids);
        sessions.push(
            " GROUP BY sessions.skill_name, sessions.project_id \
              ORDER BY count(sessions.id) DESC, sessions.skill_name ASC \
              LIMIT ",
        );
        sessions.push_bind(limit);

        let rows = sessions
            .build()
            .fetch_all(&self.pool)
            .await
            .map_err(storage)?;
        rows.into_iter()
            .map(|row| row_to_skill_summary(row, &job_counts))
            .collect()
    }

    pub async fn list_recent_sessions(
        &self,
        tenant_id: &str,
        project_ids: &[String],
        limit: i64,
    ) -> CoreResult<Vec<SkillEvolutionSessionRecord>> {
        let mut query = QueryBuilder::new(
            "SELECT id, skill_name, conversation_id, project_id, user_query, summary, \
                judge_scores, overall_score, success, execution_time_ms, tool_call_count, \
                processed, created_at \
             FROM skill_evolution_sessions WHERE tenant_id = ",
        );
        query.push_bind(tenant_id);
        push_project_access_filter(&mut query, "project_id", project_ids);
        query.push(" ORDER BY created_at DESC LIMIT ");
        query.push_bind(limit);
        let rows = query.build().fetch_all(&self.pool).await.map_err(storage)?;
        rows.into_iter().map(row_to_session).collect()
    }

    pub async fn list_jobs(
        &self,
        tenant_id: &str,
        project_ids: &[String],
        limit: i64,
    ) -> CoreResult<Vec<SkillEvolutionJobRecord>> {
        let mut query = QueryBuilder::new(format!(
            "SELECT {JOB_COLS} FROM skill_evolution_jobs WHERE tenant_id = "
        ));
        query.push_bind(tenant_id);
        push_project_access_filter(&mut query, "project_id", project_ids);
        query.push(" ORDER BY created_at DESC LIMIT ");
        query.push_bind(limit);
        let rows = query.build().fetch_all(&self.pool).await.map_err(storage)?;
        rows.into_iter().map(row_to_job).collect()
    }

    pub async fn list_jobs_for_skill(
        &self,
        tenant_id: &str,
        skill_name: &str,
        project_id: Option<&str>,
        limit: i64,
    ) -> CoreResult<Vec<SkillEvolutionJobRecord>> {
        let mut query = QueryBuilder::new(format!(
            "SELECT {JOB_COLS} FROM skill_evolution_jobs WHERE tenant_id = "
        ));
        query.push_bind(tenant_id);
        query.push(" AND skill_name = ");
        query.push_bind(skill_name);
        push_exact_project_filter(&mut query, "project_id", project_id);
        query.push(" ORDER BY created_at DESC LIMIT ");
        query.push_bind(limit);
        let rows = query.build().fetch_all(&self.pool).await.map_err(storage)?;
        rows.into_iter().map(row_to_job).collect()
    }

    pub async fn list_unprocessed_sessions(
        &self,
        tenant_id: &str,
        skill_name: Option<&str>,
        project_id: Option<&str>,
        filter_project_id: bool,
        min_skill_sessions: i64,
        limit: i64,
    ) -> CoreResult<Vec<SkillEvolutionPipelineSessionRecord>> {
        let mut query = QueryBuilder::new(
            "SELECT id, skill_name, conversation_id, project_id, user_query, trajectory, \
                summary, judge_scores, overall_score, success, execution_time_ms, \
                tool_call_count, processed, created_at \
             FROM skill_evolution_sessions \
             WHERE tenant_id = ",
        );
        query.push_bind(tenant_id);
        query.push(" AND processed = false");
        push_skill_name_filter(&mut query, skill_name);
        if filter_project_id {
            push_exact_project_filter(&mut query, "project_id", project_id);
        }
        push_min_skill_sessions_filter(
            &mut query,
            tenant_id,
            project_id,
            filter_project_id,
            min_skill_sessions,
        );
        query.push(" ORDER BY created_at ASC LIMIT ");
        query.push_bind(limit.max(1));
        let rows = query.build().fetch_all(&self.pool).await.map_err(storage)?;
        rows.into_iter().map(row_to_pipeline_session).collect()
    }

    pub async fn list_unscored_sessions(
        &self,
        tenant_id: &str,
        skill_name: Option<&str>,
        project_id: Option<&str>,
        filter_project_id: bool,
        min_skill_sessions: i64,
        limit: i64,
    ) -> CoreResult<Vec<SkillEvolutionPipelineSessionRecord>> {
        let mut query = QueryBuilder::new(
            "SELECT id, skill_name, conversation_id, project_id, user_query, trajectory, \
                summary, judge_scores, overall_score, success, execution_time_ms, \
                tool_call_count, processed, created_at \
             FROM skill_evolution_sessions \
             WHERE tenant_id = ",
        );
        query.push_bind(tenant_id);
        query.push(" AND processed = true AND overall_score IS NULL");
        push_skill_name_filter(&mut query, skill_name);
        if filter_project_id {
            push_exact_project_filter(&mut query, "project_id", project_id);
        }
        push_min_skill_sessions_filter(
            &mut query,
            tenant_id,
            project_id,
            filter_project_id,
            min_skill_sessions,
        );
        query.push(" ORDER BY created_at ASC LIMIT ");
        query.push_bind(limit.max(1));
        let rows = query.build().fetch_all(&self.pool).await.map_err(storage)?;
        rows.into_iter().map(row_to_pipeline_session).collect()
    }

    pub async fn update_session_summary(
        &self,
        session_id: &str,
        trajectory: &Value,
        summary: &str,
    ) -> CoreResult<bool> {
        let rows = sqlx::query(
            "UPDATE skill_evolution_sessions \
             SET trajectory = $2, summary = $3, processed = true \
             WHERE id = $1",
        )
        .bind(session_id)
        .bind(trajectory)
        .bind(summary)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(rows.rows_affected() > 0)
    }

    pub async fn update_session_scores(
        &self,
        session_id: &str,
        judge_scores: &Value,
        overall_score: f64,
    ) -> CoreResult<bool> {
        let rows = sqlx::query(
            "UPDATE skill_evolution_sessions \
             SET judge_scores = $2, overall_score = $3 \
             WHERE id = $1",
        )
        .bind(session_id)
        .bind(judge_scores)
        .bind(overall_score)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(rows.rows_affected() > 0)
    }

    pub async fn scored_session_groups(
        &self,
        tenant_id: &str,
        project_id: Option<&str>,
        filter_project_id: bool,
        min_sessions: i64,
        min_avg_score: f64,
    ) -> CoreResult<Vec<SkillEvolutionSessionGroupRecord>> {
        let mut query = QueryBuilder::new(
            "SELECT skill_name, project_id, count(id) AS session_count, \
                avg(overall_score) AS avg_score, \
                count(*) FILTER (WHERE success = true) AS success_count \
             FROM skill_evolution_sessions \
             WHERE tenant_id = ",
        );
        query.push_bind(tenant_id);
        query.push(" AND overall_score IS NOT NULL");
        if filter_project_id {
            push_exact_project_filter(&mut query, "project_id", project_id);
        }
        query.push(
            " GROUP BY skill_name, project_id, coalesce(project_id, '') \
              HAVING count(id) >= ",
        );
        query.push_bind(min_sessions.max(1));
        query.push(" AND avg(overall_score) >= ");
        query.push_bind(min_avg_score);
        query.push(" ORDER BY count(id) DESC, skill_name ASC");
        let rows = query.build().fetch_all(&self.pool).await.map_err(storage)?;
        rows.into_iter().map(row_to_session_group).collect()
    }

    pub async fn list_scored_sessions_by_skill(
        &self,
        tenant_id: &str,
        skill_name: &str,
        project_id: Option<&str>,
        filter_project_id: bool,
        min_score: Option<f64>,
        limit: i64,
    ) -> CoreResult<Vec<SkillEvolutionPipelineSessionRecord>> {
        let mut query = QueryBuilder::new(
            "SELECT id, skill_name, conversation_id, project_id, user_query, trajectory, \
                summary, judge_scores, overall_score, success, execution_time_ms, \
                tool_call_count, processed, created_at \
             FROM skill_evolution_sessions \
             WHERE tenant_id = ",
        );
        query.push_bind(tenant_id);
        query.push(" AND skill_name = ");
        query.push_bind(skill_name);
        query.push(" AND overall_score IS NOT NULL");
        if filter_project_id {
            push_exact_project_filter(&mut query, "project_id", project_id);
        }
        if let Some(min_score) = min_score {
            query.push(" AND overall_score >= ");
            query.push_bind(min_score);
        }
        query.push(" ORDER BY created_at DESC LIMIT ");
        query.push_bind(limit.max(1));
        let rows = query.build().fetch_all(&self.pool).await.map_err(storage)?;
        rows.into_iter().map(row_to_pipeline_session).collect()
    }

    pub async fn get_job_for_sessions(
        &self,
        tenant_id: &str,
        skill_name: &str,
        project_id: Option<&str>,
        filter_project_id: bool,
        session_ids: &[String],
        excluded_statuses: &[&str],
    ) -> CoreResult<Option<SkillEvolutionJobRecord>> {
        if session_ids.is_empty() {
            return Ok(None);
        }
        let expected = session_ids.iter().collect::<std::collections::HashSet<_>>();
        let mut query = QueryBuilder::new(format!(
            "SELECT {JOB_COLS} FROM skill_evolution_jobs WHERE tenant_id = "
        ));
        query.push_bind(tenant_id);
        query.push(" AND skill_name = ");
        query.push_bind(skill_name);
        if filter_project_id {
            push_exact_project_filter(&mut query, "project_id", project_id);
        }
        query.push(" ORDER BY created_at DESC");
        let rows = query.build().fetch_all(&self.pool).await.map_err(storage)?;
        for row in rows {
            let job = row_to_job(row)?;
            if excluded_statuses.contains(&job.status.as_str()) {
                continue;
            }
            if job.session_ids.len() == expected.len()
                && job.session_ids.iter().all(|id| expected.contains(id))
            {
                return Ok(Some(job));
            }
        }
        Ok(None)
    }

    pub async fn get_job_for_tenant(
        &self,
        tenant_id: &str,
        job_id: &str,
    ) -> CoreResult<Option<SkillEvolutionJobRecord>> {
        let sql =
            format!("SELECT {JOB_COLS} FROM skill_evolution_jobs WHERE tenant_id = $1 AND id = $2");
        let row = sqlx::query(&sql)
            .bind(tenant_id)
            .bind(job_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?;
        row.map(row_to_job).transpose()
    }

    pub async fn update_job_status(
        &self,
        tenant_id: &str,
        job_id: &str,
        status: &str,
        skill_version_id: Option<&str>,
    ) -> CoreResult<Option<SkillEvolutionJobRecord>> {
        let sql = format!(
            "UPDATE skill_evolution_jobs \
             SET status = $3, \
                 skill_version_id = COALESCE($4, skill_version_id), \
                 applied_at = CASE WHEN $3 = 'applied' THEN now() ELSE applied_at END \
             WHERE tenant_id = $1 AND id = $2 \
             RETURNING {JOB_COLS}"
        );
        let row = sqlx::query(&sql)
            .bind(tenant_id)
            .bind(job_id)
            .bind(status)
            .bind(skill_version_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?;
        row.map(row_to_job).transpose()
    }

    pub async fn schedule_evolution_run(
        &self,
        run_id: &str,
        tenant_id: &str,
        project_id: Option<&str>,
        skill_name: Option<&str>,
        reason: &str,
    ) -> CoreResult<bool> {
        let scope_key = skill_evolution_run_scope_key(project_id, skill_name);
        let inserted = sqlx::query_scalar::<_, String>(
            "INSERT INTO agistack_skill_evolution_runs \
                (id, tenant_id, scope_key, project_id, skill_name, reason, status, updated_at) \
             VALUES ($1, $2, $3, $4, $5, $6, 'queued', now()) \
             ON CONFLICT (tenant_id, scope_key) \
                WHERE status IN ('queued', 'running') \
             DO NOTHING \
             RETURNING id",
        )
        .bind(run_id)
        .bind(tenant_id)
        .bind(scope_key)
        .bind(project_id)
        .bind(skill_name)
        .bind(reason)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        Ok(inserted.is_some())
    }

    pub async fn claim_next_evolution_run(
        &self,
        worker_id: &str,
    ) -> CoreResult<Option<SkillEvolutionRunRecord>> {
        let sql = format!(
            "WITH candidate AS (\
                SELECT id FROM agistack_skill_evolution_runs \
                WHERE status = 'queued' \
                ORDER BY created_at ASC \
                FOR UPDATE SKIP LOCKED \
                LIMIT 1\
             ) \
             UPDATE agistack_skill_evolution_runs runs \
             SET status = 'running', \
                 attempts = attempts + 1, \
                 worker_id = $1, \
                 started_at = now(), \
                 completed_at = NULL, \
                 last_error = NULL, \
                 updated_at = now() \
             FROM candidate \
             WHERE runs.id = candidate.id \
             RETURNING {RUN_COLS}"
        );
        let row = sqlx::query(&sql)
            .bind(worker_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?;
        row.map(row_to_run).transpose()
    }

    pub async fn complete_evolution_run(
        &self,
        run_id: &str,
        worker_id: Option<&str>,
        result_json: &Value,
    ) -> CoreResult<bool> {
        let rows = sqlx::query(
            "UPDATE agistack_skill_evolution_runs \
             SET status = 'completed', \
                 completed_at = now(), \
                 updated_at = now(), \
                 last_error = NULL, \
                 result_json = $3 \
             WHERE id = $1 \
               AND status = 'running' \
               AND ($2::text IS NULL OR worker_id = $2)",
        )
        .bind(run_id)
        .bind(worker_id)
        .bind(result_json)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(rows.rows_affected() > 0)
    }

    pub async fn fail_evolution_run(
        &self,
        run_id: &str,
        worker_id: Option<&str>,
        error: &str,
    ) -> CoreResult<bool> {
        let rows = sqlx::query(
            "UPDATE agistack_skill_evolution_runs \
             SET status = 'failed', \
                 completed_at = now(), \
                 updated_at = now(), \
                 last_error = left($3, 2000) \
             WHERE id = $1 \
               AND status = 'running' \
               AND ($2::text IS NULL OR worker_id = $2)",
        )
        .bind(run_id)
        .bind(worker_id)
        .bind(error)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(rows.rows_affected() > 0)
    }

    pub async fn count_sessions_by_skill(
        &self,
        tenant_id: &str,
        skill_name: &str,
        project_id: Option<&str>,
    ) -> CoreResult<i64> {
        let mut query = QueryBuilder::new(
            "SELECT count(id) AS captured_session_count \
             FROM skill_evolution_sessions WHERE tenant_id = ",
        );
        query.push_bind(tenant_id);
        query.push(" AND skill_name = ");
        query.push_bind(skill_name);
        push_exact_project_filter(&mut query, "project_id", project_id);
        let row = query.build().fetch_one(&self.pool).await.map_err(storage)?;
        row.try_get("captured_session_count").map_err(storage)
    }

    async fn job_counts_by_skill(
        &self,
        tenant_id: &str,
        project_ids: &[String],
    ) -> CoreResult<HashMap<(String, Option<String>), JobCountRecord>> {
        let mut query = QueryBuilder::new(
            "SELECT skill_name, project_id, count(id) AS job_count, \
                count(*) FILTER (WHERE status = 'pending_review') AS pending_job_count, \
                max(created_at) AS latest_job_at \
             FROM skill_evolution_jobs WHERE tenant_id = ",
        );
        query.push_bind(tenant_id);
        push_project_access_filter(&mut query, "project_id", project_ids);
        query.push(" GROUP BY skill_name, project_id");
        let rows = query.build().fetch_all(&self.pool).await.map_err(storage)?;

        let mut counts = HashMap::with_capacity(rows.len());
        for row in rows {
            let skill_name: String = row.try_get("skill_name").map_err(storage)?;
            let project_id: Option<String> = row.try_get("project_id").map_err(storage)?;
            counts.insert(
                (skill_name, project_id),
                JobCountRecord {
                    job_count: row.try_get("job_count").map_err(storage)?,
                    pending_job_count: row.try_get("pending_job_count").map_err(storage)?,
                    latest_job_at: row.try_get("latest_job_at").map_err(storage)?,
                },
            );
        }
        Ok(counts)
    }
}

fn skill_evolution_run_scope_key(project_id: Option<&str>, skill_name: Option<&str>) -> String {
    let mut key = String::with_capacity(
        "project=".len()
            + project_id.map_or(0, str::len)
            + "\nskill=".len()
            + skill_name.map_or(0, str::len),
    );
    key.push_str("project=");
    if let Some(project_id) = project_id {
        key.push_str(project_id);
    }
    key.push_str("\nskill=");
    if let Some(skill_name) = skill_name {
        key.push_str(skill_name);
    }
    key
}

#[derive(Debug, Clone, Default)]
struct JobCountRecord {
    job_count: i64,
    pending_job_count: i64,
    latest_job_at: Option<DateTime<Utc>>,
}

fn push_project_access_filter<'q>(
    query: &mut QueryBuilder<'q, Postgres>,
    column: &str,
    project_ids: &'q [String],
) {
    if project_ids.is_empty() {
        query.push(" AND ");
        query.push(column);
        query.push(" IS NULL");
        return;
    }

    query.push(" AND (");
    query.push(column);
    query.push(" IS NULL OR ");
    query.push(column);
    query.push(" IN (");
    let mut separated = query.separated(", ");
    for project_id in project_ids {
        separated.push_bind(project_id);
    }
    separated.push_unseparated("))");
}

fn push_exact_project_filter<'q>(
    query: &mut QueryBuilder<'q, Postgres>,
    column: &str,
    project_id: Option<&'q str>,
) {
    query.push(" AND ");
    query.push(column);
    if let Some(project_id) = project_id {
        query.push(" = ");
        query.push_bind(project_id);
    } else {
        query.push(" IS NULL");
    }
}

fn push_skill_name_filter<'q>(query: &mut QueryBuilder<'q, Postgres>, skill_name: Option<&'q str>) {
    match skill_name {
        Some(skill_name) => {
            query.push(" AND skill_name = ");
            query.push_bind(skill_name);
        }
        None => {
            query.push(" AND skill_name <> '__no_skill__'");
        }
    }
}

fn push_min_skill_sessions_filter<'q>(
    query: &mut QueryBuilder<'q, Postgres>,
    tenant_id: &'q str,
    project_id: Option<&'q str>,
    filter_project_id: bool,
    min_skill_sessions: i64,
) {
    if min_skill_sessions <= 1 {
        return;
    }
    query.push(
        " AND (skill_name, coalesce(project_id, '')) IN (\
             SELECT skill_name, coalesce(project_id, '') \
             FROM skill_evolution_sessions \
             WHERE tenant_id = ",
    );
    query.push_bind(tenant_id);
    query.push(" AND skill_name <> '__no_skill__'");
    if filter_project_id {
        push_exact_project_filter(query, "project_id", project_id);
    }
    query.push(" GROUP BY skill_name, coalesce(project_id, '') HAVING count(id) >= ");
    query.push_bind(min_skill_sessions);
    query.push(")");
}

fn row_to_skill_summary(
    row: PgRow,
    job_counts: &HashMap<(String, Option<String>), JobCountRecord>,
) -> CoreResult<SkillEvolutionSkillSummaryRecord> {
    let skill_name: String = row.try_get("skill_name").map_err(storage)?;
    let project_id: Option<String> = row.try_get("project_id").map_err(storage)?;
    let counts = job_counts
        .get(&(skill_name.clone(), project_id.clone()))
        .cloned()
        .unwrap_or_default();
    Ok(SkillEvolutionSkillSummaryRecord {
        skill_id: row.try_get("skill_id").map_err(storage)?,
        project_id,
        skill_name,
        session_count: row.try_get("session_count").map_err(storage)?,
        success_count: row.try_get("success_count").map_err(storage)?,
        unprocessed_count: row.try_get("unprocessed_count").map_err(storage)?,
        scored_count: row.try_get("scored_count").map_err(storage)?,
        avg_score: row.try_get("avg_score").map_err(storage)?,
        latest_session_at: row.try_get("latest_session_at").map_err(storage)?,
        job_count: counts.job_count,
        pending_job_count: counts.pending_job_count,
        latest_job_at: counts.latest_job_at,
    })
}

fn row_to_pipeline_session(row: PgRow) -> CoreResult<SkillEvolutionPipelineSessionRecord> {
    let execution_time_ms: i32 = row.try_get("execution_time_ms").map_err(storage)?;
    let tool_call_count: i32 = row.try_get("tool_call_count").map_err(storage)?;
    Ok(SkillEvolutionPipelineSessionRecord {
        id: row.try_get("id").map_err(storage)?,
        skill_name: row.try_get("skill_name").map_err(storage)?,
        conversation_id: row.try_get("conversation_id").map_err(storage)?,
        project_id: row.try_get("project_id").map_err(storage)?,
        user_query: row.try_get("user_query").map_err(storage)?,
        trajectory: row.try_get("trajectory").map_err(storage)?,
        summary: row.try_get("summary").map_err(storage)?,
        judge_scores: row.try_get("judge_scores").map_err(storage)?,
        overall_score: row.try_get("overall_score").map_err(storage)?,
        success: row.try_get("success").map_err(storage)?,
        execution_time_ms: i64::from(execution_time_ms),
        tool_call_count: i64::from(tool_call_count),
        processed: row.try_get("processed").map_err(storage)?,
        created_at: row.try_get("created_at").map_err(storage)?,
    })
}

fn row_to_session_group(row: PgRow) -> CoreResult<SkillEvolutionSessionGroupRecord> {
    let avg_score = row
        .try_get::<Option<f64>, _>("avg_score")
        .map_err(storage)?
        .unwrap_or_default();
    Ok(SkillEvolutionSessionGroupRecord {
        skill_name: row.try_get("skill_name").map_err(storage)?,
        project_id: row.try_get("project_id").map_err(storage)?,
        session_count: row.try_get("session_count").map_err(storage)?,
        avg_score,
        success_count: row.try_get("success_count").map_err(storage)?,
    })
}

fn row_to_session(row: PgRow) -> CoreResult<SkillEvolutionSessionRecord> {
    let execution_time_ms: i32 = row.try_get("execution_time_ms").map_err(storage)?;
    let tool_call_count: i32 = row.try_get("tool_call_count").map_err(storage)?;
    Ok(SkillEvolutionSessionRecord {
        id: row.try_get("id").map_err(storage)?,
        skill_name: row.try_get("skill_name").map_err(storage)?,
        conversation_id: row.try_get("conversation_id").map_err(storage)?,
        project_id: row.try_get("project_id").map_err(storage)?,
        user_query: row.try_get("user_query").map_err(storage)?,
        summary: row.try_get("summary").map_err(storage)?,
        judge_scores: row.try_get("judge_scores").map_err(storage)?,
        overall_score: row.try_get("overall_score").map_err(storage)?,
        success: row.try_get("success").map_err(storage)?,
        execution_time_ms: i64::from(execution_time_ms),
        tool_call_count: i64::from(tool_call_count),
        processed: row.try_get("processed").map_err(storage)?,
        created_at: row.try_get("created_at").map_err(storage)?,
    })
}

fn row_to_job(row: PgRow) -> CoreResult<SkillEvolutionJobRecord> {
    Ok(SkillEvolutionJobRecord {
        id: row.try_get("id").map_err(storage)?,
        tenant_id: row.try_get("tenant_id").map_err(storage)?,
        project_id: row.try_get("project_id").map_err(storage)?,
        skill_name: row.try_get("skill_name").map_err(storage)?,
        action: row.try_get("action").map_err(storage)?,
        status: row.try_get("status").map_err(storage)?,
        rationale: row.try_get("rationale").map_err(storage)?,
        candidate_content: row.try_get("candidate_content").map_err(storage)?,
        session_ids: session_ids_from_value(row.try_get("session_ids").map_err(storage)?),
        skill_version_id: row.try_get("skill_version_id").map_err(storage)?,
        created_at: row.try_get("created_at").map_err(storage)?,
        applied_at: row.try_get("applied_at").map_err(storage)?,
    })
}

fn row_to_run(row: PgRow) -> CoreResult<SkillEvolutionRunRecord> {
    Ok(SkillEvolutionRunRecord {
        id: row.try_get("id").map_err(storage)?,
        tenant_id: row.try_get("tenant_id").map_err(storage)?,
        project_id: row.try_get("project_id").map_err(storage)?,
        skill_name: row.try_get("skill_name").map_err(storage)?,
        reason: row.try_get("reason").map_err(storage)?,
        status: row.try_get("status").map_err(storage)?,
        attempts: row.try_get("attempts").map_err(storage)?,
        worker_id: row.try_get("worker_id").map_err(storage)?,
        started_at: row.try_get("started_at").map_err(storage)?,
        completed_at: row.try_get("completed_at").map_err(storage)?,
        last_error: row.try_get("last_error").map_err(storage)?,
        result_json: row.try_get("result_json").map_err(storage)?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
    })
}

fn session_ids_from_value(value: Option<Value>) -> Vec<String> {
    let Some(Value::Array(items)) = value else {
        return Vec::new();
    };
    items
        .into_iter()
        .map(|value| match value {
            Value::String(value) => value,
            other => other.to_string(),
        })
        .collect()
}

fn storage<E: std::fmt::Display>(error: E) -> CoreError {
    CoreError::Storage(error.to_string())
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{session_ids_from_value, skill_evolution_run_scope_key};

    #[test]
    fn session_ids_from_value_preserves_string_items_and_stringifies_scalars() {
        let actual = session_ids_from_value(Some(json!(["s1", 2, true])));

        assert_eq!(
            actual,
            vec!["s1".to_string(), "2".to_string(), "true".to_string()]
        );
    }

    #[test]
    fn session_ids_from_value_returns_empty_for_missing_or_non_array_values() {
        assert!(session_ids_from_value(None).is_empty());
        assert!(session_ids_from_value(Some(json!({"id": "s1"}))).is_empty());
    }

    #[test]
    fn skill_evolution_run_scope_key_preserves_none_vs_some_scope() {
        assert_eq!(
            skill_evolution_run_scope_key(None, None),
            "project=\nskill="
        );
        assert_eq!(
            skill_evolution_run_scope_key(Some("p1"), Some("code-review")),
            "project=p1\nskill=code-review"
        );
    }
}
