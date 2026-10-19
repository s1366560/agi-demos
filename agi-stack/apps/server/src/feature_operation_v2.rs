//! Admit declared new operations using current accepted scope configuration.

use std::{collections::BTreeMap, sync::Arc};

use agistack_plugin_host::{ScopeKindV2, ScopeV2};
use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;
use sqlx::PgPool;

use crate::{
    feature_configuration_v2::{feature_entries, require_enabled, AcceptedFeatureConfigurationV2},
    feature_operation_owners_v2::FeatureOperationOwnerV2,
    feature_operation_repository_v2::{
        FeatureOperationRepositoryV2, PgFeatureOperationRepositoryV2, ScopeIdentifiersV2,
    },
};

#[derive(Clone, Debug)]
pub(crate) struct FeatureAdmissionErrorV2 {
    pub(crate) code: &'static str,
    pub(crate) status: StatusCode,
}

impl FeatureAdmissionErrorV2 {
    pub(crate) const fn unavailable() -> Self {
        Self {
            code: "feature_configuration_unavailable",
            status: StatusCode::SERVICE_UNAVAILABLE,
        }
    }
    pub(crate) const fn disabled() -> Self {
        Self {
            code: "feature_disabled",
            status: StatusCode::FORBIDDEN,
        }
    }
    pub(crate) const fn forbidden() -> Self {
        Self {
            code: "scope_read_forbidden",
            status: StatusCode::FORBIDDEN,
        }
    }
    pub(crate) const fn scope_mismatch() -> Self {
        Self {
            code: "scope_resource_unavailable",
            status: StatusCode::NOT_FOUND,
        }
    }
    pub(crate) const fn invalid() -> Self {
        Self {
            code: "feature_scope_invalid",
            status: StatusCode::BAD_REQUEST,
        }
    }
}

impl IntoResponse for FeatureAdmissionErrorV2 {
    fn into_response(self) -> Response {
        (self.status, Json(json!({"detail":{"code":self.code,"message":"This feature is unavailable in the current scope"}}))).into_response()
    }
}

#[derive(Clone, Default)]
pub(crate) struct FeatureOperationAdmissionV2 {
    repository: Option<Arc<dyn FeatureOperationRepositoryV2>>,
}

impl FeatureOperationAdmissionV2 {
    pub(crate) fn from_pool(pool: Option<PgPool>) -> Self {
        Self {
            repository: pool.map(|pool| {
                Arc::new(PgFeatureOperationRepositoryV2(pool))
                    as Arc<dyn FeatureOperationRepositoryV2>
            }),
        }
    }

    pub(crate) async fn admit(
        &self,
        user_id: &str,
        owner: &FeatureOperationOwnerV2,
        arguments: &BTreeMap<String, String>,
        features: &[&str],
    ) -> Result<(), FeatureAdmissionErrorV2> {
        let Some(repository) = self.repository.as_ref() else {
            // Offline/dev state has no scope store; it uses the declared bundled default.
            return require_enabled(&bootstrap_entries()?, features);
        };
        let scopes = resolve_scopes(repository.as_ref(), user_id, owner, arguments).await?;
        for scope in scopes {
            self.admit_scope(user_id, &scope, features).await?;
        }
        Ok(())
    }

    pub(crate) async fn admit_project(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        features: &[&str],
    ) -> Result<(), FeatureAdmissionErrorV2> {
        self.admit_scope(
            user_id,
            &ScopeV2 {
                kind: ScopeKindV2::Project,
                tenant_id: Some(tenant_id.into()),
                project_id: Some(project_id.into()),
                session_id: None,
            },
            features,
        )
        .await
    }

    async fn admit_scope(
        &self,
        user_id: &str,
        scope: &ScopeV2,
        features: &[&str],
    ) -> Result<(), FeatureAdmissionErrorV2> {
        let Some(repository) = self.repository.as_ref() else {
            return require_enabled(&bootstrap_entries()?, features);
        };
        if !repository.authorize(user_id, scope).await? {
            return Err(FeatureAdmissionErrorV2::forbidden());
        }
        match repository.accepted(scope).await? {
            AcceptedFeatureConfigurationV2::Standalone => {
                require_enabled(&bootstrap_entries()?, features)
            }
            accepted => require_enabled(&feature_entries(accepted, scope)?, features),
        }
    }
}

fn bootstrap_entries() -> Result<
    BTreeMap<String, agistack_plugin_host::protocol_v2::ProfileEntryV2>,
    FeatureAdmissionErrorV2,
