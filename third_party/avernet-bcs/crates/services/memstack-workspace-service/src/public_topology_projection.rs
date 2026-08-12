//! Topology validation, canonical hashing, IDs, and response projection.

use chrono::{SecondsFormat, Utc};
use memstack_workspace_store::{
    WorkspaceTopologyEdgeRecord, WorkspaceTopologyNodeRecord, WorkspaceTopologyScope,
    WorkspaceTopologyStore,
};
use serde_json::Value;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::canonical_json;

use super::{
    PublicCreateTopologyEdgeInput, PublicCreateTopologyNodeInput, PublicUpdateTopologyEdgeFields,
    PublicUpdateTopologyNodeFields, PublicWorkspaceTopologyContext, PublicWorkspaceTopologyEdge,
    PublicWorkspaceTopologyError, PublicWorkspaceTopologyNode, TOPOLOGY_NODE_TYPES,
};

const PUBLIC_TOPOLOGY_NAMESPACE: Uuid = Uuid::from_u128(0x5e85_c2d9_0c2b_46ec_92e0_4cc2_65d5_7e42);
const MAX_IDEMPOTENCY_KEY_CHARS: usize = 256;
const MAX_REF_ID_CHARS: usize = 255;
const MAX_TITLE_CHARS: usize = 64;
const MAX_STATUS_CHARS: usize = 32;
const MAX_LABEL_CHARS: usize = 64;
const MAX_DIRECTION_CHARS: usize = 32;
const MAX_TAG_COUNT: usize = 12;
const MAX_TAG_CHARS: usize = 32;
const MAX_DATA_KEYS: usize = 16;
const MAX_DATA_LIST_ITEMS: usize = 16;
const MAX_DATA_KEY_CHARS: usize = 32;
const MAX_DATA_STRING_CHARS: usize = 256;
const MAX_DATA_DEPTH: usize = 3;
const MAX_DATA_BYTES: usize = 2048;
const MAX_HEX_COORDINATE: i64 = 24;
const MAX_POSITION: f64 = 1000.0;

pub(super) fn topology_scope(context: &PublicWorkspaceTopologyContext) -> WorkspaceTopologyScope {
    WorkspaceTopologyScope {
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
    }
}

pub(super) fn prepared_context(
    context: &PublicWorkspaceTopologyContext,
    action: &str,
) -> PublicWorkspaceTopologyContext {
    let mut context = context.clone();
    if context.idempotency_key.is_none() {
        context.idempotency_key = Some(format!("legacy-{action}:{}", Uuid::new_v4()));
    }
    context
}

pub(super) fn deterministic_id(
    context: &PublicWorkspaceTopologyContext,
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
    Uuid::new_v5(&PUBLIC_TOPOLOGY_NAMESPACE, identity.as_bytes()).to_string()
}

pub(super) fn timestamp() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true)
}

pub(super) fn validate_node_input(
    input: &PublicCreateTopologyNodeInput,
) -> Result<(), PublicWorkspaceTopologyError> {
    validate_node_type(input.node_type.as_str())?;
    validate_optional_text(input.ref_id.as_deref(), MAX_REF_ID_CHARS)?;
    validate_text(input.title.as_str(), MAX_TITLE_CHARS)?;
    validate_text(input.status.as_str(), MAX_STATUS_CHARS)?;
    validate_position(input.position_x)?;
    validate_position(input.position_y)?;
    validate_hex(input.hex_q, input.hex_r)?;
    validate_tags(&input.tags)?;
    validate_data(&input.data)
}

pub(super) fn apply_node_fields(
    record: &mut WorkspaceTopologyNodeRecord,
    fields: &PublicUpdateTopologyNodeFields,
) -> Result<(), PublicWorkspaceTopologyError> {
    if let Some(value) = &fields.node_type {
        validate_node_type(value)?;
        record.node_type.clone_from(value);
    }
    if let Some(value) = &fields.ref_id {
        validate_text(value, MAX_REF_ID_CHARS)?;
        record.ref_id = Some(value.clone());
    }
    if let Some(value) = &fields.title {
        validate_text(value, MAX_TITLE_CHARS)?;
        record.title.clone_from(value);
    }
    if let Some(value) = fields.position_x {
        validate_position(value)?;
        record.position_x = value;
    }
    if let Some(value) = fields.position_y {
        validate_position(value)?;
        record.position_y = value;
    }
    if fields.hex_q.is_some() || fields.hex_r.is_some() {
        let hex_q = fields.hex_q.or(record.hex_q);
        let hex_r = fields.hex_r.or(record.hex_r);
        validate_hex(hex_q, hex_r)?;
        record.hex_q = hex_q;
        record.hex_r = hex_r;
    }
    if let Some(value) = &fields.status {
        validate_text(value, MAX_STATUS_CHARS)?;
        record.status.clone_from(value);
    }
    if let Some(value) = &fields.tags {
        validate_tags(value)?;
        record.tags.clone_from(value);
    }
    if let Some(value) = &fields.data {
        validate_data(value)?;
        record.data.clone_from(value);
    }
    Ok(())
}

