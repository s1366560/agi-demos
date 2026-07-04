//! P5 skill-store and versioning foundation.
//!
//! This module mirrors the database-backed subset of Python's `/api/v1/skills`
//! router: tenant/project skill CRUD, content updates, version snapshots,
//! rollback/import/export, filesystem-backed system skill listing/package
//! export, zip import, and the skill-evolution strategy config/overview/detail
//! plus apply/reject review job actions. Evolution run actions remain
//! Python-owned until the scheduler/evolution-engine semantics are migrated.

use std::collections::{BTreeMap, HashMap};
use std::sync::Mutex;

use async_trait::async_trait;
use axum::{
    extract::{Multipart, Path, Query, State},
    http::StatusCode,
    Extension, Json,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde_json::{json, Map, Value};
use serde_yaml_ng::{Mapping as YamlMapping, Value as YamlValue};

use agistack_adapters_postgres::{
    PgSkillEvolutionRepository, PgSkillRepository, SkillEvolutionJobRecord, SkillProjectAccess,
    SkillRecord, SkillUpdateRecord, SkillVersionRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;

use crate::auth::Identity;
use crate::AppState;

const SKILL_EVOLUTION_PLUGIN: &str = "skill_evolution";

mod routes;
mod service;
mod system_skills;
mod types;
mod views;
mod zip_import;

pub(crate) use routes::router;
pub(crate) use service::{SharedSkills, SkillService};
use types::*;
use views::*;

pub(crate) struct PgSkillService {
    repo: PgSkillRepository,
    evolution_repo: Option<PgSkillEvolutionRepository>,
}

impl PgSkillService {
    pub(crate) fn new(repo: PgSkillRepository) -> Self {
        Self {
            repo,
            evolution_repo: None,
        }
    }

    pub(crate) fn with_evolution_repo(mut self, repo: PgSkillEvolutionRepository) -> Self {
        self.evolution_repo = Some(repo);
        self
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

    async fn import_package(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SkillImportPayload,
    ) -> Result<SkillLifecycleView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let scope = normalize_scope(&body.scope, body.project_id.as_deref())?;
        self.ensure_write_access(user_id, &tenant_id, &scope, body.project_id.as_deref())
            .await?;
        validate_change_summary(body.change_summary.as_deref())?;

        let parsed = ParsedImportPackage::from_payload(&body)?;
        let existing = self
            .repo
            .find_skill(&tenant_id, &parsed.name, &scope, body.project_id.as_deref())
            .await
            .map_err(SkillApiError::internal)?;
        if existing.is_some() && !body.overwrite {
            return Err(SkillApiError::conflict("Skill already exists"));
        }

        let now = Utc::now();
        let resource_files = json!(body.resource_files);
        let (skill, action, should_create) = match existing {
            Some(skill) => (skill, "update".to_string(), false),
            None => (
                SkillRecord {
                    id: generate_uuid_v4(),
                    tenant_id,
                    project_id: body.project_id.clone(),
                    name: parsed.name.clone(),
                    description: parsed.description.clone(),
                    tools: parsed.tools.clone(),
                    status: "active".to_string(),
                    metadata_json: parsed.metadata.clone(),
                    created_at: now,
                    updated_at: Some(now),
                    scope,
                    is_system_skill: false,
                    full_content: Some(body.skill_md_content.clone()),
                    resource_files: resource_files.clone(),
                    license: parsed.license.clone(),
                    compatibility: parsed.compatibility.clone(),
                    allowed_tools_raw: parsed.allowed_tools_raw.clone(),
                    spec_version: parsed.spec_version.clone(),
                    current_version: 0,
                    version_label: parsed.version_label.clone(),
                },
                "import".to_string(),
                true,
            ),
        };
        let skill = if should_create {
            self.repo
                .create_skill(&skill)
                .await
                .map_err(SkillApiError::internal)?
        } else {
            skill
        };

        let next_version = self
            .repo
            .max_version_number(&skill.id)
            .await
            .map_err(SkillApiError::internal)?
            + 1;
        let version_label = parsed
            .version_label
            .clone()
            .or_else(|| Some(next_version.to_string()));
        let version = SkillVersionRecord {
            id: generate_uuid_v4(),
            skill_id: skill.id.clone(),
            version_number: next_version,
            version_label: version_label.clone(),
            skill_md_content: body.skill_md_content.clone(),
            resource_files: resource_files.clone(),
            change_summary: import_change_summary(body.change_summary.as_deref(), next_version),
            created_by: "import".to_string(),
            created_at: now,
        };
        self.repo
            .create_version(&version)
            .await
            .map_err(SkillApiError::internal)?;
        let updated = SkillUpdateRecord {
            name: Some(parsed.name),
            description: Some(parsed.description),
            tools: Some(parsed.tools),
            metadata_json: Some(parsed.metadata),
            full_content: Some(Some(body.skill_md_content)),
            resource_files: Some(resource_files),
            license: Some(parsed.license),
            compatibility: Some(parsed.compatibility),
            allowed_tools_raw: Some(parsed.allowed_tools_raw),
            spec_version: Some(parsed.spec_version),
            current_version: Some(next_version),
            version_label: Some(version_label.clone()),
            ..Default::default()
        }
        .apply_to(skill, now);
        let updated = self
            .repo
            .update_skill(&updated)
            .await
            .map_err(SkillApiError::internal)?;
        Ok(SkillLifecycleView {
            action,
            skill: updated.into(),
            version_number: Some(next_version),
            version_label,
        })
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

    async fn list_system_skills(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        status: Option<&str>,
    ) -> Result<SkillListView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        system_skills::list_filesystem_system_skills(&tenant_id, status).await
    }

    async fn import_system_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SystemSkillImportPayload,
    ) -> Result<SkillLifecycleView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let target = body.target()?.to_string();
        let package = system_skills::export_filesystem_system_skill(&tenant_id, &target)
            .await?
            .ok_or_else(|| SkillApiError::not_found("Skill not found"))?;
        let import_payload = SkillImportPayload {
            skill_md_content: package.skill_md_content,
            resource_files: resource_files_map(package.resource_files)?,
            scope: body.scope,
            project_id: body.project_id,
            overwrite: body.overwrite,
            change_summary: body.change_summary,
        };
        self.import_package(user_id, Some(&tenant_id), import_payload)
            .await
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
        let skill = match self.readable_skill(user_id, &tenant_id, skill_id).await {
            Ok(skill) => skill,
            Err(err) if err.status == StatusCode::NOT_FOUND => {
                return system_skills::export_filesystem_system_skill(&tenant_id, skill_id)
                    .await?
                    .ok_or_else(|| SkillApiError::not_found("Skill not found"));
            }
            Err(err) => return Err(err),
        };
        let version = self
            .repo
            .get_latest_version(skill_id)
            .await
            .map_err(SkillApiError::internal)?;
        Ok(skill_package_view(skill, version))
    }

    async fn get_evolution_config(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<SkillEvolutionConfigView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let config = self.load_evolution_config(&tenant_id).await?;
        Ok(config.into())
    }

    async fn update_evolution_config(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SkillEvolutionConfigUpdatePayload,
    ) -> Result<SkillEvolutionConfigView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        self.ensure_write_access(user_id, &tenant_id, "tenant", None)
            .await?;
        body.validate()?;
        let config = self.load_evolution_config(&tenant_id).await?;
        let next_config = config.with_overrides(&body)?;
        let view = SkillEvolutionConfigView::from(next_config);
        self.repo
            .upsert_plugin_config(
                &generate_uuid_v4(),
                &tenant_id,
                SKILL_EVOLUTION_PLUGIN,
                &serde_json::to_value(&view).map_err(SkillApiError::internal)?,
            )
            .await
            .map_err(SkillApiError::internal)?;
        Ok(view)
    }

    async fn get_evolution_overview(
        &self,
        user_id: &str,
        query: SkillEvolutionOverviewQuery,
    ) -> Result<SkillEvolutionOverviewView, SkillApiError> {
        let tenant_id = self
            .resolve_tenant(user_id, query.tenant_id.as_deref())
            .await?;
        let (skill_limit, session_limit, job_limit) = query.validated_limits()?;
        let config = self.load_evolution_config(&tenant_id).await?;
        let Some(repo) = self.evolution_repo.as_ref() else {
            return Ok(empty_evolution_overview(config));
        };
        let project_ids = repo
            .accessible_project_ids(user_id, &tenant_id)
            .await
            .map_err(SkillApiError::internal)?;
        let stats = repo
            .overview_stats(&tenant_id, &project_ids)
            .await
            .map_err(SkillApiError::internal)?;
        let skill_summaries = repo
            .skill_session_summaries(&tenant_id, &project_ids, skill_limit)
            .await
            .map_err(SkillApiError::internal)?;
        let recent_sessions = repo
            .list_recent_sessions(&tenant_id, &project_ids, session_limit)
            .await
            .map_err(SkillApiError::internal)?;
        let recent_jobs = repo
            .list_jobs(&tenant_id, &project_ids, job_limit)
            .await
            .map_err(SkillApiError::internal)?;
        Ok(evolution_overview_from_records(
            config,
            stats,
            skill_summaries,
            recent_sessions,
            recent_jobs,
        ))
    }

    async fn get_evolution_detail(
        &self,
        user_id: &str,
        query: SkillEvolutionDetailQuery,
        skill_id: &str,
    ) -> Result<SkillEvolutionDetailView, SkillApiError> {
        let tenant_id = self
            .resolve_tenant(user_id, query.tenant_id.as_deref())
            .await?;
        let limit = query.validated_limit()?;
        let config = self.load_evolution_config(&tenant_id).await?;
        let skill = self.readable_skill(user_id, &tenant_id, skill_id).await?;
        let versions = self
            .repo
            .list_versions(skill_id, limit, 0)
            .await
            .map_err(SkillApiError::internal)?;
        let Some(repo) = self.evolution_repo.as_ref() else {
            return Ok(evolution_detail_from_records(
                &skill,
                config,
                versions,
                Vec::new(),
                0,
            ));
        };
        let jobs = repo
            .list_jobs_for_skill(&tenant_id, &skill.name, skill.project_id.as_deref(), limit)
            .await
            .map_err(SkillApiError::internal)?;
        let captured_session_count = repo
            .count_sessions_by_skill(&tenant_id, &skill.name, skill.project_id.as_deref())
            .await
            .map_err(SkillApiError::internal)?;
        Ok(evolution_detail_from_records(
            &skill,
            config,
            versions,
            jobs,
            captured_session_count,
        ))
    }

    async fn apply_evolution_job(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        job_id: &str,
    ) -> Result<SkillEvolutionJobView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let job = self.pending_evolution_job(&tenant_id, job_id).await?;
        self.ensure_evolution_job_write_access(user_id, &tenant_id, &job)
            .await?;
        let version_id = self
            .apply_pending_evolution_job(&tenant_id, &job)
            .await?
            .ok_or_else(|| SkillApiError::bad_request("Skill evolution job cannot be applied"))?;
        let repo = self.evolution_repo()?;
        let updated = repo
            .update_job_status(&tenant_id, &job.id, "applied", Some(&version_id))
            .await
            .map_err(SkillApiError::internal)?
            .ok_or_else(|| SkillApiError::not_found("Skill evolution job not found"))?;
        Ok(updated.into())
    }

    async fn reject_evolution_job(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        job_id: &str,
    ) -> Result<SkillEvolutionJobView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let job = self.pending_evolution_job(&tenant_id, job_id).await?;
        self.ensure_evolution_job_write_access(user_id, &tenant_id, &job)
            .await?;
        let updated = self
            .evolution_repo()?
            .update_job_status(&tenant_id, &job.id, "rejected", None)
            .await
            .map_err(SkillApiError::internal)?
            .ok_or_else(|| SkillApiError::not_found("Skill evolution job not found"))?;
        Ok(updated.into())
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

    async fn load_evolution_config(
        &self,
        tenant_id: &str,
    ) -> Result<SkillEvolutionConfig, SkillApiError> {
        let base = SkillEvolutionConfig::from_env();
        let Some(row) = self
            .repo
            .get_plugin_config(tenant_id, SKILL_EVOLUTION_PLUGIN)
            .await
            .map_err(SkillApiError::internal)?
        else {
            return Ok(base);
        };
        Ok(base.with_stored_overrides(&row.config))
    }

    fn evolution_repo(&self) -> Result<&PgSkillEvolutionRepository, SkillApiError> {
        self.evolution_repo
            .as_ref()
            .ok_or_else(|| SkillApiError::internal("skill evolution repository unavailable"))
    }

    async fn pending_evolution_job(
        &self,
        tenant_id: &str,
        job_id: &str,
    ) -> Result<SkillEvolutionJobRecord, SkillApiError> {
        let job = self
            .evolution_repo()?
            .get_job_for_tenant(tenant_id, job_id)
            .await
            .map_err(SkillApiError::internal)?
            .ok_or_else(|| SkillApiError::not_found("Skill evolution job not found"))?;
        if job.status != "pending_review" {
            return Err(SkillApiError::bad_request(
                "Skill evolution job is not pending review",
            ));
        }
        Ok(job)
    }

    async fn ensure_evolution_job_write_access(
        &self,
        user_id: &str,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<(), SkillApiError> {
        match job.project_id.as_deref() {
            Some(project_id) => {
                self.ensure_project_access(
                    user_id,
                    tenant_id,
                    project_id,
                    SkillProjectAccess::Write,
                )
                .await
            }
            None => {
                self.ensure_write_access(user_id, tenant_id, "tenant", None)
                    .await
            }
        }
    }

    async fn apply_pending_evolution_job(
        &self,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<Option<String>, SkillApiError> {
        match job.action.as_str() {
            "create_skill" => self.create_skill_from_evolution_job(tenant_id, job).await,
            "improve_skill" | "optimize_description" => {
                self.update_skill_from_evolution_job(tenant_id, job).await
            }
            _ => Ok(None),
        }
    }

    async fn create_skill_from_evolution_job(
        &self,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<Option<String>, SkillApiError> {
        let Some(candidate_content) = job
            .candidate_content
            .as_deref()
            .filter(|content| !content.is_empty())
        else {
            return Ok(None);
        };
        let payload = SkillImportPayload {
            skill_md_content: candidate_content.to_string(),
            resource_files: BTreeMap::new(),
            scope: evolution_job_scope(job).to_string(),
            project_id: job.project_id.clone(),
            overwrite: false,
            change_summary: None,
        };
        let Ok(parsed) = ParsedImportPackage::from_payload(&payload) else {
            return Ok(None);
        };
        if parsed.name != job.skill_name {
            return Ok(None);
        }
        if self
            .repo
            .find_skill(
                tenant_id,
                &parsed.name,
                evolution_job_scope(job),
                job.project_id.as_deref(),
            )
            .await
            .map_err(SkillApiError::internal)?
            .is_some()
        {
            return Ok(None);
        }

        let now = Utc::now();
        let version_label = parsed
            .version_label
            .clone()
            .or_else(|| Some("1".to_string()));
        let skill = SkillRecord {
            id: generate_uuid_v4(),
            tenant_id: tenant_id.to_string(),
            project_id: job.project_id.clone(),
            name: parsed.name.clone(),
            description: parsed.description,
            tools: parsed.tools,
            status: "active".to_string(),
            metadata_json: parsed.metadata,
            created_at: now,
            updated_at: Some(now),
            scope: evolution_job_scope(job).to_string(),
            is_system_skill: false,
            full_content: Some(candidate_content.to_string()),
            resource_files: json!({}),
            license: parsed.license,
            compatibility: parsed.compatibility,
            allowed_tools_raw: parsed.allowed_tools_raw,
            spec_version: parsed.spec_version,
            current_version: 0,
            version_label: parsed.version_label,
        };
        let created = self
            .repo
            .create_skill(&skill)
            .await
            .map_err(SkillApiError::internal)?;
        let version = SkillVersionRecord {
            id: generate_uuid_v4(),
            skill_id: created.id.clone(),
            version_number: 1,
            version_label: version_label.clone(),
            skill_md_content: candidate_content.to_string(),
            resource_files: json!({}),
            change_summary: evolution_change_summary(job, "create_skill"),
            created_by: "evolution".to_string(),
            created_at: now,
        };
        let version_id = version.id.clone();
        self.repo
            .create_version(&version)
            .await
            .map_err(SkillApiError::internal)?;
        let updated = SkillUpdateRecord {
            current_version: Some(1),
            version_label: Some(version_label),
            ..Default::default()
        }
        .apply_to(created, now);
        self.repo
            .update_skill(&updated)
            .await
            .map_err(SkillApiError::internal)?;
        Ok(Some(version_id))
    }

    async fn update_skill_from_evolution_job(
        &self,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<Option<String>, SkillApiError> {
        let Some(candidate_content) = job
            .candidate_content
            .as_deref()
            .filter(|content| !content.is_empty())
        else {
            return Ok(None);
        };
        let Some(skill) = self.skill_for_evolution_job(tenant_id, job).await? else {
            return Ok(None);
        };
        let updated_content = if job.action == "optimize_description" {
            replace_frontmatter_description(
                skill.full_content.as_deref().unwrap_or_default(),
                candidate_content,
            )
        } else {
            candidate_content.to_string()
        };
        let next_version = self
            .repo
            .max_version_number(&skill.id)
            .await
            .map_err(SkillApiError::internal)?
            + 1;
        let now = Utc::now();
        let version_label = Some(next_version.to_string());
        let version = SkillVersionRecord {
            id: generate_uuid_v4(),
            skill_id: skill.id.clone(),
            version_number: next_version,
            version_label: version_label.clone(),
            skill_md_content: updated_content.clone(),
            resource_files: json!({}),
            change_summary: evolution_change_summary(job, &job.action),
            created_by: "evolution".to_string(),
            created_at: now,
        };
        let version_id = version.id.clone();
        self.repo
            .create_version(&version)
            .await
            .map_err(SkillApiError::internal)?;
        let updated = SkillUpdateRecord {
            full_content: Some(Some(updated_content)),
            current_version: Some(next_version),
            version_label: Some(version_label),
            ..Default::default()
        }
        .apply_to(skill, now);
        self.repo
            .update_skill(&updated)
            .await
            .map_err(SkillApiError::internal)?;
        Ok(Some(version_id))
    }

    async fn skill_for_evolution_job(
        &self,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<Option<SkillRecord>, SkillApiError> {
        if let Some(project_id) = job.project_id.as_deref() {
            if let Some(skill) = self
                .repo
                .find_skill(tenant_id, &job.skill_name, "project", Some(project_id))
                .await
                .map_err(SkillApiError::internal)?
            {
                return Ok(Some(skill));
            }
        }
        self.repo
            .find_skill(tenant_id, &job.skill_name, "tenant", None)
            .await
            .map_err(SkillApiError::internal)
    }
}

#[derive(Default)]
pub(crate) struct DevSkillService {
    tenant_id: String,
    skills: Mutex<HashMap<String, SkillRecord>>,
    versions: Mutex<HashMap<String, Vec<SkillVersionRecord>>>,
    evolution_jobs: Mutex<HashMap<String, SkillEvolutionJobRecord>>,
    evolution_configs: Mutex<HashMap<String, SkillEvolutionConfig>>,
}

impl DevSkillService {
    pub(crate) fn new(tenant_id: impl Into<String>) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            skills: Mutex::new(HashMap::new()),
            versions: Mutex::new(HashMap::new()),
            evolution_jobs: Mutex::new(HashMap::new()),
            evolution_configs: Mutex::new(HashMap::new()),
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

    fn evolution_config_for(&self, tenant_id: &str) -> Result<SkillEvolutionConfig, SkillApiError> {
        Ok(self
            .evolution_configs
            .lock()
            .map_err(SkillApiError::internal)?
            .get(tenant_id)
            .cloned()
            .unwrap_or_else(SkillEvolutionConfig::from_env))
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

    async fn import_package(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        body: SkillImportPayload,
    ) -> Result<SkillLifecycleView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let scope = normalize_scope(&body.scope, body.project_id.as_deref())?;
        validate_change_summary(body.change_summary.as_deref())?;
        let parsed = ParsedImportPackage::from_payload(&body)?;
        let existing = {
            let skills = self.skills.lock().map_err(SkillApiError::internal)?;
            skills
                .values()
                .find(|skill| {
                    skill.tenant_id == tenant_id
                        && skill.name == parsed.name
                        && skill.scope == scope
                        && skill.project_id == body.project_id
                })
                .cloned()
        };
        if existing.is_some() && !body.overwrite {
            return Err(SkillApiError::conflict("Skill already exists"));
        }

        let now = Utc::now();
        let resource_files = json!(body.resource_files);
        let (skill, action) = match existing {
            Some(skill) => (skill, "update".to_string()),
            None => (
                SkillRecord {
                    id: generate_uuid_v4(),
                    tenant_id,
                    project_id: body.project_id.clone(),
                    name: parsed.name.clone(),
                    description: parsed.description.clone(),
                    tools: parsed.tools.clone(),
                    status: "active".to_string(),
                    metadata_json: parsed.metadata.clone(),
                    created_at: now,
                    updated_at: Some(now),
                    scope,
                    is_system_skill: false,
                    full_content: Some(body.skill_md_content.clone()),
                    resource_files: resource_files.clone(),
                    license: parsed.license.clone(),
                    compatibility: parsed.compatibility.clone(),
                    allowed_tools_raw: parsed.allowed_tools_raw.clone(),
                    spec_version: parsed.spec_version.clone(),
                    current_version: 0,
                    version_label: parsed.version_label.clone(),
                },
                "import".to_string(),
            ),
        };
        let next_version = self
            .versions
            .lock()
            .map_err(SkillApiError::internal)?
            .get(&skill.id)
            .map(|versions| versions.iter().map(|v| v.version_number).max().unwrap_or(0))
            .unwrap_or(0)
            + 1;
        let version_label = parsed
            .version_label
            .clone()
            .or_else(|| Some(next_version.to_string()));
        let updated = SkillUpdateRecord {
            name: Some(parsed.name),
            description: Some(parsed.description),
            tools: Some(parsed.tools),
            metadata_json: Some(parsed.metadata),
            full_content: Some(Some(body.skill_md_content.clone())),
            resource_files: Some(resource_files.clone()),
            license: Some(parsed.license),
            compatibility: Some(parsed.compatibility),
            allowed_tools_raw: Some(parsed.allowed_tools_raw),
            spec_version: Some(parsed.spec_version),
            current_version: Some(next_version),
            version_label: Some(version_label.clone()),
            ..Default::default()
        }
        .apply_to(skill, now);
        let version = SkillVersionRecord {
            id: generate_uuid_v4(),
            skill_id: updated.id.clone(),
            version_number: next_version,
            version_label: version_label.clone(),
            skill_md_content: body.skill_md_content,
            resource_files,
            change_summary: import_change_summary(body.change_summary.as_deref(), next_version),
            created_by: "import".to_string(),
            created_at: now,
        };
        self.versions
            .lock()
            .map_err(SkillApiError::internal)?
            .entry(updated.id.clone())
            .or_default()
            .push(version);
        let updated = self.write_record(updated)?;
        Ok(SkillLifecycleView {
            action,
            skill: updated.into(),
            version_number: Some(next_version),
            version_label,
        })
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

    async fn list_system_skills(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        status: Option<&str>,
    ) -> Result<SkillListView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        system_skills::list_filesystem_system_skills(&tenant_id, status).await
    }

    async fn import_system_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SystemSkillImportPayload,
    ) -> Result<SkillLifecycleView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let target = body.target()?.to_string();
        let package = system_skills::export_filesystem_system_skill(&tenant_id, &target)
            .await?
            .ok_or_else(|| SkillApiError::not_found("Skill not found"))?;
        let import_payload = SkillImportPayload {
            skill_md_content: package.skill_md_content,
            resource_files: resource_files_map(package.resource_files)?,
            scope: body.scope,
            project_id: body.project_id,
            overwrite: body.overwrite,
            change_summary: body.change_summary,
        };
        self.import_package(user_id, Some(&tenant_id), import_payload)
            .await
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
        let skill = match self.get_owned(&tenant_id, skill_id) {
            Ok(skill) => skill,
            Err(err) if err.status == StatusCode::NOT_FOUND => {
                return system_skills::export_filesystem_system_skill(&tenant_id, skill_id)
                    .await?
                    .ok_or_else(|| SkillApiError::not_found("Skill not found"));
            }
            Err(err) => return Err(err),
        };
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

    async fn get_evolution_config(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<SkillEvolutionConfigView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        Ok(self.evolution_config_for(&tenant_id)?.into())
    }

    async fn update_evolution_config(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        body: SkillEvolutionConfigUpdatePayload,
    ) -> Result<SkillEvolutionConfigView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        body.validate()?;
        let next_config = self
            .evolution_config_for(&tenant_id)?
            .with_overrides(&body)?;
        self.evolution_configs
            .lock()
            .map_err(SkillApiError::internal)?
            .insert(tenant_id, next_config.clone());
        Ok(next_config.into())
    }

    async fn get_evolution_overview(
        &self,
        _user_id: &str,
        query: SkillEvolutionOverviewQuery,
    ) -> Result<SkillEvolutionOverviewView, SkillApiError> {
        let tenant_id = self.resolve_tenant(query.tenant_id.as_deref());
        query.validated_limits()?;
        Ok(empty_evolution_overview(
            self.evolution_config_for(&tenant_id)?,
        ))
    }

    async fn get_evolution_detail(
        &self,
        _user_id: &str,
        query: SkillEvolutionDetailQuery,
        skill_id: &str,
    ) -> Result<SkillEvolutionDetailView, SkillApiError> {
        let tenant_id = self.resolve_tenant(query.tenant_id.as_deref());
        let limit = query.validated_limit()? as usize;
        let config = self.evolution_config_for(&tenant_id)?;
        let skill = self.get_owned(&tenant_id, skill_id)?;
        let mut versions = self
            .versions
            .lock()
            .map_err(SkillApiError::internal)?
            .get(skill_id)
            .cloned()
            .unwrap_or_default();
        versions.sort_by(|left, right| {
            right
                .version_number
                .cmp(&left.version_number)
                .then_with(|| right.created_at.cmp(&left.created_at))
        });
        versions.truncate(limit);
        Ok(evolution_detail_from_records(
            &skill,
            config,
            versions,
            Vec::new(),
            0,
        ))
    }

    async fn apply_evolution_job(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        job_id: &str,
    ) -> Result<SkillEvolutionJobView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let job = self.pending_dev_evolution_job(&tenant_id, job_id)?;
        let version_id = self
            .apply_dev_evolution_job(&tenant_id, &job)?
            .ok_or_else(|| SkillApiError::bad_request("Skill evolution job cannot be applied"))?;
        self.update_dev_evolution_job_status(&tenant_id, job_id, "applied", Some(&version_id))
    }

    async fn reject_evolution_job(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        job_id: &str,
    ) -> Result<SkillEvolutionJobView, SkillApiError> {
        let tenant_id = self.resolve_tenant(tenant_id);
        let _job = self.pending_dev_evolution_job(&tenant_id, job_id)?;
        self.update_dev_evolution_job_status(&tenant_id, job_id, "rejected", None)
    }
}

impl DevSkillService {
    fn pending_dev_evolution_job(
        &self,
        tenant_id: &str,
        job_id: &str,
    ) -> Result<SkillEvolutionJobRecord, SkillApiError> {
        let job = self
            .evolution_jobs
            .lock()
            .map_err(SkillApiError::internal)?
            .get(job_id)
            .cloned()
            .filter(|job| job.tenant_id == tenant_id)
            .ok_or_else(|| SkillApiError::not_found("Skill evolution job not found"))?;
        if job.status != "pending_review" {
            return Err(SkillApiError::bad_request(
                "Skill evolution job is not pending review",
            ));
        }
        Ok(job)
    }

    fn update_dev_evolution_job_status(
        &self,
        tenant_id: &str,
        job_id: &str,
        status: &str,
        skill_version_id: Option<&str>,
    ) -> Result<SkillEvolutionJobView, SkillApiError> {
        let mut jobs = self
            .evolution_jobs
            .lock()
            .map_err(SkillApiError::internal)?;
        let job = jobs
            .get_mut(job_id)
            .filter(|job| job.tenant_id == tenant_id)
            .ok_or_else(|| SkillApiError::not_found("Skill evolution job not found"))?;
        job.status = status.to_string();
        if let Some(skill_version_id) = skill_version_id {
            job.skill_version_id = Some(skill_version_id.to_string());
        }
        if status == "applied" {
            job.applied_at = Some(Utc::now());
        }
        Ok(job.clone().into())
    }

    fn apply_dev_evolution_job(
        &self,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<Option<String>, SkillApiError> {
        match job.action.as_str() {
            "create_skill" => self.create_dev_skill_from_evolution_job(tenant_id, job),
            "improve_skill" | "optimize_description" => {
                self.update_dev_skill_from_evolution_job(tenant_id, job)
            }
            _ => Ok(None),
        }
    }

    fn create_dev_skill_from_evolution_job(
        &self,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<Option<String>, SkillApiError> {
        let Some(candidate_content) = job
            .candidate_content
            .as_deref()
            .filter(|content| !content.is_empty())
        else {
            return Ok(None);
        };
        let payload = SkillImportPayload {
            skill_md_content: candidate_content.to_string(),
            resource_files: BTreeMap::new(),
            scope: evolution_job_scope(job).to_string(),
            project_id: job.project_id.clone(),
            overwrite: false,
            change_summary: None,
        };
        let Ok(parsed) = ParsedImportPackage::from_payload(&payload) else {
            return Ok(None);
        };
        if parsed.name != job.skill_name {
            return Ok(None);
        }
        let mut skills = self.skills.lock().map_err(SkillApiError::internal)?;
        if skills.values().any(|skill| {
            skill.tenant_id == tenant_id
                && skill.name == parsed.name
                && skill.scope == evolution_job_scope(job)
                && skill.project_id == job.project_id
        }) {
            return Ok(None);
        }

        let now = Utc::now();
        let version_label = parsed
            .version_label
            .clone()
            .or_else(|| Some("1".to_string()));
        let mut skill = SkillRecord {
            id: generate_uuid_v4(),
            tenant_id: tenant_id.to_string(),
            project_id: job.project_id.clone(),
            name: parsed.name,
            description: parsed.description,
            tools: parsed.tools,
            status: "active".to_string(),
            metadata_json: parsed.metadata,
            created_at: now,
            updated_at: Some(now),
            scope: evolution_job_scope(job).to_string(),
            is_system_skill: false,
            full_content: Some(candidate_content.to_string()),
            resource_files: json!({}),
            license: parsed.license,
            compatibility: parsed.compatibility,
            allowed_tools_raw: parsed.allowed_tools_raw,
            spec_version: parsed.spec_version,
            current_version: 1,
            version_label: version_label.clone(),
        };
        let version = SkillVersionRecord {
            id: generate_uuid_v4(),
            skill_id: skill.id.clone(),
            version_number: 1,
            version_label: version_label.clone(),
            skill_md_content: candidate_content.to_string(),
            resource_files: json!({}),
            change_summary: evolution_change_summary(job, "create_skill"),
            created_by: "evolution".to_string(),
            created_at: now,
        };
        let version_id = version.id.clone();
        skill.version_label = version_label;
        self.versions
            .lock()
            .map_err(SkillApiError::internal)?
            .entry(skill.id.clone())
            .or_default()
            .push(version);
        skills.insert(skill.id.clone(), skill);
        Ok(Some(version_id))
    }

    fn update_dev_skill_from_evolution_job(
        &self,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<Option<String>, SkillApiError> {
        let Some(candidate_content) = job
            .candidate_content
            .as_deref()
            .filter(|content| !content.is_empty())
        else {
            return Ok(None);
        };
        let Some(skill) = self.dev_skill_for_evolution_job(tenant_id, job)? else {
            return Ok(None);
        };
        let updated_content = if job.action == "optimize_description" {
            replace_frontmatter_description(
                skill.full_content.as_deref().unwrap_or_default(),
                candidate_content,
            )
        } else {
            candidate_content.to_string()
        };
        let mut versions = self.versions.lock().map_err(SkillApiError::internal)?;
        let next_version = versions
            .get(&skill.id)
            .map(|versions| {
                versions
                    .iter()
                    .map(|version| version.version_number)
                    .max()
                    .unwrap_or(0)
            })
            .unwrap_or(0)
            + 1;
        let now = Utc::now();
        let version_label = Some(next_version.to_string());
        let version = SkillVersionRecord {
            id: generate_uuid_v4(),
            skill_id: skill.id.clone(),
            version_number: next_version,
            version_label: version_label.clone(),
            skill_md_content: updated_content.clone(),
            resource_files: json!({}),
            change_summary: evolution_change_summary(job, &job.action),
            created_by: "evolution".to_string(),
            created_at: now,
        };
        let version_id = version.id.clone();
        versions.entry(skill.id.clone()).or_default().push(version);
        drop(versions);

        let updated = SkillUpdateRecord {
            full_content: Some(Some(updated_content)),
            current_version: Some(next_version),
            version_label: Some(version_label),
            ..Default::default()
        }
        .apply_to(skill, now);
        self.write_record(updated)?;
        Ok(Some(version_id))
    }

    fn dev_skill_for_evolution_job(
        &self,
        tenant_id: &str,
        job: &SkillEvolutionJobRecord,
    ) -> Result<Option<SkillRecord>, SkillApiError> {
        let skills = self.skills.lock().map_err(SkillApiError::internal)?;
        if let Some(project_id) = job.project_id.as_deref() {
            if let Some(skill) = skills.values().find(|skill| {
                skill.tenant_id == tenant_id
                    && skill.name == job.skill_name
                    && skill.scope == "project"
                    && skill.project_id.as_deref() == Some(project_id)
            }) {
                return Ok(Some(skill.clone()));
            }
        }
        Ok(skills
            .values()
            .find(|skill| {
                skill.tenant_id == tenant_id
                    && skill.name == job.skill_name
                    && skill.scope == "tenant"
                    && skill.project_id.is_none()
            })
            .cloned())
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

async fn import_skill_package(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Json(body): Json<SkillImportPayload>,
) -> Result<(StatusCode, Json<SkillLifecycleView>), SkillApiError> {
    let view = app
        .skills
        .import_package(&identity.user_id, q.tenant_id.as_deref(), body)
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn import_skill_zip_package(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    multipart: Multipart,
) -> Result<(StatusCode, Json<SkillLifecycleView>), SkillApiError> {
    let body = zip_import::skill_import_payload_from_multipart(multipart).await?;
    let view = app
        .skills
        .import_package(&identity.user_id, q.tenant_id.as_deref(), body)
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn import_system_skill(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Json(body): Json<SystemSkillImportPayload>,
) -> Result<(StatusCode, Json<SkillLifecycleView>), SkillApiError> {
    let view = app
        .skills
        .import_system_skill(&identity.user_id, q.tenant_id.as_deref(), body)
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn list_system_skills(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<SystemSkillListQuery>,
) -> Result<Json<SkillListView>, SkillApiError> {
    let mut view = app
        .skills
        .list_system_skills(
            &identity.user_id,
            q.tenant_id.as_deref(),
            q.status.as_deref(),
        )
        .await?;
    let disabled_names = app
        .tenant_skill_configs
        .list_configs(&identity.user_id, q.tenant_id.as_deref())
        .await
        .map_err(tenant_skill_config_error)?
        .disabled_system_skill_names();
    filter_disabled_system_skills(&mut view, &disabled_names);
    Ok(Json(view))
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

async fn get_skill_evolution_config(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
) -> Result<Json<SkillEvolutionConfigView>, SkillApiError> {
    Ok(Json(
        app.skills
            .get_evolution_config(&identity.user_id, q.tenant_id.as_deref())
            .await?,
    ))
}

async fn update_skill_evolution_config(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Json(body): Json<SkillEvolutionConfigUpdatePayload>,
) -> Result<Json<SkillEvolutionConfigView>, SkillApiError> {
    Ok(Json(
        app.skills
            .update_evolution_config(&identity.user_id, q.tenant_id.as_deref(), body)
            .await?,
    ))
}

async fn get_skill_evolution_overview(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<SkillEvolutionOverviewQuery>,
) -> Result<Json<SkillEvolutionOverviewView>, SkillApiError> {
    Ok(Json(
        app.skills
            .get_evolution_overview(&identity.user_id, query)
            .await?,
    ))
}

async fn get_skill_evolution_detail(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<SkillEvolutionDetailQuery>,
    Path(skill_id): Path<String>,
) -> Result<Json<SkillEvolutionDetailView>, SkillApiError> {
    Ok(Json(
        app.skills
            .get_evolution_detail(&identity.user_id, query, &skill_id)
            .await?,
    ))
}

async fn apply_skill_evolution_job(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(job_id): Path<String>,
) -> Result<Json<SkillEvolutionJobView>, SkillApiError> {
    Ok(Json(
        app.skills
            .apply_evolution_job(&identity.user_id, q.tenant_id.as_deref(), &job_id)
            .await?,
    ))
}

async fn reject_skill_evolution_job(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantQuery>,
    Path(job_id): Path<String>,
) -> Result<Json<SkillEvolutionJobView>, SkillApiError> {
    Ok(Json(
        app.skills
            .reject_evolution_job(&identity.user_id, q.tenant_id.as_deref(), &job_id)
            .await?,
    ))
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

fn tenant_skill_config_error(
    error: crate::tenant_skill_config_api::TenantSkillConfigApiError,
) -> SkillApiError {
    let (status, detail) = error.into_parts();
    SkillApiError::new(status, detail)
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

fn validate_change_summary(summary: Option<&str>) -> Result<(), SkillApiError> {
    if summary.is_some_and(|summary| summary.chars().count() > 2_000) {
        return Err(SkillApiError::bad_request("Invalid skill request"));
    }
    Ok(())
}

fn import_change_summary(summary: Option<&str>, version_number: i32) -> Option<String> {
    Some(present(summary).map_or_else(|| format!("Version {version_number}"), ToString::to_string))
}

fn resource_files_map(value: Value) -> Result<BTreeMap<String, String>, SkillApiError> {
    let Value::Object(files) = value else {
        return Ok(BTreeMap::new());
    };

    let mut resource_files = BTreeMap::new();
    for (path, content) in files {
        let Value::String(content) = content else {
            return Err(SkillApiError::bad_request("Invalid Agent Skill package"));
        };
        resource_files.insert(path, content);
    }
    Ok(resource_files)
}

fn evolution_job_scope(job: &SkillEvolutionJobRecord) -> &'static str {
    if job.project_id.is_some() {
        "project"
    } else {
        "tenant"
    }
}

fn evolution_change_summary(job: &SkillEvolutionJobRecord, action: &str) -> Option<String> {
    Some(
        job.rationale
            .as_deref()
            .filter(|rationale| !rationale.is_empty())
            .map_or_else(|| format!("Evolution {action}"), ToString::to_string),
    )
}

fn replace_frontmatter_description(content: &str, description: &str) -> String {
    let Some(rest) = content.strip_prefix("---\n") else {
        return if content.is_empty() {
            description.to_string()
        } else {
            content.to_string()
        };
    };
    let Some((frontmatter, body)) = rest.split_once("\n---") else {
        return if content.is_empty() {
            description.to_string()
        } else {
            content.to_string()
        };
    };
    let Ok(value) = serde_yaml_ng::from_str::<YamlValue>(frontmatter.trim()) else {
        return content.to_string();
    };
    let mut map = match value {
        YamlValue::Mapping(map) => map,
        YamlValue::Null => YamlMapping::new(),
        _ => return content.to_string(),
    };
    map.insert(
        YamlValue::String("description".to_string()),
        YamlValue::String(description.to_string()),
    );
    let value = YamlValue::Mapping(map);
    let Ok(yaml_text) = serde_yaml_ng::to_string(&value) else {
        return content.to_string();
    };
    format!("---\n{}\n---{}", yaml_text.trim(), body)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SkillEvolutionPublishMode {
    Review,
    Direct,
}

impl SkillEvolutionPublishMode {
    fn parse(raw: &str) -> Option<Self> {
        match raw {
            "review" => Some(Self::Review),
            "direct" => Some(Self::Direct),
            _ => None,
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::Review => "review",
            Self::Direct => "direct",
        }
    }
}

#[derive(Debug, Clone)]
struct SkillEvolutionConfig {
    enabled: bool,
    min_sessions_per_skill: i64,
    scoring_min_sessions_per_skill: i64,
    min_avg_score: f64,
    max_sessions_per_batch: i64,
    evolution_interval_minutes: i64,
    publish_mode: SkillEvolutionPublishMode,
    auto_apply: bool,
}

impl SkillEvolutionConfig {
    fn from_env() -> Self {
        Self {
            enabled: env_bool("SKILL_EVOLUTION_ENABLED", true),
            min_sessions_per_skill: env_i64("SKILL_EVOLUTION_MIN_SESSIONS", 5),
            scoring_min_sessions_per_skill: env_i64("SKILL_EVOLUTION_SCORING_MIN_SESSIONS", 5),
            min_avg_score: env_f64("SKILL_EVOLUTION_MIN_AVG_SCORE", 0.6),
            max_sessions_per_batch: env_i64("SKILL_EVOLUTION_MAX_SESSIONS_PER_BATCH", 50),
            evolution_interval_minutes: env_i64("SKILL_EVOLUTION_INTERVAL_MINUTES", 60),
            publish_mode: std::env::var("SKILL_EVOLUTION_PUBLISH_MODE")
                .ok()
                .and_then(|value| SkillEvolutionPublishMode::parse(value.as_str()))
                .unwrap_or(SkillEvolutionPublishMode::Review),
            auto_apply: env_bool("SKILL_EVOLUTION_AUTO_APPLY", false),
        }
    }

    fn with_overrides(
        mut self,
        body: &SkillEvolutionConfigUpdatePayload,
    ) -> Result<Self, SkillApiError> {
        if let Some(value) = body.enabled {
            self.enabled = value;
        }
        if let Some(value) = body.min_sessions_per_skill {
            self.min_sessions_per_skill = value;
        }
        if let Some(value) = body.scoring_min_sessions_per_skill {
            self.scoring_min_sessions_per_skill = value;
        }
        if let Some(value) = body.min_avg_score {
            self.min_avg_score = value;
        }
        if let Some(value) = body.max_sessions_per_batch {
            self.max_sessions_per_batch = value;
        }
        if let Some(value) = body.evolution_interval_minutes {
            self.evolution_interval_minutes = value;
        }
        if let Some(mode) = body.publish_mode.as_deref() {
            self.publish_mode = SkillEvolutionPublishMode::parse(mode).ok_or_else(|| {
                SkillApiError::bad_request("Invalid skill evolution publish mode")
            })?;
        }
        if let Some(value) = body.auto_apply {
            self.auto_apply = value;
        }
        Ok(self)
    }

    fn with_stored_overrides(mut self, value: &Value) -> Self {
        let Value::Object(map) = value else {
            return self;
        };
        if let Some(value) = stored_bool(map, "enabled") {
            self.enabled = value;
        }
        if let Some(value) = stored_i64(map, "min_sessions_per_skill") {
            self.min_sessions_per_skill = value.max(1);
        }
        if let Some(value) = stored_i64(map, "scoring_min_sessions_per_skill") {
            self.scoring_min_sessions_per_skill = value.max(1);
        }
        if let Some(value) = stored_f64(map, "min_avg_score") {
            self.min_avg_score = value.clamp(0.0, 1.0);
        }
        if let Some(value) = stored_i64(map, "max_sessions_per_batch") {
            self.max_sessions_per_batch = value.max(1);
        }
        if let Some(value) = stored_i64(map, "evolution_interval_minutes") {
            self.evolution_interval_minutes = value.max(1);
        }
        if let Some(mode) = map
            .get("publish_mode")
            .and_then(Value::as_str)
            .and_then(SkillEvolutionPublishMode::parse)
        {
            self.publish_mode = mode;
        }
        if let Some(value) = stored_bool(map, "auto_apply") {
            self.auto_apply = value;
        }
        self
    }
}

impl SkillEvolutionConfigUpdatePayload {
    fn validate(&self) -> Result<(), SkillApiError> {
        validate_i64_bounds(self.min_sessions_per_skill, 1, 100)?;
        validate_i64_bounds(self.scoring_min_sessions_per_skill, 1, 100)?;
        validate_i64_bounds(self.max_sessions_per_batch, 1, 100)?;
        validate_i64_bounds(self.evolution_interval_minutes, 1, 10_080)?;
        if self
            .min_avg_score
            .is_some_and(|value| !(0.0..=1.0).contains(&value))
        {
            return Err(SkillApiError::unprocessable(
                "Invalid skill evolution config",
            ));
        }
        if self
            .publish_mode
            .as_deref()
            .is_some_and(|mode| SkillEvolutionPublishMode::parse(mode).is_none())
        {
            return Err(SkillApiError::bad_request(
                "Invalid skill evolution publish mode",
            ));
        }
        Ok(())
    }
}

fn validate_i64_bounds(value: Option<i64>, min: i64, max: i64) -> Result<(), SkillApiError> {
    if value.is_some_and(|value| value < min || value > max) {
        return Err(SkillApiError::unprocessable(
            "Invalid skill evolution config",
        ));
    }
    Ok(())
}

fn validate_overview_limit(value: Option<i64>) -> Result<i64, SkillApiError> {
    match value {
        Some(value) if !(1..=200).contains(&value) => Err(SkillApiError::unprocessable(
            "Invalid skill evolution overview query",
        )),
        Some(value) => Ok(value),
        None => Ok(50),
    }
}

fn validate_evolution_detail_limit(value: Option<i64>) -> Result<i64, SkillApiError> {
    match value {
        Some(value) if !(1..=100).contains(&value) => Err(SkillApiError::unprocessable(
            "Invalid skill evolution detail query",
        )),
        Some(value) => Ok(value),
        None => Ok(20),
    }
}

fn env_bool(name: &str, default: bool) -> bool {
    std::env::var(name)
        .map(|value| value.eq_ignore_ascii_case("true"))
        .unwrap_or(default)
}

fn env_i64(name: &str, default: i64) -> i64 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<i64>().ok())
        .unwrap_or(default)
}

fn env_f64(name: &str, default: f64) -> f64 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<f64>().ok())
        .unwrap_or(default)
}

fn stored_bool(map: &Map<String, Value>, key: &str) -> Option<bool> {
    map.get(key).and_then(|value| match value {
        Value::Bool(value) => Some(*value),
        Value::Number(value) => value.as_i64().map(|value| value != 0),
        Value::String(value) => Some(value.eq_ignore_ascii_case("true")),
        _ => None,
    })
}

fn stored_i64(map: &Map<String, Value>, key: &str) -> Option<i64> {
    map.get(key).and_then(|value| match value {
        Value::Number(value) => value
            .as_i64()
            .or_else(|| value.as_f64().map(|value| value as i64)),
        Value::String(value) => value.parse::<i64>().ok(),
        Value::Bool(value) => Some(i64::from(u8::from(*value))),
        _ => None,
    })
}

fn stored_f64(map: &Map<String, Value>, key: &str) -> Option<f64> {
    map.get(key).and_then(|value| match value {
        Value::Number(value) => value.as_f64(),
        Value::String(value) => value.parse::<f64>().ok(),
        Value::Bool(value) => Some(f64::from(u8::from(*value))),
        _ => None,
    })
}

#[derive(Default)]
struct ParsedSkillPayload {
    name: Option<String>,
    description: Option<String>,
    tools: Option<Vec<String>>,
    metadata: Option<Value>,
    license: Option<String>,
    compatibility: Option<String>,
    allowed_tools_raw: Option<String>,
    spec_version: Option<String>,
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
                "license" => {
                    parsed.license = Some(value.to_string());
                    metadata.insert(key.to_string(), Value::String(value.to_string()));
                }
                "compatibility" => {
                    parsed.compatibility = Some(value.to_string());
                    metadata.insert(key.to_string(), Value::String(value.to_string()));
                }
                "allowed_tools" | "allowed-tools" => {
                    parsed.allowed_tools_raw = Some(value.to_string());
                    if parsed.tools.is_none() {
                        let tools = parse_allowed_tools(value);
                        if !tools.is_empty() {
                            parsed.tools = Some(tools);
                        }
                    }
                    metadata.insert(
                        "allowed_tools".to_string(),
                        Value::String(value.to_string()),
                    );
                }
                "spec_version" | "spec-version" => {
                    parsed.spec_version = Some(value.to_string());
                    metadata.insert("spec_version".to_string(), Value::String(value.to_string()));
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

struct ParsedImportPackage {
    name: String,
    description: String,
    tools: Vec<String>,
    metadata: Option<Value>,
    license: Option<String>,
    compatibility: Option<String>,
    allowed_tools_raw: Option<String>,
    spec_version: String,
    version_label: Option<String>,
}

impl ParsedImportPackage {
    fn from_payload(body: &SkillImportPayload) -> Result<Self, SkillApiError> {
        if body.skill_md_content.trim().is_empty() {
            return Err(SkillApiError::bad_request("Invalid Agent Skill package"));
        }
        let parsed = ParsedSkillPayload::from_content(Some(&body.skill_md_content));
        let Some(name) = parsed.name else {
            return Err(SkillApiError::bad_request("Invalid Agent Skill package"));
        };
        let Some(description) = parsed.description else {
            return Err(SkillApiError::bad_request("Invalid Agent Skill package"));
        };
        let tools = parsed.tools.unwrap_or_else(|| vec!["*".to_string()]);
        validate_skill_input(&name, &description, &tools)
            .map_err(|_| SkillApiError::bad_request("Invalid Agent Skill package"))?;
        let declared_spec_version = parsed.spec_version.clone();
        let spec_version = declared_spec_version
            .clone()
            .unwrap_or_else(|| "1.0".to_string());
        let metadata = merge_agentskills_metadata(
            parsed.metadata,
            parsed.license.as_deref(),
            parsed.compatibility.as_deref(),
            parsed.allowed_tools_raw.as_deref(),
            declared_spec_version.as_deref(),
        );
        Ok(Self {
            name,
            description,
            tools,
            metadata,
            license: parsed.license,
            compatibility: parsed.compatibility,
            allowed_tools_raw: parsed.allowed_tools_raw,
            spec_version,
            version_label: parsed.version_label,
        })
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

fn parse_allowed_tools(value: &str) -> Vec<String> {
    let raw_items = if value.contains(',') || value.trim_start().starts_with('[') {
        parse_inline_list(value)
    } else {
        value
            .split_whitespace()
            .map(|item| item.trim().trim_matches('"').trim_matches('\'').to_string())
            .collect()
    };
    raw_items
        .into_iter()
        .filter_map(|item| {
            let name = item
                .split_once('(')
                .map(|(name, _)| name)
                .unwrap_or(item.as_str())
                .trim();
            if name.is_empty() {
                None
            } else {
                Some(name.to_string())
            }
        })
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
mod tests;
