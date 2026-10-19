//! Persisted resource ancestry and membership for direct-listener feature admission.

use agistack_plugin_host::ScopeV2;
use async_trait::async_trait;
use sqlx::PgPool;

use crate::{
    feature_configuration_v2::{read_accepted_configuration, AcceptedFeatureConfigurationV2},
    feature_operation_v2::FeatureAdmissionErrorV2,
};

#[derive(Clone, Debug, Default, sqlx::FromRow)]
pub(crate) struct ScopeIdentifiersV2 {
    pub(crate) tenant_id: Option<String>,
    pub(crate) project_id: Option<String>,
}

#[async_trait]
pub(crate) trait FeatureOperationRepositoryV2: Send + Sync {
    async fn support_tenants(
        &self,
        user_id: &str,
        status: Option<&str>,
    ) -> Result<Vec<Option<String>>, FeatureAdmissionErrorV2>;
    async fn resource_scope(
        &self,
        kind: &str,
        id: &str,
    ) -> Result<Option<ScopeIdentifiersV2>, FeatureAdmissionErrorV2>;
    async fn default_tenant(
        &self,
        user_id: &str,
    ) -> Result<Option<String>, FeatureAdmissionErrorV2>;
    async fn accessible_projects(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<Vec<ScopeIdentifiersV2>, FeatureAdmissionErrorV2>;
    async fn authorize(
        &self,
        user_id: &str,
        scope: &ScopeV2,
    ) -> Result<bool, FeatureAdmissionErrorV2>;
    async fn accepted(
        &self,
        scope: &ScopeV2,
    ) -> Result<AcceptedFeatureConfigurationV2, FeatureAdmissionErrorV2>;
}

pub(crate) struct PgFeatureOperationRepositoryV2(pub(crate) PgPool);

#[async_trait]
impl FeatureOperationRepositoryV2 for PgFeatureOperationRepositoryV2 {
    async fn support_tenants(
        &self,
        user_id: &str,
        status: Option<&str>,
    ) -> Result<Vec<Option<String>>, FeatureAdmissionErrorV2> {
        sqlx::query_scalar("SELECT DISTINCT tenant_id FROM support_tickets WHERE user_id = $1 AND ($2::text IS NULL OR status = $2) ORDER BY tenant_id")
            .bind(user_id).bind(status).fetch_all(&self.0).await.map_err(|_| FeatureAdmissionErrorV2::unavailable())
    }
    async fn resource_scope(
        &self,
        kind: &str,
        id: &str,
    ) -> Result<Option<ScopeIdentifiersV2>, FeatureAdmissionErrorV2> {
        let query = match kind {
            "project" => "SELECT tenant_id, id AS project_id FROM projects WHERE id = $1",
            "memory" => "SELECT p.tenant_id, m.project_id FROM memories m JOIN projects p ON p.id = m.project_id WHERE m.id = $1",
            "conversation" => "SELECT tenant_id, project_id FROM conversations WHERE id = $1",
            "skill" => "SELECT tenant_id, project_id FROM skills WHERE id = $1 AND scope <> 'system'",
            "instance" => "SELECT tenant_id, NULL::text AS project_id FROM instances WHERE id = $1",
            "deploy" => "SELECT i.tenant_id, NULL::text AS project_id FROM deploy_records d JOIN instances i ON i.id = d.instance_id WHERE d.id = $1",
            "cron" => "SELECT tenant_id, project_id FROM cron_jobs WHERE id = $1",
            "channel" => "SELECT p.tenant_id, c.project_id FROM channel_configs c JOIN projects p ON p.id = c.project_id WHERE c.id = $1",
            "webhook" => "SELECT tenant_id, NULL::text AS project_id FROM webhooks WHERE id = $1",
            "support_ticket" => "SELECT tenant_id, NULL::text AS project_id FROM support_tickets WHERE id = $1",
            "skill_evolution" => "SELECT tenant_id, project_id FROM skill_evolution_jobs WHERE id = $1",
            _ => return Err(FeatureAdmissionErrorV2::unavailable()),
        };
        sqlx::query_as(query)
            .bind(id)
            .fetch_optional(&self.0)
            .await
            .map_err(|_| FeatureAdmissionErrorV2::unavailable())
    }

    async fn default_tenant(
        &self,
        user_id: &str,
    ) -> Result<Option<String>, FeatureAdmissionErrorV2> {
        sqlx::query_scalar("SELECT tenant_id FROM user_tenants WHERE user_id = $1 ORDER BY created_at ASC, id ASC LIMIT 1")
            .bind(user_id).fetch_optional(&self.0).await.map_err(|_| FeatureAdmissionErrorV2::unavailable())
    }

    async fn accessible_projects(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<Vec<ScopeIdentifiersV2>, FeatureAdmissionErrorV2> {
        sqlx::query_as("SELECT p.tenant_id, p.id AS project_id FROM projects p WHERE ($2::text IS NULL OR p.tenant_id = $2) AND (EXISTS(SELECT 1 FROM users u WHERE u.id = $1 AND u.is_superuser = TRUE) OR EXISTS(SELECT 1 FROM user_projects up WHERE up.user_id = $1 AND up.project_id = p.id)) ORDER BY p.id")
            .bind(user_id).bind(tenant_id).fetch_all(&self.0).await.map_err(|_| FeatureAdmissionErrorV2::unavailable())
    }

    async fn authorize(
        &self,
        user_id: &str,
        scope: &ScopeV2,
    ) -> Result<bool, FeatureAdmissionErrorV2> {
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM tenants t WHERE t.id = $2 AND (EXISTS(SELECT 1 FROM users u WHERE u.id = $1 AND u.is_superuser = TRUE) OR EXISTS(SELECT 1 FROM user_tenants ut WHERE ut.user_id = $1 AND ut.tenant_id = t.id)) AND ($3::text IS NULL OR EXISTS(SELECT 1 FROM projects p JOIN user_projects up ON up.project_id = p.id AND up.user_id = $1 WHERE p.id = $3 AND p.tenant_id = t.id)))")
            .bind(user_id).bind(&scope.tenant_id).bind(&scope.project_id)
            .fetch_one(&self.0).await.map_err(|_| FeatureAdmissionErrorV2::unavailable())
    }

    async fn accepted(
        &self,
        scope: &ScopeV2,
    ) -> Result<AcceptedFeatureConfigurationV2, FeatureAdmissionErrorV2> {
        read_accepted_configuration(&self.0, scope).await
    }
}
