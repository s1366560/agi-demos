use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use agistack_adapters_postgres::{DecisionRecordRecord, TrustPolicyRecord};

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct TrustPolicyListQuery {
    pub(super) workspace_id: String,
    #[serde(default)]
    pub(super) agent_instance_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct TrustPolicyCreatePayload {
    pub(super) workspace_id: String,
    pub(super) agent_instance_id: String,
    pub(super) action_type: String,
    pub(super) grant_type: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct TrustCheckQuery {
    pub(super) workspace_id: String,
    pub(super) agent_instance_id: String,
    pub(super) action_type: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ApprovalRequestCreatePayload {
    pub(super) workspace_id: String,
    pub(super) agent_instance_id: String,
    pub(super) action_type: String,
    #[serde(default = "empty_object")]
    pub(super) proposal: Value,
    #[serde(default)]
    pub(super) context_summary: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ApprovalResolvePayload {
    pub(super) decision: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct DecisionRecordListQuery {
    pub(super) workspace_id: String,
    #[serde(default)]
    pub(super) agent_id: Option<String>,
    #[serde(default)]
    pub(super) decision_type: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct DecisionRecordGetQuery {
    pub(super) workspace_id: String,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct TrustPolicyView {
    pub(super) id: String,
    pub(super) tenant_id: String,
    pub(super) workspace_id: String,
    pub(super) agent_instance_id: String,
    pub(super) action_type: String,
    pub(super) granted_by: String,
    pub(super) grant_type: String,
    pub(super) created_at: String,
    pub(super) deleted_at: Option<String>,
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
    pub(super) items: Vec<TrustPolicyView>,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct TrustCheckView {
    pub(super) trusted: bool,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct DecisionRecordView {
    pub(super) id: String,
    pub(super) tenant_id: String,
    pub(super) workspace_id: String,
    pub(super) agent_instance_id: String,
    pub(super) decision_type: String,
    pub(super) context_summary: Option<String>,
    pub(super) proposal: Value,
    pub(super) outcome: String,
    pub(super) reviewer_id: Option<String>,
    pub(super) review_type: Option<String>,
    pub(super) review_comment: Option<String>,
    pub(super) resolved_at: Option<String>,
    pub(super) created_at: String,
    pub(super) updated_at: Option<String>,
    pub(super) deleted_at: Option<String>,
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
    pub(super) items: Vec<DecisionRecordView>,
}

fn empty_object() -> Value {
    json!({})
}

fn iso8601(dt: DateTime<Utc>) -> String {
    dt.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}