> {
    let snapshot = serde_json::from_str(include_str!(
        "../../../../shared/profiles/memstack-default-bootstrap.v2.json"
    ))
    .map_err(|_| FeatureAdmissionErrorV2::unavailable())?;
    feature_entries(
        AcceptedFeatureConfigurationV2::Snapshot(snapshot),
        &ScopeV2 {
            kind: ScopeKindV2::Root,
            tenant_id: None,
            project_id: None,
            session_id: None,
        },
    )
}

fn merge(
    current: &mut Option<String>,
    candidate: Option<&str>,
) -> Result<(), FeatureAdmissionErrorV2> {
    if let Some(candidate) = candidate {
        if candidate.is_empty() || current.as_deref().is_some_and(|value| value != candidate) {
            return Err(FeatureAdmissionErrorV2::scope_mismatch());
        }
        *current = Some(candidate.to_owned());
    }
    Ok(())
}

async fn resolve_scopes(
    repository: &dyn FeatureOperationRepositoryV2,
    user_id: &str,
    owner: &FeatureOperationOwnerV2,
    arguments: &BTreeMap<String, String>,
) -> Result<Vec<ScopeV2>, FeatureAdmissionErrorV2> {
    let mut tenant_id = arguments.get("tenant_id").cloned();
    let mut project_id = arguments.get("project_id").cloned();
    let requested_tenant = tenant_id.clone();
    for resource in owner.resources {
        if let Some(id) = arguments.get(resource.parameter) {
            if matches!(resource.kind, "graph_entity" | "graph_community") {
                // Rust GraphStore methods always bind both project and resource ID.
                if project_id.is_none() {
                    return Err(FeatureAdmissionErrorV2::invalid());
                }
                continue;
            }
            if let Some(scope) = repository.resource_scope(resource.kind, id).await? {
                merge(&mut tenant_id, scope.tenant_id.as_deref())?;
                merge(&mut project_id, scope.project_id.as_deref())?;
            }
        }
    }
    if let Some(project) = project_id.as_deref() {
        let actual = repository
            .resource_scope("project", project)
            .await?
            .ok_or_else(FeatureAdmissionErrorV2::scope_mismatch)?;
        merge(&mut tenant_id, actual.tenant_id.as_deref())?;
        return Ok(vec![ScopeV2 {
            kind: ScopeKindV2::Project,
            tenant_id,
            project_id,
            session_id: None,
        }]);
    }
    if owner.project_aggregate {
        let projects = repository
            .accessible_projects(user_id, requested_tenant.as_deref())
            .await?;
        if !projects.is_empty() {
            return projects.into_iter().map(project_scope).collect();
        }
    }
    if owner.support_tenant_aggregate && tenant_id.is_none() {
        let tenants = repository
            .support_tenants(user_id, arguments.get("support_status").map(String::as_str))
            .await?;
        if !tenants.is_empty() {
            let default_tenant = if tenants.contains(&None) {
                Some(
                    repository
                        .default_tenant(user_id)
                        .await?
                        .ok_or_else(FeatureAdmissionErrorV2::forbidden)?,
                )
            } else {
                None
            };
            return Ok(tenants
                .into_iter()
                .map(|tenant_id| ScopeV2 {
                    kind: ScopeKindV2::Tenant,
                    tenant_id: tenant_id.or_else(|| default_tenant.clone()),
                    project_id: None,
                    session_id: None,
                })
                .collect());
        }
    }
    if tenant_id.is_none() {
        tenant_id = repository.default_tenant(user_id).await?;
    }
    if tenant_id.is_none() {
        return Err(FeatureAdmissionErrorV2::forbidden());
    }
    Ok(vec![ScopeV2 {
        kind: ScopeKindV2::Tenant,
        tenant_id,
        project_id: None,
        session_id: None,
    }])
}

fn project_scope(ids: ScopeIdentifiersV2) -> Result<ScopeV2, FeatureAdmissionErrorV2> {
    if ids.tenant_id.is_none() || ids.project_id.is_none() {
        return Err(FeatureAdmissionErrorV2::unavailable());
    }
    Ok(ScopeV2 {
        kind: ScopeKindV2::Project,
        tenant_id: ids.tenant_id,
        project_id: ids.project_id,
        session_id: None,
    })
}

#[cfg(test)]
#[path = "feature_operation_v2_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "feature_operation_live_tests.rs"]
mod live_tests;
