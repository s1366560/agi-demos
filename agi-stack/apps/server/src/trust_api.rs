//! P2 trust governance endpoints.
//!
//! These routes mirror `routers/trust.py`: tenant/workspace-scoped trust
//! policies, approval requests, and decision records. Persistence stays behind
//! a server-only service so the portable core remains wasm-clean.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Json, Router,
};
use chrono::Utc;
use serde_json::json;

use agistack_adapters_postgres::{
    NewDecisionRecordRecord, NewTrustPolicyRecord, PgTrustRepository, TenantAccessStatus,
    TrustDecisionResolution,
};
use agistack_adapters_secrets::generate_uuid_v4;

use crate::{auth::Identity, AppState};

mod dev_service;
#[cfg(test)]
mod tests;
mod views;

pub(crate) use dev_service::DevTrustService;
use views::*;

pub(crate) type SharedTrust = Arc<dyn TrustService>;

#[async_trait]
pub(crate) trait TrustService: Send + Sync {
    async fn list_policies(
        &self,
        tenant_id: &str,
        user_id: &str,
        query: TrustPolicyListQuery,
    ) -> Result<TrustPolicyListView, TrustError>;

    async fn create_policy(
        &self,
        tenant_id: &str,
        user_id: &str,
        body: TrustPolicyCreatePayload,
    ) -> Result<TrustPolicyView, TrustError>;

    async fn check_trust(
        &self,
        tenant_id: &str,
        user_id: &str,
        query: TrustCheckQuery,
    ) -> Result<TrustCheckView, TrustError>;

    async fn submit_approval(
        &self,
        tenant_id: &str,
        user_id: &str,
        body: ApprovalRequestCreatePayload,
    ) -> Result<DecisionRecordView, TrustError>;

    async fn resolve_approval(
        &self,
        tenant_id: &str,
        user_id: &str,
        record_id: &str,
        body: ApprovalResolvePayload,
    ) -> Result<DecisionRecordView, TrustError>;

    async fn list_decisions(
        &self,
        tenant_id: &str,
        user_id: &str,
        query: DecisionRecordListQuery,
    ) -> Result<DecisionRecordListView, TrustError>;

    async fn get_decision(
        &self,
        tenant_id: &str,
        user_id: &str,
        record_id: &str,
        query: DecisionRecordGetQuery,
    ) -> Result<DecisionRecordView, TrustError>;
}

#[derive(Debug)]
pub(crate) struct TrustError {
    status: StatusCode,
    detail: String,
}

impl TrustError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for TrustError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

pub(crate) struct PgTrustService {
    repo: PgTrustRepository,
}

impl PgTrustService {
    pub(crate) fn new(repo: PgTrustRepository) -> Self {
        Self { repo }
    }

    async fn require_tenant_access(
        &self,
        user_id: &str,
        tenant_id: &str,
        require_admin: bool,
    ) -> Result<(), TrustError> {
        match self
            .repo
            .tenant_access_status(user_id, tenant_id, require_admin)
            .await
            .map_err(TrustError::internal)?
        {
            TenantAccessStatus::Authorized => Ok(()),
            TenantAccessStatus::TenantNotFound => Err(TrustError::not_found("Tenant not found")),
            TenantAccessStatus::NotMember => Err(TrustError::forbidden("Tenant access required")),
            TenantAccessStatus::NotAdmin => Err(TrustError::forbidden("Admin access required")),
        }
    }

    async fn require_workspace(
        &self,
        tenant_id: &str,
        workspace_id: &str,
    ) -> Result<(), TrustError> {
        if self
            .repo
            .workspace_exists_in_tenant(tenant_id, workspace_id)
            .await
            .map_err(TrustError::internal)?
        {
            Ok(())
        } else {
            Err(TrustError::not_found("Workspace not found"))
        }
    }
}

