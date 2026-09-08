//! Portable user content owned by the scoped knowledge authority.
//! Legacy `model::Memory` remains a separate, unchanged boundary.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::model::Entity;

/// Persisted local document, including user metadata. Derived entities and
/// embeddings remain local projections and are excluded from the sync content.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KnowledgeMemory {
    pub id: String,
    pub project_id: String,
    pub title: String,
    pub content: String,
    pub author_id: String,
    pub content_type: String,
    pub tags: Vec<String>,
    #[serde(default)]
    pub metadata: Map<String, Value>,
    pub entities: Vec<Entity>,
    pub version: u32,
    pub status: String,
    pub created_at_ms: i64,
    #[serde(default)]
    pub embedding: Option<Vec<f32>>,
}

/// Commands must distinguish an explicit empty object from an omitted field.
/// Stored historical documents alone may use the serde default during upgrade.
pub(super) fn deserialize_mutation_memory<'de, D>(
    deserializer: D,
) -> Result<KnowledgeMemory, D::Error>
where
    D: serde::Deserializer<'de>,
{
    use serde::de::Error;
    let value = Value::deserialize(deserializer)?;
    if value.get("metadata").is_none() {
        return Err(D::Error::missing_field("metadata"));
    }
    serde_json::from_value(value).map_err(D::Error::custom)
}
