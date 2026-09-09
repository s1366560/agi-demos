//! Durable schema transfer intent and accepted mappings under the existing sync binding.
//! Parsing/projection does not establish source authenticity or grant operation authority.

use agistack_core::project_schema::cloud_rpc::CloudSchemaReceipt;

use super::{
    change_id_valid, identifier, scope_valid, Current, ProjectSchemaStorageError,
    ProjectSchemaStorageResult,
};

mod apply;
mod cloud;
mod cursor;
mod prepared;
mod schema;
pub(in super::super) use schema::migrate;
mod types;

pub use types::{
    ProjectSchemaSyncAnchor, ProjectSchemaSyncAnchorKind, ProjectSchemaSyncBinding,
    ProjectSchemaSyncImportedSide, ProjectSchemaSyncPrepared, ProjectSchemaSyncState,
    ProjectSchemaSyncStepKind,
};

#[cfg(test)]
#[path = "sync/tests.rs"]
mod tests;

fn binding_valid(binding: &ProjectSchemaSyncBinding) -> ProjectSchemaStorageResult<()> {
    scope_valid(&binding.scope)?;
    identifier(&binding.authority)?;
    identifier(&binding.remote_tenant_id)?;
    identifier(&binding.remote_project_id)?;
    identifier(&binding.remote_actor_id)?;
    change_id_valid(&binding.sync_key)?;
    change_id_valid(&binding.schema_id)
}

/// A presented cloud receipt must belong to this binding's exact remote scope
/// and schema identity, regardless of the scope its parser was handed.
fn remote_scoped(
    binding: &ProjectSchemaSyncBinding,
    receipt: &CloudSchemaReceipt,
) -> ProjectSchemaStorageResult<()> {
    if receipt.document().tenant_id() != binding.remote_tenant_id
        || receipt.document().project_id() != binding.remote_project_id
        || receipt.document().schema_id() != binding.schema_id
    {
        return Err(ProjectSchemaStorageError::ScopeMismatch);
    }
    Ok(())
}
