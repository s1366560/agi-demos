use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};

use agistack_adapters_postgres::PgSkillEvolutionRepository;
use agistack_adapters_secrets::generate_uuid_v4;
use async_trait::async_trait;

use super::*;

pub(crate) type SharedSkillEvolutionScheduler = Arc<dyn SkillEvolutionScheduler>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct SkillEvolutionScheduleResult {
    pub(crate) scheduled: bool,
    pub(crate) reason: String,
    pub(crate) status: String,
}

#[async_trait]
pub(crate) trait SkillEvolutionScheduler: Send + Sync {
    async fn schedule_evolution(
        &self,
        tenant_id: &str,
        project_id: Option<&str>,
        skill_name: Option<&str>,
        reason: &str,
    ) -> Result<SkillEvolutionScheduleResult, SkillApiError>;
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct SkillEvolutionScheduleKey {
    tenant_id: String,
    project_id: Option<String>,
    skill_name: Option<String>,
}

#[derive(Debug, Default)]
pub(crate) struct InMemorySkillEvolutionScheduler {
    queued: Mutex<BTreeSet<SkillEvolutionScheduleKey>>,
}

impl InMemorySkillEvolutionScheduler {
    pub(crate) fn new() -> Self {
        Self::default()
    }
}

#[async_trait]
impl SkillEvolutionScheduler for InMemorySkillEvolutionScheduler {
    async fn schedule_evolution(
        &self,
        tenant_id: &str,
        project_id: Option<&str>,
        skill_name: Option<&str>,
        reason: &str,
    ) -> Result<SkillEvolutionScheduleResult, SkillApiError> {
        let key = SkillEvolutionScheduleKey {
            tenant_id: tenant_id.to_string(),
            project_id: project_id.map(ToString::to_string),
            skill_name: skill_name.map(ToString::to_string),
        };
        let scheduled = self
            .queued
            .lock()
            .map_err(SkillApiError::internal)?
            .insert(key);
        Ok(SkillEvolutionScheduleResult {
            scheduled,
            reason: reason.to_string(),
            status: if scheduled {
                "queued".to_string()
            } else {
                "already_scheduled_or_not_running".to_string()
            },
        })
    }
}

#[derive(Debug, Clone)]
pub(crate) struct PgSkillEvolutionScheduler {
    repo: PgSkillEvolutionRepository,
}

impl PgSkillEvolutionScheduler {
    pub(crate) fn new(repo: PgSkillEvolutionRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl SkillEvolutionScheduler for PgSkillEvolutionScheduler {
    async fn schedule_evolution(
        &self,
        tenant_id: &str,
        project_id: Option<&str>,
        skill_name: Option<&str>,
        reason: &str,
    ) -> Result<SkillEvolutionScheduleResult, SkillApiError> {
        let run_id = generate_uuid_v4();
        let scheduled = self
            .repo
            .schedule_evolution_run(&run_id, tenant_id, project_id, skill_name, reason)
            .await
            .map_err(SkillApiError::internal)?;
        Ok(SkillEvolutionScheduleResult {
            scheduled,
            reason: reason.to_string(),
            status: if scheduled {
                "queued".to_string()
            } else {
                "already_scheduled_or_not_running".to_string()
            },
        })
    }
}
