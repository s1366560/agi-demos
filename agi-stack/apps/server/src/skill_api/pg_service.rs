use super::*;

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
