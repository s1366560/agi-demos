use super::*;

impl DevSkillService {
    pub(in crate::skill_api) fn import_dev_package(
        &self,
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

    pub(in crate::skill_api) fn update_dev_content(
        &self,
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

    pub(in crate::skill_api) fn list_dev_versions(
        &self,
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

    pub(in crate::skill_api) fn get_dev_version(
        &self,
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

    pub(in crate::skill_api) fn rollback_dev_skill(
        &self,
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

    pub(in crate::skill_api) async fn export_dev_package(
        &self,
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
}
