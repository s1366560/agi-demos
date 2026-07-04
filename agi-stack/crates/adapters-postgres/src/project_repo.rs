//! Read-side repository over the Python-owned `projects` + `user_projects`
//! tables for the P2 project list/detail endpoints.

mod delete;
mod members;
mod read;

use serde_json::Value;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::{Postgres, QueryBuilder};

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

use delete::delete_project_dependents;
use read::{
    row_to_activity, row_to_record, PROJECT_COUNT_SQL, PROJECT_DASHBOARD_STATS_SQL,
    PROJECT_GET_SQL, PROJECT_LIST_SQL, PROJECT_OWNER_IDS_SQL, PROJECT_RECENT_ACTIVITY_SQL,
};

#[derive(Debug, Clone)]
pub struct ProjectStatsRecord {
    pub memory_count: i64,
    pub storage_used: i64,
    pub member_count: i64,
    pub last_active: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone)]
pub struct ProjectActivityRecord {
    pub id: String,
    pub user: String,
    pub target: String,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub struct ProjectMemberRecord {
    pub user_id: String,
    pub email: String,
    pub name: Option<String>,
    pub role: String,
    pub permissions: Value,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub struct ProjectMembersRecord {
    pub members: Vec<ProjectMemberRecord>,
    pub total: i64,
}

#[derive(Debug, Clone)]
pub struct ProjectMemberMutationRecord {
    pub role: String,
}

#[derive(Debug, Clone)]
pub struct ProjectDashboardStatsRecord {
    pub memory_count: i64,
    pub conversation_count: i64,
    pub storage_used: i64,
    pub member_count: i64,
    pub recent_activity: Vec<ProjectActivityRecord>,
}

#[derive(Debug, Clone)]
pub struct ProjectReadRecord {
    pub id: String,
    pub tenant_id: String,
    pub name: String,
    pub description: Option<String>,
    pub owner_id: String,
    pub member_ids: Vec<String>,
    pub memory_rules: Value,
    pub graph_config: Value,
    pub graph_store_id: Option<String>,
    pub retrieval_store_id: Option<String>,
    pub sandbox_type: String,
    pub sandbox_config: Value,
    pub is_public: bool,
    pub agent_conversation_mode: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
    pub stats: ProjectStatsRecord,
}

#[derive(Debug, Clone)]
pub struct ProjectCreateRecord {
    pub id: String,
    pub membership_id: String,
    pub tenant_id: String,
    pub name: String,
    pub description: Option<String>,
    pub owner_id: String,
    pub memory_rules: Value,
    pub graph_config: Value,
    pub graph_store_id: Option<String>,
    pub retrieval_store_id: Option<String>,
    pub sandbox_type: String,
    pub sandbox_config: Value,
    pub is_public: bool,
    pub agent_conversation_mode: String,
    pub owner_permissions: Value,
}

#[derive(Debug, Clone, Default)]
pub struct ProjectUpdatePatch {
    pub name: Option<String>,
    pub description: Option<Option<String>>,
    pub memory_rules: Option<Value>,
    pub graph_config: Option<Value>,
    pub graph_store_id: Option<Option<String>>,
    pub retrieval_store_id: Option<Option<String>>,
    pub sandbox_config: Option<Value>,
    pub is_public: Option<bool>,
    pub agent_conversation_mode: Option<String>,
}

impl ProjectUpdatePatch {
    pub fn is_empty(&self) -> bool {
        self.name.is_none()
            && self.description.is_none()
            && self.memory_rules.is_none()
            && self.graph_config.is_none()
            && self.graph_store_id.is_none()
            && self.retrieval_store_id.is_none()
            && self.sandbox_config.is_none()
            && self.is_public.is_none()
            && self.agent_conversation_mode.is_none()
    }
}

#[derive(Debug)]
pub struct ProjectListRecords {
    pub projects: Vec<ProjectReadRecord>,
    pub total: i64,
    pub owner_ids: Vec<String>,
}

#[derive(Debug)]
pub enum ProjectLookup {
    Found(Box<ProjectReadRecord>),
    Forbidden,
    NotFound,
    TenantMismatch,
}

#[derive(Debug, Clone, Copy)]
pub struct ProjectListForUserQuery<'a> {
    pub user_id: &'a str,
    pub tenant_id: Option<&'a str>,
    pub search: Option<&'a str>,
    pub visibility: &'a str,
    pub owner_id: Option<&'a str>,
    pub offset: i64,
    pub limit: i64,
}

#[derive(Debug)]
pub enum ProjectStatsLookup {
    Found(ProjectDashboardStatsRecord),
    Forbidden,
    NotFound,
}

#[derive(Debug)]
pub enum ProjectMembersLookup {
    Found(ProjectMembersRecord),
    InvalidId,
    Forbidden,
    NotFound,
}

pub struct PgProjectReadRepository {
    pool: PgPool,
}

impl PgProjectReadRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn list_for_user(
        &self,
        query: ProjectListForUserQuery<'_>,
    ) -> CoreResult<ProjectListRecords> {
        let tenant_id = blank_to_none(query.tenant_id);
        let owner_id = blank_to_none(query.owner_id);
        let search_value = query.search.unwrap_or("").trim();
        let search_pattern = like(search_value);
        let visibility = normalize_visibility(query.visibility);

        let total = sqlx::query_as::<_, (i64,)>(PROJECT_COUNT_SQL)
            .bind(query.user_id)
            .bind(tenant_id)
            .bind(search_value)
            .bind(&search_pattern)
            .bind(visibility)
            .bind(owner_id)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?
            .0;

        let owner_rows = sqlx::query_as::<_, (String,)>(PROJECT_OWNER_IDS_SQL)
            .bind(query.user_id)
            .bind(tenant_id)
            .bind(search_value)
            .bind(&search_pattern)
            .bind(visibility)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        let owner_ids = owner_rows.into_iter().map(|(owner,)| owner).collect();

        let rows = sqlx::query(PROJECT_LIST_SQL)
            .bind(query.user_id)
            .bind(tenant_id)
            .bind(search_value)
            .bind(&search_pattern)
            .bind(visibility)
            .bind(owner_id)
            .bind(query.offset)
            .bind(query.limit)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;

        Ok(ProjectListRecords {
            projects: rows
                .into_iter()
                .map(row_to_record)
                .collect::<Result<Vec<_>, _>>()
                .map_err(|e| CoreError::Storage(e.to_string()))?,
            total,
            owner_ids,
        })
    }

