use super::*;

impl PgSkillService {
    pub(super) async fn get_evolution_config_for_user(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<SkillEvolutionConfigView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let config = self.load_evolution_config(&tenant_id).await?;
        Ok(config.into())
    }

    pub(super) async fn update_evolution_config_for_user(
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

    pub(super) async fn evolution_overview_for_user(
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

    pub(super) async fn evolution_detail_for_user(
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

    pub(super) async fn run_tenant_evolution_for_user(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<SkillEvolutionTenantRunView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        self.ensure_write_access(user_id, &tenant_id, "tenant", None)
            .await?;
        let scheduler = self
            .evolution_scheduler
            .as_ref()
            .ok_or_else(skill_evolution_plugin_unavailable)?;
        let result = scheduler
            .schedule_evolution(&tenant_id, None, None, "manual")
            .await?;
        Ok(SkillEvolutionTenantRunView {
            tenant_id,
            result: result.into(),
        })
    }

    pub(super) async fn run_skill_evolution_for_user(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillEvolutionRunView, SkillApiError> {
        let tenant_id = self.resolve_tenant(user_id, tenant_id).await?;
        let skill = self.readable_skill(user_id, &tenant_id, skill_id).await?;
        if skill.is_system_skill || skill.scope == "system" {
            return Err(SkillApiError::bad_request(
                "Skill evolution is only available for managed skills",
            ));
        }
        self.ensure_write_access(
            user_id,
            &tenant_id,
            &skill.scope,
            skill.project_id.as_deref(),
        )
        .await?;
        let scheduler = self
            .evolution_scheduler
            .as_ref()
            .ok_or_else(skill_evolution_plugin_unavailable)?;
        let result = scheduler
            .schedule_evolution(
                &tenant_id,
                skill.project_id.as_deref(),
                Some(&skill.name),
                "manual",
            )
            .await?;
        Ok(SkillEvolutionRunView {
            skill_id: skill.id,
            skill_name: skill.name,
            result: result.into(),
        })
    }

    pub(super) async fn apply_evolution_job_for_user(
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

    pub(super) async fn reject_evolution_job_for_user(
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
