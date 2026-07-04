use std::sync::Arc;

use async_trait::async_trait;

use super::*;

pub(crate) type SharedSkills = Arc<dyn SkillService>;

#[async_trait]
pub(crate) trait SkillService: Send + Sync {
    async fn create_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SkillCreatePayload,
    ) -> Result<SkillView, SkillApiError>;

    async fn import_package(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SkillImportPayload,
    ) -> Result<SkillLifecycleView, SkillApiError>;

    async fn list_skills(
        &self,
        user_id: &str,
        query: SkillListQuery,
    ) -> Result<SkillListView, SkillApiError>;

    async fn list_system_skills(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        status: Option<&str>,
    ) -> Result<SkillListView, SkillApiError>;

    async fn import_system_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SystemSkillImportPayload,
    ) -> Result<SkillLifecycleView, SkillApiError>;

    async fn get_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillView, SkillApiError>;

    async fn update_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        body: SkillUpdatePayload,
    ) -> Result<SkillView, SkillApiError>;

    async fn delete_skill(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<(), SkillApiError>;

    async fn update_status(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        status: &str,
    ) -> Result<SkillView, SkillApiError>;

    async fn get_content(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillContentView, SkillApiError>;

    async fn update_content(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        body: SkillContentUpdatePayload,
    ) -> Result<SkillView, SkillApiError>;

    async fn list_versions(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<SkillVersionListView, SkillApiError>;

    async fn get_version(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        version_number: i32,
    ) -> Result<SkillVersionDetailView, SkillApiError>;

    async fn rollback(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
        body: SkillRollbackPayload,
    ) -> Result<SkillView, SkillApiError>;

    async fn export_package(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillPackageView, SkillApiError>;

    async fn get_evolution_config(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<SkillEvolutionConfigView, SkillApiError>;

    async fn update_evolution_config(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: SkillEvolutionConfigUpdatePayload,
    ) -> Result<SkillEvolutionConfigView, SkillApiError>;

    async fn get_evolution_overview(
        &self,
        user_id: &str,
        query: SkillEvolutionOverviewQuery,
    ) -> Result<SkillEvolutionOverviewView, SkillApiError>;

    async fn get_evolution_detail(
        &self,
        user_id: &str,
        query: SkillEvolutionDetailQuery,
        skill_id: &str,
    ) -> Result<SkillEvolutionDetailView, SkillApiError>;

    async fn run_tenant_evolution(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<SkillEvolutionTenantRunView, SkillApiError>;

    async fn run_skill_evolution(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        skill_id: &str,
    ) -> Result<SkillEvolutionRunView, SkillApiError>;

    async fn apply_evolution_job(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        job_id: &str,
    ) -> Result<SkillEvolutionJobView, SkillApiError>;

    async fn reject_evolution_job(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        job_id: &str,
    ) -> Result<SkillEvolutionJobView, SkillApiError>;
}
