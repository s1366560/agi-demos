use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use super::{
    managed_mutations::{
        ensure_managed_resource_mutable, insert_managed_resource_receipt,
        insert_managed_resource_version, persist_managed_resource, query_managed_resource_receipt,
        query_stored_managed_resource, resolve_mutation_value, stamp_managed_resource_value,
        validate_managed_resource_mutation, validate_mutation_authority,
    },
    routing_policy::ensure_provider_policy_compatible,
    schema::iso_from_millis,
    DesktopSessionStore, ManagedResourceKind, ManagedResourceMutationCommand,
    ManagedResourceMutationReceipt, ManagedResourceVersion, ResourceRegistryError,
};

impl DesktopSessionStore {
    pub(in crate::local_runtime) fn list_managed_resources(
        &self,
        kind: ManagedResourceKind,
        scope_kind: &str,
        scope_id: &str,
    ) -> Result<Vec<Value>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_managed_resources
                 WHERE kind = ?1 AND scope_kind = ?2 AND scope_id = ?3
                   AND status <> 'deleted'
                 ORDER BY id ASC",
            )
            .map_err(|error| error.to_string())?;
        let resources = statement
            .query_map(params![kind.as_str(), scope_kind, scope_id], |row| {
                row.get::<_, String>(0)
            })
            .map_err(|error| error.to_string())?
            .map(|row| {
                let value_json = row.map_err(|error| error.to_string())?;
                serde_json::from_str(&value_json).map_err(|error| error.to_string())
            })
            .collect();
        resources
    }

    pub(in crate::local_runtime) fn managed_resource(
        &self,
        kind: ManagedResourceKind,
        scope_kind: &str,
        scope_id: &str,
        id: &str,
    ) -> Result<Option<Value>, String> {
        let connection = self.connection()?;
        let value_json = connection
            .query_row(
                "SELECT value_json FROM desktop_managed_resources
                 WHERE kind = ?1 AND scope_kind = ?2 AND scope_id = ?3 AND id = ?4
                   AND status <> 'deleted'",
                params![kind.as_str(), scope_kind, scope_id, id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        value_json
            .map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
            .transpose()
    }

    #[allow(clippy::too_many_arguments)]
    pub(in crate::local_runtime) fn put_managed_resource(
        &self,
        kind: ManagedResourceKind,
        scope_kind: &str,
        scope_id: &str,
        id: &str,
        status: &str,
        expected_revision: Option<u64>,
        mut value: Value,
        now_ms: i64,
    ) -> Result<Value, ResourceRegistryError> {
        let clear_provider_selection = kind == ManagedResourceKind::Provider
            && (status != "active"
                || value.get("is_active").and_then(Value::as_bool) != Some(true)
                || value
                    .get("base_url")
                    .and_then(Value::as_str)
                    .map_or(true, |value| value.trim().is_empty())
                || value
                    .get("llm_model")
                    .and_then(Value::as_str)
                    .map_or(true, |value| value.trim().is_empty()));
        let mut connection = self.connection().map_err(ResourceRegistryError::Storage)?;
        let transaction = connection
            .transaction()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        let current = transaction
            .query_row(
                "SELECT revision, value_json, vault_refs_json
                 FROM desktop_managed_resources
                 WHERE kind = ?1 AND scope_kind = ?2 AND scope_id = ?3 AND id = ?4",
                params![kind.as_str(), scope_kind, scope_id, id],
                |row| {
                    Ok((
                        row.get::<_, u64>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                    ))
                },
            )
            .optional()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        if let Some((_, current_json, _)) = current.as_ref() {
            let current_value = serde_json::from_str(current_json)
                .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
            ensure_managed_resource_mutable(kind, id, &current_value)?;
        }
        let current_revision = current.as_ref().map(|(revision, _, _)| *revision);
        let actual_revision = current_revision.unwrap_or(0);
        if let Some(expected) = expected_revision {
            if expected != actual_revision {
                return Err(ResourceRegistryError::RevisionConflict {
                    expected,
                    actual: actual_revision,
                });
            }
        }
        if kind == ManagedResourceKind::Provider && scope_kind == "tenant" {
            ensure_provider_policy_compatible(&transaction, scope_id, id, status, &value)?;
        }
        let next_revision = current_revision.map_or(0, |revision| revision.saturating_add(1));
        let updated_at = iso_from_millis(now_ms);
        let object = value.as_object_mut().ok_or_else(|| {
            ResourceRegistryError::Storage("managed resource must be an object".to_string())
        })?;
        object.insert("id".to_string(), json!(id));
        object.insert("revision".to_string(), json!(next_revision));
        object.insert("updated_at".to_string(), json!(updated_at));
        let value_json = serde_json::to_string(&value)
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        let vault_refs_json = current
            .as_ref()
            .map(|(_, _, vault_refs_json)| vault_refs_json.as_str())
            .unwrap_or("[]");
        transaction
            .execute(
                "INSERT INTO desktop_managed_resources(
                   kind, scope_kind, scope_id, id, status, revision,
                   created_at_ms, updated_at_ms, value_json, vault_refs_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?7, ?8, ?9)
                 ON CONFLICT(kind, scope_kind, scope_id, id) DO UPDATE SET
                   status = excluded.status,
                   revision = excluded.revision,
                   updated_at_ms = excluded.updated_at_ms,
                   value_json = excluded.value_json,
                   vault_refs_json = excluded.vault_refs_json",
                params![
                    kind.as_str(),
                    scope_kind,
                    scope_id,
                    id,
                    status,
                    next_revision,
                    now_ms,
                    value_json,
                    vault_refs_json,
                ],
            )
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        insert_managed_resource_version(
            &transaction,
            kind,
            scope_kind,
            scope_id,
            id,
            next_revision,
            status,
            false,
            now_ms,
            &value,
            vault_refs_json,
        )?;
        if clear_provider_selection && scope_kind == "tenant" {
            transaction
                .execute(
                    "DELETE FROM desktop_llm_provider_selections
                     WHERE tenant_id = ?1 AND provider_id = ?2",
                    params![scope_id, id],
                )
                .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        }
        transaction
            .commit()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        Ok(value)
    }

    pub(in crate::local_runtime) fn mutate_managed_resource(
        &self,
        command: ManagedResourceMutationCommand,
    ) -> Result<ManagedResourceMutationReceipt, ResourceRegistryError> {
        validate_managed_resource_mutation(&command)?;
        let mut connection = self.connection().map_err(ResourceRegistryError::Storage)?;
        let transaction = connection
            .transaction()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        if let Some(receipt) = query_managed_resource_receipt(&transaction, &command)? {
            return Ok(receipt);
        }

        let current = query_stored_managed_resource(
            &transaction,
            command.kind,
            &command.scope_kind,
            &command.scope_id,
            &command.resource_id,
        )?;
        if let Some(current) = current.as_ref() {
            ensure_managed_resource_mutable(command.kind, &command.resource_id, &current.value)?;
        }
        validate_mutation_authority(&command, current.as_ref())?;

        let next_revision = match current.as_ref() {
            Some(current) => current.revision.saturating_add(1),
            None => 0,
        };
        let (mut next_value, next_vault_refs, tombstone) =
            resolve_mutation_value(&transaction, &command, current.as_ref())?;
        if !tombstone {
            stamp_managed_resource_value(
                &mut next_value,
                &command.resource_id,
                &command.status,
                next_revision,
                command.now_ms,
            )?;
        }
        let stored_value = if tombstone {
            let mut value = current
                .as_ref()
                .map(|resource| resource.value.clone())
                .unwrap_or_else(|| json!({}));
            stamp_managed_resource_value(
                &mut value,
                &command.resource_id,
                "deleted",
                next_revision,
                command.now_ms,
            )?;
            value
        } else {
            next_value.clone()
        };
        let created_at_ms = current
            .as_ref()
            .map(|resource| resource.created_at_ms)
            .unwrap_or(command.now_ms);
        persist_managed_resource(
            &transaction,
            &command,
            next_revision,
            created_at_ms,
            &stored_value,
            &next_vault_refs,
        )?;
        let version_value = if tombstone {
            Value::Null
        } else {
            next_value.clone()
        };
        let vault_refs_json = serde_json::to_string(&next_vault_refs)
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        insert_managed_resource_version(
            &transaction,
            command.kind,
            &command.scope_kind,
            &command.scope_id,
            &command.resource_id,
            next_revision,
            if tombstone {
                "deleted"
            } else {
                &command.status
            },
            tombstone,
            command.now_ms,
            &version_value,
            &vault_refs_json,
        )?;

        let receipt = ManagedResourceMutationReceipt {
            receipt_id: format!("managed-resource-receipt-{}", Uuid::new_v4()),
            operation: command.operation,
            resource_id: command.resource_id.clone(),
            resource: (!tombstone).then_some(next_value),
            duplicate: false,
        };
        insert_managed_resource_receipt(&transaction, &command, &receipt)?;
        transaction
            .commit()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        Ok(receipt)
    }

    pub(in crate::local_runtime) fn list_managed_resource_versions(
        &self,
        kind: ManagedResourceKind,
        scope_kind: &str,
        scope_id: &str,
        resource_id: &str,
    ) -> Result<Vec<ManagedResourceVersion>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT revision, status, tombstone, value_json, vault_refs_json, created_at_ms
                 FROM desktop_managed_resource_versions
                 WHERE kind = ?1 AND scope_kind = ?2 AND scope_id = ?3
                   AND resource_id = ?4
                 ORDER BY revision DESC",
            )
            .map_err(|error| error.to_string())?;
        let versions = statement
            .query_map(
                params![kind.as_str(), scope_kind, scope_id, resource_id],
                |row| {
                    Ok((
                        row.get::<_, u64>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, bool>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, String>(4)?,
                        row.get::<_, i64>(5)?,
                    ))
                },
            )
            .map_err(|error| error.to_string())?
            .map(|row| {
                let (revision, status, tombstone, value_json, vault_refs_json, created_at_ms) =
                    row.map_err(|error| error.to_string())?;
                Ok(ManagedResourceVersion {
                    revision,
                    status,
                    tombstone,
                    value: serde_json::from_str(&value_json).map_err(|error| error.to_string())?,
                    vault_refs: serde_json::from_str(&vault_refs_json)
                        .map_err(|error| error.to_string())?,
                    created_at_ms,
                })
            })
            .collect();
        versions
    }

    pub(in crate::local_runtime) fn set_managed_resource_enabled(
        &self,
        kind: ManagedResourceKind,
        scope_kind: &str,
        scope_id: &str,
        id: &str,
        enabled: bool,
        now_ms: i64,
    ) -> Result<Value, ResourceRegistryError> {
        let mut value = self
            .managed_resource(kind, scope_kind, scope_id, id)
            .map_err(ResourceRegistryError::Storage)?
            .ok_or(ResourceRegistryError::NotFound)?;
        let revision = value.get("revision").and_then(Value::as_u64).unwrap_or(0);
        let object = value.as_object_mut().ok_or_else(|| {
            ResourceRegistryError::Storage("managed resource must be an object".to_string())
        })?;
        match kind {
            ManagedResourceKind::Skill => {
                object.insert(
                    "status".to_string(),
                    json!(if enabled { "active" } else { "disabled" }),
                );
            }
            ManagedResourceKind::Plugin
            | ManagedResourceKind::Agent
            | ManagedResourceKind::SubAgent => {
                object.insert("enabled".to_string(), json!(enabled));
                object.insert(
                    "status".to_string(),
                    json!(if enabled { "active" } else { "disabled" }),
                );
            }
            ManagedResourceKind::Provider => {
                object.insert("is_active".to_string(), json!(enabled));
            }
            ManagedResourceKind::PromptTemplate => {
                return Err(ResourceRegistryError::InvalidMutation(
                    "prompt templates do not expose an enabled state".to_string(),
                ));
            }
        }
        self.put_managed_resource(
            kind,
            scope_kind,
            scope_id,
            id,
            if enabled { "active" } else { "disabled" },
            Some(revision),
            value,
            now_ms,
        )
    }
}