#[async_trait]
impl TrustService for PgTrustService {
    async fn list_policies(
        &self,
        tenant_id: &str,
        user_id: &str,
        query: TrustPolicyListQuery,
    ) -> Result<TrustPolicyListView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, false)
            .await?;
        self.require_workspace(tenant_id, &query.workspace_id)
            .await?;
        let items = self
            .repo
            .list_policies(&query.workspace_id, query.agent_instance_id.as_deref())
            .await
            .map_err(TrustError::internal)?
            .into_iter()
            .map(TrustPolicyView::from)
            .collect();
        Ok(TrustPolicyListView { items })
    }

    async fn create_policy(
        &self,
        tenant_id: &str,
        user_id: &str,
        body: TrustPolicyCreatePayload,
    ) -> Result<TrustPolicyView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, true).await?;
        self.require_workspace(tenant_id, &body.workspace_id)
            .await?;
        self.repo
            .create_policy(NewTrustPolicyRecord {
                id: generate_uuid_v4(),
                tenant_id: tenant_id.to_string(),
                workspace_id: body.workspace_id,
                agent_instance_id: body.agent_instance_id,
                action_type: body.action_type,
                granted_by: user_id.to_string(),
                grant_type: body.grant_type,
                created_at: Utc::now(),
            })
            .await
            .map(TrustPolicyView::from)
            .map_err(TrustError::internal)
    }

    async fn check_trust(
        &self,
        tenant_id: &str,
        user_id: &str,
        query: TrustCheckQuery,
    ) -> Result<TrustCheckView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, false)
            .await?;
        self.require_workspace(tenant_id, &query.workspace_id)
            .await?;
        let trusted = self
            .repo
            .check_always_trust(
                &query.workspace_id,
                &query.agent_instance_id,
                &query.action_type,
            )
            .await
            .map_err(TrustError::internal)?;
        Ok(TrustCheckView { trusted })
    }

    async fn submit_approval(
        &self,
        tenant_id: &str,
        user_id: &str,
        body: ApprovalRequestCreatePayload,
    ) -> Result<DecisionRecordView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, false)
            .await?;
        self.require_workspace(tenant_id, &body.workspace_id)
            .await?;
        self.repo
            .create_decision(NewDecisionRecordRecord {
                id: generate_uuid_v4(),
                tenant_id: tenant_id.to_string(),
                workspace_id: body.workspace_id,
                agent_instance_id: body.agent_instance_id,
                decision_type: body.action_type,
                context_summary: body.context_summary,
                proposal: body.proposal,
                outcome: "pending".to_string(),
                created_at: Utc::now(),
            })
            .await
            .map(DecisionRecordView::from)
            .map_err(TrustError::internal)
    }

    async fn resolve_approval(
        &self,
        tenant_id: &str,
        user_id: &str,
        record_id: &str,
        body: ApprovalResolvePayload,
    ) -> Result<DecisionRecordView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, true).await?;
        let record = self
            .repo
            .find_decision(record_id)
            .await
            .map_err(TrustError::internal)?
            .filter(|record| record.tenant_id == tenant_id)
            .ok_or_else(approval_not_found)?;

        let now = Utc::now();
        let (outcome, review_comment, new_policy) = match body.decision.as_str() {
            "allow_once" => ("success", "Allowed once", None),
            "allow_always" => (
                "success",
                "Allowed always — trust policy created",
                Some(NewTrustPolicyRecord {
                    id: generate_uuid_v4(),
                    tenant_id: record.tenant_id.clone(),
                    workspace_id: record.workspace_id.clone(),
                    agent_instance_id: record.agent_instance_id.clone(),
                    action_type: record.decision_type.clone(),
                    granted_by: user_id.to_string(),
                    grant_type: "always".to_string(),
                    created_at: now,
                }),
            ),
            "deny" => ("rejected", "Denied by reviewer", None),
            _ => return Err(approval_not_found()),
        };

        self.repo
            .resolve_decision(TrustDecisionResolution {
                record_id,
                reviewer_id: user_id,
                review_type: "human",
                review_comment,
                outcome,
                resolved_at: now,
                new_policy,
            })
            .await
            .map_err(TrustError::internal)?
            .map(DecisionRecordView::from)
            .ok_or_else(approval_not_found)
    }

    async fn list_decisions(
        &self,
        tenant_id: &str,
        user_id: &str,
        query: DecisionRecordListQuery,
    ) -> Result<DecisionRecordListView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, false)
            .await?;
        self.require_workspace(tenant_id, &query.workspace_id)
            .await?;
        let items = self
            .repo
            .list_decisions(
                &query.workspace_id,
                query.agent_id.as_deref(),
                query.decision_type.as_deref(),
            )
            .await
            .map_err(TrustError::internal)?
            .into_iter()
            .map(DecisionRecordView::from)
            .collect();
        Ok(DecisionRecordListView { items })
    }

    async fn get_decision(
        &self,
        tenant_id: &str,
        user_id: &str,
        record_id: &str,
        query: DecisionRecordGetQuery,
    ) -> Result<DecisionRecordView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, false)
            .await?;
        self.require_workspace(tenant_id, &query.workspace_id)
            .await?;
        let record = self
            .repo
            .find_decision(record_id)
            .await
            .map_err(TrustError::internal)?
            .filter(|record| {
                record.tenant_id == tenant_id && record.workspace_id == query.workspace_id
            })
            .ok_or_else(|| TrustError::not_found("Decision record not found"))?;
        Ok(DecisionRecordView::from(record))
    }
}

