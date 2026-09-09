//! Structural history projection between explicitly chosen schema scopes.
//!
//! Callers must prove receipt authenticity, authorize the existing project binding,
//! choose direction explicitly and enforce destination CAS. These functions grant
//! none of those rights and never choose a winner or reconcile different content.

use std::collections::BTreeMap;

use super::{
    validation, ProjectSchemaDocument, ProjectSchemaError, SchemaTypeDefinition, MAX_REVISION,
};

fn same_types(left: &[SchemaTypeDefinition], right: &[SchemaTypeDefinition]) -> bool {
    fn by_id(items: &[SchemaTypeDefinition]) -> BTreeMap<&str, &SchemaTypeDefinition> {
        items
            .iter()
            .map(|item| (item.id.as_str(), item))
            .collect::<BTreeMap<_, _>>()
    }
    by_id(left) == by_id(right)
}

/// Compare complete content by stable member ID, ignoring only scope, revision,
/// array order and the side-specific revision at which each tombstone was accepted.
/// Matching schema IDs alone are never a sufficient baseline.
pub fn equivalent_content(left: &ProjectSchemaDocument, right: &ProjectSchemaDocument) -> bool {
    left.schema_id() == right.schema_id()
        && left.is_deleted() == right.is_deleted()
        && same_types(left.entity_types(), right.entity_types())
        && same_types(left.edge_types(), right.edge_types())
        && left
            .mappings()
            .iter()
            .map(|item| (item.id.as_str(), item))
            .collect::<BTreeMap<_, _>>()
            == right
                .mappings()
                .iter()
                .map(|item| (item.id.as_str(), item))
                .collect::<BTreeMap<_, _>>()
        && left
            .tombstones()
            .iter()
            .map(|item| (item.id.as_str(), item.kind))
            .collect::<BTreeMap<_, _>>()
            == right
                .tombstones()
                .iter()
                .map(|item| (item.id.as_str(), item.kind))
                .collect::<BTreeMap<_, _>>()
}

/// Project a live revision-1 root into a caller-authorized destination scope.
///
/// # Errors
/// Rejects later snapshots, tombstones, terminal roots and invalid destination scope.
pub fn project_bootstrap(
    source_root: &ProjectSchemaDocument,
    tenant_id: &str,
    project_id: &str,
) -> Result<ProjectSchemaDocument, ProjectSchemaError> {
    source_root.validate_successor(None, 0)?;
    let mut raw = source_root.raw.clone();
    raw.tenant_id = tenant_id.to_owned();
    raw.project_id = project_id.to_owned();
    validation::validate(&raw)?;
    Ok(ProjectSchemaDocument { raw })
}

/// Seed initialization only: transfer a source root after an accepted empty root.
/// The seed itself does not prove a source/destination pair.
///
/// # Errors
/// Rejects non-root snapshots, nonempty seeds and different schema identities.
pub fn project_root_after_empty_seed(
    source_root: &ProjectSchemaDocument,
    destination_seed: &ProjectSchemaDocument,
) -> Result<ProjectSchemaDocument, ProjectSchemaError> {
    source_root.validate_successor(None, 0)?;
    destination_seed.validate_successor(None, 0)?;
    if source_root.schema_id() != destination_seed.schema_id()
        || !destination_seed.entity_types().is_empty()
        || !destination_seed.edge_types().is_empty()
        || !destination_seed.mappings().is_empty()
    {
        return Err(ProjectSchemaError::InvalidTransition);
    }
    let mut projected = project_bootstrap(
        source_root,
        destination_seed.tenant_id(),
        destination_seed.project_id(),
    )?;
    projected.raw.revision = destination_seed.revision() + 1;
    validation::validate(&projected.raw)?;
    projected.validate_successor(Some(destination_seed), destination_seed.revision())?;
    Ok(projected)
}

/// Transfer exactly one adjacent accepted source transition from an equivalent pair.
/// Old destination tombstones retain their original deletion revision; only newly
/// introduced deletions receive the next destination revision.
///
/// # Errors
/// Rejects source history gaps, incompatible baselines, illegal transitions and
/// exhausted destination counters. No latest-snapshot copying or rebase is performed.
pub fn project_successor(
    source_base: &ProjectSchemaDocument,
    source_next: &ProjectSchemaDocument,
    destination_base: &ProjectSchemaDocument,
) -> Result<ProjectSchemaDocument, ProjectSchemaError> {
    source_next.validate_successor(Some(source_base), source_base.revision())?;
    if !equivalent_content(source_base, destination_base) {
        return Err(ProjectSchemaError::InvalidTransition);
    }
    if destination_base.revision() >= MAX_REVISION {
        return Err(ProjectSchemaError::RevisionConflict);
    }
    let next_revision = destination_base.revision() + 1;
    let old_tombstones: BTreeMap<_, _> = destination_base
        .tombstones()
        .iter()
        .map(|item| (item.id.as_str(), item))
        .collect();
    let mut raw = source_next.raw.clone();
    raw.tenant_id = destination_base.tenant_id().to_owned();
    raw.project_id = destination_base.project_id().to_owned();
    raw.revision = next_revision;
    for tombstone in &mut raw.tombstones {
        tombstone.deleted_revision = old_tombstones
            .get(tombstone.id.as_str())
            .map_or(next_revision, |old| old.deleted_revision);
    }
    validation::validate(&raw)?;
    let projected = ProjectSchemaDocument { raw };
    projected.validate_successor(Some(destination_base), destination_base.revision())?;
    Ok(projected)
}
