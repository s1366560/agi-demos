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