fn approval_not_found() -> TrustError {
    TrustError::not_found("Approval request not found")
}

async fn list_policies(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Query(query): Query<TrustPolicyListQuery>,
) -> Result<Json<TrustPolicyListView>, TrustError> {
    app.trust
        .list_policies(&tenant_id, &identity.user_id, query)
        .await
        .map(Json)
}

async fn create_policy(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Json(body): Json<TrustPolicyCreatePayload>,
) -> Result<impl IntoResponse, TrustError> {
    let view = app
        .trust
        .create_policy(&tenant_id, &identity.user_id, body)
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn check_trust(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Query(query): Query<TrustCheckQuery>,
) -> Result<Json<TrustCheckView>, TrustError> {
    app.trust
        .check_trust(&tenant_id, &identity.user_id, query)
        .await
        .map(Json)
}

async fn submit_approval(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Json(body): Json<ApprovalRequestCreatePayload>,
) -> Result<impl IntoResponse, TrustError> {
    let view = app
        .trust
        .submit_approval(&tenant_id, &identity.user_id, body)
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn resolve_approval(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, record_id)): Path<(String, String)>,
    Json(body): Json<ApprovalResolvePayload>,
) -> Result<Json<DecisionRecordView>, TrustError> {
    app.trust
        .resolve_approval(&tenant_id, &identity.user_id, &record_id, body)
        .await
        .map(Json)
}

async fn list_decisions(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Query(query): Query<DecisionRecordListQuery>,
) -> Result<Json<DecisionRecordListView>, TrustError> {
    app.trust
        .list_decisions(&tenant_id, &identity.user_id, query)
        .await
        .map(Json)
}

async fn get_decision(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, record_id)): Path<(String, String)>,
    Query(query): Query<DecisionRecordGetQuery>,
) -> Result<Json<DecisionRecordView>, TrustError> {
    app.trust
        .get_decision(&tenant_id, &identity.user_id, &record_id, query)
        .await
        .map(Json)
}

pub(crate) fn router_authed() -> Router<AppState> {
    Router::new()
        .route(
            "/api/v1/tenants/:tenant_id/trust/policies",
            get(list_policies).post(create_policy),
        )
        .route(
            "/api/v1/tenants/:tenant_id/trust/policies/check",
            get(check_trust),
        )
        .route(
            "/api/v1/tenants/:tenant_id/trust/approval-requests",
            post(submit_approval),
        )
        .route(
            "/api/v1/tenants/:tenant_id/trust/approval-requests/:record_id/resolve",
            post(resolve_approval),
        )
        .route(
            "/api/v1/tenants/:tenant_id/trust/decision-records",
            get(list_decisions),
        )
        .route(
            "/api/v1/tenants/:tenant_id/trust/decision-records/:record_id",
            get(get_decision),
        )
}
