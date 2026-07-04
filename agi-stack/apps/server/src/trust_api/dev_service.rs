use std::{collections::HashMap, sync::Mutex};

use async_trait::async_trait;
use chrono::Utc;

use agistack_adapters_postgres::{DecisionRecordRecord, TrustPolicyRecord};
use agistack_adapters_secrets::generate_uuid_v4;

use super::views::{
    ApprovalRequestCreatePayload, ApprovalResolvePayload, DecisionRecordGetQuery,
    DecisionRecordListQuery, DecisionRecordListView, DecisionRecordView, TrustCheckQuery,
    TrustCheckView, TrustPolicyCreatePayload, TrustPolicyListQuery, TrustPolicyListView,
    TrustPolicyView,
};
use super::{approval_not_found, TrustError, TrustService};

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
        policies.sort_by_key(|policy| std::cmp::Reverse(policy.created_at));
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
        records.sort_by_key(|record| std::cmp::Reverse(record.created_at));
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
