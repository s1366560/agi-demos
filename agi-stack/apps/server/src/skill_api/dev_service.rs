use super::*;

#[derive(Default)]
pub(crate) struct DevSkillService {
    pub(super) tenant_id: String,
    pub(super) skills: Mutex<HashMap<String, SkillRecord>>,
    pub(super) versions: Mutex<HashMap<String, Vec<SkillVersionRecord>>>,
    pub(super) evolution_jobs: Mutex<HashMap<String, SkillEvolutionJobRecord>>,
    pub(super) evolution_configs: Mutex<HashMap<String, SkillEvolutionConfig>>,
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

    pub(in crate::skill_api) fn resolve_tenant(&self, tenant_id: Option<&str>) -> String {
        present(tenant_id)
            .map(ToString::to_string)
            .unwrap_or_else(|| self.tenant_id.clone())
    }

    pub(in crate::skill_api) fn get_owned(
        &self,
        tenant_id: &str,
        skill_id: &str,
    ) -> Result<SkillRecord, SkillApiError> {
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

    pub(in crate::skill_api) fn write_record(
        &self,
        record: SkillRecord,
    ) -> Result<SkillRecord, SkillApiError> {
        self.skills
            .lock()
            .map_err(SkillApiError::internal)?
            .insert(record.id.clone(), record.clone());
        Ok(record)
    }

    pub(in crate::skill_api) fn evolution_config_for(
        &self,
        tenant_id: &str,
    ) -> Result<SkillEvolutionConfig, SkillApiError> {
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
        self.import_dev_package(tenant_id, body)
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
        self.update_dev_content(tenant_id, skill_id, body)
    }

    async fn list_versions(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<SkillVersionListView, SkillApiError> {
        self.list_dev_versions(tenant_id, skill_id, limit, offset)
    }

    async fn get_version(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        version_number: i32,
    ) -> Result<SkillVersionDetailView, SkillApiError> {
        self.get_dev_version(tenant_id, skill_id, version_number)
    }

    async fn rollback(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        body: SkillRollbackPayload,
    ) -> Result<SkillView, SkillApiError> {
        self.rollback_dev_skill(tenant_id, skill_id, body)
    }

    async fn export_package(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillPackageView, SkillApiError> {
        self.export_dev_package(tenant_id, skill_id).await
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
