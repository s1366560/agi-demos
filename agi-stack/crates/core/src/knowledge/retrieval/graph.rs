use super::{Entity, ProcessingRelationship, ProcessingSource};
use serde::{Deserialize, Serialize};

/// One complete projection and source payload read from the same audited source.
/// Array positions identify nodes and edges within this exact source and attempt;
/// equal entity names do not imply shared identity.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RetrievedSourceGraph {
    pub source: ProcessingSource,
    pub audit_attempt: u32,
    pub title: String,
    pub content: String,
    pub entities: Vec<Entity>,
    pub relationships: Vec<ProcessingRelationship>,
}