    pub async fn get_for_user(
        &self,
        user_id: &str,
        project_id: &str,
        tenant_id: Option<&str>,
    ) -> CoreResult<ProjectLookup> {
        let membership = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects WHERE user_id = $1 AND project_id = $2",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;

        // Python checks membership before loading the project, so a missing project
        // without a membership row is a 403, not a 404.
        if membership.0 == 0 {
            return Ok(ProjectLookup::Forbidden);
        }

        let row = sqlx::query(PROJECT_GET_SQL)
            .bind(project_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;

        let Some(row) = row else {
            return Ok(ProjectLookup::NotFound);
        };
        let record = row_to_record(row).map_err(|e| CoreError::Storage(e.to_string()))?;
        if let Some(expected_tenant) = blank_to_none(tenant_id) {
            if record.tenant_id != expected_tenant {
                return Ok(ProjectLookup::TenantMismatch);
            }
        }
        Ok(ProjectLookup::Found(Box::new(record)))
    }

    pub async fn get_by_id(&self, project_id: &str) -> CoreResult<Option<ProjectReadRecord>> {
        let row = sqlx::query(PROJECT_GET_SQL)
            .bind(project_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        row.map(row_to_record)
            .transpose()
            .map_err(|e| CoreError::Storage(e.to_string()))
    }

    pub async fn create_project(
        &self,
        project: &ProjectCreateRecord,
    ) -> CoreResult<ProjectReadRecord> {
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        sqlx::query(
            "INSERT INTO projects \
             (id, tenant_id, name, description, owner_id, memory_rules, graph_config, \
              graph_store_id, retrieval_store_id, sandbox_type, sandbox_config, is_public, \
              agent_conversation_mode) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)",
        )
        .bind(&project.id)
        .bind(&project.tenant_id)
        .bind(&project.name)
        .bind(project.description.as_deref())
        .bind(&project.owner_id)
        .bind(&project.memory_rules)
        .bind(&project.graph_config)
        .bind(project.graph_store_id.as_deref())
        .bind(project.retrieval_store_id.as_deref())
        .bind(&project.sandbox_type)
        .bind(&project.sandbox_config)
        .bind(project.is_public)
        .bind(&project.agent_conversation_mode)
        .execute(&mut *tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        sqlx::query(
            "INSERT INTO user_projects (id, user_id, project_id, role, permissions) \
             VALUES ($1, $2, $3, 'owner', $4)",
        )
        .bind(&project.membership_id)
        .bind(&project.owner_id)
        .bind(&project.id)
        .bind(&project.owner_permissions)
        .execute(&mut *tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        let row = sqlx::query(PROJECT_GET_SQL)
            .bind(&project.id)
            .fetch_one(&mut *tx)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        tx.commit()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        row_to_record(row).map_err(|e| CoreError::Storage(e.to_string()))
    }

    pub async fn update_project(
        &self,
        project_id: &str,
        patch: &ProjectUpdatePatch,
    ) -> CoreResult<Option<ProjectReadRecord>> {
        if !patch.is_empty() {
            let mut builder = QueryBuilder::<Postgres>::new("UPDATE projects SET ");
            let mut separated = builder.separated(", ");
            if let Some(name) = patch.name.as_deref() {
                separated.push("name = ").push_bind_unseparated(name);
            }
            if let Some(description) = &patch.description {
                separated
                    .push("description = ")
                    .push_bind_unseparated(description.as_deref());
            }
            if let Some(memory_rules) = &patch.memory_rules {
                separated
                    .push("memory_rules = ")
                    .push_bind_unseparated(memory_rules);
            }
            if let Some(graph_config) = &patch.graph_config {
                separated
                    .push("graph_config = ")
                    .push_bind_unseparated(graph_config);
            }
            if let Some(graph_store_id) = &patch.graph_store_id {
                separated
                    .push("graph_store_id = ")
                    .push_bind_unseparated(graph_store_id.as_deref());
            }
            if let Some(retrieval_store_id) = &patch.retrieval_store_id {
                separated
                    .push("retrieval_store_id = ")
                    .push_bind_unseparated(retrieval_store_id.as_deref());
            }
            if let Some(sandbox_config) = &patch.sandbox_config {
                separated
                    .push("sandbox_config = ")
                    .push_bind_unseparated(sandbox_config);
            }
            if let Some(is_public) = patch.is_public {
                separated
                    .push("is_public = ")
                    .push_bind_unseparated(is_public);
            }
            if let Some(mode) = patch.agent_conversation_mode.as_deref() {
                separated
                    .push("agent_conversation_mode = ")
                    .push_bind_unseparated(mode);
            }
            separated.push("updated_at = now()");
            builder.push(" WHERE id = ").push_bind(project_id);
            builder
                .build()
                .execute(&self.pool)
                .await
                .map_err(|e| CoreError::Storage(e.to_string()))?;
        }
        self.get_by_id(project_id).await
    }

    pub async fn stats_for_user(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> CoreResult<ProjectStatsLookup> {
        let membership = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects WHERE user_id = $1 AND project_id = $2",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;

        if membership.0 == 0 {
            return Ok(ProjectStatsLookup::Forbidden);
        }

        let exists = sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM projects WHERE id = $1")
            .bind(project_id)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        if exists.0 == 0 {
            return Ok(ProjectStatsLookup::NotFound);
        }

        let stats = sqlx::query_as::<_, (i64, i64, i64, i64)>(PROJECT_DASHBOARD_STATS_SQL)
            .bind(project_id)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;

        let activity_rows = sqlx::query(PROJECT_RECENT_ACTIVITY_SQL)
            .bind(project_id)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        let recent_activity = activity_rows
            .into_iter()
            .map(row_to_activity)
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| CoreError::Storage(e.to_string()))?;

        Ok(ProjectStatsLookup::Found(ProjectDashboardStatsRecord {
            memory_count: stats.0,
            storage_used: stats.1,
            member_count: stats.2,
            conversation_count: stats.3,
            recent_activity,
        }))
    }

    pub async fn graph_store_exists(&self, tenant_id: &str, store_id: &str) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM graph_stores WHERE tenant_id = $1 AND id = $2",
        )
        .bind(tenant_id)
        .bind(store_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(count.0 > 0)
    }

    pub async fn retrieval_store_exists(
        &self,
        tenant_id: &str,
        store_id: &str,
    ) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM retrieval_stores WHERE tenant_id = $1 AND id = $2",
        )
        .bind(tenant_id)
        .bind(store_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(count.0 > 0)
    }

    pub async fn delete_project(&self, project_id: &str) -> CoreResult<bool> {
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;

        delete_project_dependents(&mut tx, project_id).await?;
        let result = sqlx::query("DELETE FROM projects WHERE id = $1")
            .bind(project_id)
            .execute(&mut *tx)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        tx.commit()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(result.rows_affected() > 0)
    }
}

fn blank_to_none(value: Option<&str>) -> Option<&str> {
    value.and_then(|v| {
        let trimmed = v.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed)
        }
    })
}

