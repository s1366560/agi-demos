use chrono::{DateTime, SecondsFormat, Utc};
use serde_json::{json, Value};

use super::*;

impl From<WorkspaceRecord> for WorkspaceView {
    fn from(record: WorkspaceRecord) -> Self {
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            project_id: record.project_id,
            name: record.name,
            created_by: record.created_by,
            description: record.description,
            is_archived: record.is_archived,
            metadata: record.metadata_json,
            office_status: record.office_status,
            hex_layout_config: record.hex_layout_config_json,
            created_at: iso(record.created_at),
            updated_at: record.updated_at.map(iso),
        }
    }
}

impl From<WorkspaceTaskRecord> for WorkspaceTaskView {
    fn from(record: WorkspaceTaskRecord) -> Self {
        let metadata = object_or_empty(record.metadata_json);
        let workspace_agent_id = string_field(&metadata, "workspace_agent_binding_id");
        Self {
            id: record.id,
            workspace_id: record.workspace_id,
            title: record.title,
            description: record.description,
            created_by: record.created_by,
            assignee_user_id: record.assignee_user_id,
            assignee_agent_id: record.assignee_agent_id,
            workspace_agent_id,
            current_attempt_id: string_field(&metadata, "current_attempt_id"),
            current_attempt_number: metadata
                .get("current_attempt_number")
                .and_then(|value| value.as_i64()),
            current_attempt_conversation_id: string_field(
                &metadata,
                "current_attempt_conversation_id",
            ),
            current_attempt_worker_binding_id: string_field(
                &metadata,
                "current_attempt_worker_binding_id",
            ),
            current_attempt_worker_agent_id: string_field(
                &metadata,
                "current_attempt_worker_agent_id",
            ),
            last_attempt_status: string_field(&metadata, "last_attempt_status"),
            pending_leader_adjudication: metadata
                .get("pending_leader_adjudication")
                .and_then(|value| value.as_bool())
                .unwrap_or(false),
            last_worker_report_type: string_field(&metadata, "last_worker_report_type"),
            last_worker_report_summary: string_field(&metadata, "last_worker_report_summary"),
            last_worker_report_artifacts: string_array_field(
                &metadata,
                "last_worker_report_artifacts",
            ),
            last_worker_report_verifications: string_array_field(
                &metadata,
                "last_worker_report_verifications",
            ),
            status: record.status,
            metadata,
            created_at: iso(record.created_at),
            updated_at: record.updated_at.map(iso),
            priority: public_priority(record.priority),
            estimated_effort: record.estimated_effort,
            blocker_reason: record.blocker_reason,
            completed_at: record.completed_at.map(iso),
            archived_at: record.archived_at.map(iso),
        }
    }
}

impl From<WorkspaceMessageRecord> for MessageView {
    fn from(record: WorkspaceMessageRecord) -> Self {
        Self {
            id: record.id,
            workspace_id: record.workspace_id,
            sender_id: record.sender_id,
            sender_type: record.sender_type,
            content: record.content,
            mentions: record.mentions_json,
            parent_message_id: record.parent_message_id,
            metadata: record.metadata_json,
            created_at: iso(record.created_at),
        }
    }
}

impl From<TopologyNodeRecord> for TopologyNodeView {
    fn from(record: TopologyNodeRecord) -> Self {
        Self {
            id: record.id,
            workspace_id: record.workspace_id,
            node_type: record.node_type,
            ref_id: record.ref_id,
            title: record.title,
            position_x: record.position_x,
            position_y: record.position_y,
            hex_q: record.hex_q,
            hex_r: record.hex_r,
            status: record.status,
            tags: record.tags_json,
            data: record.data_json,
            created_at: iso(record.created_at),
            updated_at: record.updated_at.map(iso),
        }
    }
}

impl From<TopologyEdgeRecord> for TopologyEdgeView {
    fn from(record: TopologyEdgeRecord) -> Self {
        Self {
            id: record.id,
            workspace_id: record.workspace_id,
            source_node_id: record.source_node_id,
            target_node_id: record.target_node_id,
            label: record.label,
            source_hex_q: record.source_hex_q,
            source_hex_r: record.source_hex_r,
            target_hex_q: record.target_hex_q,
            target_hex_r: record.target_hex_r,
            direction: record.direction,
            auto_created: record.auto_created,
            data: record.data_json,
            created_at: iso(record.created_at),
            updated_at: record.updated_at.map(iso),
        }
    }
}

