//! P2 trust governance endpoints.
//!
//! These routes mirror `routers/trust.py`: tenant/workspace-scoped trust
//! policies, approval requests, and decision records. Persistence stays behind
//! a server-only service so the portable core remains wasm-clean.

use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Json, Router,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use agistack_adapters_postgres::{
    DecisionRecordRecord, NewDecisionRecordRecord, NewTrustPolicyRecord, PgTrustRepository,
    TenantAccessStatus, TrustDecisionResolution, TrustPolicyRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;

use crate::{auth::Identity, AppState};

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

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct TrustPolicyListQuery {
    workspace_id: String,
    #[serde(default)]
    agent_instance_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct TrustPolicyCreatePayload {
    workspace_id: String,
    agent_instance_id: String,
    action_type: String,
    grant_type: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct TrustCheckQuery {
    workspace_id: String,
    agent_instance_id: String,
    action_type: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ApprovalRequestCreatePayload {
    workspace_id: String,
    agent_instance_id: String,
    action_type: String,
    #[serde(default = "empty_object")]
    proposal: Value,
    #[serde(default)]
    context_summary: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ApprovalResolvePayload {
    decision: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct DecisionRecordListQuery {
    workspace_id: String,
    #[serde(default)]
    agent_id: Option<String>,
    #[serde(default)]
    decision_type: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct DecisionRecordGetQuery {
    workspace_id: String,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct TrustPolicyView {
    id: String,
    tenant_id: String,
    workspace_id: String,
    agent_instance_id: String,
    action_type: String,
    granted_by: String,
    grant_type: String,
    created_at: String,
    deleted_at: Option<String>,
}

impl From<TrustPolicyRecord> for TrustPolicyView {
    fn from(record: TrustPolicyRecord) -> Self {
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            workspace_id: record.workspace_id,
            agent_instance_id: record.agent_instance_id,
            action_type: record.action_type,
            granted_by: record.granted_by,
            grant_type: record.grant_type,
            created_at: iso8601(record.created_at),
            deleted_at: record.deleted_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct TrustPolicyListView {
    items: Vec<TrustPolicyView>,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct TrustCheckView {
    trusted: bool,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct DecisionRecordView {
    id: String,
    tenant_id: String,
    workspace_id: String,
    agent_instance_id: String,
    decision_type: String,
    context_summary: Option<String>,
    proposal: Value,
    outcome: String,
    reviewer_id: Option<String>,
    review_type: Option<String>,
    review_comment: Option<String>,
    resolved_at: Option<String>,
    created_at: String,
    updated_at: Option<String>,
    deleted_at: Option<String>,
}

impl From<DecisionRecordRecord> for DecisionRecordView {
    fn from(record: DecisionRecordRecord) -> Self {
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            workspace_id: record.workspace_id,
            agent_instance_id: record.agent_instance_id,
            decision_type: record.decision_type,
            context_summary: record.context_summary,
            proposal: record.proposal,
            outcome: record.outcome,
            reviewer_id: record.reviewer_id,
            review_type: record.review_type,
            review_comment: record.review_comment,
            resolved_at: record.resolved_at.map(iso8601),
            created_at: iso8601(record.created_at),
            updated_at: record.updated_at.map(iso8601),
            deleted_at: record.deleted_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct DecisionRecordListView {
    items: Vec<DecisionRecordView>,
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

pub(crate) struct DevTrustService {
    dev_user_id: String,
    policies: Mutex<Vec<TrustPolicyRecord>>,
    decisions: Mutex<HashMap<String, DecisionRecordRecord>>,
}

impl DevTrustService {
    pub(crate) fn new(dev_user_id: impl Into<String>) -> Self {
        Self {
            dev_user_id: dev_user_id.into(),
            policies: Mutex::new(Vec::new()),
            decisions: Mutex::new(HashMap::new()),
        }
    }

    fn require_tenant_access(
        &self,
        user_id: &str,
        tenant_id: &str,
        require_admin: bool,
    ) -> Result<(), TrustError> {
        if tenant_id != "dev-tenant" {
            return Err(TrustError::not_found("Tenant not found"));
        }
        if user_id != self.dev_user_id {
            return Err(TrustError::forbidden("Tenant access required"));
        }
        if require_admin && user_id != self.dev_user_id {
            return Err(TrustError::forbidden("Admin access required"));
        }
        Ok(())
    }

    fn require_workspace(&self, tenant_id: &str, workspace_id: &str) -> Result<(), TrustError> {
        if tenant_id == "dev-tenant" && workspace_id == "dev-workspace" {
            Ok(())
        } else {
            Err(TrustError::not_found("Workspace not found"))
        }
    }
}

#[async_trait]
impl TrustService for DevTrustService {
    async fn list_policies(
        &self,
        tenant_id: &str,
        user_id: &str,
        query: TrustPolicyListQuery,
    ) -> Result<TrustPolicyListView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, false)?;
        self.require_workspace(tenant_id, &query.workspace_id)?;
        let mut policies = self
            .policies
            .lock()
            .map_err(TrustError::internal)?
            .iter()
            .filter(|p| {
                p.workspace_id == query.workspace_id
                    && p.deleted_at.is_none()
                    && query
                        .agent_instance_id
                        .as_deref()
                        .map(|agent_id| p.agent_instance_id == agent_id)
                        .unwrap_or(true)
            })
            .cloned()
            .collect::<Vec<_>>();
        policies.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        Ok(TrustPolicyListView {
            items: policies.into_iter().map(TrustPolicyView::from).collect(),
        })
    }

    async fn create_policy(
        &self,
        tenant_id: &str,
        user_id: &str,
        body: TrustPolicyCreatePayload,
    ) -> Result<TrustPolicyView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, true)?;
        self.require_workspace(tenant_id, &body.workspace_id)?;
        let record = TrustPolicyRecord {
            id: generate_uuid_v4(),
            tenant_id: tenant_id.to_string(),
            workspace_id: body.workspace_id,
            agent_instance_id: body.agent_instance_id,
            action_type: body.action_type,
            granted_by: user_id.to_string(),
            grant_type: body.grant_type,
            created_at: Utc::now(),
            deleted_at: None,
        };
        self.policies
            .lock()
            .map_err(TrustError::internal)?
            .push(record.clone());
        Ok(TrustPolicyView::from(record))
    }

    async fn check_trust(
        &self,
        tenant_id: &str,
        user_id: &str,
        query: TrustCheckQuery,
    ) -> Result<TrustCheckView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, false)?;
        self.require_workspace(tenant_id, &query.workspace_id)?;
        let trusted = self
            .policies
            .lock()
            .map_err(TrustError::internal)?
            .iter()
            .any(|p| {
                p.workspace_id == query.workspace_id
                    && p.agent_instance_id == query.agent_instance_id
                    && p.action_type == query.action_type
                    && p.grant_type == "always"
                    && p.deleted_at.is_none()
            });
        Ok(TrustCheckView { trusted })
    }

    async fn submit_approval(
        &self,
        tenant_id: &str,
        user_id: &str,
        body: ApprovalRequestCreatePayload,
    ) -> Result<DecisionRecordView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, false)?;
        self.require_workspace(tenant_id, &body.workspace_id)?;
        let record = DecisionRecordRecord {
            id: generate_uuid_v4(),
            tenant_id: tenant_id.to_string(),
            workspace_id: body.workspace_id,
            agent_instance_id: body.agent_instance_id,
            decision_type: body.action_type,
            context_summary: body.context_summary,
            proposal: body.proposal,
            outcome: "pending".to_string(),
            reviewer_id: None,
            review_type: None,
            review_comment: None,
            resolved_at: None,
            created_at: Utc::now(),
            updated_at: None,
            deleted_at: None,
        };
        self.decisions
            .lock()
            .map_err(TrustError::internal)?
            .insert(record.id.clone(), record.clone());
        Ok(DecisionRecordView::from(record))
    }

    async fn resolve_approval(
        &self,
        tenant_id: &str,
        user_id: &str,
        record_id: &str,
        body: ApprovalResolvePayload,
    ) -> Result<DecisionRecordView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, true)?;
        let now = Utc::now();
        let mut decisions = self.decisions.lock().map_err(TrustError::internal)?;
        let record = decisions
            .get_mut(record_id)
            .filter(|record| record.tenant_id == tenant_id)
            .ok_or_else(approval_not_found)?;
        match body.decision.as_str() {
            "allow_once" => {
                record.outcome = "success".to_string();
                record.review_comment = Some("Allowed once".to_string());
            }
            "allow_always" => {
                record.outcome = "success".to_string();
                record.review_comment = Some("Allowed always — trust policy created".to_string());
                self.policies
                    .lock()
                    .map_err(TrustError::internal)?
                    .push(TrustPolicyRecord {
                        id: generate_uuid_v4(),
                        tenant_id: record.tenant_id.clone(),
                        workspace_id: record.workspace_id.clone(),
                        agent_instance_id: record.agent_instance_id.clone(),
                        action_type: record.decision_type.clone(),
                        granted_by: user_id.to_string(),
                        grant_type: "always".to_string(),
                        created_at: now,
                        deleted_at: None,
                    });
            }
            "deny" => {
                record.outcome = "rejected".to_string();
                record.review_comment = Some("Denied by reviewer".to_string());
            }
            _ => return Err(approval_not_found()),
        }
        record.reviewer_id = Some(user_id.to_string());
        record.review_type = Some("human".to_string());
        record.resolved_at = Some(now);
        record.updated_at = Some(now);
        Ok(DecisionRecordView::from(record.clone()))
    }

    async fn list_decisions(
        &self,
        tenant_id: &str,
        user_id: &str,
        query: DecisionRecordListQuery,
    ) -> Result<DecisionRecordListView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, false)?;
        self.require_workspace(tenant_id, &query.workspace_id)?;
        let mut records = self
            .decisions
            .lock()
            .map_err(TrustError::internal)?
            .values()
            .filter(|record| {
                record.workspace_id == query.workspace_id
                    && record.deleted_at.is_none()
                    && query
                        .agent_id
                        .as_deref()
                        .map(|agent_id| record.agent_instance_id == agent_id)
                        .unwrap_or(true)
                    && query
                        .decision_type
                        .as_deref()
                        .map(|decision_type| record.decision_type == decision_type)
                        .unwrap_or(true)
            })
            .cloned()
            .collect::<Vec<_>>();
        records.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        Ok(DecisionRecordListView {
            items: records.into_iter().map(DecisionRecordView::from).collect(),
        })
    }

    async fn get_decision(
        &self,
        tenant_id: &str,
        user_id: &str,
        record_id: &str,
        query: DecisionRecordGetQuery,
    ) -> Result<DecisionRecordView, TrustError> {
        self.require_tenant_access(user_id, tenant_id, false)?;
        self.require_workspace(tenant_id, &query.workspace_id)?;
        let record = self
            .decisions
            .lock()
            .map_err(TrustError::internal)?
            .get(record_id)
            .filter(|record| {
                record.tenant_id == tenant_id && record.workspace_id == query.workspace_id
            })
            .cloned()
            .ok_or_else(|| TrustError::not_found("Decision record not found"))?;
        Ok(DecisionRecordView::from(record))
    }
}

fn approval_not_found() -> TrustError {
    TrustError::not_found("Approval request not found")
}

fn empty_object() -> Value {
    json!({})
}

fn iso8601(dt: DateTime<Utc>) -> String {
    dt.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

#[cfg(test)]
fn sample_dt() -> DateTime<Utc> {
    DateTime::<Utc>::from_timestamp_millis(1_700_000_000_000).unwrap()
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

#[cfg(test)]
mod unit {
    use super::*;

    fn sample_policy() -> TrustPolicyRecord {
        TrustPolicyRecord {
            id: "11111111-1111-4111-8111-111111111111".into(),
            tenant_id: "22222222-2222-4222-8222-222222222222".into(),
            workspace_id: "33333333-3333-4333-8333-333333333333".into(),
            agent_instance_id: "44444444-4444-4444-8444-444444444444".into(),
            action_type: "terminal.execute".into(),
            granted_by: "55555555-5555-4555-8555-555555555555".into(),
            grant_type: "always".into(),
            created_at: sample_dt(),
            deleted_at: None,
        }
    }

    fn sample_decision() -> DecisionRecordRecord {
        DecisionRecordRecord {
            id: "66666666-6666-4666-8666-666666666666".into(),
            tenant_id: "22222222-2222-4222-8222-222222222222".into(),
            workspace_id: "33333333-3333-4333-8333-333333333333".into(),
            agent_instance_id: "44444444-4444-4444-8444-444444444444".into(),
            decision_type: "terminal.execute".into(),
            context_summary: Some("Agent wants to run a shell command.".into()),
            proposal: json!({"command": "cargo test", "cwd": "/workspace"}),
            outcome: "pending".into(),
            reviewer_id: None,
            review_type: None,
            review_comment: None,
            resolved_at: None,
            created_at: sample_dt(),
            updated_at: None,
            deleted_at: None,
        }
    }

    #[test]
    fn trust_policy_response_matches_golden() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/trust_policy_response.json"))
                .unwrap();
        let actual = serde_json::to_value(TrustPolicyView::from(sample_policy())).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn trust_policy_list_matches_golden() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/trust_policy_list.json")).unwrap();
        let actual = serde_json::to_value(TrustPolicyListView {
            items: vec![TrustPolicyView::from(sample_policy())],
        })
        .unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn trust_check_matches_golden() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/trust_check_response.json"))
                .unwrap();
        let actual = serde_json::to_value(TrustCheckView { trusted: true }).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn decision_record_response_matches_golden() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/decision_record_response.json"
        ))
        .unwrap();
        let actual = serde_json::to_value(DecisionRecordView::from(sample_decision())).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn decision_record_list_matches_golden() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/decision_record_list.json"))
                .unwrap();
        let actual = serde_json::to_value(DecisionRecordListView {
            items: vec![DecisionRecordView::from(sample_decision())],
        })
        .unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[tokio::test]
    async fn dev_resolve_allow_always_creates_policy_and_python_comment() {
        let svc = DevTrustService::new("dev-user");
        let created = svc
            .submit_approval(
                "dev-tenant",
                "dev-user",
                ApprovalRequestCreatePayload {
                    workspace_id: "dev-workspace".into(),
                    agent_instance_id: "agent-1".into(),
                    action_type: "terminal.execute".into(),
                    proposal: json!({}),
                    context_summary: None,
                },
            )
            .await
            .unwrap();
        let resolved = svc
            .resolve_approval(
                "dev-tenant",
                "dev-user",
                &created.id,
                ApprovalResolvePayload {
                    decision: "allow_always".into(),
                },
            )
            .await
            .unwrap();
        assert_eq!(resolved.outcome, "success");
        assert_eq!(
            resolved.review_comment.as_deref(),
            Some("Allowed always — trust policy created")
        );

        let check = svc
            .check_trust(
                "dev-tenant",
                "dev-user",
                TrustCheckQuery {
                    workspace_id: "dev-workspace".into(),
                    agent_instance_id: "agent-1".into(),
                    action_type: "terminal.execute".into(),
                },
            )
            .await
            .unwrap();
        assert!(check.trusted);
    }

    #[tokio::test]
    async fn invalid_resolve_decision_matches_python_404() {
        let svc = DevTrustService::new("dev-user");
        let err = svc
            .resolve_approval(
                "dev-tenant",
                "dev-user",
                "missing",
                ApprovalResolvePayload {
                    decision: "bogus".into(),
                },
            )
            .await
            .unwrap_err();
        assert_eq!(err.status, StatusCode::NOT_FOUND);
        assert_eq!(err.detail, "Approval request not found");
    }
}
