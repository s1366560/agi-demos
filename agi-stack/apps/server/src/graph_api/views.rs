use serde::{Deserialize, Serialize};
use serde_json::Value;

use agistack_core::model::{GraphEntity, Relationship};

use super::{now_ms, rfc3339};

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(super) struct EntityView {
    pub(super) uuid: String,
    pub(super) name: String,
    pub(super) entity_type: String,
    pub(super) summary: String,
    pub(super) tenant_id: Option<String>,
    pub(super) project_id: String,
    pub(super) created_at: String,
}

impl From<GraphEntity> for EntityView {
    fn from(entity: GraphEntity) -> Self {
        Self {
            uuid: entity.uuid,
            name: entity.name,
            entity_type: entity.entity_type,
            summary: entity.summary,
            tenant_id: entity.tenant_id,
            project_id: entity.project_id,
            created_at: rfc3339(entity.created_at_ms),
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct EntityPage {
    pub(super) entities: Vec<EntityView>,
    pub(super) total: usize,
    pub(super) limit: usize,
    pub(super) offset: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(super) struct EntityTypeCount {
    pub(super) entity_type: String,
    pub(super) count: usize,
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct EntityTypesResponse {
    pub(super) entity_types: Vec<EntityTypeCount>,
    pub(super) total: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(super) struct RelationshipView {
    pub(super) uuid: String,
    pub(super) source_uuid: String,
    pub(super) target_uuid: String,
    pub(super) relation_type: String,
    pub(super) fact: String,
    pub(super) score: f32,
    pub(super) project_id: String,
    pub(super) created_at: String,
}

impl From<Relationship> for RelationshipView {
    fn from(rel: Relationship) -> Self {
        Self {
            uuid: rel.uuid,
            source_uuid: rel.source_uuid,
            target_uuid: rel.target_uuid,
            relation_type: rel.relation_type,
            fact: rel.fact,
            score: rel.score,
            project_id: rel.project_id,
            created_at: rfc3339(rel.created_at_ms),
        }
    }
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct EntityRelationships {
    pub(super) relationships: Vec<Value>,
    pub(super) total: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(super) struct CommunityView {
    pub(super) uuid: String,
    pub(super) name: String,
    pub(super) summary: String,
    pub(super) member_count: usize,
    pub(super) tenant_id: Option<String>,
    pub(super) project_id: String,
    pub(super) formed_at: Option<String>,
    pub(super) created_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(super) struct CommunityPage {
    pub(super) communities: Vec<CommunityView>,
    pub(super) total: usize,
    pub(super) limit: usize,
    pub(super) offset: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(super) struct CommunityMembers {
    pub(super) members: Vec<EntityView>,
    pub(super) total: usize,
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct RebuildCommunitiesResponse {
    pub(super) status: String,
    pub(super) message: String,
    pub(super) communities_count: usize,
    pub(super) entities_processed: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) job_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) job_status: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) event_topic: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) requested_event_id: Option<String>,
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct RebuildCommunityJobStatusResponse {
    pub(super) job_id: String,
    pub(super) project_id: String,
    pub(super) job_status: String,
    pub(super) event_topic: String,
    pub(super) latest_event_id: String,
    pub(super) events: Vec<RebuildCommunityJobEventView>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) communities_count: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) entities_processed: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) persisted_communities_count: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) error: Option<String>,
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct RebuildCommunityJobEventView {
    pub(super) event_id: String,
    pub(super) event_type: String,
    pub(super) job_status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) created_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) started_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) completed_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) failed_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) communities_count: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) entities_processed: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) persisted_communities_count: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) error: Option<String>,
}

#[derive(Debug, Deserialize)]
pub(super) struct EntityQuery {
    pub(super) project_id: Option<String>,
    pub(super) q: Option<String>,
    pub(super) limit: Option<usize>,
    pub(super) offset: Option<usize>,
}

#[derive(Debug, Deserialize)]
pub(super) struct CommunityQuery {
    pub(super) project_id: Option<String>,
    pub(super) min_members: Option<usize>,
    pub(super) limit: Option<usize>,
    pub(super) offset: Option<usize>,
}

#[derive(Debug, Deserialize)]
pub(super) struct RebuildCommunitiesQuery {
    pub(super) project_id: Option<String>,
    #[serde(default)]
    pub(super) background: bool,
}

#[derive(Debug, Deserialize)]
pub(super) struct RebuildCommunityJobQuery {
    pub(super) project_id: Option<String>,
}

#[derive(Debug, Deserialize)]
pub(super) struct EntityPathQuery {
    pub(super) project_id: Option<String>,
}

#[derive(Debug, Deserialize)]
pub(super) struct RelationshipQuery {
    pub(super) project_id: Option<String>,
    pub(super) limit: Option<usize>,
}

