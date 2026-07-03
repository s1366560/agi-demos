//! Repository over Python-owned `skills` and `skill_versions`.
//!
//! This is the P5 skill-store bridge for the strangler migration: Rust reads and
//! writes the same database rows as the Python skill router, while keeping sqlx
//! and all server-only persistence concerns out of the portable core.

use serde_json::Value;
use sqlx::postgres::PgRow;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::types::Json;
use sqlx::{QueryBuilder, Row};

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const SKILL_COLS: &str = "id, tenant_id, project_id, name, description, tools, status, \
    metadata_json, created_at, updated_at, scope, is_system_skill, full_content, \
    resource_files, license, compatibility, allowed_tools_raw, spec_version, \
    current_version, version_label";

const VERSION_COLS: &str = "id, skill_id, version_number, version_label, skill_md_content, \
    resource_files, change_summary, created_by, created_at";

#[derive(Debug, Clone, PartialEq)]
pub struct SkillRecord {
    pub id: String,
    pub tenant_id: String,
    pub project_id: Option<String>,
    pub name: String,
    pub description: String,
    pub tools: Vec<String>,
    pub status: String,
    pub metadata_json: Option<Value>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
    pub scope: String,
    pub is_system_skill: bool,
    pub full_content: Option<String>,
    pub resource_files: Value,
    pub license: Option<String>,
    pub compatibility: Option<String>,
    pub allowed_tools_raw: Option<String>,
    pub spec_version: String,
    pub current_version: i32,
    pub version_label: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct SkillUpdateRecord {
    pub name: Option<String>,
    pub description: Option<String>,
    pub tools: Option<Vec<String>>,
    pub status: Option<String>,
    pub metadata_json: Option<Option<Value>>,
    pub full_content: Option<Option<String>>,
    pub resource_files: Option<Value>,
    pub license: Option<Option<String>>,
    pub compatibility: Option<Option<String>>,
    pub allowed_tools_raw: Option<Option<String>>,
    pub spec_version: Option<String>,
    pub current_version: Option<i32>,
    pub version_label: Option<Option<String>>,
}

impl SkillUpdateRecord {
    pub fn apply_to(self, mut record: SkillRecord, updated_at: DateTime<Utc>) -> SkillRecord {
        if let Some(value) = self.name {
            record.name = value;
        }
        if let Some(value) = self.description {
            record.description = value;
        }
        if let Some(value) = self.tools {
            record.tools = value;
        }
        if let Some(value) = self.status {
            record.status = value;
        }
        if let Some(value) = self.metadata_json {
            record.metadata_json = value;
        }
        if let Some(value) = self.full_content {
            record.full_content = value;
        }
        if let Some(value) = self.resource_files {
            record.resource_files = value;
        }
        if let Some(value) = self.license {
            record.license = value;
        }
        if let Some(value) = self.compatibility {
            record.compatibility = value;
        }
        if let Some(value) = self.allowed_tools_raw {
            record.allowed_tools_raw = value;
        }
        if let Some(value) = self.spec_version {
            record.spec_version = value;
        }
        if let Some(value) = self.current_version {
            record.current_version = value;
        }
        if let Some(value) = self.version_label {
            record.version_label = value;
        }
        record.updated_at = Some(updated_at);
        record
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct SkillVersionRecord {
    pub id: String,
    pub skill_id: String,
    pub version_number: i32,
    pub version_label: Option<String>,
    pub skill_md_content: String,
    pub resource_files: Value,
    pub change_summary: Option<String>,
    pub created_by: String,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SkillProjectAccess {
    Read,
    Write,
}

pub struct PgSkillRepository {
    pool: PgPool,
}

impl PgSkillRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn first_tenant_for_user(&self, user_id: &str) -> CoreResult<Option<String>> {
        let row = sqlx::query_as::<_, (String,)>(
            "SELECT tenant_id FROM user_tenants WHERE user_id = $1 \
             ORDER BY created_at ASC, id ASC LIMIT 1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        Ok(row.map(|(tenant_id,)| tenant_id))
    }

    pub async fn user_has_tenant_access(&self, user_id: &str, tenant_id: &str) -> CoreResult<bool> {
        let row = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_tenants WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        Ok(row.0 > 0)
    }

    pub async fn user_is_tenant_admin(&self, user_id: &str, tenant_id: &str) -> CoreResult<bool> {
        let row = sqlx::query_as::<_, (Option<String>,)>(
            "SELECT role FROM user_tenants WHERE user_id = $1 AND tenant_id = $2 LIMIT 1",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        Ok(matches!(
            row.and_then(|(role,)| role),
            Some(role) if role == "owner" || role == "admin"
        ))
    }

    pub async fn user_can_access_project(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        access: SkillProjectAccess,
    ) -> CoreResult<bool> {
        let row = sqlx::query_as::<_, (String,)>(
            "SELECT up.role FROM user_projects up \
             JOIN projects p ON p.id = up.project_id \
             WHERE up.user_id = $1 AND up.project_id = $2 AND p.tenant_id = $3 \
             LIMIT 1",
        )
        .bind(user_id)
        .bind(project_id)
        .bind(tenant_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        let Some((role,)) = row else {
            return Ok(false);
        };
        Ok(match access {
            SkillProjectAccess::Read => true,
            SkillProjectAccess::Write => matches!(role.as_str(), "owner" | "admin" | "member"),
        })
    }

    pub async fn create_skill(&self, record: &SkillRecord) -> CoreResult<SkillRecord> {
        sqlx::query(
            "INSERT INTO skills (id, tenant_id, project_id, name, description, tools, status, \
             metadata_json, created_at, updated_at, scope, is_system_skill, full_content, \
             resource_files, license, compatibility, allowed_tools_raw, spec_version, \
             current_version, version_label) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)",
        )
        .bind(&record.id)
        .bind(&record.tenant_id)
        .bind(&record.project_id)
        .bind(&record.name)
        .bind(&record.description)
        .bind(Json(&record.tools))
        .bind(&record.status)
        .bind(&record.metadata_json)
        .bind(record.created_at)
        .bind(record.updated_at)
        .bind(&record.scope)
        .bind(record.is_system_skill)
        .bind(&record.full_content)
        .bind(&record.resource_files)
        .bind(&record.license)
        .bind(&record.compatibility)
        .bind(&record.allowed_tools_raw)
        .bind(&record.spec_version)
        .bind(record.current_version)
        .bind(&record.version_label)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(record.clone())
    }

    pub async fn get_skill(&self, skill_id: &str) -> CoreResult<Option<SkillRecord>> {
        let sql = format!("SELECT {SKILL_COLS} FROM skills WHERE id = $1");
        let row = sqlx::query(&sql)
            .bind(skill_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?;
        row.map(row_to_skill).transpose()
    }

    pub async fn find_skill(
        &self,
        tenant_id: &str,
        name: &str,
        scope: &str,
        project_id: Option<&str>,
    ) -> CoreResult<Option<SkillRecord>> {
        let sql = format!(
            "SELECT {SKILL_COLS} FROM skills \
             WHERE tenant_id = $1 AND name = $2 AND scope = $3 \
             AND (($4::text IS NULL AND project_id IS NULL) OR project_id = $4) \
             LIMIT 1"
        );
        let row = sqlx::query(&sql)
            .bind(tenant_id)
            .bind(name)
            .bind(scope)
            .bind(project_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?;
        row.map(row_to_skill).transpose()
    }

    pub async fn list_for_tenant(
        &self,
        tenant_id: &str,
        status: Option<&str>,
        scope: Option<&str>,
        project_id: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<SkillRecord>> {
        let mut query = QueryBuilder::new(format!(
            "SELECT {SKILL_COLS} FROM skills WHERE tenant_id = "
        ));
        query.push_bind(tenant_id);

        if let Some(status) = status {
            query.push(" AND status = ");
            query.push_bind(status);
        }

        match (scope, project_id) {
            (Some("project"), Some(project_id)) => {
                query.push(" AND scope = 'project' AND project_id = ");
                query.push_bind(project_id);
            }
            (Some("project"), None) => {
                query.push(" AND false");
            }
            (Some(scope), _) => {
                query.push(" AND scope = ");
                query.push_bind(scope);
                query.push(" AND project_id IS NULL");
            }
            (None, Some(project_id)) => {
                query.push(" AND ((scope = 'tenant' AND project_id IS NULL) OR (scope = 'project' AND project_id = ");
                query.push_bind(project_id);
                query.push("))");
            }
            (None, None) => {
                query.push(" AND project_id IS NULL");
            }
        }

        query.push(" ORDER BY created_at DESC, id DESC LIMIT ");
        query.push_bind(limit);
        query.push(" OFFSET ");
        query.push_bind(offset);

        let rows = query.build().fetch_all(&self.pool).await.map_err(storage)?;
        rows.into_iter().map(row_to_skill).collect()
    }

    pub async fn update_skill(&self, record: &SkillRecord) -> CoreResult<SkillRecord> {
        sqlx::query(
            "UPDATE skills SET name=$2, description=$3, tools=$4, status=$5, \
             metadata_json=$6, updated_at=$7, scope=$8, is_system_skill=$9, \
             full_content=$10, resource_files=$11, license=$12, compatibility=$13, \
             allowed_tools_raw=$14, spec_version=$15, current_version=$16, version_label=$17 \
             WHERE id=$1",
        )
        .bind(&record.id)
        .bind(&record.name)
        .bind(&record.description)
        .bind(Json(&record.tools))
        .bind(&record.status)
        .bind(&record.metadata_json)
        .bind(record.updated_at)
        .bind(&record.scope)
        .bind(record.is_system_skill)
        .bind(&record.full_content)
        .bind(&record.resource_files)
        .bind(&record.license)
        .bind(&record.compatibility)
        .bind(&record.allowed_tools_raw)
        .bind(&record.spec_version)
        .bind(record.current_version)
        .bind(&record.version_label)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(record.clone())
    }

    pub async fn delete_skill(&self, skill_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM skills WHERE id = $1")
            .bind(skill_id)
            .execute(&self.pool)
            .await
            .map_err(storage)?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn max_version_number(&self, skill_id: &str) -> CoreResult<i32> {
        let row = sqlx::query_as::<_, (Option<i32>,)>(
            "SELECT max(version_number) FROM skill_versions WHERE skill_id = $1",
        )
        .bind(skill_id)
        .fetch_one(&self.pool)
        .await
        .map_err(storage)?;
        Ok(row.0.unwrap_or(0))
    }

    pub async fn create_version(
        &self,
        version: &SkillVersionRecord,
    ) -> CoreResult<SkillVersionRecord> {
        sqlx::query(
            "INSERT INTO skill_versions (id, skill_id, version_number, version_label, \
             skill_md_content, resource_files, change_summary, created_by, created_at) \
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
        )
        .bind(&version.id)
        .bind(&version.skill_id)
        .bind(version.version_number)
        .bind(&version.version_label)
        .bind(&version.skill_md_content)
        .bind(&version.resource_files)
        .bind(&version.change_summary)
        .bind(&version.created_by)
        .bind(version.created_at)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(version.clone())
    }

    pub async fn list_versions(
        &self,
        skill_id: &str,
        limit: i64,
        offset: i64,
    ) -> CoreResult<Vec<SkillVersionRecord>> {
        let sql = format!(
            "SELECT {VERSION_COLS} FROM skill_versions WHERE skill_id = $1 \
             ORDER BY version_number DESC LIMIT $2 OFFSET $3"
        );
        let rows = sqlx::query(&sql)
            .bind(skill_id)
            .bind(limit)
            .bind(offset)
            .fetch_all(&self.pool)
            .await
            .map_err(storage)?;
        rows.into_iter().map(row_to_version).collect()
    }

    pub async fn count_versions(&self, skill_id: &str) -> CoreResult<i64> {
        let row =
            sqlx::query_as::<_, (i64,)>("SELECT count(*) FROM skill_versions WHERE skill_id = $1")
                .bind(skill_id)
                .fetch_one(&self.pool)
                .await
                .map_err(storage)?;
        Ok(row.0)
    }

    pub async fn get_version(
        &self,
        skill_id: &str,
        version_number: i32,
    ) -> CoreResult<Option<SkillVersionRecord>> {
        let sql = format!(
            "SELECT {VERSION_COLS} FROM skill_versions WHERE skill_id = $1 AND version_number = $2"
        );
        let row = sqlx::query(&sql)
            .bind(skill_id)
            .bind(version_number)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?;
        row.map(row_to_version).transpose()
    }

    pub async fn get_latest_version(
        &self,
        skill_id: &str,
    ) -> CoreResult<Option<SkillVersionRecord>> {
        let sql = format!(
            "SELECT {VERSION_COLS} FROM skill_versions WHERE skill_id = $1 \
             ORDER BY version_number DESC LIMIT 1"
        );
        let row = sqlx::query(&sql)
            .bind(skill_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?;
        row.map(row_to_version).transpose()
    }
}

fn row_to_skill(row: PgRow) -> CoreResult<SkillRecord> {
    Ok(SkillRecord {
        id: row.try_get("id").map_err(storage)?,
        tenant_id: row.try_get("tenant_id").map_err(storage)?,
        project_id: row.try_get("project_id").map_err(storage)?,
        name: row.try_get("name").map_err(storage)?,
        description: row.try_get("description").map_err(storage)?,
        tools: row
            .try_get::<Json<Vec<String>>, _>("tools")
            .map_err(storage)?
            .0,
        status: row.try_get("status").map_err(storage)?,
        metadata_json: row.try_get("metadata_json").map_err(storage)?,
        created_at: row.try_get("created_at").map_err(storage)?,
        updated_at: row.try_get("updated_at").map_err(storage)?,
        scope: row.try_get("scope").map_err(storage)?,
        is_system_skill: row.try_get("is_system_skill").map_err(storage)?,
        full_content: row.try_get("full_content").map_err(storage)?,
        resource_files: row
            .try_get::<Option<Value>, _>("resource_files")
            .map_err(storage)?
            .unwrap_or_else(|| Value::Object(Default::default())),
        license: row.try_get("license").map_err(storage)?,
        compatibility: row.try_get("compatibility").map_err(storage)?,
        allowed_tools_raw: row.try_get("allowed_tools_raw").map_err(storage)?,
        spec_version: row.try_get("spec_version").map_err(storage)?,
        current_version: row.try_get("current_version").map_err(storage)?,
        version_label: row.try_get("version_label").map_err(storage)?,
    })
}

fn row_to_version(row: PgRow) -> CoreResult<SkillVersionRecord> {
    Ok(SkillVersionRecord {
        id: row.try_get("id").map_err(storage)?,
        skill_id: row.try_get("skill_id").map_err(storage)?,
        version_number: row.try_get("version_number").map_err(storage)?,
        version_label: row.try_get("version_label").map_err(storage)?,
        skill_md_content: row.try_get("skill_md_content").map_err(storage)?,
        resource_files: row
            .try_get::<Option<Value>, _>("resource_files")
            .map_err(storage)?
            .unwrap_or_else(|| Value::Object(Default::default())),
        change_summary: row.try_get("change_summary").map_err(storage)?,
        created_by: row.try_get("created_by").map_err(storage)?,
        created_at: row.try_get("created_at").map_err(storage)?,
    })
}

fn storage<E: std::fmt::Display>(error: E) -> CoreError {
    CoreError::Storage(error.to_string())
}
