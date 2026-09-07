//! Cloud push wire contract. Remote PostgreSQL INTEGER revisions are independent
//! of local u32 content revisions. Receipt ingestion is a trusted transport port,
//! not a renderer-facing mutation API.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use super::{KnowledgeResult, KnowledgeScope, KnowledgeSyncLink};
use crate::knowledge::KnowledgeError;

pub const MAX_REMOTE_REVISION: u32 = i32::MAX as u32;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RemoteMemoryContent {
    pub title: String,
    pub content: String,
    pub content_type: String,
    pub tags: Vec<String>,
    pub metadata: Map<String, Value>,
    pub status: String,
}

impl RemoteMemoryContent {
    pub fn validate(&self) -> KnowledgeResult<()> {
        valid_identifier(&self.title)?;
        let metadata =
            serde_json::to_string(&self.metadata).map_err(|_| KnowledgeError::InvalidInput)?;
        // Python's canonical JSON escapes non-ASCII UTF-16 units by default.
        let metadata_bytes: usize = metadata
            .chars()
            .map(|c| if c.is_ascii() { 1 } else { c.len_utf16() * 6 })
            .sum();
        if self.title.chars().count() > 500
            || self.content.len() > 1_048_576
            || !matches!(
                self.content_type.as_str(),
                "text" | "document" | "image" | "video"
            )
            || !matches!(self.status.as_str(), "ENABLED" | "DISABLED")
            || self.tags.len() > 100
            || metadata_bytes > 65_536
        {
            return Err(KnowledgeError::InvalidInput);
        }
        for tag in &self.tags {
            valid_identifier(tag)?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RemoteMemoryVersion {
    pub memory_id: String,
    pub revision: u32,
    pub deleted: bool,
    pub author_id: String,
    pub created_at_ms: i64,
    pub content: RemoteMemoryContent,
}

impl RemoteMemoryVersion {
    pub fn validate(&self) -> KnowledgeResult<()> {
        valid_identifier(&self.memory_id)?;
        valid_identifier(&self.author_id)?;
        if self.revision == 0 || self.revision > MAX_REMOTE_REVISION {
            return Err(KnowledgeError::InvalidInput);
        }
        self.content.validate()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KnowledgeSyncTarget {
    /// Normalized trusted cloud API origin and path, pinned before first send.
    pub authority: String,
    pub link: KnowledgeSyncLink,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PreparedKnowledgePush {
    pub local_sequence: u64,
    pub change_id: String,
    /// Exact persisted HTTP JSON body. Retries send these bytes unchanged.
    pub request_json: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct KnowledgePushReceipt {
    pub local_sequence: u64,
    pub receipt: Value,
    pub replayed: bool,
}

pub fn valid_identifier(value: &str) -> KnowledgeResult<()> {
    if value.is_empty() || value.trim() != value || value.chars().count() > 512 {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(())
}

#[async_trait]
pub trait KnowledgePushRepository: Send + Sync {
    async fn prepare_push(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
    ) -> KnowledgeResult<Option<PreparedKnowledgePush>>;
    /// The authority calls this only for a response read from its verified cloud
    /// transport. It must never expose receipt/snapshot arguments to a renderer.
    async fn accept_push_receipt(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        local_sequence: u64,
        response: Value,
        conflict: Option<Value>,
    ) -> KnowledgeResult<KnowledgePushReceipt>;
    async fn remote_baseline(
        &self,
        scope: &KnowledgeScope,
        memory_id: &str,
    ) -> KnowledgeResult<Option<Value>>;
    async fn push_conflicts(
        &self,
        scope: &KnowledgeScope,
        limit: usize,
    ) -> KnowledgeResult<Vec<Value>>;
}
