//! Read-side repository over the Python-owned `projects` + `user_projects`
//! tables for the P2 project list/detail endpoints.

use serde_json::Value;
use sqlx::postgres::PgRow;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::{Postgres, QueryBuilder, Row};

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

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
    Found(ProjectReadRecord),
    Forbidden,
    NotFound,
    TenantMismatch,
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
        user_id: &str,
        tenant_id: Option<&str>,
        search: Option<&str>,
        visibility: &str,
        owner_id: Option<&str>,
        offset: i64,
        limit: i64,
    ) -> CoreResult<ProjectListRecords> {
        let tenant_id = blank_to_none(tenant_id);
        let owner_id = blank_to_none(owner_id);
        let search_value = search.unwrap_or("").trim();
        let search_pattern = like(search_value);
        let visibility = normalize_visibility(visibility);

        let total = sqlx::query_as::<_, (i64,)>(PROJECT_COUNT_SQL)
            .bind(user_id)
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
            .bind(user_id)
            .bind(tenant_id)
            .bind(search_value)
            .bind(&search_pattern)
            .bind(visibility)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        let owner_ids = owner_rows.into_iter().map(|(owner,)| owner).collect();

        let rows = sqlx::query(PROJECT_LIST_SQL)
            .bind(user_id)
            .bind(tenant_id)
            .bind(search_value)
            .bind(&search_pattern)
            .bind(visibility)
            .bind(owner_id)
            .bind(offset)
            .bind(limit)
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
        Ok(ProjectLookup::Found(record))
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

    pub async fn members_for_user(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> CoreResult<ProjectMembersLookup> {
        let exists = sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM projects WHERE id = $1")
            .bind(project_id)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        if exists.0 == 0 {
            if !is_python_uuid_like(project_id) {
                return Ok(ProjectMembersLookup::InvalidId);
            }
            return Ok(ProjectMembersLookup::NotFound);
        }

        let membership = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects WHERE user_id = $1 AND project_id = $2",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        if membership.0 == 0 {
            return Ok(ProjectMembersLookup::Forbidden);
        }

        let rows = sqlx::query(PROJECT_MEMBERS_SQL)
            .bind(project_id)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        let members = rows
            .into_iter()
            .map(row_to_member)
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| CoreError::Storage(e.to_string()))?;

        Ok(ProjectMembersLookup::Found(ProjectMembersRecord {
            total: members.len() as i64,
            members,
        }))
    }

    pub async fn user_is_project_admin(&self, user_id: &str, project_id: &str) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects \
             WHERE user_id = $1 AND project_id = $2 AND role IN ('owner', 'admin')",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(count.0 > 0)
    }

    pub async fn user_is_project_owner(&self, user_id: &str, project_id: &str) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects \
             WHERE user_id = $1 AND project_id = $2 AND role = 'owner'",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(count.0 > 0)
    }

    pub async fn user_is_tenant_project_admin(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_tenants \
             WHERE user_id = $1 AND tenant_id = $2 AND role IN ('owner', 'admin')",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(count.0 > 0)
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

    pub async fn project_exists(&self, project_id: &str) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM projects WHERE id = $1")
            .bind(project_id)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(count.0 > 0)
    }

    pub async fn user_exists(&self, user_id: &str) -> CoreResult<bool> {
        let count = sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM users WHERE id = $1")
            .bind(user_id)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(count.0 > 0)
    }

    pub async fn project_member_role(
        &self,
        project_id: &str,
        user_id: &str,
    ) -> CoreResult<Option<ProjectMemberMutationRecord>> {
        let row = sqlx::query_as::<_, (String,)>(
            "SELECT COALESCE(role, 'member') FROM user_projects \
             WHERE project_id = $1 AND user_id = $2",
        )
        .bind(project_id)
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(row.map(|(role,)| ProjectMemberMutationRecord { role }))
    }

    pub async fn add_project_member(
        &self,
        id: &str,
        project_id: &str,
        user_id: &str,
        role: &str,
        permissions: &Value,
    ) -> CoreResult<()> {
        sqlx::query(
            "INSERT INTO user_projects (id, user_id, project_id, role, permissions) \
             VALUES ($1, $2, $3, $4, $5)",
        )
        .bind(id)
        .bind(user_id)
        .bind(project_id)
        .bind(role)
        .bind(permissions)
        .execute(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(())
    }

    pub async fn update_project_member(
        &self,
        project_id: &str,
        user_id: &str,
        role: &str,
        permissions: &Value,
    ) -> CoreResult<bool> {
        let result = sqlx::query(
            "UPDATE user_projects SET role = $1, permissions = $2 \
             WHERE project_id = $3 AND user_id = $4",
        )
        .bind(role)
        .bind(permissions)
        .bind(project_id)
        .bind(user_id)
        .execute(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn remove_project_member(&self, project_id: &str, user_id: &str) -> CoreResult<bool> {
        let result =
            sqlx::query("DELETE FROM user_projects WHERE project_id = $1 AND user_id = $2")
                .bind(project_id)
                .bind(user_id)
                .execute(&self.pool)
                .await
                .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(result.rows_affected() > 0)
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

#[derive(Debug)]
struct ForeignKeyRef {
    table_name: String,
    column_name: String,
}

async fn delete_project_dependents(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    project_id: &str,
) -> CoreResult<()> {
    let conversation_ids =
        select_ids_by_eq(tx, "conversations", "id", "project_id", project_id).await?;
    let message_ids =
        select_ids_by_any(tx, "messages", "id", "conversation_id", &conversation_ids).await?;
    let workspace_ids = select_ids_by_eq(tx, "workspaces", "id", "project_id", project_id).await?;

    if table_exists(tx, "messages").await? {
        update_null_by_any(tx, "messages", "reply_to_id", &message_ids).await?;
        delete_rows_referencing(tx, "messages", "id", &message_ids, vec!["messages".into()])
            .await?;
        delete_by_any(tx, "messages", "conversation_id", &conversation_ids).await?;
    }

    if table_exists(tx, "conversations").await? {
        update_null_by_any(
            tx,
            "conversations",
            "parent_conversation_id",
            &conversation_ids,
        )
        .await?;
        update_null_by_any(tx, "conversations", "fork_source_id", &conversation_ids).await?;
        delete_rows_referencing(
            tx,
            "conversations",
            "id",
            &conversation_ids,
            vec!["conversations".into(), "messages".into()],
        )
        .await?;
        delete_by_eq(tx, "conversations", "project_id", project_id).await?;
    }

    delete_rows_referencing(
        tx,
        "workspaces",
        "id",
        &workspace_ids,
        vec!["workspaces".into(), "conversations".into()],
    )
    .await?;
    if table_exists(tx, "workspaces").await? {
        delete_by_eq(tx, "workspaces", "project_id", project_id).await?;
    }

    delete_rows_referencing(
        tx,
        "projects",
        "id",
        &[project_id.to_string()],
        vec![
            "projects".into(),
            "conversations".into(),
            "messages".into(),
            "workspaces".into(),
        ],
    )
    .await
}

async fn delete_rows_referencing(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    target_table: &str,
    target_column: &str,
    target_ids: &[String],
    skip_tables: Vec<String>,
) -> CoreResult<()> {
    if target_ids.is_empty() || !table_exists(tx, target_table).await? {
        return Ok(());
    }

    let mut references = foreign_key_references(tx, target_table, target_column).await?;
    if let Some(fallback_column) = fallback_reference_column(target_table) {
        for reference in tables_with_column(tx, fallback_column).await? {
            if reference.table_name == target_table {
                continue;
            }
            if !references.iter().any(|existing| {
                existing.table_name == reference.table_name
                    && existing.column_name == reference.column_name
            }) {
                references.push(reference);
            }
        }
    }

    for reference in references {
        if skip_tables
            .iter()
            .any(|skip| skip.as_str() == reference.table_name)
        {
            continue;
        }

        if table_has_column(tx, &reference.table_name, "id").await? {
            let source_ids = select_ids_by_any(
                tx,
                &reference.table_name,
                "id",
                &reference.column_name,
                target_ids,
            )
            .await?;
            if !source_ids.is_empty() {
                let mut nested_skip = skip_tables.clone();
                nested_skip.push(reference.table_name.clone());
                Box::pin(delete_rows_referencing(
                    tx,
                    &reference.table_name,
                    "id",
                    &source_ids,
                    nested_skip,
                ))
                .await?;
            }
        }

        delete_by_any(
            tx,
            &reference.table_name,
            &reference.column_name,
            target_ids,
        )
        .await?;
    }

    Ok(())
}

fn fallback_reference_column(target_table: &str) -> Option<&'static str> {
    match target_table {
        "projects" => Some("project_id"),
        "conversations" => Some("conversation_id"),
        "workspaces" => Some("workspace_id"),
        "messages" => Some("message_id"),
        _ => None,
    }
}

async fn foreign_key_references(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    target_table: &str,
    target_column: &str,
) -> CoreResult<Vec<ForeignKeyRef>> {
    let rows = sqlx::query(
        "SELECT source_table.relname AS table_name, source_attr.attname AS column_name \
         FROM pg_constraint c \
         JOIN pg_class source_table ON source_table.oid = c.conrelid \
         JOIN pg_namespace source_ns ON source_ns.oid = source_table.relnamespace \
         JOIN pg_class target_table ON target_table.oid = c.confrelid \
         JOIN pg_namespace target_ns ON target_ns.oid = target_table.relnamespace \
         JOIN unnest(c.conkey) WITH ORDINALITY AS source_key(attnum, ord) ON true \
         JOIN unnest(c.confkey) WITH ORDINALITY AS target_key(attnum, ord) \
              ON source_key.ord = target_key.ord \
         JOIN pg_attribute source_attr \
              ON source_attr.attrelid = source_table.oid AND source_attr.attnum = source_key.attnum \
         JOIN pg_attribute target_attr \
              ON target_attr.attrelid = target_table.oid AND target_attr.attnum = target_key.attnum \
         WHERE c.contype = 'f' \
           AND source_ns.nspname = ANY(current_schemas(false)) \
           AND target_ns.nspname = ANY(current_schemas(false)) \
           AND target_table.relname = $1 \
           AND target_attr.attname = $2 \
         ORDER BY source_table.relname, source_attr.attname",
    )
    .bind(target_table)
    .bind(target_column)
    .fetch_all(&mut **tx)
    .await
    .map_err(|e| CoreError::Storage(e.to_string()))?;

    rows.into_iter()
        .map(|row| {
            Ok(ForeignKeyRef {
                table_name: row.try_get("table_name")?,
                column_name: row.try_get("column_name")?,
            })
        })
        .collect::<Result<Vec<_>, sqlx::Error>>()
        .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn tables_with_column(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    column: &str,
) -> CoreResult<Vec<ForeignKeyRef>> {
    let rows = sqlx::query(
        "SELECT c.table_name, c.column_name \
         FROM information_schema.columns c \
         JOIN information_schema.tables t \
           ON t.table_schema = c.table_schema AND t.table_name = c.table_name \
         WHERE c.table_schema = ANY(current_schemas(false)) \
           AND c.column_name = $1 \
           AND t.table_type = 'BASE TABLE' \
         ORDER BY c.table_name",
    )
    .bind(column)
    .fetch_all(&mut **tx)
    .await
    .map_err(|e| CoreError::Storage(e.to_string()))?;

    rows.into_iter()
        .map(|row| {
            Ok(ForeignKeyRef {
                table_name: row.try_get("table_name")?,
                column_name: row.try_get("column_name")?,
            })
        })
        .collect::<Result<Vec<_>, sqlx::Error>>()
        .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn table_exists(tx: &mut sqlx::Transaction<'_, Postgres>, table: &str) -> CoreResult<bool> {
    sqlx::query_as::<_, (bool,)>("SELECT to_regclass($1) IS NOT NULL")
        .bind(table)
        .fetch_one(&mut **tx)
        .await
        .map(|row| row.0)
        .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn table_has_column(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    column: &str,
) -> CoreResult<bool> {
    sqlx::query_as::<_, (bool,)>(
        "SELECT EXISTS ( \
             SELECT 1 FROM information_schema.columns \
             WHERE table_schema = ANY(current_schemas(false)) \
               AND table_name = $1 \
               AND column_name = $2 \
         )",
    )
    .bind(table)
    .bind(column)
    .fetch_one(&mut **tx)
    .await
    .map(|row| row.0)
    .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn select_ids_by_eq(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    id_column: &str,
    filter_column: &str,
    filter_value: &str,
) -> CoreResult<Vec<String>> {
    select_ids_by_any(
        tx,
        table,
        id_column,
        filter_column,
        &[filter_value.to_string()],
    )
    .await
}

async fn select_ids_by_any(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    id_column: &str,
    filter_column: &str,
    filter_values: &[String],
) -> CoreResult<Vec<String>> {
    if filter_values.is_empty()
        || !table_exists(tx, table).await?
        || !table_has_column(tx, table, id_column).await?
        || !table_has_column(tx, table, filter_column).await?
    {
        return Ok(Vec::new());
    }
    let sql = format!(
        "SELECT {}::text AS id FROM {} WHERE {} IS NOT NULL AND {}::text = ANY($1::text[])",
        quote_ident(id_column),
        quote_ident(table),
        quote_ident(id_column),
        quote_ident(filter_column)
    );
    let rows = sqlx::query(&sql)
        .bind(filter_values.to_vec())
        .fetch_all(&mut **tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
    rows.into_iter()
        .map(|row| row.try_get("id"))
        .collect::<Result<Vec<String>, sqlx::Error>>()
        .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn update_null_by_any(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    column: &str,
    ids: &[String],
) -> CoreResult<()> {
    if ids.is_empty()
        || !table_exists(tx, table).await?
        || !table_has_column(tx, table, column).await?
    {
        return Ok(());
    }
    let sql = format!(
        "UPDATE {} SET {} = NULL WHERE {}::text = ANY($1::text[])",
        quote_ident(table),
        quote_ident(column),
        quote_ident(column)
    );
    sqlx::query(&sql)
        .bind(ids.to_vec())
        .execute(&mut **tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
    Ok(())
}

async fn delete_by_eq(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    column: &str,
    value: &str,
) -> CoreResult<()> {
    delete_by_any(tx, table, column, &[value.to_string()]).await
}

async fn delete_by_any(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    column: &str,
    ids: &[String],
) -> CoreResult<()> {
    if ids.is_empty()
        || !table_exists(tx, table).await?
        || !table_has_column(tx, table, column).await?
    {
        return Ok(());
    }
    let sql = format!(
        "DELETE FROM {} WHERE {}::text = ANY($1::text[])",
        quote_ident(table),
        quote_ident(column)
    );
    sqlx::query(&sql)
        .bind(ids.to_vec())
        .execute(&mut **tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
    Ok(())
}

fn quote_ident(value: &str) -> String {
    format!("\"{}\"", value.replace('"', "\"\""))
}

const PROJECT_COUNT_SQL: &str = "\
    SELECT count(*) \
    FROM projects p \
    JOIN user_projects access ON access.project_id = p.id \
    WHERE access.user_id = $1 \
      AND ($2::text IS NULL OR p.tenant_id = $2) \
      AND ($3::text = '' OR p.id ILIKE $4 OR p.name ILIKE $4 \
           OR p.description ILIKE $4 OR p.owner_id ILIKE $4) \
      AND ($5::text <> 'public' OR p.is_public = true) \
      AND ($5::text <> 'private' OR p.is_public = false) \
      AND ($6::text IS NULL OR p.owner_id = $6)";

const PROJECT_OWNER_IDS_SQL: &str = "\
    SELECT DISTINCT p.owner_id \
    FROM projects p \
    JOIN user_projects access ON access.project_id = p.id \
    WHERE access.user_id = $1 \
      AND ($2::text IS NULL OR p.tenant_id = $2) \
      AND ($3::text = '' OR p.id ILIKE $4 OR p.name ILIKE $4 \
           OR p.description ILIKE $4 OR p.owner_id ILIKE $4) \
      AND ($5::text <> 'public' OR p.is_public = true) \
      AND ($5::text <> 'private' OR p.is_public = false) \
    ORDER BY p.owner_id";

const PROJECT_LIST_SQL: &str = "\
    SELECT \
    p.id, p.tenant_id, p.name, p.description, p.owner_id, \
    COALESCE((SELECT array_agg(up.user_id ORDER BY up.user_id) \
              FROM user_projects up WHERE up.project_id = p.id), ARRAY[]::text[]) AS member_ids, \
    COALESCE(p.memory_rules, '{}'::json) AS memory_rules, \
    COALESCE(p.graph_config, '{}'::json) AS graph_config, \
    p.graph_store_id, p.retrieval_store_id, \
    COALESCE(p.sandbox_type, 'cloud') AS sandbox_type, \
    COALESCE(p.sandbox_config, '{}'::json) AS sandbox_config, \
    COALESCE(p.is_public, false) AS is_public, \
    COALESCE(p.agent_conversation_mode, 'single_agent') AS agent_conversation_mode, \
    p.created_at, p.updated_at, \
    COALESCE((SELECT count(*) FROM memories m WHERE m.project_id = p.id), 0)::bigint AS memory_count, \
    COALESCE((SELECT sum(length(m.content)) FROM memories m WHERE m.project_id = p.id), 0)::bigint AS storage_used, \
    COALESCE((SELECT count(*) FROM user_projects up WHERE up.project_id = p.id), 0)::bigint AS member_count, \
    (SELECT max(m.created_at) FROM memories m WHERE m.project_id = p.id) AS last_memory_at \
    FROM projects p \
    JOIN user_projects access ON access.project_id = p.id \
    WHERE access.user_id = $1 \
      AND ($2::text IS NULL OR p.tenant_id = $2) \
      AND ($3::text = '' OR p.id ILIKE $4 OR p.name ILIKE $4 \
           OR p.description ILIKE $4 OR p.owner_id ILIKE $4) \
      AND ($5::text <> 'public' OR p.is_public = true) \
      AND ($5::text <> 'private' OR p.is_public = false) \
      AND ($6::text IS NULL OR p.owner_id = $6) \
    ORDER BY CASE WHEN p.name IN ('Default project', '默认项目') THEN 0 ELSE 1 END ASC, \
             p.created_at DESC, p.id ASC \
    OFFSET $7 LIMIT $8";

const PROJECT_GET_SQL: &str = "\
    SELECT \
    p.id, p.tenant_id, p.name, p.description, p.owner_id, \
    COALESCE((SELECT array_agg(up.user_id ORDER BY up.user_id) \
              FROM user_projects up WHERE up.project_id = p.id), ARRAY[]::text[]) AS member_ids, \
    COALESCE(p.memory_rules, '{}'::json) AS memory_rules, \
    COALESCE(p.graph_config, '{}'::json) AS graph_config, \
    p.graph_store_id, p.retrieval_store_id, \
    COALESCE(p.sandbox_type, 'cloud') AS sandbox_type, \
    COALESCE(p.sandbox_config, '{}'::json) AS sandbox_config, \
    COALESCE(p.is_public, false) AS is_public, \
    COALESCE(p.agent_conversation_mode, 'single_agent') AS agent_conversation_mode, \
    p.created_at, p.updated_at, \
    COALESCE((SELECT count(*) FROM memories m WHERE m.project_id = p.id), 0)::bigint AS memory_count, \
    COALESCE((SELECT sum(length(m.content)) FROM memories m WHERE m.project_id = p.id), 0)::bigint AS storage_used, \
    COALESCE((SELECT count(*) FROM user_projects up WHERE up.project_id = p.id), 0)::bigint AS member_count, \
    (SELECT max(m.created_at) FROM memories m WHERE m.project_id = p.id) AS last_memory_at \
    FROM projects p \
    WHERE p.id = $1";

const PROJECT_DASHBOARD_STATS_SQL: &str = "\
    SELECT \
    COALESCE((SELECT count(*) FROM memories m WHERE m.project_id = $1), 0)::bigint AS memory_count, \
    COALESCE((SELECT sum(length(m.content)) FROM memories m WHERE m.project_id = $1), 0)::bigint AS storage_used, \
    COALESCE((SELECT count(*) FROM user_projects up WHERE up.project_id = $1), 0)::bigint AS member_count, \
    COALESCE((SELECT count(*) FROM conversations c WHERE c.project_id = $1), 0)::bigint AS conversation_count";

const PROJECT_RECENT_ACTIVITY_SQL: &str = "\
    SELECT m.id, COALESCE(NULLIF(u.full_name, ''), u.email) AS user_name, \
           COALESCE(NULLIF(m.title, ''), 'Untitled Memory') AS target, m.created_at \
    FROM memories m \
    JOIN users u ON u.id = m.author_id \
    WHERE m.project_id = $1 \
    ORDER BY m.created_at DESC, m.id ASC \
    LIMIT 5";

const PROJECT_MEMBERS_SQL: &str = "\
    SELECT up.user_id, u.email, u.full_name, COALESCE(up.role, 'member') AS role, \
           COALESCE(up.permissions, '{}'::json) AS permissions, \
           COALESCE(up.created_at, now()) AS created_at \
    FROM user_projects up \
    JOIN users u ON up.user_id = u.id \
    WHERE up.project_id = $1 \
    ORDER BY up.created_at ASC NULLS LAST, up.user_id ASC";

fn row_to_record(row: PgRow) -> Result<ProjectReadRecord, sqlx::Error> {
    let updated_at: Option<DateTime<Utc>> = row.try_get("updated_at")?;
    let last_memory_at: Option<DateTime<Utc>> = row.try_get("last_memory_at")?;
    let last_active = match (updated_at, last_memory_at) {
        (Some(a), Some(b)) => Some(if b > a { b } else { a }),
        (Some(a), None) => Some(a),
        (None, Some(b)) => Some(b),
        (None, None) => None,
    };

    Ok(ProjectReadRecord {
        id: row.try_get("id")?,
        tenant_id: row.try_get("tenant_id")?,
        name: row.try_get("name")?,
        description: row.try_get("description")?,
        owner_id: row.try_get("owner_id")?,
        member_ids: row.try_get("member_ids")?,
        memory_rules: row.try_get("memory_rules")?,
        graph_config: row.try_get("graph_config")?,
        graph_store_id: row.try_get("graph_store_id")?,
        retrieval_store_id: row.try_get("retrieval_store_id")?,
        sandbox_type: row.try_get("sandbox_type")?,
        sandbox_config: row.try_get("sandbox_config")?,
        is_public: row.try_get("is_public")?,
        agent_conversation_mode: row.try_get("agent_conversation_mode")?,
        created_at: row.try_get("created_at")?,
        updated_at,
        stats: ProjectStatsRecord {
            memory_count: row.try_get("memory_count")?,
            storage_used: row.try_get("storage_used")?,
            member_count: row.try_get("member_count")?,
            last_active,
        },
    })
}

fn row_to_activity(row: PgRow) -> Result<ProjectActivityRecord, sqlx::Error> {
    Ok(ProjectActivityRecord {
        id: row.try_get("id")?,
        user: row.try_get("user_name")?,
        target: row.try_get("target")?,
        created_at: row.try_get("created_at")?,
    })
}

fn row_to_member(row: PgRow) -> Result<ProjectMemberRecord, sqlx::Error> {
    Ok(ProjectMemberRecord {
        user_id: row.try_get("user_id")?,
        email: row.try_get("email")?,
        name: row.try_get("full_name")?,
        role: row.try_get("role")?,
        permissions: row.try_get("permissions")?,
        created_at: row.try_get("created_at")?,
    })
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
