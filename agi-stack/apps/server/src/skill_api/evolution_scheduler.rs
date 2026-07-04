use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};

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
