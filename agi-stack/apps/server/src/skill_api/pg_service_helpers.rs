use super::*;

impl PgSkillService {
    pub(super) async fn resolve_tenant(
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

    pub(super) async fn ensure_write_access(
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

    pub(super) async fn ensure_project_access(
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

    pub(super) async fn readable_skill(
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

    pub(super) async fn writable_skill(
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

    pub(super) async fn load_evolution_config(
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

    pub(super) fn evolution_repo(&self) -> Result<&PgSkillEvolutionRepository, SkillApiError> {
        self.evolution_repo
            .as_ref()
            .ok_or_else(|| SkillApiError::internal("skill evolution repository unavailable"))
    }

    pub(super) async fn pending_evolution_job(
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

    pub(super) async fn ensure_evolution_job_write_access(
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

    pub(super) async fn apply_pending_evolution_job(
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
