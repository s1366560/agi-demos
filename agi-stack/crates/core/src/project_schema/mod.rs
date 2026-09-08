//! Portable schema snapshots. No persistence, authorization, transport, or semantic policy.

mod strict_json;
mod validation;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
use strict_json::StrictJson;

pub const MAX_DOCUMENT_BYTES: usize = 1_048_576;
pub const MAX_REVISION: u32 = i32::MAX as u32;
pub const MAX_MEMBERS: usize = 1_024;
pub const MAX_SCHEMA_NODES: usize = 1_024;
pub const MAX_SCHEMA_TEXT_BYTES: usize = 16_384;
pub const MAX_SCHEMA_DEPTH: usize = 16;
pub const MAX_SAFE_NUMBER: f64 = 9_007_199_254_740_991.0;

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum ProjectSchemaError {
    #[error("project_schema_document_invalid")]
    InvalidDocument,
    #[error("project_schema_transition_invalid")]
    InvalidTransition,
    #[error("project_schema_revision_conflict")]
    RevisionConflict,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SchemaStatus {
    Enabled,
    Disabled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SchemaMemberKind {
    EntityType,
    EdgeType,
    Mapping,
}

/// A declared type. Names and schema keyword meanings are not interpreted here.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SchemaTypeDefinition {
    pub id: String,
    pub name: String,
    pub description: String,
    pub schema: Value,
    pub status: SchemaStatus,
    pub source: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SchemaMapping {
    pub id: String,
    pub source_type_id: String,
    pub target_type_id: String,
    pub edge_type_id: String,
    pub status: SchemaStatus,
    pub source: String,
}

/// Retained forever within this schema identity; not a reusable member slot.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SchemaTombstone {
    pub id: String,
    pub kind: SchemaMemberKind,
    pub deleted_revision: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawDocument {
    format_version: u32,
    tenant_id: String,
    project_id: String,
    schema_id: String,
    revision: u32,
    deleted: bool,
    entity_types: Vec<SchemaTypeDefinition>,
    edge_types: Vec<SchemaTypeDefinition>,
    mappings: Vec<SchemaMapping>,
    tombstones: Vec<SchemaTombstone>,
}

/// Immutable validated snapshot. Parsing is the only public construction path.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(transparent)]
pub struct ProjectSchemaDocument {
    raw: RawDocument,
}

impl ProjectSchemaDocument {
    /// Parse a bounded, strict JSON snapshot without granting authority to use it.
    ///
    /// # Errors
    /// Rejects malformed shapes, duplicate keys/IDs, dangling references and size violations.
    pub fn from_json(raw: &str) -> Result<Self, ProjectSchemaError> {
        if raw.len() > MAX_DOCUMENT_BYTES {
            return Err(ProjectSchemaError::InvalidDocument);
        }
        let parsed: StrictJson =
            serde_json::from_str(raw).map_err(|_| ProjectSchemaError::InvalidDocument)?;
        let raw: RawDocument =
            serde_json::from_value(parsed.0).map_err(|_| ProjectSchemaError::InvalidDocument)?;
        validation::validate(&raw)?;
        Ok(Self { raw })
    }

    pub fn to_value(&self) -> Value {
        // All fields are JSON-compatible and arbitrary numbers passed finite/range checks.
        serde_json::to_value(&self.raw).expect("validated schema is serializable")
    }

    pub fn schema_id(&self) -> &str {
        &self.raw.schema_id
    }

    pub fn tenant_id(&self) -> &str {
        &self.raw.tenant_id
    }

    pub fn project_id(&self) -> &str {
        &self.raw.project_id
    }

    pub fn revision(&self) -> u32 {
        self.raw.revision
    }

    pub fn is_deleted(&self) -> bool {
        self.raw.deleted
    }

    pub fn entity_types(&self) -> &[SchemaTypeDefinition] {
        &self.raw.entity_types
    }

    pub fn edge_types(&self) -> &[SchemaTypeDefinition] {
        &self.raw.edge_types
    }

    pub fn mappings(&self) -> &[SchemaMapping] {
        &self.raw.mappings
    }

    pub fn tombstones(&self) -> &[SchemaTombstone] {
        &self.raw.tombstones
    }

    /// Validate adjacent snapshots. A future repository must enforce CAS atomically.
    ///
    /// # Errors
    /// Reports revision conflicts separately from illegal scope/identity/tombstone transitions.
    pub fn validate_successor(
        &self,
        previous: Option<&Self>,
        expected_revision: u32,
    ) -> Result<(), ProjectSchemaError> {
        let next = &self.raw;
        let base = previous.map_or(0, |document| document.raw.revision);
        if expected_revision != base || base >= MAX_REVISION || next.revision != base + 1 {
            return Err(ProjectSchemaError::RevisionConflict);
        }
        let Some(previous) = previous else {
            return if next.deleted || !next.tombstones.is_empty() {
                Err(ProjectSchemaError::InvalidTransition)
            } else {
                Ok(())
            };
        };
        let old = &previous.raw;
        if old.deleted
            || old.tenant_id != next.tenant_id
            || old.project_id != next.project_id
            || old.schema_id != next.schema_id
        {
            return Err(ProjectSchemaError::InvalidTransition);
        }
        let old_live = live_members(old);
        let new_live = live_members(next);
        let old_dead: BTreeMap<_, _> = old.tombstones.iter().map(|t| (t.id.as_str(), t)).collect();
        let new_dead: BTreeMap<_, _> = next.tombstones.iter().map(|t| (t.id.as_str(), t)).collect();
        let retained = old_dead
            .iter()
            .all(|(id, item)| new_dead.get(id) == Some(item));
        let stable = new_live.iter().all(|(id, kind)| {
            !old_dead.contains_key(id)
                && match old_live.get(id) {
                    Some(old_kind) => old_kind == kind,
                    None => true,
                }
        });
        let removed = old_live.iter().all(|(id, kind)| {
            new_live.contains_key(id)
                || new_dead.get(id).is_some_and(|item| {
                    item.kind == *kind && item.deleted_revision == next.revision
                })
        });
        let introduced = new_dead.iter().all(|(id, item)| {
            old_dead.contains_key(id)
                || (old_live.get(id) == Some(&item.kind) && item.deleted_revision == next.revision)
        });
        if retained && stable && removed && introduced {
            Ok(())
        } else {
            Err(ProjectSchemaError::InvalidTransition)
        }
    }
}

fn live_members(document: &RawDocument) -> BTreeMap<&str, SchemaMemberKind> {
    document
        .entity_types
        .iter()
        .map(|m| (m.id.as_str(), SchemaMemberKind::EntityType))
        .chain(
            document
                .edge_types
                .iter()
                .map(|m| (m.id.as_str(), SchemaMemberKind::EdgeType)),
        )
        .chain(
            document
                .mappings
                .iter()
                .map(|m| (m.id.as_str(), SchemaMemberKind::Mapping)),
        )
        .collect()
}
