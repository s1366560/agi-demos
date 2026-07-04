use super::*;

impl DevSkillService {
    pub(in crate::skill_api) fn pending_dev_evolution_job(
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

    pub(in crate::skill_api) fn update_dev_evolution_job_status(
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

    pub(in crate::skill_api) fn apply_dev_evolution_job(
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