#[derive(Debug, Deserialize)]
pub(super) struct CommunityMembersQuery {
    pub(super) project_id: Option<String>,
    pub(super) limit: Option<usize>,
}

#[derive(Debug, Deserialize)]
pub(super) struct GraphExportQuery {
    pub(super) project_id: Option<String>,
    pub(super) limit: Option<usize>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(super) struct GraphExportStats {
    pub(super) entities_count: usize,
    pub(super) relationships_count: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(super) struct GraphExportResponse {
    pub(super) version: u32,
    pub(super) project_id: String,
    pub(super) exported_at: String,
    pub(super) entities: Vec<EntityUpsertPayload>,
    pub(super) relationships: Vec<RelationshipUpsertPayload>,
    pub(super) stats: GraphExportStats,
}

#[derive(Debug, Clone, Deserialize)]
pub(super) struct GraphImportPayload {
    pub(super) version: u32,
    pub(super) project_id: String,
    #[serde(default)]
    pub(super) entities: Vec<EntityUpsertPayload>,
    #[serde(default)]
    pub(super) relationships: Vec<RelationshipUpsertPayload>,
}

#[derive(Debug, Serialize, PartialEq)]
pub(super) struct GraphImportResponse {
    pub(super) status: String,
    pub(super) message: String,
    pub(super) version: u32,
    pub(super) project_id: String,
    pub(super) entities_imported: usize,
    pub(super) relationships_imported: usize,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub(super) struct EntityUpsertPayload {
    pub(super) uuid: String,
    pub(super) name: String,
    pub(super) entity_type: String,
    #[serde(default)]
    pub(super) summary: String,
    pub(super) project_id: String,
    #[serde(default)]
    pub(super) tenant_id: Option<String>,
    #[serde(default)]
    pub(super) created_at_ms: Option<i64>,
    #[serde(default)]
    pub(super) name_embedding: Option<Vec<f32>>,
}

impl EntityUpsertPayload {
    pub(super) fn from_entity(entity: GraphEntity) -> Self {
        Self {
            uuid: entity.uuid,
            name: entity.name,
            entity_type: entity.entity_type,
            summary: entity.summary,
            project_id: entity.project_id,
            tenant_id: entity.tenant_id,
            created_at_ms: Some(entity.created_at_ms),
            name_embedding: entity.name_embedding,
        }
    }

    pub(super) fn into_entity(self) -> GraphEntity {
        GraphEntity {
            uuid: self.uuid,
            name: self.name,
            entity_type: self.entity_type,
            summary: self.summary,
            project_id: self.project_id,
            tenant_id: self.tenant_id,
            created_at_ms: self.created_at_ms.unwrap_or_else(now_ms),
            name_embedding: self.name_embedding,
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub(super) struct RelationshipUpsertPayload {
    pub(super) uuid: String,
    pub(super) source_uuid: String,
    pub(super) target_uuid: String,
    #[serde(default = "default_relation_type")]
    pub(super) relation_type: String,
    #[serde(default)]
    pub(super) fact: String,
    #[serde(default = "default_score")]
    pub(super) score: f32,
    pub(super) project_id: String,
    #[serde(default)]
    pub(super) created_at_ms: Option<i64>,
}

fn default_relation_type() -> String {
    "MENTIONS".to_string()
}

fn default_score() -> f32 {
    1.0
}

impl RelationshipUpsertPayload {
    pub(super) fn from_relationship(rel: Relationship) -> Self {
        Self {
            uuid: rel.uuid,
            source_uuid: rel.source_uuid,
            target_uuid: rel.target_uuid,
            relation_type: rel.relation_type,
            fact: rel.fact,
            score: rel.score,
            project_id: rel.project_id,
            created_at_ms: Some(rel.created_at_ms),
        }
    }

    pub(super) fn into_relationship(self) -> Relationship {
        Relationship {
            uuid: self.uuid,
            source_uuid: self.source_uuid,
            target_uuid: self.target_uuid,
            relation_type: self.relation_type,
            fact: self.fact,
            score: self.score,
            project_id: self.project_id,
            created_at_ms: self.created_at_ms.unwrap_or_else(now_ms),
        }
    }
}

#[derive(Debug, Deserialize)]
pub(super) struct SubgraphRequest {
    pub(super) node_uuids: Vec<String>,
    #[serde(default = "default_include_neighbors")]
    pub(super) include_neighbors: bool,
    #[serde(default = "default_subgraph_limit")]
    pub(super) limit: usize,
    #[serde(default)]
    pub(super) project_id: Option<String>,
    #[serde(default)]
    pub(super) tenant_id: Option<String>,
}

fn default_include_neighbors() -> bool {
    true
}

fn default_subgraph_limit() -> usize {
    100
}