pub(super) fn validate_edge_input(
    input: &PublicCreateTopologyEdgeInput,
) -> Result<(), PublicWorkspaceTopologyError> {
    validate_required_id(input.source_node_id.as_str())?;
    validate_required_id(input.target_node_id.as_str())?;
    validate_optional_text(input.label.as_deref(), MAX_LABEL_CHARS)?;
    validate_optional_text(input.direction.as_deref(), MAX_DIRECTION_CHARS)?;
    validate_data(&input.data)
}

pub(super) fn apply_edge_fields(
    record: &mut WorkspaceTopologyEdgeRecord,
    fields: &PublicUpdateTopologyEdgeFields,
) -> Result<(), PublicWorkspaceTopologyError> {
    if let Some(value) = &fields.source_node_id {
        validate_required_id(value)?;
        record.source_node_id.clone_from(value);
    }
    if let Some(value) = &fields.target_node_id {
        validate_required_id(value)?;
        record.target_node_id.clone_from(value);
    }
    if let Some(value) = &fields.label {
        validate_text(value, MAX_LABEL_CHARS)?;
        record.label = Some(value.clone());
    }
    if let Some(value) = &fields.direction {
        validate_text(value, MAX_DIRECTION_CHARS)?;
        record.direction = Some(value.clone());
    }
    if let Some(value) = fields.auto_created {
        record.auto_created = value;
    }
    if let Some(value) = &fields.data {
        validate_data(value)?;
        record.data.clone_from(value);
    }
    Ok(())
}

pub(super) async fn ensure_hex_available(
    store: &WorkspaceTopologyStore<'_>,
    context: &PublicWorkspaceTopologyContext,
    hex_q: Option<i64>,
    hex_r: Option<i64>,
    exclude_node_id: Option<&str>,
) -> Result<(), PublicWorkspaceTopologyError> {
    validate_hex(hex_q, hex_r)?;
    if let (Some(hex_q), Some(hex_r)) = (hex_q, hex_r)
        && store
            .is_hex_occupied(&topology_scope(context), hex_q, hex_r, exclude_node_id)
            .await?
    {
        return Err(PublicWorkspaceTopologyError::Conflict);
    }
    Ok(())
}

pub(super) fn validate_page(limit: i64, offset: i64) -> Result<(), PublicWorkspaceTopologyError> {
    if limit < 0 || offset < 0 {
        return Err(PublicWorkspaceTopologyError::InvalidRequest);
    }
    Ok(())
}

pub(super) fn validate_idempotency_key(value: &str) -> Result<(), PublicWorkspaceTopologyError> {
    if value.is_empty() || value.chars().count() > MAX_IDEMPOTENCY_KEY_CHARS {
        return Err(PublicWorkspaceTopologyError::InvalidRequest);
    }
    Ok(())
}

fn validate_node_type(value: &str) -> Result<(), PublicWorkspaceTopologyError> {
    if !TOPOLOGY_NODE_TYPES.contains(&value) {
        return Err(PublicWorkspaceTopologyError::InvalidRequest);
    }
    Ok(())
}

fn validate_required_id(value: &str) -> Result<(), PublicWorkspaceTopologyError> {
    if value.is_empty() {
        return Err(PublicWorkspaceTopologyError::InvalidRequest);
    }
    Ok(())
}

fn validate_optional_text(
    value: Option<&str>,
    maximum: usize,
) -> Result<(), PublicWorkspaceTopologyError> {
    if value.is_some_and(|value| value.chars().count() > maximum) {
        return Err(PublicWorkspaceTopologyError::InvalidRequest);
    }
    Ok(())
}

fn validate_text(value: &str, maximum: usize) -> Result<(), PublicWorkspaceTopologyError> {
    if value.chars().count() > maximum {
        return Err(PublicWorkspaceTopologyError::InvalidRequest);
    }
    Ok(())
}

fn validate_position(value: f64) -> Result<(), PublicWorkspaceTopologyError> {
    if !value.is_finite() || value.abs() > MAX_POSITION {
        return Err(PublicWorkspaceTopologyError::InvalidRequest);
    }
    Ok(())
}

