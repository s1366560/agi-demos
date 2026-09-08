//! Closed foundation for project community generation. A snapshot is an atomic
//! capture, not a live retrieval page. Partitions carry no semantic name/summary;
//! those require a later audited agent submission before publication.

pub mod build;
pub mod result;
pub mod worker;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

use super::{
    processing::{ProcessingProjection, ProcessingSource, ProcessingState},
    retrieval::EntityReference,
    KnowledgeError, KnowledgeResult, KnowledgeScope,
};
use crate::community::{detect_communities, CommunityEdge};

/// Version binds the fixed Louvain implementation, source-local identities,
/// undirected unit relationship weights, and canonical ordering.
pub const COMMUNITY_ALGORITHM_VERSION: &str = "source-local-louvain-unit-v1";

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunityProjection {
    pub audit_attempt: u32,
    pub audit_digest: String,
    pub projection: ProcessingProjection,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunitySource {
    pub source: ProcessingSource,
    /// Full accepted portable payload, including metadata, for exact evidence.
    pub payload: serde_json::Value,
    pub processing_state: Option<ProcessingState>,
    pub processing_attempt: Option<u32>,
    /// Only current, completed, successfully audited extraction is eligible.
    pub audited_projection: Option<CommunityProjection>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunitySnapshot {
    pub tenant_id: String,
    pub project_id: String,
    pub algorithm_version: String,
    pub min_community_size: usize,
    pub sources: Vec<CommunitySource>,
    pub graph_digest: String,
}

/// Structural candidate only. Never expose this as a named/ready community.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunityCandidate {
    pub membership_digest: String,
    pub members: Vec<EntityReference>,
}

#[async_trait]
pub trait CommunitySnapshotRepository: Send + Sync {
    async fn community_snapshot(
        &self,
        scope: &KnowledgeScope,
        min_community_size: usize,
    ) -> KnowledgeResult<CommunitySnapshot>;
}

/// Arithmetic partition only: entity names never establish identity and no
/// cross-source edges are invented. Empty/singleton graphs yield no candidates.
/// Canonical serialized references are collision-free node keys, not hashes.
pub fn partition_snapshot(
    snapshot: &CommunitySnapshot,
) -> KnowledgeResult<Vec<Vec<EntityReference>>> {
    if snapshot.algorithm_version != COMMUNITY_ALGORITHM_VERSION
        || snapshot.min_community_size < 2
        || snapshot.tenant_id.trim().is_empty()
        || snapshot.project_id.trim().is_empty()
    {
        return Err(KnowledgeError::InvalidInput);
    }
    let mut nodes = BTreeMap::new();
    let mut edges = Vec::new();
    let mut sources = std::collections::BTreeSet::new();
    for item in &snapshot.sources {
        let source = &item.source;
        if source.tenant_id != snapshot.tenant_id
            || source.project_id != snapshot.project_id
            || source.memory_id.trim().is_empty()
            || source.revision == 0
            || source.change_sequence == 0
            || !sources.insert(source.memory_id.clone())
        {
            return Err(KnowledgeError::InvalidInput);
        }
        let Some(audited) = &item.audited_projection else {
            continue;
        };
        if item.processing_state != Some(ProcessingState::Completed)
            || item.processing_attempt != Some(audited.audit_attempt)
            || audited.audit_attempt == 0
        {
            return Err(KnowledgeError::InvalidInput);
        }
        let mut keys = Vec::new();
        for index in 0..audited.projection.entities.len() {
            let reference = EntityReference {
                source: source.clone(),
                entity_index: u32::try_from(index).map_err(|_| KnowledgeError::InvalidInput)?,
            };
            let key =
                serde_json::to_string(&reference).map_err(|_| KnowledgeError::InvalidInput)?;
            nodes.insert(key.clone(), reference);
            keys.push(key);
        }
        for relation in &audited.projection.relationships {
            let from = keys.get(relation.source_index as usize);
            let to = keys.get(relation.target_index as usize);
            let (Some(from), Some(to)) = (from, to) else {
                return Err(KnowledgeError::InvalidInput);
            };
            // Unit weights use declared graph structure; model confidence does
            // not independently decide semantic quality or eligibility.
            edges.push(CommunityEdge::unit(from.min(to), from.max(to)));
        }
    }
    edges.sort_by(|a, b| a.source.cmp(&b.source).then(a.target.cmp(&b.target)));
    Ok(detect_communities(
        &nodes.keys().cloned().collect::<Vec<_>>(),
        &edges,
        snapshot.min_community_size,
    )
    .into_iter()
    .map(|group| group.members.iter().map(|key| nodes[key].clone()).collect())
    .collect())
}
