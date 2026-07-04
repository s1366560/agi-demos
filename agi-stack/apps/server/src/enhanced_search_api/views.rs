use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use agistack_core::model::GraphEntity;

use super::rfc3339;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(super) struct SearchResult {
    pub(super) uuid: String,
    pub(super) name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) summary: Option<String>,
    pub(super) content: String,
    #[serde(rename = "type")]
    pub(super) kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) entity_type: Option<String>,
    pub(super) score: f32,
    pub(super) created_at: String,
    pub(super) metadata: Value,
}

impl SearchResult {
    pub(super) fn from_entity(entity: GraphEntity, score: f32, kind: &str) -> Self {
        let created_at = rfc3339(entity.created_at_ms);
        let uuid = entity.uuid;
        let name = entity.name;
        let entity_type = entity.entity_type;
        let content = if entity.summary.is_empty() {
            name.clone()
        } else {
            entity.summary.clone()
        };
        Self {
            uuid: uuid.clone(),
            name: name.clone(),
            summary: Some(entity.summary.clone()),
            content,
            kind: kind.to_string(),
            entity_type: Some(entity_type.clone()),
            score,
            created_at: created_at.clone(),
            metadata: json!({
                "uuid": uuid,
                "name": name,
                "type": entity_type.clone(),
                "entity_type": entity_type,
                "created_at": created_at,
            }),
        }
    }

    pub(super) fn advanced(entity: GraphEntity, score: f32) -> Value {
        let content = if entity.summary.is_empty() {
            entity.name.clone()
        } else {
            entity.summary.clone()
        };
        json!({
            "content": content,
            "score": score,
            "source": "Knowledge Graph",
            "type": "Entity",
            "metadata": {
                "uuid": entity.uuid,
                "name": entity.name,
                "entity_type": entity.entity_type,
            },
        })
    }
}

#[derive(Debug, Deserialize)]
pub(super) struct AdvancedSearchRequest {
    pub(super) query: String,
    #[serde(default = "default_strategy")]
    pub(super) strategy: String,
    #[serde(default)]
    pub(super) focal_node_uuid: Option<String>,
    #[serde(default)]
    pub(super) reranker: Option<String>,
    #[serde(default)]
    pub(super) tenant_id: Option<String>,
    #[serde(default)]
    pub(super) project_id: Option<String>,
    #[serde(default)]
    pub(super) since: Option<String>,
    #[serde(default)]
    pub(super) limit: Option<usize>,
}

pub(super) fn default_strategy() -> String {
    "COMBINED_HYBRID_SEARCH_RRF".to_string()
}

#[derive(Debug, Deserialize)]
pub(super) struct TraversalSearchRequest {
    pub(super) start_entity_uuid: String,
    #[serde(default = "default_depth")]
    pub(super) max_depth: usize,
    #[serde(default)]
    pub(super) relationship_types: Option<Vec<String>>,
    #[serde(default)]
    pub(super) limit: Option<usize>,
    #[serde(default)]
    pub(super) tenant_id: Option<String>,
    #[serde(default)]
    pub(super) project_id: Option<String>,
}

pub(super) fn default_depth() -> usize {
    2
}

#[derive(Debug, Deserialize)]
pub(super) struct CommunitySearchRequest {
    pub(super) community_uuid: String,
    #[serde(default)]
    pub(super) limit: Option<usize>,
    #[serde(default = "default_include_episodes")]
    pub(super) include_episodes: bool,
    #[serde(default)]
    pub(super) project_id: Option<String>,
}

pub(super) fn default_include_episodes() -> bool {
    true
}

#[derive(Debug, Deserialize)]
pub(super) struct TemporalSearchRequest {
    pub(super) query: String,
    #[serde(default)]
    pub(super) since: Option<String>,
    #[serde(default)]
    pub(super) until: Option<String>,
    #[serde(default)]
    pub(super) limit: Option<usize>,
    #[serde(default)]
    pub(super) tenant_id: Option<String>,
    #[serde(default)]
    pub(super) project_id: Option<String>,
}

#[derive(Debug, Deserialize)]
pub(super) struct FacetedSearchRequest {
    pub(super) query: String,
    #[serde(default)]
    pub(super) entity_types: Option<Vec<String>>,
    #[serde(default)]
    pub(super) tags: Option<Vec<String>>,
    #[serde(default)]
    pub(super) since: Option<String>,
    #[serde(default)]
    pub(super) limit: Option<usize>,
    #[serde(default)]
    pub(super) offset: Option<usize>,
    #[serde(default)]
    pub(super) tenant_id: Option<String>,
    #[serde(default)]
    pub(super) project_id: Option<String>,
}

#[derive(Debug, Deserialize)]
pub(super) struct MemorySearchRequest {
    pub(super) query: String,
    #[serde(default)]
    pub(super) limit: Option<usize>,
    #[serde(default)]
    pub(super) project_id: Option<String>,
}
