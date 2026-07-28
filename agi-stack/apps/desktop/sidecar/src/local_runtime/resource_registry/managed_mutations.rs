use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};

use super::{
    schema::iso_from_millis, ManagedResourceKind, ManagedResourceMutationCommand,
    ManagedResourceMutationOperation, ManagedResourceMutationReceipt, ManagedResourceVersion,
    ResourceRegistryError,
};

pub(super) struct StoredManagedResource {
    pub(super) status: String,
    pub(super) revision: u64,
    pub(super) created_at_ms: i64,
    pub(super) value: Value,
    pub(super) vault_refs: Vec<String>,
}

pub(super) fn validate_managed_resource_mutation(
    command: &ManagedResourceMutationCommand,
) -> Result<(), ResourceRegistryError> {
    if !matches!(command.scope_kind.as_str(), "tenant" | "project") {
        return Err(ResourceRegistryError::InvalidMutation(
            "managed resource scope_kind must be tenant or project".to_string(),
        ));
    }
    for (field, value) in [
        ("actor_id", command.actor_id.as_str()),
        ("scope_id", command.scope_id.as_str()),
        ("resource_id", command.resource_id.as_str()),
        ("idempotency_key", command.idempotency_key.as_str()),
        ("payload_hash", command.payload_hash.as_str()),
    ] {
        if value.trim().is_empty() {
            return Err(ResourceRegistryError::InvalidMutation(format!(
                "managed resource {field} cannot be empty"
            )));
        }
    }
    if command
        .vault_refs
        .iter()
        .any(|reference| !reference.starts_with("vault://") || reference.trim().len() <= 8)
    {
        return Err(ResourceRegistryError::InvalidMutation(
            "managed resource vault_refs must contain only vault:// references".to_string(),
        ));
    }
    match command.operation {
        ManagedResourceMutationOperation::Create
        | ManagedResourceMutationOperation::Update
        | ManagedResourceMutationOperation::Import => {
            if command.value.as_ref().and_then(Value::as_object).is_none() {
                return Err(ResourceRegistryError::InvalidMutation(
                    "managed resource create, update, and import require an object value"
                        .to_string(),
                ));
            }
            if command.status.trim().is_empty() || command.status == "deleted" {
                return Err(ResourceRegistryError::InvalidMutation(
                    "managed resource mutation requires a non-deleted status".to_string(),
                ));
            }
        }
        ManagedResourceMutationOperation::Rollback => {
            if command.target_revision.is_none() || command.value.is_some() {
                return Err(ResourceRegistryError::InvalidMutation(
                    "managed resource rollback requires target_revision and no value".to_string(),
                ));
            }
        }
        ManagedResourceMutationOperation::Delete => {
            if command.value.is_some() || command.status != "deleted" {
                return Err(ResourceRegistryError::InvalidMutation(
                    "managed resource delete requires status deleted and no value".to_string(),
                ));
            }
        }
    }
    Ok(())
}

pub(super) fn query_managed_resource_receipt(
    transaction: &rusqlite::Transaction<'_>,
    command: &ManagedResourceMutationCommand,
) -> Result<Option<ManagedResourceMutationReceipt>, ResourceRegistryError> {
    let stored = transaction
        .query_row(
            "SELECT payload_hash, operation, resource_id, response_json
             FROM desktop_managed_resource_receipts
             WHERE actor_id = ?1 AND kind = ?2 AND scope_kind = ?3 AND scope_id = ?4
               AND idempotency_key = ?5",
            params![
                command.actor_id,
                command.kind.as_str(),
                command.scope_kind,
                command.scope_id,
                command.idempotency_key,
            ],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                ))
            },
        )
        .optional()
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    let Some((payload_hash, operation, resource_id, response_json)) = stored else {
        return Ok(None);
    };
    if payload_hash != command.payload_hash
        || operation != command.operation.as_str()
        || resource_id != command.resource_id
    {
        return Err(ResourceRegistryError::IdempotencyConflict);
    }
    let mut receipt: ManagedResourceMutationReceipt = serde_json::from_str(&response_json)
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    receipt.duplicate = true;
    Ok(Some(receipt))
}

pub(super) fn query_stored_managed_resource(
    transaction: &rusqlite::Transaction<'_>,
    kind: ManagedResourceKind,
    scope_kind: &str,
    scope_id: &str,
    resource_id: &str,
) -> Result<Option<StoredManagedResource>, ResourceRegistryError> {
    let stored = transaction
        .query_row(
            "SELECT status, revision, created_at_ms, value_json, vault_refs_json
             FROM desktop_managed_resources
             WHERE kind = ?1 AND scope_kind = ?2 AND scope_id = ?3 AND id = ?4",
            params![kind.as_str(), scope_kind, scope_id, resource_id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, u64>(1)?,
                    row.get::<_, i64>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                ))
            },
        )
        .optional()
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    stored
        .map(
            |(status, revision, created_at_ms, value_json, vault_refs_json)| {
                Ok(StoredManagedResource {
                    status,
                    revision,
                    created_at_ms,
                    value: serde_json::from_str(&value_json)
                        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?,
                    vault_refs: serde_json::from_str(&vault_refs_json)
                        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?,
                })
            },
        )
        .transpose()
}

