//! Read-only repository for Python-owned skill evolution tables.
//!
//! The skill evolution plugin stores capture sessions and review jobs in
//! `skill_evolution_sessions` and `skill_evolution_jobs`. Rust reads those rows
//! verbatim for the P5 strangler overview endpoint; it does not create or alter
//! the Python-owned schema.

use std::collections::HashMap;

use serde_json::Value;
use sqlx::postgres::PgRow;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::{Postgres, QueryBuilder, Row};

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

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
pub struct SkillEvolutionJobRecord {
    pub id: String,
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
        let mut query = QueryBuilder::new(
            "SELECT id, project_id, skill_name, action, status, rationale, candidate_content, \
                session_ids, skill_version_id, created_at, applied_at \
             FROM skill_evolution_jobs WHERE tenant_id = ",
        );
        query.push_bind(tenant_id);
        push_project_access_filter(&mut query, "project_id", project_ids);
        query.push(" ORDER BY created_at DESC LIMIT ");
        query.push_bind(limit);
        let rows = query.build().fetch_all(&self.pool).await.map_err(storage)?;
        rows.into_iter().map(row_to_job).collect()
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

    use super::session_ids_from_value;

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
}
