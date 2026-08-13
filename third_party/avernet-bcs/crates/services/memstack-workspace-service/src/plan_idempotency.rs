//! Canonical Workspace Plan request identities and deterministic record IDs.

use serde_json::json;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::canonical_json;
use crate::{PublicWorkspacePlanActionInput, PublicWorkspacePlanError};

const PLAN_ID_NAMESPACE: Uuid = Uuid::from_u128(0x36c4_6d7f_d2e9_4b9e_9f03_e287_531b_88d9);

pub(super) fn action_idempotency_key(
    input: &PublicWorkspacePlanActionInput,
    revision: u64,
    node_id: Option<&str>,
) -> String {
    input.idempotency_key.clone().unwrap_or_else(|| {
        deterministic_id(
            "plan-action",
            &format!(
                "{}:{}:{}:{}:{}",
                input.context.actor_id,
                input.action.as_str(),
                revision,
                node_id.unwrap_or(""),
                input.outbox_id.as_deref().unwrap_or("")
            ),
        )
    })
}

pub(super) fn action_request_hash(
    input: &PublicWorkspacePlanActionInput,
    plan_id: &str,
) -> Result<String, PublicWorkspacePlanError> {
    let payload = canonical_json(&json!({
        "action": input.action.as_str(),
        "tenant_id": &input.context.tenant_id,
        "project_id": &input.context.project_id,
        "workspace_id": &input.context.workspace_id,
        "actor_id": &input.context.actor_id,
        "plan_id": plan_id,
        "node_id": &input.node_id,
        "outbox_id": &input.outbox_id,
        "reason": &input.reason,
        "evidence_refs": &input.evidence_refs,
        "expected_revision": input.expected_revision,
    }));
    let bytes = serde_json::to_vec(&payload).map_err(PublicWorkspacePlanError::Json)?;
    Ok(hex::encode(Sha256::digest(bytes)))
}

pub(super) struct TransitionIds {
    pub(super) outbox_id: String,
    pub(super) compatibility_outbox_id: String,
    pub(super) event_id: String,
    pub(super) audit_id: String,
}

pub(super) fn transition_ids(workspace_id: &str, idempotency_key: &str) -> TransitionIds {
    let seed = format!("{workspace_id}:{idempotency_key}");
    TransitionIds {
        outbox_id: deterministic_id("outbox", &seed),
        compatibility_outbox_id: deterministic_id("compatibility-outbox", &seed),
        event_id: deterministic_id("event", &seed),
        audit_id: deterministic_id("audit", &seed),
    }
}

pub(super) fn deterministic_id(prefix: &str, seed: &str) -> String {
    let value = Uuid::new_v5(&PLAN_ID_NAMESPACE, format!("{prefix}:{seed}").as_bytes());
    format!("{prefix}-{value}")
}
