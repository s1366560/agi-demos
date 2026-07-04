use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use agistack_adapters_postgres::{ShareMemoryRecord, ShareRecord};

#[derive(Clone, Debug, Default, Deserialize)]
pub(crate) struct ShareCreatePayload {
    #[serde(default)]
    pub(super) target_type: Option<Value>,
    #[serde(default)]
    pub(super) permission_level: Option<Value>,
    #[serde(default)]
    pub(super) target_id: Option<Value>,
    #[serde(default)]
    pub(super) permissions: Option<Value>,
    #[serde(default)]
    pub(super) expires_at: Option<Value>,
    #[serde(default)]
    pub(super) expires_in_days: Option<Value>,
}

#[derive(Debug, Serialize)]
pub(crate) struct ShareView {
    pub(super) id: String,
    pub(super) share_token: Option<String>,
    pub(super) memory_id: String,
    pub(super) shared_with_user_id: Option<String>,
    pub(super) shared_with_project_id: Option<String>,
    pub(super) permissions: Value,
    pub(super) expires_at: Option<String>,
    pub(super) created_at: String,
    pub(super) access_count: i32,
}

impl From<ShareRecord> for ShareView {
    fn from(record: ShareRecord) -> Self {
        Self {
            id: record.id,
            share_token: record.share_token,
            memory_id: record.memory_id,
            shared_with_user_id: record.shared_with_user_id,
            shared_with_project_id: record.shared_with_project_id,
            permissions: record.permissions,
            expires_at: record.expires_at.map(iso8601),
            created_at: iso8601(record.created_at),
            access_count: record.access_count,
        }
    }
}

#[derive(Debug, Serialize)]
pub(crate) struct ShareList {
    shares: Vec<ShareListItem>,
}

impl ShareList {
    pub(super) fn from_records(records: Vec<ShareRecord>) -> Self {
        Self {
            shares: records.into_iter().map(ShareListItem::from).collect(),
        }
    }
}

#[derive(Debug, Serialize)]
struct ShareListItem {
    id: String,
    share_token: Option<String>,
    permissions: Value,
    expires_at: Option<String>,
    created_at: String,
    access_count: i32,
}

impl From<ShareRecord> for ShareListItem {
    fn from(record: ShareRecord) -> Self {
        Self {
            id: record.id,
            share_token: record.share_token,
            permissions: record.permissions,
            expires_at: record.expires_at.map(iso8601),
            created_at: iso8601(record.created_at),
            access_count: record.access_count,
        }
    }
}

#[derive(Debug, Serialize)]
pub(crate) struct SharedMemoryView {
    memory: SharedMemoryBody,
    share: SharedMemoryShareBody,
}

#[derive(Debug, Serialize)]
struct SharedMemoryBody {
    id: String,
    title: String,
    content: String,
    tags: Value,
    created_at: String,
    updated_at: Option<String>,
}

impl From<ShareMemoryRecord> for SharedMemoryBody {
    fn from(record: ShareMemoryRecord) -> Self {
        Self {
            id: record.id,
            title: record.title,
            content: record.content,
            tags: record.tags,
            created_at: iso8601(record.created_at),
            updated_at: record.updated_at.map(iso8601),
        }
    }
}

#[derive(Debug, Serialize)]
struct SharedMemoryShareBody {
    permissions: Value,
    expires_at: Option<String>,
}

pub(super) fn shared_memory_view(
    memory: ShareMemoryRecord,
    share: ShareRecord,
) -> SharedMemoryView {
    SharedMemoryView {
        memory: SharedMemoryBody::from(memory),
        share: SharedMemoryShareBody {
            permissions: share.permissions,
            expires_at: share.expires_at.map(iso8601),
        },
    }
}

#[derive(Debug)]
pub(super) enum TargetKind {
    User,
    Project,
}

impl TargetKind {
    pub(super) fn as_str(&self) -> &'static str {
        match self {
            Self::User => "user",
            Self::Project => "project",
        }
    }
}

#[derive(Debug)]
pub(super) struct ValidatedTarget {
    pub(super) kind: TargetKind,
    pub(super) id: String,
}

fn iso8601(dt: DateTime<Utc>) -> String {
    dt.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}