fn validate_hex(
    hex_q: Option<i64>,
    hex_r: Option<i64>,
) -> Result<(), PublicWorkspaceTopologyError> {
    match (hex_q, hex_r) {
        (None, None) => Ok(()),
        (Some(hex_q), Some(hex_r)) => {
            let hex_s = hex_q
                .checked_add(hex_r)
                .and_then(i64::checked_neg)
                .ok_or(PublicWorkspaceTopologyError::InvalidRequest)?;
            let distance = hex_q
                .checked_abs()
                .zip(hex_r.checked_abs())
                .zip(hex_s.checked_abs())
                .map(|((q, r), s)| q.max(r).max(s))
                .ok_or(PublicWorkspaceTopologyError::InvalidRequest)?;
            if distance > MAX_HEX_COORDINATE || (hex_q == 0 && hex_r == 0) {
                return Err(PublicWorkspaceTopologyError::InvalidRequest);
            }
            Ok(())
        }
        _ => Err(PublicWorkspaceTopologyError::InvalidRequest),
    }
}

fn validate_tags(value: &Value) -> Result<(), PublicWorkspaceTopologyError> {
    let tags = value
        .as_array()
        .ok_or(PublicWorkspaceTopologyError::InvalidRequest)?;
    if tags.len() > MAX_TAG_COUNT {
        return Err(PublicWorkspaceTopologyError::InvalidRequest);
    }
    for tag in tags {
        let tag = tag
            .as_str()
            .ok_or(PublicWorkspaceTopologyError::InvalidRequest)?;
        if tag.chars().count() > MAX_TAG_CHARS {
            return Err(PublicWorkspaceTopologyError::InvalidRequest);
        }
    }
    Ok(())
}

fn validate_data(value: &Value) -> Result<(), PublicWorkspaceTopologyError> {
    if !value.is_object() {
        return Err(PublicWorkspaceTopologyError::InvalidRequest);
    }
    validate_json_value(value, 0)?;
    let encoded = serde_json::to_vec(&canonical_json(value))?;
    if encoded.len() > MAX_DATA_BYTES {
        return Err(PublicWorkspaceTopologyError::InvalidRequest);
    }
    Ok(())
}

fn validate_json_value(value: &Value, depth: usize) -> Result<(), PublicWorkspaceTopologyError> {
    if depth > MAX_DATA_DEPTH {
        return Err(PublicWorkspaceTopologyError::InvalidRequest);
    }
    match value {
        Value::Null | Value::Bool(_) | Value::Number(_) => Ok(()),
        Value::String(value) => {
            if value.chars().count() > MAX_DATA_STRING_CHARS {
                return Err(PublicWorkspaceTopologyError::InvalidRequest);
            }
            Ok(())
        }
        Value::Array(values) => {
            if values.len() > MAX_DATA_LIST_ITEMS {
                return Err(PublicWorkspaceTopologyError::InvalidRequest);
            }
            for value in values {
                validate_json_value(value, depth + 1)?;
            }
            Ok(())
        }
        Value::Object(values) => {
            if values.len() > MAX_DATA_KEYS
                || values
                    .keys()
                    .any(|key| key.chars().count() > MAX_DATA_KEY_CHARS)
            {
                return Err(PublicWorkspaceTopologyError::InvalidRequest);
            }
            for value in values.values() {
                validate_json_value(value, depth + 1)?;
            }
            Ok(())
        }
    }
}

pub(super) fn request_hash(value: Value) -> Result<String, PublicWorkspaceTopologyError> {
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

pub(super) fn public_node(
    record: &WorkspaceTopologyNodeRecord,
) -> Result<PublicWorkspaceTopologyNode, PublicWorkspaceTopologyError> {
    validate_tags(&record.tags)?;
    validate_data(&record.data)?;
    Ok(PublicWorkspaceTopologyNode {
        id: record.node_id.clone(),
        workspace_id: record.workspace_id.clone(),
        node_type: record.node_type.clone(),
        ref_id: record.ref_id.clone(),
        title: record.title.clone(),
        position_x: record.position_x,
        position_y: record.position_y,
        hex_q: record.hex_q,
        hex_r: record.hex_r,
        status: record.status.clone(),
        tags: record.tags.clone(),
        data: record.data.clone(),
        created_at: record.created_at.clone(),
        updated_at: record.updated_at.clone(),
    })
}

pub(super) fn public_edge(
    record: &WorkspaceTopologyEdgeRecord,
) -> Result<PublicWorkspaceTopologyEdge, PublicWorkspaceTopologyError> {
    validate_data(&record.data)?;
    Ok(PublicWorkspaceTopologyEdge {
        id: record.edge_id.clone(),
        workspace_id: record.workspace_id.clone(),
        source_node_id: record.source_node_id.clone(),
        target_node_id: record.target_node_id.clone(),
        label: record.label.clone(),
        source_hex_q: record.source_hex_q,
        source_hex_r: record.source_hex_r,
        target_hex_q: record.target_hex_q,
        target_hex_r: record.target_hex_r,
        direction: record.direction.clone(),
        auto_created: record.auto_created,
        data: record.data.clone(),
        created_at: record.created_at.clone(),
        updated_at: record.updated_at.clone(),
    })
}