pub(super) fn validate_mutation_authority(
    command: &ManagedResourceMutationCommand,
    current: Option<&StoredManagedResource>,
) -> Result<(), ResourceRegistryError> {
    match command.operation {
        ManagedResourceMutationOperation::Create => {
            if current.is_some() {
                return Err(ResourceRegistryError::AlreadyExists);
            }
            if command.expected_revision != 0 {
                return Err(ResourceRegistryError::RevisionConflict {
                    expected: command.expected_revision,
                    actual: 0,
                });
            }
        }
        ManagedResourceMutationOperation::Import => {
            let actual = current.map(|resource| resource.revision).unwrap_or(0);
            if command.expected_revision != actual {
                return Err(ResourceRegistryError::RevisionConflict {
                    expected: command.expected_revision,
                    actual,
                });
            }
        }
        ManagedResourceMutationOperation::Update
        | ManagedResourceMutationOperation::Delete
        | ManagedResourceMutationOperation::Rollback => {
            let current = current.ok_or(ResourceRegistryError::NotFound)?;
            if command.operation != ManagedResourceMutationOperation::Rollback
                && current.status == "deleted"
            {
                return Err(ResourceRegistryError::NotFound);
            }
            if command.expected_revision != current.revision {
                return Err(ResourceRegistryError::RevisionConflict {
                    expected: command.expected_revision,
                    actual: current.revision,
                });
            }
        }
    }
    Ok(())
}

pub(super) fn resolve_mutation_value(
    transaction: &rusqlite::Transaction<'_>,
    command: &ManagedResourceMutationCommand,
    current: Option<&StoredManagedResource>,
) -> Result<(Value, Vec<String>, bool), ResourceRegistryError> {
    match command.operation {
        ManagedResourceMutationOperation::Create
        | ManagedResourceMutationOperation::Update
        | ManagedResourceMutationOperation::Import => Ok((
            command.value.clone().ok_or_else(|| {
                ResourceRegistryError::InvalidMutation(
                    "managed resource mutation value is required".to_string(),
                )
            })?,
            command.vault_refs.clone(),
            false,
        )),
        ManagedResourceMutationOperation::Delete => {
            let current = current.ok_or(ResourceRegistryError::NotFound)?;
            Ok((Value::Null, current.vault_refs.clone(), true))
        }
        ManagedResourceMutationOperation::Rollback => {
            let target_revision = command.target_revision.ok_or_else(|| {
                ResourceRegistryError::InvalidMutation(
                    "managed resource rollback target_revision is required".to_string(),
                )
            })?;
            let version = query_managed_resource_version(
                transaction,
                command.kind,
                &command.scope_kind,
                &command.scope_id,
                &command.resource_id,
                target_revision,
            )?
            .ok_or(ResourceRegistryError::NotFound)?;
            if version.tombstone {
                return Err(ResourceRegistryError::InvalidMutation(
                    "managed resource cannot roll back to a tombstone".to_string(),
                ));
            }
            Ok((version.value, version.vault_refs, false))
        }
    }
}

fn query_managed_resource_version(
    transaction: &rusqlite::Transaction<'_>,
    kind: ManagedResourceKind,
    scope_kind: &str,
    scope_id: &str,
    resource_id: &str,
    revision: u64,
) -> Result<Option<ManagedResourceVersion>, ResourceRegistryError> {
    let stored = transaction
        .query_row(
            "SELECT status, tombstone, value_json, vault_refs_json, created_at_ms
             FROM desktop_managed_resource_versions
             WHERE kind = ?1 AND scope_kind = ?2 AND scope_id = ?3
               AND resource_id = ?4 AND revision = ?5",
            params![kind.as_str(), scope_kind, scope_id, resource_id, revision],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, bool>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, i64>(4)?,
                ))
            },
        )
        .optional()
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    stored
        .map(
            |(status, tombstone, value_json, vault_refs_json, created_at_ms)| {
                Ok(ManagedResourceVersion {
                    revision,
                    status,
                    tombstone,
                    value: serde_json::from_str(&value_json)
                        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?,
                    vault_refs: serde_json::from_str(&vault_refs_json)
                        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?,
                    created_at_ms,
                })
            },
        )
        .transpose()
}

