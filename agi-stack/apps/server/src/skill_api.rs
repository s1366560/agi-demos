//! P5 skill-store and versioning foundation.
//!
//! This module mirrors the database-backed subset of Python's `/api/v1/skills`
//! router: tenant/project skill CRUD, content updates, version snapshots, and
//! rollback/export. Filesystem system skills, package import/zip, publish/clone,
//! and evolution jobs remain Python-owned until their full semantics are migrated.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, patch, post},
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use serde_yaml_ng::{Mapping as YamlMapping, Value as YamlValue};

use agistack_adapters_postgres::{
    PgSkillRepository, SkillProjectAccess, SkillRecord, SkillUpdateRecord, SkillVersionRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedSkills = Arc<dyn SkillService>;

#[async_trait]
pub(crate) trait SkillService: Send + Sync {
    async fn create_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SkillCreatePayload,
    ) -> Result<SkillView, SkillApiError>;

    async fn list_skills(
        &self,
        user_id: &str,
        query: SkillListQuery,
    ) -> Result<SkillListView, SkillApiError>;

    async fn get_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillView, SkillApiError>;

    async fn update_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        body: SkillUpdatePayload,
    ) -> Result<SkillView, SkillApiError>;

    async fn delete_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<(), SkillApiError>;

    async fn update_status(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        status: &str,
    ) -> Result<SkillView, SkillApiError>;

    async fn get_content(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillContentView, SkillApiError>;

    async fn update_content(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        body: SkillContentUpdatePayload,
    ) -> Result<SkillView, SkillApiError>;

    async fn list_versions(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<SkillVersionListView, SkillApiError>;

    async fn get_version(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        version_number: i32,
    ) -> Result<SkillVersionDetailView, SkillApiError>;

    async fn rollback(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        body: SkillRollbackPayload,
    ) -> Result<SkillView, SkillApiError>;

    async fn export_package(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillPackageView, SkillApiError>;
}

#[derive(Debug)]
pub(crate) struct SkillApiError {
    status: StatusCode,
    detail: String,
}

impl SkillApiError {
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

    fn conflict(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::CONFLICT, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for SkillApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SkillCreatePayload {
    name: String,
    description: String,
    tools: Vec<String>,
    #[serde(default)]
    full_content: Option<String>,
    #[serde(default)]
    project_id: Option<String>,
    #[serde(default = "default_scope")]
    scope: String,
    #[serde(default)]
    metadata: Option<Value>,
    #[serde(default)]
    license: Option<String>,
    #[serde(default)]
    compatibility: Option<String>,
    #[serde(default)]
    allowed_tools_raw: Option<String>,
    #[serde(default)]
    spec_version: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct SkillUpdatePayload {
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    tools: Option<Vec<String>>,
    #[serde(default)]
    full_content: Option<String>,
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    metadata: Option<Value>,
    #[serde(default)]
    license: Option<String>,
    #[serde(default)]
    compatibility: Option<String>,
    #[serde(default)]
    allowed_tools_raw: Option<String>,
    #[serde(default)]
    spec_version: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SkillContentUpdatePayload {
    full_content: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SkillRollbackPayload {
    version_number: i32,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SkillListQuery {
    #[serde(default)]
    search: Option<String>,
    #[serde(default)]
    q: Option<String>,
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    scope: Option<String>,
    #[serde(default)]
    project_id: Option<String>,
    #[serde(default)]
    tenant_id: Option<String>,
    #[serde(default)]
    skip: Option<i64>,
    #[serde(default)]
    offset: Option<i64>,
    #[serde(default)]
    limit: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
struct TenantQuery {
    #[serde(default)]
    tenant_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct SkillStatusQuery {
    status: String,
    #[serde(default)]
    tenant_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct SkillVersionQuery {
    #[serde(default)]
    tenant_id: Option<String>,
    #[serde(default)]
    limit: Option<i64>,
    #[serde(default)]
    offset: Option<i64>,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillView {
    id: String,
    tenant_id: String,
    project_id: Option<String>,
    name: String,
    description: String,
    tools: Vec<String>,
    full_content: Option<String>,
    status: String,
    scope: String,
    is_system_skill: bool,
    source: String,
    file_path: Option<String>,
    created_at: String,
    updated_at: String,
    metadata: Option<Value>,
    resource_files: Value,
    agent_modes: Vec<String>,
    license: Option<String>,
    compatibility: Option<String>,
    allowed_tools_raw: Option<String>,
    spec_version: String,
    current_version: i32,
    version_label: Option<String>,
}

impl From<SkillRecord> for SkillView {
    fn from(record: SkillRecord) -> Self {
        let updated_at = record.updated_at.unwrap_or(record.created_at);
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            project_id: record.project_id,
            name: record.name,
            description: record.description,
            tools: record.tools,
            full_content: record.full_content,
            status: record.status,
            scope: record.scope,
            is_system_skill: record.is_system_skill,
            source: "database".to_string(),
            file_path: None,
            created_at: iso8601(record.created_at),
            updated_at: iso8601(updated_at),
            metadata: record.metadata_json,
            resource_files: record.resource_files,
            agent_modes: vec!["*".to_string()],
            license: record.license,
            compatibility: record.compatibility,
            allowed_tools_raw: record.allowed_tools_raw,
            spec_version: record.spec_version,
            current_version: record.current_version,
            version_label: record.version_label,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillListView {
    skills: Vec<SkillView>,
    total: usize,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillContentView {
    skill_id: String,
    name: String,
    full_content: Option<String>,
    scope: String,
    is_system_skill: bool,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillVersionView {
    id: String,
    skill_id: String,
    version_number: i32,
    version_label: Option<String>,
    change_summary: Option<String>,
    created_by: String,
    created_at: String,
}

impl From<SkillVersionRecord> for SkillVersionView {
    fn from(record: SkillVersionRecord) -> Self {
        Self {
            id: record.id,
            skill_id: record.skill_id,
            version_number: record.version_number,
            version_label: record.version_label,
            change_summary: record.change_summary,
            created_by: record.created_by,
            created_at: iso8601(record.created_at),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillVersionDetailView {
    id: String,
    skill_id: String,
    version_number: i32,
    version_label: Option<String>,
    skill_md_content: String,
    resource_files: Value,
    change_summary: Option<String>,
    created_by: String,
    created_at: String,
}

impl From<SkillVersionRecord> for SkillVersionDetailView {
    fn from(record: SkillVersionRecord) -> Self {
        Self {
            id: record.id,
            skill_id: record.skill_id,
            version_number: record.version_number,
            version_label: record.version_label,
            skill_md_content: record.skill_md_content,
            resource_files: record.resource_files,
            change_summary: record.change_summary,
            created_by: record.created_by,
            created_at: iso8601(record.created_at),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillVersionListView {
    versions: Vec<SkillVersionView>,
    total: i64,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SkillPackageView {
    format: String,
    skill: SkillView,
    skill_md_content: String,
    resource_files: Value,
    version_number: Option<i32>,
    version_label: Option<String>,
}

pub(crate) struct PgSkillService {
    repo: PgSkillRepository,
}

impl PgSkillService {
    pub(crate) fn new(repo: PgSkillRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl SkillService for PgSkillService {
    async fn create_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SkillCreatePayload,
    ) -> Result<SkillView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let scope = normalize_scope(&body.scope, body.project_id.as_deref())?;
        self.ensure_write_access(user_id, &tenant_id, &scope, body.project_id.as_deref())
            .await?;

        let parsed = ParsedSkillPayload::from_content(body.full_content.as_deref());
        let name = parsed.name.unwrap_or(body.name);
        let description = parsed.description.unwrap_or(body.description);
        let tools = parsed.tools.unwrap_or(body.tools);
        validate_skill_input(&name, &description, &tools)?;
        if self
            .repo
            .find_skill(&tenant_id, &name, &scope, body.project_id.as_deref())
            .await
            .map_err(SkillApiError::internal)?
            .is_some()
        {
            return Err(SkillApiError::conflict("Skill already exists"));
        }

        let now = Utc::now();
        let metadata = merge_agentskills_metadata(
            body.metadata,
            body.license.as_deref(),
            body.compatibility.as_deref(),
            body.allowed_tools_raw.as_deref(),
            body.spec_version.as_deref(),
        );
        let record = SkillRecord {
            id: generate_uuid_v4(),
            tenant_id,
            project_id: body.project_id,
            name,
            description,
            tools,
            status: "active".to_string(),
            metadata_json: metadata,
            created_at: now,
            updated_at: Some(now),
            scope,
            is_system_skill: false,
            full_content: body.full_content,
            resource_files: json!({}),
            license: body.license,
            compatibility: body.compatibility,
            allowed_tools_raw: body.allowed_tools_raw,
            spec_version: body.spec_version.unwrap_or_else(|| "1.0".to_string()),
            current_version: 0,
            version_label: parsed.version_label,
        };
        Ok(self
            .repo
            .create_skill(&record)
            .await
            .map_err(SkillApiError::internal)?
            .into())
    }

    async fn list_skills(
        &self,
        user_id: &str,
        query: SkillListQuery,
    ) -> Result<SkillListView, SkillApiError> {
        let tenant_id = self
            .resolve_tenant(user_id, query.tenant_id.as_deref())
            .await?;
        let scope = query
            .scope
            .as_deref()
            .map(normalize_scope_filter)
            .transpose()?;
        let status = query.status.as_deref().map(normalize_status).transpose()?;
        if let Some(project_id) = query.project_id.as_deref() {
            self.ensure_project_access(user_id, &tenant_id, project_id, SkillProjectAccess::Read)
                .await?;
        }

        let mut records = self
            .repo
            .list_for_tenant(
                &tenant_id,
                status.as_deref(),
                scope.as_deref(),
                query.project_id.as_deref(),
                5_000,
                0,
            )
            .await
            .map_err(SkillApiError::internal)?;
        let search = query.search.or(query.q).unwrap_or_default();
        if !search.trim().is_empty() {
            let needle = search.trim().to_ascii_lowercase();
            records.retain(|record| skill_matches_search(record, &needle));
        }
        let total = records.len();
        let offset = query.skip.or(query.offset).unwrap_or(0).clamp(0, i64::MAX) as usize;
        let limit = query.limit.unwrap_or(100).clamp(1, 500) as usize;
        let skills = records
            .into_iter()
            .skip(offset)
            .take(limit)
            .map(SkillView::from)
            .collect();
        Ok(SkillListView { skills, total })
    }

    async fn get_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let skill = self.readable_skill(user_id, &tenant_id, skill_id).await?;
        Ok(skill.into())
    }

    async fn update_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        body: SkillUpdatePayload,
    ) -> Result<SkillView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let skill = self.writable_skill(user_id, &tenant_id, skill_id).await?;
        let parsed = ParsedSkillPayload::from_content(body.full_content.as_deref());
        let next_name = parsed
            .name
            .clone()
            .or_else(|| body.name.clone())
            .unwrap_or_else(|| skill.name.clone());
        let next_description = parsed
            .description
            .clone()
            .or_else(|| body.description.clone())
            .unwrap_or_else(|| skill.description.clone());
        let next_tools = parsed
            .tools
            .clone()
            .or_else(|| body.tools.clone())
            .unwrap_or_else(|| skill.tools.clone());
        validate_skill_input(&next_name, &next_description, &next_tools)?;
        if next_name != skill.name {
            if let Some(existing) = self
                .repo
                .find_skill(
                    &tenant_id,
                    &next_name,
                    &skill.scope,
                    skill.project_id.as_deref(),
                )
                .await
                .map_err(SkillApiError::internal)?
            {
                if existing.id != skill.id {
                    return Err(SkillApiError::conflict("Skill already exists"));
                }
            }
        }

        let status = body
            .status
            .as_deref()
            .map(normalize_status)
            .transpose()?
            .unwrap_or_else(|| skill.status.clone());
        let now = Utc::now();
        let patch = SkillUpdateRecord {
            name: Some(next_name),
            description: Some(next_description),
            tools: Some(next_tools),
            status: Some(status),
            metadata_json: body.metadata.map(Some),
            full_content: body.full_content.map(Some),
            license: body.license.map(Some),
            compatibility: body.compatibility.map(Some),
            allowed_tools_raw: body.allowed_tools_raw.map(Some),
            spec_version: body.spec_version,
            version_label: parsed.version_label.map(Some),
            ..Default::default()
        };
        let updated = patch.apply_to(skill, now);
        Ok(self
            .repo
            .update_skill(&updated)
            .await
            .map_err(SkillApiError::internal)?
            .into())
    }

    async fn delete_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<(), SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let _skill = self.writable_skill(user_id, &tenant_id, skill_id).await?;
        self.repo
            .delete_skill(skill_id)
            .await
            .map_err(SkillApiError::internal)?;
        Ok(())
    }

    async fn update_status(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        status: &str,
    ) -> Result<SkillView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let skill = self.writable_skill(user_id, &tenant_id, skill_id).await?;
        let now = Utc::now();
        let updated = SkillUpdateRecord {
            status: Some(normalize_status(status)?),
            ..Default::default()
        }
        .apply_to(skill, now);
        Ok(self
            .repo
            .update_skill(&updated)
            .await
            .map_err(SkillApiError::internal)?
            .into())
    }

    async fn get_content(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillContentView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let skill = self.readable_skill(user_id, &tenant_id, skill_id).await?;
        Ok(SkillContentView {
            skill_id: skill.id,
            name: skill.name,
            full_content: skill.full_content,
            scope: skill.scope,
            is_system_skill: skill.is_system_skill,
        })
    }

    async fn update_content(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        body: SkillContentUpdatePayload,
    ) -> Result<SkillView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let skill = self.writable_skill(user_id, &tenant_id, skill_id).await?;
        let parsed = ParsedSkillPayload::from_content(Some(&body.full_content));
        let next_name = parsed.name.unwrap_or_else(|| skill.name.clone());
        let next_description = parsed
            .description
            .unwrap_or_else(|| skill.description.clone());
        let next_tools = parsed.tools.unwrap_or_else(|| skill.tools.clone());
        validate_skill_input(&next_name, &next_description, &next_tools)?;
        let now = Utc::now();
        let mut updated = SkillUpdateRecord {
            name: Some(next_name),
            description: Some(next_description),
            tools: Some(next_tools),
            full_content: Some(Some(body.full_content.clone())),
            metadata_json: parsed.metadata.map(Some),
            version_label: parsed.version_label.clone().map(Some),
            ..Default::default()
        }
        .apply_to(skill, now);
        let next_version = self
            .repo
            .max_version_number(skill_id)
            .await
            .map_err(SkillApiError::internal)?
            + 1;
        let version_label = updated
            .version_label
            .clone()
            .or_else(|| Some(next_version.to_string()));
        let version = SkillVersionRecord {
            id: generate_uuid_v4(),
            skill_id: skill_id.to_string(),
            version_number: next_version,
            version_label: version_label.clone(),
            skill_md_content: body.full_content,
            resource_files: updated.resource_files.clone(),
            change_summary: Some("Manual content update".to_string()),
            created_by: "agent".to_string(),
            created_at: now,
        };
        self.repo
            .create_version(&version)
            .await
            .map_err(SkillApiError::internal)?;
        updated.current_version = next_version;
        updated.version_label = version_label;
        Ok(self
            .repo
            .update_skill(&updated)
            .await
            .map_err(SkillApiError::internal)?
            .into())
    }

    async fn list_versions(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<SkillVersionListView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let _skill = self.readable_skill(user_id, &tenant_id, skill_id).await?;
        let versions = self
            .repo
            .list_versions(skill_id, limit.clamp(1, 100), offset.max(0))
            .await
            .map_err(SkillApiError::internal)?;
        let total = self
            .repo
            .count_versions(skill_id)
            .await
            .map_err(SkillApiError::internal)?;
        Ok(SkillVersionListView {
            versions: versions.into_iter().map(SkillVersionView::from).collect(),
            total,
        })
    }

    async fn get_version(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        version_number: i32,
    ) -> Result<SkillVersionDetailView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let _skill = self.readable_skill(user_id, &tenant_id, skill_id).await?;
        let version = self
            .repo
            .get_version(skill_id, version_number)
            .await
            .map_err(SkillApiError::internal)?
            .ok_or_else(|| SkillApiError::not_found("Skill version not found"))?;
        Ok(version.into())
    }

    async fn rollback(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        body: SkillRollbackPayload,
    ) -> Result<SkillView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let skill = self.writable_skill(user_id, &tenant_id, skill_id).await?;
        let target = self
            .repo
            .get_version(skill_id, body.version_number)
            .await
            .map_err(SkillApiError::internal)?
            .ok_or_else(|| SkillApiError::bad_request("Skill version not found"))?;
        let now = Utc::now();
        let next_version = self
            .repo
            .max_version_number(skill_id)
            .await
            .map_err(SkillApiError::internal)?
            + 1;
        let rollback_version = SkillVersionRecord {
            id: generate_uuid_v4(),
            skill_id: skill_id.to_string(),
            version_number: next_version,
            version_label: target.version_label.clone(),
            skill_md_content: target.skill_md_content.clone(),
            resource_files: target.resource_files.clone(),
            change_summary: Some(format!("Rollback to version {}", body.version_number)),
            created_by: "rollback".to_string(),
            created_at: now,
        };
        self.repo
            .create_version(&rollback_version)
            .await
            .map_err(SkillApiError::internal)?;
        let updated = SkillUpdateRecord {
            full_content: Some(Some(target.skill_md_content)),
            resource_files: Some(target.resource_files),
            current_version: Some(next_version),
            version_label: target.version_label.map(Some),
            ..Default::default()
        }
        .apply_to(skill, now);
        Ok(self
            .repo
            .update_skill(&updated)
            .await
            .map_err(SkillApiError::internal)?
            .into())
    }

    async fn export_package(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillPackageView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let skill = self.readable_skill(user_id, &tenant_id, skill_id).await?;
        let version = self
            .repo
            .get_latest_version(skill_id)
            .await
            .map_err(SkillApiError::internal)?;
        Ok(skill_package_view(skill, version))
    }
}

impl PgSkillService {
    async fn resolve_tenant(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<String, SkillApiError> {
        if let Some(tenant_id) = present(tenant_id) {
            let allowed = self
                .repo
                .user_has_tenant_access(user_id, tenant_id)
                .await
                .map_err(SkillApiError::internal)?;
            if allowed {
                return Ok(tenant_id.to_string());
            }
            return Err(SkillApiError::forbidden("Access denied"));
        }
        self.repo
            .first_tenant_for_user(user_id)
            .await
            .map_err(SkillApiError::internal)?
            .ok_or_else(|| SkillApiError::forbidden("Access denied"))
    }

    async fn ensure_write_access(
        &self,
        user_id: &str,
        tenant_id: &str,
        scope: &str,
        project_id: Option<&str>,
    ) -> Result<(), SkillApiError> {
        if scope == "project" {
            let project_id = project_id.ok_or_else(|| {
                SkillApiError::bad_request("project_id is required for project-scoped skills")
            })?;
            self.ensure_project_access(user_id, tenant_id, project_id, SkillProjectAccess::Write)
                .await
        } else {
            let allowed = self
                .repo
                .user_is_tenant_admin(user_id, tenant_id)
                .await
                .map_err(SkillApiError::internal)?;
            if allowed {
                Ok(())
            } else {
                Err(SkillApiError::forbidden("Access denied"))
            }
        }
    }

    async fn ensure_project_access(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        access: SkillProjectAccess,
    ) -> Result<(), SkillApiError> {
        let allowed = self
            .repo
            .user_can_access_project(user_id, tenant_id, project_id, access)
            .await
            .map_err(SkillApiError::internal)?;
        if allowed {
            Ok(())
        } else {
            Err(SkillApiError::forbidden("Access denied"))
        }
    }

    async fn readable_skill(
        &self,
        user_id: &str,
        tenant_id: &str,
        skill_id: &str,
    ) -> Result<SkillRecord, SkillApiError> {
        let skill = self
            .repo
            .get_skill(skill_id)
            .await
            .map_err(SkillApiError::internal)?
            .ok_or_else(|| SkillApiError::not_found("Skill not found"))?;
        if !skill.is_system_skill && skill.tenant_id != tenant_id {
            return Err(SkillApiError::not_found("Skill not found"));
        }
        if skill.scope == "project" {
            let project_id = skill
                .project_id
                .as_deref()
                .ok_or_else(|| SkillApiError::forbidden("Access denied"))?;
            self.ensure_project_access(user_id, tenant_id, project_id, SkillProjectAccess::Read)
                .await?;
        }
        Ok(skill)
    }

    async fn writable_skill(
        &self,
        user_id: &str,
        tenant_id: &str,
        skill_id: &str,
    ) -> Result<SkillRecord, SkillApiError> {
        let skill = self.readable_skill(user_id, tenant_id, skill_id).await?;
        if skill.is_system_skill || skill.scope == "system" {
            return Err(SkillApiError::forbidden(
                "Cannot modify system skills. Use tenant skill config to override instead.",
            ));
        }
        self.ensure_write_access(
            user_id,
            tenant_id,
            &skill.scope,
            skill.project_id.as_deref(),
        )
        .await?;
        Ok(skill)
    }
}

#[derive(Default)]
pub(crate) struct DevSkillService {
    tenant_id: String,
    skills: Mutex<HashMap<String, SkillRecord>>,
    versions: Mutex<HashMap<String, Vec<SkillVersionRecord>>>,
}

impl DevSkillService {
    pub(crate) fn new(tenant_id: impl Into<String>) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            skills: Mutex::new(HashMap::new()),
            versions: Mutex::new(HashMap::new()),
        }
    }

    fn resolve_tenant(&self, tenant_id: Option<&str>) -> String {
        present(tenant_id)
            .map(ToString::to_string)
            .unwrap_or_else(|| self.tenant_id.clone())
    }

    fn get_owned(&self, tenant_id: &str, skill_id: &str) -> Result<SkillRecord, SkillApiError> {
        let skills = self.skills.lock().map_err(SkillApiError::internal)?;
        let skill = skills
            .get(skill_id)
            .cloned()
            .ok_or_else(|| SkillApiError::not_found("Skill not found"))?;
        if skill.tenant_id == tenant_id || skill.is_system_skill {
            Ok(skill)
        } else {
            Err(SkillApiError::not_found("Skill not found"))
        }
    }

    fn write_record(&self, record: SkillRecord) -> Result<SkillRecord, SkillApiError> {
        self.skills
            .lock()
            .map_err(SkillApiError::internal)?
            .insert(record.id.clone(), record.clone());
        Ok(record)
    }
}

#[async_trait]
impl SkillService for DevSkillService {
    async fn create_skill(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        body: SkillCreatePayload,
    ) -> Result<SkillView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let scope = normalize_scope(&body.scope, body.project_id.as_deref())?;
        let parsed = ParsedSkillPayload::from_content(body.full_content.as_deref());
        let name = parsed.name.unwrap_or(body.name);
        let description = parsed.description.unwrap_or(body.description);
        let tools = parsed.tools.unwrap_or(body.tools);
        validate_skill_input(&name, &description, &tools)?;
        let mut skills = self.skills.lock().map_err(SkillApiError::internal)?;
        if skills.values().any(|skill| {
            skill.tenant_id == tenant_id
                && skill.name == name
                && skill.scope == scope
                && skill.project_id == body.project_id
        }) {
            return Err(SkillApiError::conflict("Skill already exists"));
        }
        let now = Utc::now();
        let record = SkillRecord {
            id: generate_uuid_v4(),
            tenant_id,
            project_id: body.project_id,
            name,
            description,
            tools,
            status: "active".to_string(),
            metadata_json: merge_agentskills_metadata(
                body.metadata,
                body.license.as_deref(),
                body.compatibility.as_deref(),
                body.allowed_tools_raw.as_deref(),
                body.spec_version.as_deref(),
            ),
            created_at: now,
            updated_at: Some(now),
            scope,
            is_system_skill: false,
            full_content: body.full_content,
            resource_files: json!({}),
            license: body.license,
            compatibility: body.compatibility,
            allowed_tools_raw: body.allowed_tools_raw,
            spec_version: body.spec_version.unwrap_or_else(|| "1.0".to_string()),
            current_version: 0,
            version_label: parsed.version_label,
        };
        skills.insert(record.id.clone(), record.clone());
        Ok(record.into())
    }

    async fn list_skills(
        &self,
        _user_id: &str,
        query: SkillListQuery,
    ) -> Result<SkillListView, SkillApiError> {
        let tenant_id = self.resolve_tenant(query.tenant_id.as_deref());
        let scope = query
            .scope
            .as_deref()
            .map(normalize_scope_filter)
            .transpose()?;
        let status = query.status.as_deref().map(normalize_status).transpose()?;
        let search = query.search.or(query.q).unwrap_or_default();
        let needle = search.trim().to_ascii_lowercase();
        let mut records: Vec<SkillRecord> = self
            .skills
            .lock()
            .map_err(SkillApiError::internal)?
            .values()
            .filter(|skill| skill.tenant_id == tenant_id || skill.is_system_skill)
            .filter(|skill| {
                status
                    .as_deref()
                    .map(|status| skill.status == status)
                    .unwrap_or(true)
            })
            .filter(|skill| {
                scope
                    .as_deref()
                    .map(|scope| skill.scope == scope)
                    .unwrap_or(true)
            })
            .filter(|skill| {
                query
                    .project_id
                    .as_deref()
                    .map(|project_id| {
                        (skill.scope == "tenant" && skill.project_id.is_none())
                            || (skill.scope == "project"
                                && skill.project_id.as_deref() == Some(project_id))
                    })
                    .unwrap_or_else(|| skill.project_id.is_none())
            })
            .filter(|skill| needle.is_empty() || skill_matches_search(skill, &needle))
            .cloned()
            .collect();
        records.sort_by(|a, b| {
            b.created_at
                .cmp(&a.created_at)
                .then_with(|| b.id.cmp(&a.id))
        });
        let total = records.len();
        let offset = query.skip.or(query.offset).unwrap_or(0).clamp(0, i64::MAX) as usize;
        let limit = query.limit.unwrap_or(100).clamp(1, 500) as usize;
        let skills = records
            .into_iter()
            .skip(offset)
            .take(limit)
            .map(SkillView::from)
            .collect();
        Ok(SkillListView { skills, total })
    }

    async fn get_skill(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        Ok(self.get_owned(&tenant_id, skill_id)?.into())
    }

    async fn update_skill(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        body: SkillUpdatePayload,
    ) -> Result<SkillView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let skill = self.get_owned(&tenant_id, skill_id)?;
        let parsed = ParsedSkillPayload::from_content(body.full_content.as_deref());
        let next_name = parsed
            .name
            .clone()
            .or_else(|| body.name.clone())
            .unwrap_or_else(|| skill.name.clone());
        let next_description = parsed
            .description
            .clone()
            .or_else(|| body.description.clone())
            .unwrap_or_else(|| skill.description.clone());
        let next_tools = parsed
            .tools
            .clone()
            .or_else(|| body.tools.clone())
            .unwrap_or_else(|| skill.tools.clone());
        validate_skill_input(&next_name, &next_description, &next_tools)?;
        let status = body
            .status
            .as_deref()
            .map(normalize_status)
            .transpose()?
            .unwrap_or_else(|| skill.status.clone());
        let record = SkillUpdateRecord {
            name: Some(next_name),
            description: Some(next_description),
            tools: Some(next_tools),
            status: Some(status),
            metadata_json: body.metadata.map(Some),
            full_content: body.full_content.map(Some),
            license: body.license.map(Some),
            compatibility: body.compatibility.map(Some),
            allowed_tools_raw: body.allowed_tools_raw.map(Some),
            spec_version: body.spec_version,
            version_label: parsed.version_label.map(Some),
            ..Default::default()
        }
        .apply_to(skill, Utc::now());
        Ok(self.write_record(record)?.into())
    }

    async fn delete_skill(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<(), SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let _skill = self.get_owned(&tenant_id, skill_id)?;
        self.skills
            .lock()
            .map_err(SkillApiError::internal)?
            .remove(skill_id);
        Ok(())
    }

    async fn update_status(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        status: &str,
    ) -> Result<SkillView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let skill = self.get_owned(&tenant_id, skill_id)?;
        let record = SkillUpdateRecord {
            status: Some(normalize_status(status)?),
            ..Default::default()
        }
        .apply_to(skill, Utc::now());
        Ok(self.write_record(record)?.into())
    }

    async fn get_content(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillContentView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let skill = self.get_owned(&tenant_id, skill_id)?;
        Ok(SkillContentView {
            skill_id: skill.id,
            name: skill.name,
            full_content: skill.full_content,
            scope: skill.scope,
            is_system_skill: skill.is_system_skill,
        })
    }

    async fn update_content(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        body: SkillContentUpdatePayload,
    ) -> Result<SkillView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let skill = self.get_owned(&tenant_id, skill_id)?;
        let parsed = ParsedSkillPayload::from_content(Some(&body.full_content));
        let now = Utc::now();
        let next_number = self
            .versions
            .lock()
            .map_err(SkillApiError::internal)?
            .get(skill_id)
            .map(|versions| versions.iter().map(|v| v.version_number).max().unwrap_or(0))
            .unwrap_or(0)
            + 1;
        let updated = SkillUpdateRecord {
            full_content: Some(Some(body.full_content.clone())),
            name: parsed.name.clone(),
            description: parsed.description.clone(),
            tools: parsed.tools.clone(),
            metadata_json: parsed.metadata.map(Some),
            current_version: Some(next_number),
            version_label: parsed
                .version_label
                .clone()
                .or_else(|| Some(next_number.to_string()))
                .map(Some),
            ..Default::default()
        }
        .apply_to(skill, now);
        validate_skill_input(&updated.name, &updated.description, &updated.tools)?;
        let version = SkillVersionRecord {
            id: generate_uuid_v4(),
            skill_id: skill_id.to_string(),
            version_number: next_number,
            version_label: updated.version_label.clone(),
            skill_md_content: body.full_content,
            resource_files: updated.resource_files.clone(),
            change_summary: Some("Manual content update".to_string()),
            created_by: "agent".to_string(),
            created_at: now,
        };
        self.versions
            .lock()
            .map_err(SkillApiError::internal)?
            .entry(skill_id.to_string())
            .or_default()
            .push(version);
        Ok(self.write_record(updated)?.into())
    }

    async fn list_versions(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<SkillVersionListView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let _skill = self.get_owned(&tenant_id, skill_id)?;
        let mut versions = self
            .versions
            .lock()
            .map_err(SkillApiError::internal)?
            .get(skill_id)
            .cloned()
            .unwrap_or_default();
        versions.sort_by_key(|version| std::cmp::Reverse(version.version_number));
        let total = versions.len() as i64;
        let versions = versions
            .into_iter()
            .skip(offset.max(0) as usize)
            .take(limit.clamp(1, 100) as usize)
            .map(SkillVersionView::from)
            .collect();
        Ok(SkillVersionListView { versions, total })
    }

    async fn get_version(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        version_number: i32,
    ) -> Result<SkillVersionDetailView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let _skill = self.get_owned(&tenant_id, skill_id)?;
        let version = self
            .versions
            .lock()
            .map_err(SkillApiError::internal)?
            .get(skill_id)
            .and_then(|versions| {
                versions
                    .iter()
                    .find(|version| version.version_number == version_number)
                    .cloned()
            })
            .ok_or_else(|| SkillApiError::not_found("Skill version not found"))?;
        Ok(version.into())
    }

    async fn rollback(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        body: SkillRollbackPayload,
    ) -> Result<SkillView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let skill = self.get_owned(&tenant_id, skill_id)?;
        let mut versions = self.versions.lock().map_err(SkillApiError::internal)?;
        let target = versions
            .get(skill_id)
            .and_then(|items| {
                items
                    .iter()
                    .find(|version| version.version_number == body.version_number)
                    .cloned()
            })
            .ok_or_else(|| SkillApiError::bad_request("Skill version not found"))?;
        let next_number = versions
            .get(skill_id)
            .map(|items| items.iter().map(|v| v.version_number).max().unwrap_or(0))
            .unwrap_or(0)
            + 1;
        let now = Utc::now();
        versions
            .entry(skill_id.to_string())
            .or_default()
            .push(SkillVersionRecord {
                id: generate_uuid_v4(),
                skill_id: skill_id.to_string(),
                version_number: next_number,
                version_label: target.version_label.clone(),
                skill_md_content: target.skill_md_content.clone(),
                resource_files: target.resource_files.clone(),
                change_summary: Some(format!("Rollback to version {}", body.version_number)),
                created_by: "rollback".to_string(),
                created_at: now,
            });
        drop(versions);
        let updated = SkillUpdateRecord {
            full_content: Some(Some(target.skill_md_content)),
            resource_files: Some(target.resource_files),
            current_version: Some(next_number),
            version_label: target.version_label.map(Some),
            ..Default::default()
        }
        .apply_to(skill, now);
        Ok(self.write_record(updated)?.into())
    }

    async fn export_package(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillPackageView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let skill = self.get_owned(&tenant_id, skill_id)?;
        let version = self
            .versions
            .lock()
            .map_err(SkillApiError::internal)?
            .get(skill_id)
            .and_then(|versions| {
                versions
                    .iter()
                    .max_by_key(|version| version.version_number)
                    .cloned()
            });
        Ok(skill_package_view(skill, version))
    }
}

async fn create_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Json(body): Json<SkillCreatePayload>,
) -> Result<(StatusCode, Json<SkillView>), SkillApiError> {
    let view = app
        .skills
        .create_skill(&identity.user_id, q.tenant_id.as_deref(), body)
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn list_skills(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<SkillListQuery>,
) -> Result<Json<SkillListView>, SkillApiError> {
    Ok(Json(
        app.skills.list_skills(&identity.user_id, query).await?,
    ))
}

async fn list_system_skills() -> Json<SkillListView> {
    Json(SkillListView {
        skills: Vec::new(),
        total: 0,
    })
}

async fn get_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
) -> Result<Json<SkillView>, SkillApiError> {
    Ok(Json(
        app.skills
            .get_skill(&identity.user_id, q.tenant_id.as_deref(), &skill_id)
            .await?,
    ))
}

async fn update_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
    Json(body): Json<SkillUpdatePayload>,
) -> Result<Json<SkillView>, SkillApiError> {
    Ok(Json(
        app.skills
            .update_skill(&identity.user_id, q.tenant_id.as_deref(), &skill_id, body)
            .await?,
    ))
}

async fn delete_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
) -> Result<StatusCode, SkillApiError> {
    app.skills
        .delete_skill(&identity.user_id, q.tenant_id.as_deref(), &skill_id)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn update_skill_status(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<SkillStatusQuery>,
    Path(skill_id): Path<String>,
) -> Result<Json<SkillView>, SkillApiError> {
    Ok(Json(
        app.skills
            .update_status(
                &identity.user_id,
                q.tenant_id.as_deref(),
                &skill_id,
                &q.status,
            )
            .await?,
    ))
}

async fn get_skill_content(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
) -> Result<Json<SkillContentView>, SkillApiError> {
    Ok(Json(
        app.skills
            .get_content(&identity.user_id, q.tenant_id.as_deref(), &skill_id)
            .await?,
    ))
}

async fn update_skill_content(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
    Json(body): Json<SkillContentUpdatePayload>,
) -> Result<Json<SkillView>, SkillApiError> {
    Ok(Json(
        app.skills
            .update_content(&identity.user_id, q.tenant_id.as_deref(), &skill_id, body)
            .await?,
    ))
}

async fn list_skill_versions(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<SkillVersionQuery>,
    Path(skill_id): Path<String>,
) -> Result<Json<SkillVersionListView>, SkillApiError> {
    Ok(Json(
        app.skills
            .list_versions(
                &identity.user_id,
                q.tenant_id.as_deref(),
                &skill_id,
                q.limit.unwrap_or(50),
                q.offset.unwrap_or(0),
            )
            .await?,
    ))
}

async fn get_skill_version(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path((skill_id, version_number)): Path<(String, i32)>,
) -> Result<Json<SkillVersionDetailView>, SkillApiError> {
    Ok(Json(
        app.skills
            .get_version(
                &identity.user_id,
                q.tenant_id.as_deref(),
                &skill_id,
                version_number,
            )
            .await?,
    ))
}

async fn rollback_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
    Json(body): Json<SkillRollbackPayload>,
) -> Result<Json<SkillView>, SkillApiError> {
    Ok(Json(
        app.skills
            .rollback(&identity.user_id, q.tenant_id.as_deref(), &skill_id, body)
            .await?,
    ))
}

async fn export_skill_package(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(skill_id): Path<String>,
) -> Result<Json<SkillPackageView>, SkillApiError> {
    Ok(Json(
        app.skills
            .export_package(&identity.user_id, q.tenant_id.as_deref(), &skill_id)
            .await?,
    ))
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/skills/", get(list_skills).post(create_skill))
        .route("/api/v1/skills", get(list_skills).post(create_skill))
        .route("/api/v1/skills/system/list", get(list_system_skills))
        .route(
            "/api/v1/skills/:skill_id/content",
            get(get_skill_content).put(update_skill_content),
        )
        .route(
            "/api/v1/skills/:skill_id/status",
            patch(update_skill_status),
        )
        .route(
            "/api/v1/skills/:skill_id/versions",
            get(list_skill_versions),
        )
        .route(
            "/api/v1/skills/:skill_id/versions/:version_number",
            get(get_skill_version),
        )
        .route("/api/v1/skills/:skill_id/rollback", post(rollback_skill))
        .route("/api/v1/skills/:skill_id/export", get(export_skill_package))
        .route(
            "/api/v1/skills/:skill_id",
            get(get_skill).put(update_skill).delete(delete_skill),
        )
}

fn default_scope() -> String {
    "tenant".to_string()
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn present(value: Option<&str>) -> Option<&str> {
    value.map(str::trim).filter(|value| !value.is_empty())
}

fn normalize_scope(raw: &str, project_id: Option<&str>) -> Result<String, SkillApiError> {
    let scope = normalize_scope_filter(raw)?;
    if scope == "system" {
        return Err(SkillApiError::bad_request(
            "Cannot create system-level skills via API",
        ));
    }
    if scope == "project" && present(project_id).is_none() {
        return Err(SkillApiError::bad_request(
            "project_id is required for project-scoped skills",
        ));
    }
    Ok(scope)
}

fn normalize_scope_filter(raw: &str) -> Result<String, SkillApiError> {
    match raw {
        "system" | "tenant" | "project" => Ok(raw.to_string()),
        _ => Err(SkillApiError::bad_request("Invalid skill scope")),
    }
}

fn normalize_status(raw: &str) -> Result<String, SkillApiError> {
    match raw {
        "active" | "disabled" | "deprecated" => Ok(raw.to_string()),
        _ => Err(SkillApiError::bad_request("Invalid skill status")),
    }
}

fn validate_skill_input(
    name: &str,
    description: &str,
    tools: &[String],
) -> Result<(), SkillApiError> {
    if !valid_skill_name(name) || description.is_empty() || description.len() > 1024 {
        return Err(SkillApiError::bad_request("Invalid skill request"));
    }
    if tools.is_empty() || tools.iter().any(|tool| tool.trim().is_empty()) {
        return Err(SkillApiError::bad_request("Invalid skill request"));
    }
    Ok(())
}

fn valid_skill_name(name: &str) -> bool {
    if name.is_empty() || name.len() > 64 {
        return false;
    }
    let mut last_dash = true;
    for ch in name.chars() {
        if ch == '-' {
            if last_dash {
                return false;
            }
            last_dash = true;
        } else if ch.is_ascii_lowercase() || ch.is_ascii_digit() {
            last_dash = false;
        } else {
            return false;
        }
    }
    !last_dash
}

#[derive(Default)]
struct ParsedSkillPayload {
    name: Option<String>,
    description: Option<String>,
    tools: Option<Vec<String>>,
    metadata: Option<Value>,
    version_label: Option<String>,
}

impl ParsedSkillPayload {
    fn from_content(content: Option<&str>) -> Self {
        let Some(content) = content else {
            return Self::default();
        };
        let Some(frontmatter) = frontmatter(content) else {
            return Self::default();
        };
        let mut parsed = Self::default();
        let mut metadata = Map::new();
        for line in frontmatter.lines() {
            let Some((key, value)) = line.split_once(':') else {
                continue;
            };
            let key = key.trim();
            let value = value.trim().trim_matches('"').trim_matches('\'');
            if value.is_empty() {
                continue;
            }
            match key {
                "name" => parsed.name = Some(value.to_string()),
                "description" => parsed.description = Some(value.to_string()),
                "version" => parsed.version_label = Some(value.to_string()),
                "license" | "compatibility" | "allowed_tools" | "allowed-tools"
                | "spec_version" | "spec-version" => {
                    metadata.insert(key.replace('-', "_"), Value::String(value.to_string()));
                }
                "tools" => {
                    let tools = parse_inline_list(value);
                    if !tools.is_empty() {
                        parsed.tools = Some(tools);
                    }
                }
                _ => {}
            }
        }
        if !metadata.is_empty() {
            parsed.metadata = Some(Value::Object(Map::from_iter([(
                "agentskills".to_string(),
                Value::Object(metadata),
            )])));
        }
        parsed
    }
}

fn frontmatter(content: &str) -> Option<&str> {
    let rest = content.strip_prefix("---\n")?;
    rest.split_once("\n---").map(|(frontmatter, _)| frontmatter)
}

fn parse_inline_list(value: &str) -> Vec<String> {
    let value = value.trim();
    let value = value
        .strip_prefix('[')
        .and_then(|inner| inner.strip_suffix(']'))
        .unwrap_or(value);
    value
        .split(',')
        .map(|item| item.trim().trim_matches('"').trim_matches('\''))
        .filter(|item| !item.is_empty())
        .map(ToString::to_string)
        .collect()
}

fn merge_agentskills_metadata(
    metadata: Option<Value>,
    license: Option<&str>,
    compatibility: Option<&str>,
    allowed_tools_raw: Option<&str>,
    spec_version: Option<&str>,
) -> Option<Value> {
    let mut root = match metadata {
        Some(Value::Object(map)) => map,
        _ => Map::new(),
    };
    let mut agentskills = match root.remove("agentskills") {
        Some(Value::Object(map)) => map,
        _ => Map::new(),
    };
    for (key, value) in [
        ("license", license),
        ("compatibility", compatibility),
        ("allowed_tools", allowed_tools_raw),
        ("spec_version", spec_version),
    ] {
        if let Some(value) = value.filter(|value| !value.is_empty()) {
            agentskills.insert(key.to_string(), Value::String(value.to_string()));
        }
    }
    if !agentskills.is_empty() {
        root.insert("agentskills".to_string(), Value::Object(agentskills));
    }
    if root.is_empty() {
        None
    } else {
        Some(Value::Object(root))
    }
}

fn skill_matches_search(record: &SkillRecord, needle: &str) -> bool {
    if needle.is_empty() {
        return true;
    }
    let metadata = record
        .metadata_json
        .as_ref()
        .map(Value::to_string)
        .unwrap_or_default();
    [
        record.name.as_str(),
        record.description.as_str(),
        record.version_label.as_deref().unwrap_or_default(),
        metadata.as_str(),
    ]
    .iter()
    .any(|part| part.to_ascii_lowercase().contains(needle))
}

fn skill_package_view(skill: SkillRecord, version: Option<SkillVersionRecord>) -> SkillPackageView {
    let skill_view = SkillView::from(skill.clone());
    let (skill_md_content, resource_files, version_number, version_label) = match version {
        Some(version) => (
            version.skill_md_content,
            version.resource_files,
            Some(version.version_number),
            version.version_label,
        ),
        None => (
            skill
                .full_content
                .clone()
                .unwrap_or_else(|| build_skill_md_from_record(&skill)),
            skill.resource_files.clone(),
            None,
            skill.version_label.clone(),
        ),
    };
    SkillPackageView {
        format: "agentskills.io/skill-package".to_string(),
        skill: skill_view,
        skill_md_content,
        resource_files,
        version_number,
        version_label,
    }
}

fn build_skill_md_from_record(record: &SkillRecord) -> String {
    let mut frontmatter = YamlMapping::new();
    insert_yaml_string(&mut frontmatter, "name", &record.name);
    insert_yaml_string(&mut frontmatter, "description", &record.description);
    if let Some(value) = record.license.as_deref().filter(|value| !value.is_empty()) {
        insert_yaml_string(&mut frontmatter, "license", value);
    }
    if let Some(value) = record
        .compatibility
        .as_deref()
        .filter(|value| !value.is_empty())
    {
        insert_yaml_string(&mut frontmatter, "compatibility", value);
    }
    if let Some(value) = record
        .allowed_tools_raw
        .as_deref()
        .filter(|value| !value.is_empty())
    {
        insert_yaml_string(&mut frontmatter, "allowed-tools", value);
    } else if !record.tools.is_empty() {
        insert_yaml_string(&mut frontmatter, "allowed-tools", &record.tools.join(" "));
    }
    if let Some(metadata) = export_metadata_value(record) {
        frontmatter.insert(YamlValue::String("metadata".to_string()), metadata);
    }
    let body = format!("# {}\n\n{}", record.name, record.description);
    let yaml_text =
        serde_yaml_ng::to_string(&frontmatter).unwrap_or_else(|_| fallback_frontmatter(record));
    format!("---\n{}\n---\n\n{}\n", yaml_text.trim_end(), body.trim())
}

fn insert_yaml_string(map: &mut YamlMapping, key: &str, value: &str) {
    map.insert(
        YamlValue::String(key.to_string()),
        YamlValue::String(value.to_string()),
    );
}

fn export_metadata_value(record: &SkillRecord) -> Option<YamlValue> {
    let mut metadata = match record.metadata_json.clone() {
        Some(Value::Object(map)) => map,
        _ => Map::new(),
    };
    if let Some(version_label) = record
        .version_label
        .as_deref()
        .filter(|version_label| !version_label.is_empty())
    {
        metadata
            .entry("version".to_string())
            .or_insert_with(|| Value::String(version_label.to_string()));
    }
    if metadata.is_empty() {
        return None;
    }
    serde_yaml_ng::to_value(Value::Object(metadata)).ok()
}

fn fallback_frontmatter(record: &SkillRecord) -> String {
    format!("name: {}\ndescription: {}", record.name, record.description)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_skill_record() -> SkillRecord {
        let at = DateTime::<Utc>::from_timestamp(1_700_000_000, 0).unwrap();
        SkillRecord {
            id: "11111111-1111-4111-8111-111111111111".to_string(),
            tenant_id: "tenant-1".to_string(),
            project_id: None,
            name: "code-review".to_string(),
            description: "Review code changes".to_string(),
            tools: vec!["read_file".to_string(), "grep".to_string()],
            status: "active".to_string(),
            metadata_json: Some(json!({"agentskills":{"license":"MIT"}})),
            created_at: at,
            updated_at: Some(at),
            scope: "tenant".to_string(),
            is_system_skill: false,
            full_content: Some("# Code Review\n".to_string()),
            resource_files: json!({}),
            license: Some("MIT".to_string()),
            compatibility: None,
            allowed_tools_raw: Some("read_file,grep".to_string()),
            spec_version: "1.0".to_string(),
            current_version: 2,
            version_label: Some("1.2.0".to_string()),
        }
    }

    fn sample_version_record() -> SkillVersionRecord {
        let at = DateTime::<Utc>::from_timestamp(1_700_000_100, 0).unwrap();
        SkillVersionRecord {
            id: "22222222-2222-4222-8222-222222222222".to_string(),
            skill_id: "11111111-1111-4111-8111-111111111111".to_string(),
            version_number: 2,
            version_label: Some("1.2.0".to_string()),
            skill_md_content: "# Code Review\n".to_string(),
            resource_files: json!({"rules.md":"Focus on regressions."}),
            change_summary: Some("Manual content update".to_string()),
            created_by: "agent".to_string(),
            created_at: at,
        }
    }

    #[test]
    fn skill_response_matches_golden() {
        let actual = serde_json::to_value(SkillView::from(sample_skill_record())).unwrap();
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/skill_response.json")).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn skill_list_matches_golden() {
        let actual = serde_json::to_value(SkillListView {
            skills: vec![SkillView::from(sample_skill_record())],
            total: 1,
        })
        .unwrap();
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/skill_list.json")).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn skill_content_matches_golden() {
        let actual = serde_json::to_value(SkillContentView {
            skill_id: "11111111-1111-4111-8111-111111111111".to_string(),
            name: "code-review".to_string(),
            full_content: Some("# Code Review\n".to_string()),
            scope: "tenant".to_string(),
            is_system_skill: false,
        })
        .unwrap();
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/skill_content.json")).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn skill_version_shapes_match_goldens() {
        let actual = serde_json::to_value(SkillVersionView::from(sample_version_record())).unwrap();
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/skill_version_response.json"))
                .unwrap();
        agistack_parity::assert_parity(&golden, &actual);

        let actual =
            serde_json::to_value(SkillVersionDetailView::from(sample_version_record())).unwrap();
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/skill_version_detail.json"))
                .unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn skill_package_export_matches_golden() {
        let actual = serde_json::to_value(skill_package_view(
            sample_skill_record(),
            Some(sample_version_record()),
        ))
        .unwrap();
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/skill_package_export.json"))
                .unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[tokio::test]
    async fn dev_service_content_update_creates_version_and_rollback() {
        let service = DevSkillService::new("tenant-1");
        let created = service
            .create_skill(
                "u1",
                Some("tenant-1"),
                SkillCreatePayload {
                    name: "code-review".to_string(),
                    description: "Review code".to_string(),
                    tools: vec!["read_file".to_string()],
                    full_content: Some("# Code Review\n".to_string()),
                    project_id: None,
                    scope: "tenant".to_string(),
                    metadata: None,
                    license: None,
                    compatibility: None,
                    allowed_tools_raw: None,
                    spec_version: None,
                },
            )
            .await
            .unwrap();
        assert_eq!(created.current_version, 0);

        let updated = service
            .update_content(
                "u1",
                Some("tenant-1"),
                &created.id,
                SkillContentUpdatePayload {
                    full_content: "---\nversion: 1.0.0\n---\n# New\n".to_string(),
                },
            )
            .await
            .unwrap();
        assert_eq!(updated.current_version, 1);
        assert_eq!(updated.version_label.as_deref(), Some("1.0.0"));
        let exported = service
            .export_package("u1", Some("tenant-1"), &created.id)
            .await
            .unwrap();
        assert_eq!(exported.version_number, Some(1));
        assert_eq!(
            Some(exported.skill_md_content.as_str()),
            updated.full_content.as_deref()
        );
        let versions = service
            .list_versions("u1", Some("tenant-1"), &created.id, 50, 0)
            .await
            .unwrap();
        assert_eq!(versions.total, 1);

        let rolled_back = service
            .rollback(
                "u1",
                Some("tenant-1"),
                &created.id,
                SkillRollbackPayload { version_number: 1 },
            )
            .await
            .unwrap();
        assert_eq!(rolled_back.current_version, 2);
        assert_eq!(rolled_back.full_content, updated.full_content);
    }

    #[test]
    fn router_builds() {
        let _router: Router<AppState> = router();
    }
}
