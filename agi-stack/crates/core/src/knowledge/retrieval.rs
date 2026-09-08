//! Live keyset reads over current, successfully audited extraction projections.
//! References identify positions within an exact source; names are never IDs.

use super::{
    processing::{ProcessingRelationship, ProcessingSource},
    KnowledgeResult, KnowledgeScope,
};
use crate::model::Entity;
use async_trait::async_trait;
use serde::{Deserialize, Serialize};

mod graph;
pub use graph::RetrievedSourceGraph;

pub const MAX_RETRIEVAL_PAGE_SIZE: usize = 100;
pub const MAX_LITERAL_QUERY_BYTES: usize = 4096;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RetrievalKind {
    Entities,
    Relationships,
    Text,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RetrievalPosition {
    pub change_sequence: u64,
    pub item_index: u32,
}

/// Bound to the exact query. New source changes above the first page's upper
/// bound are excluded. Every page rechecks live visibility, so deletions and
/// revisions disappear immediately; this is not a historical snapshot. An
/// extraction completed later behind the cursor is seen after a fresh traversal.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RetrievalCursor {
    pub tenant_id: String,
    pub project_id: String,
    pub kind: RetrievalKind,
    pub source: Option<ProcessingSource>,
    pub literal: Option<String>,
    pub upper_change_sequence: u64,
    pub after: RetrievalPosition,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RetrievalRequest {
    pub source: Option<ProcessingSource>,
    pub cursor: Option<RetrievalCursor>,
    pub limit: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RetrievalPage<T> {
    pub items: Vec<T>,
    pub next_cursor: Option<RetrievalCursor>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EntityReference {
    pub source: ProcessingSource,
    pub entity_index: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RetrievedEntity {
    pub reference: EntityReference,
    pub audit_attempt: u32,
    pub entity: Entity,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RetrievedRelationship {
    pub source: ProcessingSource,
    pub relationship_index: u32,
    pub audit_attempt: u32,
    pub source_entity: EntityReference,
    pub target_entity: EntityReference,
    pub relationship: ProcessingRelationship,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LiteralTextHit {
    pub source: ProcessingSource,
    pub audit_attempt: u32,
    pub title: String,
    pub content: String,
}

#[async_trait]
pub trait KnowledgeRetrievalRepository: Send + Sync {
    async fn entities(
        &self,
        scope: &KnowledgeScope,
        request: &RetrievalRequest,
    ) -> KnowledgeResult<RetrievalPage<RetrievedEntity>>;
    async fn relationships(
        &self,
        scope: &KnowledgeScope,
        request: &RetrievalRequest,
    ) -> KnowledgeResult<RetrievalPage<RetrievedRelationship>>;
    /// Case-sensitive literal substring matching in title or content. No SQL
    /// wildcard, query-language parsing, semantic routing or relevance verdict.
    async fn search_text(
        &self,
        scope: &KnowledgeScope,
        literal: &str,
        request: &RetrievalRequest,
    ) -> KnowledgeResult<RetrievalPage<LiteralTextHit>>;
}