impl From<BlackboardPostRecord> for BlackboardPostView {
    fn from(record: BlackboardPostRecord) -> Self {
        Self {
            id: record.id,
            workspace_id: record.workspace_id,
            author_id: record.author_id,
            title: record.title,
            content: record.content,
            status: record.status,
            is_pinned: record.is_pinned,
            metadata: record.metadata_json,
            created_at: iso(record.created_at),
            updated_at: record.updated_at.map(iso),
        }
    }
}

impl From<BlackboardReplyRecord> for BlackboardReplyView {
    fn from(record: BlackboardReplyRecord) -> Self {
        Self {
            id: record.id,
            post_id: record.post_id,
            workspace_id: record.workspace_id,
            author_id: record.author_id,
            content: record.content,
            metadata: record.metadata_json,
            created_at: iso(record.created_at),
            updated_at: record.updated_at.map(iso),
        }
    }
}

impl From<BlackboardFileRecord> for BlackboardFileView {
    fn from(record: BlackboardFileRecord) -> Self {
        Self {
            id: record.id,
            workspace_id: record.workspace_id,
            parent_path: record.parent_path,
            name: record.name,
            is_directory: record.is_directory,
            file_size: record.file_size,
            content_type: record.content_type,
            uploader_type: record.uploader_type,
            uploader_id: record.uploader_id,
            uploader_name: record.uploader_name,
            created_at: iso(record.created_at),
        }
    }
}

pub(super) fn phase_label(phase: &str) -> String {
    match phase {
        "research" => "Research",
        "plan" => "Plan",
        "implement" => "Implement",
        "test" => "Test",
        "deploy" => "Deploy",
        "review" => "Review",
        _ => phase,
    }
    .to_string()
}

pub(super) fn string_from_value(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

pub(super) fn int_from_value(value: Option<&Value>, fallback: i32) -> i32 {
    value
        .and_then(|value| {
            value
                .as_i64()
                .or_else(|| value.as_str().and_then(|text| text.parse::<i64>().ok()))
        })
        .filter(|value| *value >= 0)
        .map(|value| value as i32)
        .unwrap_or(fallback)
}

pub(super) fn int_list_from_value(value: Option<&Value>) -> Vec<i32> {
    value
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_i64().map(|value| value as i32))
                .collect()
        })
        .unwrap_or_default()
}

pub(super) fn metadata_string_values(value: &Value, keys: &[&str]) -> Vec<String> {
    let mut items = Vec::new();
    for key in keys {
        items.extend(string_values(value.get(*key)));
    }
    dedup_truncate(&mut items, usize::MAX);
    items
}

pub(super) fn string_values(value: Option<&Value>) -> Vec<String> {
    match value {
        Some(Value::String(text)) if !text.is_empty() => vec![text.clone()],
        Some(Value::Array(items)) => items
            .iter()
            .filter_map(|item| item.as_str().filter(|text| !text.is_empty()))
            .map(ToOwned::to_owned)
            .collect(),
        _ => Vec::new(),
    }
}

pub(super) fn first_metadata_string(value: &Value, keys: &[&str]) -> String {
    keys.iter()
        .find_map(|key| string_from_value(value.get(*key)))
        .unwrap_or_default()
}

pub(super) fn dedup_truncate(items: &mut Vec<String>, limit: usize) {
    let mut seen = std::collections::HashSet::new();
    items.retain(|item| seen.insert(item.clone()));
    if items.len() > limit {
        items.truncate(limit);
    }
}

pub(super) fn object_or_empty(value: Value) -> Value {
    if value.is_object() {
        value
    } else {
        json!({})
    }
}

fn string_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(|value| value.as_str())
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn string_array_field(value: &Value, key: &str) -> Vec<String> {
    value
        .get(key)
        .and_then(|value| value.as_array())
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(ToOwned::to_owned))
                .collect()
        })
        .unwrap_or_default()
}

fn public_priority(rank: i32) -> String {
    match rank {
        1 => "P1",
        2 => "P2",
        3 => "P3",
        4 => "P4",
        _ => "",
    }
    .to_string()
}

pub(super) fn iso(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Millis, true)
}