pub(super) fn stamp_managed_resource_value(
    value: &mut Value,
    resource_id: &str,
    status: &str,
    revision: u64,
    now_ms: i64,
) -> Result<(), ResourceRegistryError> {
    let object = value.as_object_mut().ok_or_else(|| {
        ResourceRegistryError::InvalidMutation(
            "managed resource mutation value must be an object".to_string(),
        )
    })?;
    object.insert("id".to_string(), json!(resource_id));
    object.insert("status".to_string(), json!(status));
    object.insert("revision".to_string(), json!(revision));
    let updated_at = iso_from_millis(now_ms);
    if revision == 0 {
        object
            .entry("created_at".to_string())
            .or_insert_with(|| json!(updated_at.clone()));
    }
    object.insert("updated_at".to_string(), json!(updated_at));
    Ok(())
}

pub(super) fn persist_managed_resource(
    transaction: &rusqlite::Transaction<'_>,
    command: &ManagedResourceMutationCommand,
    revision: u64,
    created_at_ms: i64,
    value: &Value,
    vault_refs: &[String],
) -> Result<(), ResourceRegistryError> {
    let value_json = serde_json::to_string(value)
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    let vault_refs_json = serde_json::to_string(vault_refs)
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    transaction
        .execute(
            "INSERT INTO desktop_managed_resources(
               kind, scope_kind, scope_id, id, status, revision,
               created_at_ms, updated_at_ms, value_json, vault_refs_json
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)
             ON CONFLICT(kind, scope_kind, scope_id, id) DO UPDATE SET
               status = excluded.status,
               revision = excluded.revision,
               updated_at_ms = excluded.updated_at_ms,
               value_json = excluded.value_json,
               vault_refs_json = excluded.vault_refs_json",
            params![
                command.kind.as_str(),
                command.scope_kind,
                command.scope_id,
                command.resource_id,
                if command.operation == ManagedResourceMutationOperation::Delete {
                    "deleted"
                } else {
                    command.status.as_str()
                },
                revision,
                created_at_ms,
                command.now_ms,
                value_json,
                vault_refs_json,
            ],
        )
        .map(|_| ())
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))
}

#[allow(clippy::too_many_arguments)]
pub(super) fn insert_managed_resource_version(
    transaction: &rusqlite::Transaction<'_>,
    kind: ManagedResourceKind,
    scope_kind: &str,
    scope_id: &str,
    resource_id: &str,
    revision: u64,
    status: &str,
    tombstone: bool,
    now_ms: i64,
    value: &Value,
    vault_refs_json: &str,
) -> Result<(), ResourceRegistryError> {
    let value_json = serde_json::to_string(value)
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    transaction
        .execute(
            "INSERT OR REPLACE INTO desktop_managed_resource_versions(
               kind, scope_kind, scope_id, resource_id, revision, status,
               tombstone, created_at_ms, value_json, vault_refs_json
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
            params![
                kind.as_str(),
                scope_kind,
                scope_id,
                resource_id,
                revision,
                status,
                tombstone,
                now_ms,
                value_json,
                vault_refs_json,
            ],
        )
        .map(|_| ())
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))
}

pub(super) fn insert_managed_resource_receipt(
    transaction: &rusqlite::Transaction<'_>,
    command: &ManagedResourceMutationCommand,
    receipt: &ManagedResourceMutationReceipt,
) -> Result<(), ResourceRegistryError> {
    let response_json = serde_json::to_string(receipt)
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    transaction
        .execute(
            "INSERT INTO desktop_managed_resource_receipts(
               actor_id, kind, scope_kind, scope_id, idempotency_key, payload_hash,
               operation, resource_id, response_json, created_at_ms
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
            params![
                command.actor_id,
                command.kind.as_str(),
                command.scope_kind,
                command.scope_id,
                command.idempotency_key,
                command.payload_hash,
                command.operation.as_str(),
                command.resource_id,
                response_json,
                command.now_ms,
            ],
        )
        .map(|_| ())
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))
}

pub(super) fn ensure_managed_resource_mutable(
    kind: ManagedResourceKind,
    id: &str,
    value: &Value,
) -> Result<(), ResourceRegistryError> {
    let field_is = |field: &str, expected: &str| {
        value
            .get(field)
            .and_then(Value::as_str)
            .is_some_and(|actual| actual.trim().eq_ignore_ascii_case(expected))
    };
    let immutable = match kind {
        ManagedResourceKind::Provider => false,
        ManagedResourceKind::Skill => {
            value.get("is_system_skill").and_then(Value::as_bool) == Some(true)
                || field_is("scope", "system")
        }
        ManagedResourceKind::Plugin => field_is("source", "builtin"),
        ManagedResourceKind::Agent => field_is("source", "builtin") || id.starts_with("builtin:"),
        ManagedResourceKind::SubAgent | ManagedResourceKind::PromptTemplate => {
            field_is("source", "builtin")
                || value.get("is_system").and_then(Value::as_bool) == Some(true)
        }
    };
    if immutable {
        return Err(ResourceRegistryError::Immutable {
            kind,
            id: id.to_string(),
        });
    }
    Ok(())
}