fn like(term: &str) -> String {
    format!("%{term}%")
}

fn normalize_visibility(value: &str) -> &str {
    match value {
        "public" => "public",
        "private" => "private",
        _ => "all",
    }
}

fn is_python_uuid_like(value: &str) -> bool {
    value.len() == 36
        && value
            .bytes()
            .all(|b| b == b'-' || b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

#[cfg(test)]
mod unit {
    use super::*;

    #[test]
    fn blank_to_none_trims() {
        assert_eq!(blank_to_none(None), None);
        assert_eq!(blank_to_none(Some("")), None);
        assert_eq!(blank_to_none(Some("  ")), None);
        assert_eq!(blank_to_none(Some("tenant")), Some("tenant"));
    }

    #[test]
    fn visibility_is_allowlisted() {
        assert_eq!(normalize_visibility("public"), "public");
        assert_eq!(normalize_visibility("private"), "private");
        assert_eq!(normalize_visibility("bad"), "all");
    }

    #[test]
    fn uuid_like_matches_python_regex_contract() {
        assert!(is_python_uuid_like("00000000-0000-0000-0000-000000000000"));
        assert!(is_python_uuid_like("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"));
        assert!(!is_python_uuid_like("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"));
        assert!(!is_python_uuid_like("not-a-uuid"));
    }

    #[test]
    fn list_sql_keeps_python_ordering_terms_visible() {
        assert!(PROJECT_LIST_SQL.contains("Default project"));
        assert!(PROJECT_LIST_SQL.contains("created_at DESC"));
    }
}
