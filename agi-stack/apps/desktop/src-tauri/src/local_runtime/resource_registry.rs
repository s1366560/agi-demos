use std::{collections::HashSet, fmt};

use chrono::{DateTime, Utc};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

use super::session_store::DesktopSessionStore;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum ManagedResourceKind {
    Provider,
    Skill,
    Plugin,
    Agent,
}

impl ManagedResourceKind {
    fn as_str(self) -> &'static str {
        match self {
            Self::Provider => "provider",
            Self::Skill => "skill",
            Self::Plugin => "plugin",
            Self::Agent => "agent",
        }
    }
}

#[derive(Debug)]
pub(super) enum ResourceRegistryError {
    NotFound,
    InvalidRoutingPolicy(String),
    Immutable {
        kind: ManagedResourceKind,
        id: String,
    },
    RevisionConflict {
        expected: u64,
        actual: u64,
    },
    Storage(String),
}

impl fmt::Display for ResourceRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotFound => formatter.write_str("managed resource not found"),
            Self::InvalidRoutingPolicy(detail) => formatter.write_str(detail),
            Self::Immutable { kind, id } => {
                write!(formatter, "managed {} {id} is immutable", kind.as_str())
            }
            Self::RevisionConflict { expected, actual } => write!(
                formatter,
                "managed resource revision conflict: expected {expected}, found {actual}"
            ),
            Self::Storage(error) => formatter.write_str(error),
        }
    }
}

pub(super) fn initialize_resource_registry(connection: &Connection) -> Result<(), String> {
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS desktop_managed_resources (
               kind TEXT NOT NULL CHECK(kind IN ('provider', 'skill', 'plugin', 'agent')),
               scope_kind TEXT NOT NULL CHECK(scope_kind IN ('tenant', 'project')),
               scope_id TEXT NOT NULL,
               id TEXT NOT NULL,
               status TEXT NOT NULL,
               revision INTEGER NOT NULL CHECK(revision >= 0),
               created_at_ms INTEGER NOT NULL,
               updated_at_ms INTEGER NOT NULL,
               value_json TEXT NOT NULL,
               PRIMARY KEY(kind, scope_kind, scope_id, id)
             );
             CREATE INDEX IF NOT EXISTS idx_desktop_managed_resources_scope
               ON desktop_managed_resources(kind, scope_kind, scope_id, status);
             CREATE TABLE IF NOT EXISTS desktop_llm_provider_selections (
               tenant_id TEXT PRIMARY KEY,
               provider_id TEXT NOT NULL,
               selected_at_ms INTEGER NOT NULL
             );
             CREATE TABLE IF NOT EXISTS desktop_llm_routing_policies (
               tenant_id TEXT PRIMARY KEY,
               revision INTEGER NOT NULL CHECK(revision >= 0),
               updated_at_ms INTEGER NOT NULL,
               value_json TEXT NOT NULL
             );
             CREATE TABLE IF NOT EXISTS desktop_llm_workspace_routing_policies (
               tenant_id TEXT NOT NULL,
               project_id TEXT NOT NULL,
               workspace_id TEXT NOT NULL,
               revision INTEGER NOT NULL CHECK(revision >= 0),
               updated_at_ms INTEGER NOT NULL,
               value_json TEXT NOT NULL,
               PRIMARY KEY(tenant_id, project_id, workspace_id)
             );",
        )
        .map_err(|error| error.to_string())?;
    seed_resource_registry(connection)
}

