//! Derived entity/relationship record sync wire contracts. Records are the
//! portable form of one source memory's extraction projection plus its
//! provenance. Identity is positional: relationships reference entity indexes
//! inside the same record, and the object id is the stable source memory id
//! already synced by memory sync. Vector indexes and processing leases are
//! never part of this envelope; each end rebuilds its own.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::push::{valid_identifier, KnowledgeSyncTarget, PreparedKnowledgePush, MAX_REMOTE_REVISION};
use super::{KnowledgeResult, KnowledgeScope};
use crate::knowledge::KnowledgeError;

pub const MAX_GRAPH_ENTITIES: usize = 200;
pub const MAX_GRAPH_RELATIONSHIPS: usize = 500;
pub const MAX_GRAPH_PAYLOAD_BYTES: usize = 262_144;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RemoteGraphEntity {
    pub name: String,
    pub kind: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RemoteGraphRelationship {
    pub source_index: u32,
    pub target_index: u32,
    pub relation_type: String,
    pub fact: String,
    pub score: f64,
}

/// Provenance names the exact origin-end source: the source memory revision,
/// the origin processing change sequence and the origin audit attempt. These
/// are references across ends, never local cursor state.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RemoteGraphContent {
    pub source_revision: u32,
    pub change_sequence: u64,
    pub audit_attempt: u32,
    pub entities: Vec<RemoteGraphEntity>,
    pub relationships: Vec<RemoteGraphRelationship>,
}

impl RemoteGraphContent {
    pub fn validate(&self) -> KnowledgeResult<()> {
        if self.source_revision == 0
            || self.source_revision >= MAX_REMOTE_REVISION
            || self.change_sequence == 0
            || self.change_sequence > i64::MAX as u64
            || self.audit_attempt == 0
            || self.audit_attempt >= MAX_REMOTE_REVISION
            || self.entities.len() > MAX_GRAPH_ENTITIES
            || self.relationships.len() > MAX_GRAPH_RELATIONSHIPS
        {
            return Err(KnowledgeError::InvalidInput);
        }
        for entity in &self.entities {
            valid_identifier(&entity.name)?;
            valid_identifier(&entity.kind)?;
        }
        for relationship in &self.relationships {
            valid_identifier(&relationship.relation_type)?;
            valid_identifier(&relationship.fact)?;
            if !relationship.score.is_finite()
                || !(0.0..=1.0).contains(&relationship.score)
                || relationship.source_index as usize >= self.entities.len()
                || relationship.target_index as usize >= self.entities.len()
            {
                return Err(KnowledgeError::InvalidInput);
            }
        }
        let bytes = serde_json::to_vec(self).map_err(|_| KnowledgeError::InvalidInput)?;
        if bytes.len() > MAX_GRAPH_PAYLOAD_BYTES {
            return Err(KnowledgeError::InvalidInput);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RemoteGraphVersion {
    pub object_id: String,
    pub revision: u32,
    pub deleted: bool,
    pub author_id: String,
    pub created_at_ms: i64,
    pub content: RemoteGraphContent,
}

impl RemoteGraphVersion {
    pub fn validate(&self) -> KnowledgeResult<()> {
        valid_identifier(&self.object_id)?;
        valid_identifier(&self.author_id)?;
        if self.revision == 0 || self.revision > MAX_REMOTE_REVISION {
            return Err(KnowledgeError::InvalidInput);
        }
        self.content.validate()
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct KnowledgeGraphPushReceipt {
    pub local_sequence: u64,
    pub receipt: Value,
    pub replayed: bool,
}

#[async_trait]
pub trait KnowledgeGraphPushRepository: Send + Sync {
    async fn prepare_graph_push(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
    ) -> KnowledgeResult<Option<PreparedKnowledgePush>>;
    /// The authority calls this only for a response read from its verified
    /// cloud transport; renderer payloads never reach this port.
    async fn accept_graph_push_receipt(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        local_sequence: u64,
        response: Value,
        conflict: Option<Value>,
    ) -> KnowledgeResult<KnowledgeGraphPushReceipt>;
    async fn remote_graph_baseline(
        &self,
        scope: &KnowledgeScope,
        object_id: &str,
    ) -> KnowledgeResult<Option<Value>>;
    async fn graph_push_conflicts(
        &self,
        scope: &KnowledgeScope,
        limit: usize,
    ) -> KnowledgeResult<Vec<Value>>;
}

#[async_trait]
pub trait KnowledgeGraphPullRepository: Send + Sync {
    async fn graph_pull_cursor(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
    ) -> KnowledgeResult<u64>;
    /// Commits records, conflict copies and the cursor atomically. A stale
    /// expected cursor is rejected; callers fetch from the durable cursor.
    async fn accept_graph_pull_page(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        after: u64,
        response: Value,
    ) -> KnowledgeResult<GraphPullReceipt>;
    async fn graph_pull_conflicts(
        &self,
        scope: &KnowledgeScope,
        limit: usize,
    ) -> KnowledgeResult<Vec<Value>>;
}

#[derive(Debug, Clone, Serialize)]
pub struct GraphPullReceipt {
    pub next_cursor: u64,
    pub applied: usize,
    pub conflicts: usize,
    pub has_more: bool,
}

/// One synced derived record as served by the receiving end. `source_available`
/// reports whether the source memory is currently live locally; `source_current`
/// reports whether the live memory still matches the provenance revision. A
/// record that arrived before its source memory is durable but reports
/// `source_available == false` until the memory sync delivers the source.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SyncedGraphProjection {
    pub object_id: String,
    pub revision: u32,
    pub deleted: bool,
    pub author_id: String,
    pub created_at_ms: i64,
    pub content: RemoteGraphContent,
    pub source_available: bool,
    pub source_current: bool,
}

#[async_trait]
pub trait KnowledgeGraphSyncReadRepository: Send + Sync {
    async fn synced_graph_projection(
        &self,
        scope: &KnowledgeScope,
        object_id: &str,
    ) -> KnowledgeResult<Option<SyncedGraphProjection>>;
    async fn synced_graph_projections(
        &self,
        scope: &KnowledgeScope,
        limit: usize,
        offset: usize,
    ) -> KnowledgeResult<Vec<SyncedGraphProjection>>;
}
