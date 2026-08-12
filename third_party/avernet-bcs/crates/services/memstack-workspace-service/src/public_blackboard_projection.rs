//! Blackboard validation, canonical hashing, IDs, and response projection.

use chrono::{SecondsFormat, Utc};
use memstack_workspace_store::{
    WorkspaceBlackboardPostRecord, WorkspaceBlackboardReplyRecord, WorkspaceBlackboardScope,
};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::canonical_json;

use super::{
    BLACKBOARD_STATUSES, MAX_IDEMPOTENCY_KEY_CHARS, MAX_TITLE_CHARS,
    PublicWorkspaceBlackboardContext, PublicWorkspaceBlackboardError,
    PublicWorkspaceBlackboardPost, PublicWorkspaceBlackboardReply,
};

const PUBLIC_BLACKBOARD_NAMESPACE: Uuid =
    Uuid::from_u128(0x8561_892e_8b8c_42fd_aa8a_f49e_0e06_5068);

pub(super) fn blackboard_scope(
    context: &PublicWorkspaceBlackboardContext,
) -> WorkspaceBlackboardScope {
    WorkspaceBlackboardScope {
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
    }
}

pub(super) fn prepared_context(
    context: &PublicWorkspaceBlackboardContext,
    action: &str,
) -> PublicWorkspaceBlackboardContext {
    let mut context = context.clone();
    if context.idempotency_key.is_none() {
        context.idempotency_key = Some(format!("legacy-{action}:{}", Uuid::new_v4()));
    }
    context
}

pub(super) fn deterministic_id(
    context: &PublicWorkspaceBlackboardContext,
    kind: &str,
    parent: &str,
) -> String {
    let identity = format!(
        "{kind}\0{}\0{}\0{}\0{}\0{}\0{parent}",
        context.tenant_id,
        context.project_id,
        context.workspace_id,
        context.user_id,
        context.idempotency_key.as_deref().unwrap_or_default(),
    );
    Uuid::new_v5(&PUBLIC_BLACKBOARD_NAMESPACE, identity.as_bytes()).to_string()
}

pub(super) fn timestamp() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true)
}

pub(super) fn validate_title(value: &str) -> Result<(), PublicWorkspaceBlackboardError> {
    let chars = value.chars().count();
    if chars == 0 || chars > MAX_TITLE_CHARS {
        return Err(PublicWorkspaceBlackboardError::InvalidRequest);
    }
    Ok(())
}

pub(super) fn validate_content(value: &str) -> Result<(), PublicWorkspaceBlackboardError> {
    if value.is_empty() {
        return Err(PublicWorkspaceBlackboardError::InvalidRequest);
    }
    Ok(())
}

pub(super) fn validate_status(value: &str) -> Result<(), PublicWorkspaceBlackboardError> {
    if !BLACKBOARD_STATUSES.contains(&value) {
        return Err(PublicWorkspaceBlackboardError::InvalidRequest);
    }
    Ok(())
}

pub(super) fn validate_page(
    limit: i64,
    offset: i64,
    maximum: i64,
) -> Result<(), PublicWorkspaceBlackboardError> {
    if !(1..=maximum).contains(&limit) || offset < 0 {
        return Err(PublicWorkspaceBlackboardError::InvalidRequest);
    }
    Ok(())
}

pub(super) fn validate_idempotency_key(value: &str) -> Result<(), PublicWorkspaceBlackboardError> {
    if value.is_empty() || value.chars().count() > MAX_IDEMPOTENCY_KEY_CHARS {
        return Err(PublicWorkspaceBlackboardError::InvalidRequest);
    }
    Ok(())
}

pub(super) fn owned_metadata(value: &Value) -> Result<Value, PublicWorkspaceBlackboardError> {
    let Some(object) = value.as_object() else {
        return Err(PublicWorkspaceBlackboardError::InvalidRequest);
    };
    let mut object = object.clone();
    for (key, value) in [
        ("surface_owner", "blackboard"),
        ("surface_boundary", "owned"),
        ("authority_class", "authoritative"),
        ("signal_role", "sensing-capable"),
    ] {
        object.insert(key.to_string(), Value::String(value.to_string()));
    }
    Ok(Value::Object(object))
}

pub(super) fn blackboard_event(value: Value) -> Result<Value, PublicWorkspaceBlackboardError> {
    let Some(object) = value.as_object() else {
        return Err(PublicWorkspaceBlackboardError::InvalidRequest);
    };
    let mut object: Map<String, Value> = object.clone();
    object.insert(
        "surface_boundary".to_string(),
        Value::String("owned".to_string()),
    );
    object.insert(
        "authority_class".to_string(),
        Value::String("authoritative".to_string()),
    );
    Ok(Value::Object(object))
}

pub(super) fn request_hash(value: Value) -> Result<String, PublicWorkspaceBlackboardError> {
    let encoded = serde_json::to_vec(&canonical_json(&value))?;
    Ok(hex::encode(Sha256::digest(encoded)))
}

pub(super) fn hash_payload(value: &Value) -> Value {
    match value {
        Value::Object(fields) => Value::Object(
            fields
                .iter()
                .filter(|(key, _)| !matches!(key.as_str(), "created_at" | "updated_at"))
                .map(|(key, value)| (key.clone(), hash_payload(value)))
                .collect(),
        ),
        Value::Array(values) => Value::Array(values.iter().map(hash_payload).collect()),
        _ => value.clone(),
    }
}

pub(super) fn public_post(
    record: &WorkspaceBlackboardPostRecord,
) -> Result<PublicWorkspaceBlackboardPost, PublicWorkspaceBlackboardError> {
    if !record.metadata.is_object() {
        return Err(PublicWorkspaceBlackboardError::InvalidRequest);
    }
    Ok(PublicWorkspaceBlackboardPost {
        id: record.post_id.clone(),
        workspace_id: record.workspace_id.clone(),
        author_id: record.author_actor_id.clone(),
        title: record.title.clone(),
        content: record.content.clone(),
        status: record.status.clone(),
        is_pinned: record.is_pinned,
        metadata: record.metadata.clone(),
        created_at: record.created_at.clone(),
        updated_at: record.updated_at.clone(),
    })
}

pub(super) fn public_reply(
    record: &WorkspaceBlackboardReplyRecord,
) -> Result<PublicWorkspaceBlackboardReply, PublicWorkspaceBlackboardError> {
    if !record.metadata.is_object() {
        return Err(PublicWorkspaceBlackboardError::InvalidRequest);
    }
    Ok(PublicWorkspaceBlackboardReply {
        id: record.reply_id.clone(),
        post_id: record.post_id.clone(),
        workspace_id: record.workspace_id.clone(),
        author_id: record.author_actor_id.clone(),
        content: record.content.clone(),
        metadata: record.metadata.clone(),
        created_at: record.created_at.clone(),
        updated_at: record.updated_at.clone(),
    })
}