impl DesktopSessionStore {
    pub(super) fn list_runtime_provider_connections(&self) -> Result<Vec<(String, Value)>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT scope_id, value_json FROM desktop_managed_resources
                 WHERE kind = 'provider' AND scope_kind = 'tenant'
                 ORDER BY scope_id ASC, id ASC",
            )
            .map_err(|error| error.to_string())?;
        let providers = statement
            .query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })
            .map_err(|error| error.to_string())?
            .map(|row| {
                let (tenant_id, value_json) = row.map_err(|error| error.to_string())?;
                let provider =
                    serde_json::from_str(&value_json).map_err(|error| error.to_string())?;
                Ok((tenant_id, provider))
            })
            .collect();
        providers
    }

    pub(super) fn list_selected_llm_providers(&self) -> Result<Vec<(String, String)>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT tenant_id, provider_id FROM desktop_llm_provider_selections
                 ORDER BY tenant_id ASC, provider_id ASC",
            )
            .map_err(|error| error.to_string())?;
        let selections = statement
            .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))
            .map_err(|error| error.to_string())?
            .map(|row| row.map_err(|error| error.to_string()))
            .collect();
        selections
    }

    pub(super) fn list_llm_routing_policies(&self) -> Result<Vec<(String, Value)>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT tenant_id, value_json FROM desktop_llm_routing_policies
                 ORDER BY tenant_id ASC",
            )
            .map_err(|error| error.to_string())?;
        let policies = statement
            .query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })
            .map_err(|error| error.to_string())?
            .map(|row| {
                let (tenant_id, value_json) = row.map_err(|error| error.to_string())?;
                let policy =
                    serde_json::from_str(&value_json).map_err(|error| error.to_string())?;
                Ok((tenant_id, policy))
            })
            .collect();
        policies
    }

    pub(super) fn workspace_llm_routing_policy(
        &self,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        now_ms: i64,
    ) -> Result<Value, ResourceRegistryError> {
        let mut connection = self.connection().map_err(ResourceRegistryError::Storage)?;
        let transaction = connection
            .transaction()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        if let Some(policy) =
            query_workspace_routing_policy(&transaction, tenant_id, project_id, workspace_id)?
        {
            return Ok(policy);
        }
        let baseline = query_routing_policy(&transaction, tenant_id)?
            .or(legacy_routing_policy(&transaction, tenant_id)?)
            .unwrap_or_else(|| empty_routing_policy(tenant_id, now_ms));
        let policy = workspace_routing_policy_from_baseline(
            baseline,
            tenant_id,
            project_id,
            workspace_id,
            now_ms,
        )?;
        let value_json = serde_json::to_string(&policy)
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        transaction
            .execute(
                "INSERT INTO desktop_llm_workspace_routing_policies(
                   tenant_id, project_id, workspace_id, revision, updated_at_ms, value_json
                 ) VALUES (?1, ?2, ?3, 0, ?4, ?5)",
                params![tenant_id, project_id, workspace_id, now_ms, value_json],
            )
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        transaction
            .commit()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        Ok(policy)
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn put_workspace_llm_routing_policy(
        &self,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        expected_revision: u64,
        roles: Value,
        fallbacks: Value,
        now_ms: i64,
    ) -> Result<Value, ResourceRegistryError> {
        let mut connection = self.connection().map_err(ResourceRegistryError::Storage)?;
        let transaction = connection
            .transaction()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        validate_routing_policy_targets(&transaction, tenant_id, &roles, &fallbacks)?;
        let current_revision = transaction
            .query_row(
                "SELECT revision FROM desktop_llm_workspace_routing_policies
                 WHERE tenant_id = ?1 AND project_id = ?2 AND workspace_id = ?3",
                params![tenant_id, project_id, workspace_id],
                |row| row.get::<_, u64>(0),
            )
            .optional()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?
            .unwrap_or(0);
        if expected_revision != current_revision {
            return Err(ResourceRegistryError::RevisionConflict {
                expected: expected_revision,
                actual: current_revision,
            });
        }
        let next_revision = current_revision.saturating_add(1);
        let policy = json!({
            "tenant_id": tenant_id,
            "project_id": project_id,
            "workspace_id": workspace_id,
            "revision": next_revision,
            "roles": roles,
            "fallbacks": fallbacks,
            "updated_at": iso_from_millis(now_ms),
        });
        let value_json = serde_json::to_string(&policy)
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        transaction
            .execute(
                "INSERT INTO desktop_llm_workspace_routing_policies(
                   tenant_id, project_id, workspace_id, revision, updated_at_ms, value_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6)
                 ON CONFLICT(tenant_id, project_id, workspace_id) DO UPDATE SET
                   revision = excluded.revision,
                   updated_at_ms = excluded.updated_at_ms,
                   value_json = excluded.value_json",
                params![
                    tenant_id,
                    project_id,
                    workspace_id,
                    next_revision,
                    now_ms,
                    value_json
                ],
            )
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        transaction
            .commit()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        Ok(policy)
    }

    pub(super) fn select_llm_provider(
        &self,
        tenant_id: &str,
        provider_id: &str,
        expected_revision: u64,
        expected_policy_revision: u64,
        now_ms: i64,
    ) -> Result<Value, ResourceRegistryError> {
        let mut connection = self.connection().map_err(ResourceRegistryError::Storage)?;
        let transaction = connection
            .transaction()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        let provider = transaction
            .query_row(
                "SELECT revision, value_json FROM desktop_managed_resources
                 WHERE kind = 'provider' AND scope_kind = 'tenant'
                   AND scope_id = ?1 AND id = ?2",
                params![tenant_id, provider_id],
                |row| Ok((row.get::<_, u64>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?
            .ok_or(ResourceRegistryError::NotFound)?;
        if provider.0 != expected_revision {
            return Err(ResourceRegistryError::RevisionConflict {
                expected: expected_revision,
                actual: provider.0,
            });
        }
        let provider_value: Value = serde_json::from_str(&provider.1)
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        let model_id = provider_value
            .get("llm_model")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|model| !model.is_empty())
            .ok_or_else(|| {
                ResourceRegistryError::InvalidRoutingPolicy(
                    "selected provider must have a configured model".to_string(),
                )
            })?;
        sync_routing_policy_default(
            &transaction,
            tenant_id,
            provider_id,
            model_id,
            expected_policy_revision,
            now_ms,
        )?;
        transaction
            .execute(
                "INSERT INTO desktop_llm_provider_selections(tenant_id, provider_id, selected_at_ms)
                 VALUES (?1, ?2, ?3)
                 ON CONFLICT(tenant_id) DO UPDATE SET
                   provider_id = excluded.provider_id,
                   selected_at_ms = excluded.selected_at_ms",
                params![tenant_id, provider_id, now_ms],
            )
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        transaction
            .commit()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        Ok(provider_value)
    }

    pub(super) fn clear_llm_provider_selection_if_matches(
        &self,
        tenant_id: &str,
        provider_id: &str,
    ) -> Result<bool, String> {
        self.connection()?
            .execute(
                "DELETE FROM desktop_llm_provider_selections
                 WHERE tenant_id = ?1 AND provider_id = ?2",
                params![tenant_id, provider_id],
            )
            .map(|changed| changed > 0)
            .map_err(|error| error.to_string())
    }

    pub(super) fn list_managed_resources(
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

    pub(super) fn managed_resource(
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
                 WHERE kind = ?1 AND scope_kind = ?2 AND scope_id = ?3 AND id = ?4",
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
    pub(super) fn put_managed_resource(
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
                "SELECT revision, value_json FROM desktop_managed_resources
                 WHERE kind = ?1 AND scope_kind = ?2 AND scope_id = ?3 AND id = ?4",
                params![kind.as_str(), scope_kind, scope_id, id],
                |row| Ok((row.get::<_, u64>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        if let Some((_, current_json)) = current.as_ref() {
            let current_value = serde_json::from_str(current_json)
                .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
            ensure_managed_resource_mutable(kind, id, &current_value)?;
        }
        let current_revision = current.as_ref().map(|(revision, _)| *revision);
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
        transaction
            .execute(
                "INSERT INTO desktop_managed_resources(
                   kind, scope_kind, scope_id, id, status, revision,
                   created_at_ms, updated_at_ms, value_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?7, ?8)
                 ON CONFLICT(kind, scope_kind, scope_id, id) DO UPDATE SET
                   status = excluded.status,
                   revision = excluded.revision,
                   updated_at_ms = excluded.updated_at_ms,
                   value_json = excluded.value_json",
                params![
                    kind.as_str(),
                    scope_kind,
                    scope_id,
                    id,
                    status,
                    next_revision,
                    now_ms,
                    value_json,
                ],
            )
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
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

    pub(super) fn set_managed_resource_enabled(
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
            ManagedResourceKind::Plugin | ManagedResourceKind::Agent => {
                object.insert("enabled".to_string(), json!(enabled));
                object.insert(
                    "status".to_string(),
                    json!(if enabled { "active" } else { "disabled" }),
                );
            }
            ManagedResourceKind::Provider => {
                object.insert("is_active".to_string(), json!(enabled));
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

fn ensure_managed_resource_mutable(
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
    };
    if immutable {
        return Err(ResourceRegistryError::Immutable {
            kind,
            id: id.to_string(),
        });
    }
    Ok(())
}

fn query_routing_policy(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
) -> Result<Option<Value>, ResourceRegistryError> {
    let value_json = transaction
        .query_row(
            "SELECT value_json FROM desktop_llm_routing_policies WHERE tenant_id = ?1",
            params![tenant_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    value_json
        .map(|value| {
            serde_json::from_str(&value)
                .map_err(|error| ResourceRegistryError::Storage(error.to_string()))
        })
        .transpose()
}

fn query_workspace_routing_policy(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
) -> Result<Option<Value>, ResourceRegistryError> {
    let value_json = transaction
        .query_row(
            "SELECT value_json FROM desktop_llm_workspace_routing_policies
             WHERE tenant_id = ?1 AND project_id = ?2 AND workspace_id = ?3",
            params![tenant_id, project_id, workspace_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    value_json
        .map(|value| {
            serde_json::from_str(&value)
                .map_err(|error| ResourceRegistryError::Storage(error.to_string()))
        })
        .transpose()
}

fn workspace_routing_policy_from_baseline(
    mut policy: Value,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
    now_ms: i64,
) -> Result<Value, ResourceRegistryError> {
    let object = policy.as_object_mut().ok_or_else(|| {
        ResourceRegistryError::Storage("routing policy must be an object".to_string())
    })?;
    object.insert("tenant_id".to_string(), json!(tenant_id));
    object.insert("project_id".to_string(), json!(project_id));
    object.insert("workspace_id".to_string(), json!(workspace_id));
    object.insert("revision".to_string(), json!(0));
    object.insert("updated_at".to_string(), json!(iso_from_millis(now_ms)));
    Ok(policy)
}

fn query_workspace_routing_policies_for_tenant(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
) -> Result<Vec<Value>, ResourceRegistryError> {
    let mut statement = transaction
        .prepare(
            "SELECT value_json FROM desktop_llm_workspace_routing_policies
             WHERE tenant_id = ?1 ORDER BY project_id ASC, workspace_id ASC",
        )
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    let policies = statement
        .query_map(params![tenant_id], |row| row.get::<_, String>(0))
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?
        .map(|row| {
            let value_json =
                row.map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
            serde_json::from_str(&value_json)
                .map_err(|error| ResourceRegistryError::Storage(error.to_string()))
        })
        .collect();
    policies
}

fn sync_routing_policy_default(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
    provider_id: &str,
    model_id: &str,
    expected_revision: u64,
    now_ms: i64,
) -> Result<(), ResourceRegistryError> {
    let target = json!({
        "provider_id": provider_id,
        "model_id": model_id,
    });
    let mut policy = query_routing_policy(transaction, tenant_id)?.unwrap_or_else(|| {
        json!({
            "tenant_id": tenant_id,
            "revision": 0,
            "roles": {
                "default": null,
                "fast": null,
                "coding": null,
                "vision": null,
            },
            "fallbacks": [],
            "updated_at": iso_from_millis(now_ms),
        })
    });
    let current_revision = policy.get("revision").and_then(Value::as_u64).unwrap_or(0);
    if expected_revision != current_revision {
        return Err(ResourceRegistryError::RevisionConflict {
            expected: expected_revision,
            actual: current_revision,
        });
    }
    if policy.get("roles").and_then(|roles| roles.get("default")) == Some(&target) {
        return Ok(());
    }
    let next_revision = current_revision.saturating_add(1);
    let policy_object = policy.as_object_mut().ok_or_else(|| {
        ResourceRegistryError::Storage("routing policy must be an object".to_string())
    })?;
    let roles = policy_object
        .get_mut("roles")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| {
            ResourceRegistryError::Storage("routing policy roles must be an object".to_string())
        })?;
    roles.insert("default".to_string(), target);
    policy_object.insert("revision".to_string(), json!(next_revision));
    policy_object.insert("updated_at".to_string(), json!(iso_from_millis(now_ms)));
    let value_json = serde_json::to_string(&policy)
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    transaction
        .execute(
            "INSERT INTO desktop_llm_routing_policies(
               tenant_id, revision, updated_at_ms, value_json
             ) VALUES (?1, ?2, ?3, ?4)
             ON CONFLICT(tenant_id) DO UPDATE SET
               revision = excluded.revision,
               updated_at_ms = excluded.updated_at_ms,
               value_json = excluded.value_json",
            params![tenant_id, next_revision, now_ms, value_json],
        )
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    Ok(())
}

fn legacy_routing_policy(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
) -> Result<Option<Value>, ResourceRegistryError> {
    let selected = transaction
        .query_row(
            "SELECT selection.provider_id, selection.selected_at_ms, resource.value_json
             FROM desktop_llm_provider_selections AS selection
             JOIN desktop_managed_resources AS resource
               ON resource.kind = 'provider'
              AND resource.scope_kind = 'tenant'
              AND resource.scope_id = selection.tenant_id
              AND resource.id = selection.provider_id
             WHERE selection.tenant_id = ?1",
            params![tenant_id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, i64>(1)?,
                    row.get::<_, String>(2)?,
                ))
            },
        )
        .optional()
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    let Some((provider_id, selected_at_ms, provider_json)) = selected else {
        return Ok(None);
    };
    let provider: Value = serde_json::from_str(&provider_json)
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    let Some(model_id) = provider
        .get("llm_model")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|model| !model.is_empty())
    else {
        return Ok(None);
    };
    Ok(Some(json!({
        "tenant_id": tenant_id,
        "revision": 0,
        "roles": {
            "default": {
                "provider_id": provider_id,
                "model_id": model_id,
            },
            "fast": null,
            "coding": null,
            "vision": null,
        },
        "fallbacks": [],
        "updated_at": iso_from_millis(selected_at_ms),
    })))
}

fn empty_routing_policy(tenant_id: &str, now_ms: i64) -> Value {
    json!({
        "tenant_id": tenant_id,
        "revision": 0,
        "roles": {
            "default": null,
            "fast": null,
            "coding": null,
            "vision": null,
        },
        "fallbacks": [],
        "updated_at": iso_from_millis(now_ms),
    })
}

fn validate_routing_policy_targets(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
    roles: &Value,
    fallbacks: &Value,
) -> Result<(), ResourceRegistryError> {
    let roles = roles.as_object().ok_or_else(|| {
        ResourceRegistryError::InvalidRoutingPolicy("routing roles must be an object".to_string())
    })?;
    let default = roles
        .get("default")
        .filter(|target| !target.is_null())
        .ok_or_else(|| {
            ResourceRegistryError::InvalidRoutingPolicy(
                "default routing target is required".to_string(),
            )
        })?;
    validate_routing_target(transaction, tenant_id, default)?;
    for role in ["fast", "coding", "vision"] {
        if let Some(target) = roles.get(role).filter(|target| !target.is_null()) {
            validate_routing_target(transaction, tenant_id, target)?;
        }
    }
    let fallbacks = fallbacks.as_array().ok_or_else(|| {
        ResourceRegistryError::InvalidRoutingPolicy(
            "routing fallbacks must be an array".to_string(),
        )
    })?;
    if fallbacks.len() > 8 {
        return Err(ResourceRegistryError::InvalidRoutingPolicy(
            "routing fallbacks cannot contain more than 8 targets".to_string(),
        ));
    }
    let mut seen = HashSet::with_capacity(fallbacks.len());
    for target in fallbacks {
        let identity = routing_target_identity(target)?;
        if !seen.insert(identity) {
            return Err(ResourceRegistryError::InvalidRoutingPolicy(
                "routing fallbacks cannot contain duplicate targets".to_string(),
            ));
        }
        validate_routing_target(transaction, tenant_id, target)?;
    }
    Ok(())
}

fn validate_routing_target(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
    target: &Value,
) -> Result<(), ResourceRegistryError> {
    let (provider_id, model_id) = routing_target_identity(target)?;
    let provider = transaction
        .query_row(
            "SELECT status, value_json FROM desktop_managed_resources
             WHERE kind = 'provider' AND scope_kind = 'tenant'
               AND scope_id = ?1 AND id = ?2",
            params![tenant_id, provider_id],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
        )
        .optional()
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?
        .ok_or(ResourceRegistryError::NotFound)?;
    let provider_value: Value = serde_json::from_str(&provider.1)
        .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
    if !provider_is_configured(&provider.0, &provider_value) {
        return Err(ResourceRegistryError::InvalidRoutingPolicy(format!(
            "provider {provider_id} must be active and configured"
        )));
    }
    if !provider_supports_model(&provider_value, &model_id) {
        return Err(ResourceRegistryError::InvalidRoutingPolicy(format!(
            "model {model_id} is not configured for provider {provider_id}"
        )));
    }
    Ok(())
}

fn ensure_provider_policy_compatible(
    transaction: &rusqlite::Transaction<'_>,
    tenant_id: &str,
    provider_id: &str,
    status: &str,
    provider: &Value,
) -> Result<(), ResourceRegistryError> {
    let mut policies = query_workspace_routing_policies_for_tenant(transaction, tenant_id)?;
    if let Some(policy) = query_routing_policy(transaction, tenant_id)? {
        policies.push(policy);
    } else if let Some(policy) = legacy_routing_policy(transaction, tenant_id)? {
        policies.push(policy);
    }
    if policies.is_empty() {
        return Ok(());
    }
    let mut referenced_models = Vec::new();
    for policy in policies {
        if let Some(roles) = policy.get("roles").and_then(Value::as_object) {
            for role in ["default", "fast", "coding", "vision"] {
                if let Some(target) = roles.get(role).filter(|target| !target.is_null()) {
                    let (target_provider_id, model_id) = routing_target_identity(target)?;
                    if target_provider_id == provider_id {
                        referenced_models.push((role.to_string(), model_id));
                    }
                }
            }
        }
        if let Some(fallbacks) = policy.get("fallbacks").and_then(Value::as_array) {
            for target in fallbacks {
                let (target_provider_id, model_id) = routing_target_identity(target)?;
                if target_provider_id == provider_id {
                    referenced_models.push(("fallback".to_string(), model_id));
                }
            }
        }
    }
    if referenced_models.is_empty() {
        return Ok(());
    }
    if !provider_is_configured(status, provider) {
        return Err(ResourceRegistryError::InvalidRoutingPolicy(format!(
            "provider update would invalidate routing policy target {provider_id}"
        )));
    }
    if let Some((role, model_id)) = referenced_models
        .into_iter()
        .find(|(_, model_id)| !provider_supports_model(provider, model_id))
    {
        return Err(ResourceRegistryError::InvalidRoutingPolicy(format!(
            "provider update would invalidate {role} routing model {model_id}"
        )));
    }
    Ok(())
}

fn routing_target_identity(target: &Value) -> Result<(String, String), ResourceRegistryError> {
    let provider_id = target
        .get("provider_id")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            ResourceRegistryError::InvalidRoutingPolicy(
                "routing target provider_id cannot be empty".to_string(),
            )
        })?;
    let model_id = target
        .get("model_id")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            ResourceRegistryError::InvalidRoutingPolicy(
                "routing target model_id cannot be empty".to_string(),
            )
        })?;
    Ok((provider_id.to_string(), model_id.to_string()))
}

fn provider_supports_model(provider: &Value, model_id: &str) -> bool {
    provider
        .get("llm_model")
        .and_then(Value::as_str)
        .is_some_and(|model| model.trim() == model_id)
        || provider
            .get("allowed_models")
            .and_then(Value::as_array)
            .is_some_and(|models| {
                models
                    .iter()
                    .any(|model| model.as_str().is_some_and(|model| model.trim() == model_id))
            })
}

fn provider_is_configured(status: &str, provider: &Value) -> bool {
    let credential_configured = provider
        .get("auth_method")
        .and_then(Value::as_str)
        .is_some_and(|auth_method| auth_method == "none")
        || provider
            .get("credential_configured")
            .and_then(Value::as_bool)
            == Some(true);
    status == "active"
        && credential_configured
        && provider.get("is_active").and_then(Value::as_bool) == Some(true)
        && provider
            .get("provider_type")
            .and_then(Value::as_str)
            .is_some_and(|value| !value.trim().is_empty())
        && provider
            .get("base_url")
            .and_then(Value::as_str)
            .is_some_and(|value| !value.trim().is_empty())
        && provider
            .get("llm_model")
            .and_then(Value::as_str)
            .is_some_and(|value| !value.trim().is_empty())
}

fn seed_resource_registry(connection: &Connection) -> Result<(), String> {
    let now_ms = Utc::now().timestamp_millis();
    let tenants = query_ids(
        connection,
        "SELECT id FROM desktop_tenants WHERE status = 'active'",
    )?;
    for tenant_id in tenants {
        let provider = json!({
            "id": "local-runtime",
            "name": "Local runtime",
            "provider_type": "openai_compatible",
            "tenant_id": tenant_id,
            "is_active": false,
            "base_url": "http://127.0.0.1:11434/v1",
            "auth_method": "none",
            "credential_source": "none",
            "credential_configured": false,
            "llm_model": null,
            "allowed_models": [],
            "secondary_models": [],
            "health_status": "not_configured",
            "revision": 0,
            "updated_at": iso_from_millis(now_ms),
        });
        insert_seed(
            connection,
            ManagedResourceKind::Provider,
            "tenant",
            &tenant_id,
            "local-runtime",
            "disabled",
            &provider,
            now_ms,
        )?;
        for (id, name, description, tools) in [
            (
                "code-exploration",
                "Code exploration",
                "Inspect symbols, references, and repository structure before implementation.",
                vec![
                    "read",
                    "glob",
                    "grep",
                    "find_definition",
                    "find_references",
                    "call_graph",
                ],
            ),
            (
                "implementation",
                "Implementation",
                "Apply approved workspace changes inside the active run authority boundary.",
                vec![
                    "read",
                    "write",
                    "edit",
                    "apply_patch",
                    "run_tests",
                    "git_diff",
                ],
            ),
            (
                "verification",
                "Verification",
                "Run tests and collect structured evidence for human review.",
                vec![
                    "run_tests",
                    "analyze_coverage",
                    "git_diff",
                    "list_artifacts",
                ],
            ),
        ] {
            let skill = json!({
                "id": id,
                "name": name,
                "description": description,
                "status": "active",
                "scope": "tenant",
                "tools": tools,
                "current_version": 1,
                "is_system_skill": true,
                "revision": 0,
                "updated_at": iso_from_millis(now_ms),
            });
            insert_seed(
                connection,
                ManagedResourceKind::Skill,
                "tenant",
                &tenant_id,
                id,
                "active",
                &skill,
                now_ms,
            )?;
            reconcile_immutable_seed(
                connection,
                ManagedResourceKind::Skill,
                "tenant",
                &tenant_id,
                id,
                now_ms,
            )?;
        }
        for (id, name, package, tools) in [
            (
                "local-workspace",
                "Local workspace tools",
                "builtin:local-tools",
                vec!["read", "write", "edit", "glob", "grep", "terminal"],
            ),
            (
                "model-context-protocol",
                "Model Context Protocol",
                "builtin:mcp-runtime",
                vec!["mcp_tools_list", "mcp_tools_call"],
            ),
        ] {
            let tool_definitions = tools
                .into_iter()
                .map(|name| json!({ "name": name }))
                .collect::<Vec<_>>();
            let plugin = json!({
                "id": id,
                "name": name,
                "source": "builtin",
                "package": package,
                "version": env!("CARGO_PKG_VERSION"),
                "kind": "runtime",
                "enabled": true,
                "status": "active",
                "discovered": true,
                "providers": ["local"],
                "skills": [],
                "channel_types": [],
                "tool_definitions": tool_definitions,
                "revision": 0,
                "updated_at": iso_from_millis(now_ms),
            });
            insert_seed(
                connection,
                ManagedResourceKind::Plugin,
                "tenant",
                &tenant_id,
                id,
                "active",
                &plugin,
                now_ms,
            )?;
            reconcile_immutable_seed(
                connection,
                ManagedResourceKind::Plugin,
                "tenant",
                &tenant_id,
                id,
                now_ms,
            )?;
        }
    }

    let projects = query_ids(
        connection,
        "SELECT id FROM desktop_projects WHERE status = 'active'",
    )?;
    for project_id in projects {
        let agent = json!({
            "id": "builtin:all-access",
            "name": "Local Agent",
            "display_name": "General and coding Agent",
            "source": "builtin",
            "system_prompt": null,
            "enabled": true,
            "status": "active",
            "model_name": null,
            "allowed_tools": ["read", "write", "edit", "glob", "grep", "terminal"],
            "allowed_skills": ["code-exploration", "implementation", "verification"],
            "allowed_mcp_servers": ["local-runtime"],
            "project_id": project_id,
            "revision": 0,
            "updated_at": iso_from_millis(now_ms),
        });
        insert_seed(
            connection,
            ManagedResourceKind::Agent,
            "project",
            &project_id,
            "builtin:all-access",
            "active",
            &agent,
            now_ms,
        )?;
        reconcile_immutable_seed(
            connection,
            ManagedResourceKind::Agent,
            "project",
            &project_id,
            "builtin:all-access",
            now_ms,
        )?;
    }
    Ok(())
}

fn query_ids(connection: &Connection, query: &str) -> Result<Vec<String>, String> {
    let mut statement = connection
        .prepare(query)
        .map_err(|error| error.to_string())?;
    let ids = statement
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(|error| error.to_string())?
        .map(|row| row.map_err(|error| error.to_string()))
        .collect();
    ids
}

#[allow(clippy::too_many_arguments)]
fn insert_seed(
    connection: &Connection,
    kind: ManagedResourceKind,
    scope_kind: &str,
    scope_id: &str,
    id: &str,
    status: &str,
    value: &Value,
    now_ms: i64,
) -> Result<(), String> {
    connection
        .execute(
            "INSERT OR IGNORE INTO desktop_managed_resources(
               kind, scope_kind, scope_id, id, status, revision,
               created_at_ms, updated_at_ms, value_json
             ) VALUES (?1, ?2, ?3, ?4, ?5, 0, ?6, ?6, ?7)",
            params![
                kind.as_str(),
                scope_kind,
                scope_id,
                id,
                status,
                now_ms,
                serde_json::to_string(value).map_err(|error| error.to_string())?,
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn reconcile_immutable_seed(
    connection: &Connection,
    kind: ManagedResourceKind,
    scope_kind: &str,
    scope_id: &str,
    id: &str,
    now_ms: i64,
) -> Result<(), String> {
    let existing = connection
        .query_row(
            "SELECT status, revision, value_json FROM desktop_managed_resources
             WHERE kind = ?1 AND scope_kind = ?2 AND scope_id = ?3 AND id = ?4",
            params![kind.as_str(), scope_kind, scope_id, id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, u64>(1)?,
                    row.get::<_, String>(2)?,
                ))
            },
        )
        .optional()
        .map_err(|error| error.to_string())?;
    let Some((stored_status, revision, value_json)) = existing else {
        return Ok(());
    };
    let mut value: Value = serde_json::from_str(&value_json).map_err(|error| error.to_string())?;
    let object = value
        .as_object_mut()
        .ok_or_else(|| "managed resource must be an object".to_string())?;
    let mut changed = stored_status != "active";
    changed |= replace_if_different(object, "id", json!(id));
    match kind {
        ManagedResourceKind::Skill => {
            changed |= replace_if_different(object, "status", json!("active"));
            changed |= replace_if_different(object, "is_system_skill", json!(true));
        }
        ManagedResourceKind::Plugin => {
            changed |= replace_if_different(object, "source", json!("builtin"));
            changed |= replace_if_different(object, "enabled", json!(true));
            changed |= replace_if_different(object, "status", json!("active"));
            changed |= replace_if_different(object, "discovered", json!(true));
        }
        ManagedResourceKind::Agent => {
            changed |= replace_if_different(object, "source", json!("builtin"));
            changed |= replace_if_different(object, "enabled", json!(true));
            changed |= replace_if_different(object, "status", json!("active"));
        }
        ManagedResourceKind::Provider => return Ok(()),
    }
    if !changed {
        return Ok(());
    }
    let next_revision = revision.saturating_add(1);
    object.insert("revision".to_string(), json!(next_revision));
    object.insert("updated_at".to_string(), json!(iso_from_millis(now_ms)));
    let value_json = serde_json::to_string(&value).map_err(|error| error.to_string())?;
    connection
        .execute(
            "UPDATE desktop_managed_resources
             SET status = 'active', revision = ?1, updated_at_ms = ?2, value_json = ?3
             WHERE kind = ?4 AND scope_kind = ?5 AND scope_id = ?6 AND id = ?7",
            params![
                next_revision,
                now_ms,
                value_json,
                kind.as_str(),
                scope_kind,
                scope_id,
                id,
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn replace_if_different(
    object: &mut serde_json::Map<String, Value>,
    key: &str,
    expected: Value,
) -> bool {
    if object.get(key) == Some(&expected) {
        return false;
    }
    object.insert(key.to_string(), expected);
    true
}

fn iso_from_millis(timestamp_ms: i64) -> String {
    DateTime::<Utc>::from_timestamp_millis(timestamp_ms)
        .unwrap_or_else(Utc::now)
        .to_rfc3339()
}

#[cfg(test)]
#[path = "resource_registry_tests.rs"]
mod tests;
