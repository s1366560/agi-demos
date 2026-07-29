use std::fmt;

use rusqlite::{params, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use super::session_store::DesktopSessionStore;

mod managed_mutations;
mod managed_store;
mod routing_policy;
mod schema;

pub(super) use routing_policy::{
    apply_workspace_agent_policy_mutation, ensure_workspace_agent_policy_in_transaction,
};
use routing_policy::{
    query_workspace_routing_policy, sync_routing_policy_default, validate_routing_policy_targets,
};
pub(super) use schema::initialize_resource_registry;
use schema::iso_from_millis;

pub(super) const WORKSPACE_AGENT_POLICY_CAPABILITY_VERSION: &str = "workspace-agent-policy-v1";

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum WorkspaceAgentCapabilityMode {
    Work,
    Code,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WorkspaceAgentPolicyMutation {
    pub(super) expected_revision: u64,
    pub(super) capability_mode: WorkspaceAgentCapabilityMode,
    pub(super) route: Value,
    pub(super) reasoning_effort: String,
    pub(super) permission_mode: String,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum ManagedResourceKind {
    Provider,
    Skill,
    Plugin,
    Agent,
    SubAgent,
    PromptTemplate,
}

impl ManagedResourceKind {
    fn as_str(self) -> &'static str {
        match self {
            Self::Provider => "provider",
            Self::Skill => "skill",
            Self::Plugin => "plugin",
            Self::Agent => "agent",
            Self::SubAgent => "subagent",
            Self::PromptTemplate => "prompt_template",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum ManagedResourceMutationOperation {
    Create,
    Update,
    Delete,
    Import,
    Rollback,
}

impl ManagedResourceMutationOperation {
    fn as_str(self) -> &'static str {
        match self {
            Self::Create => "create",
            Self::Update => "update",
            Self::Delete => "delete",
            Self::Import => "import",
            Self::Rollback => "rollback",
        }
    }
}

#[derive(Clone, Debug)]
pub(super) struct ManagedResourceMutationCommand {
    pub(super) actor_id: String,
    pub(super) kind: ManagedResourceKind,
    pub(super) scope_kind: String,
    pub(super) scope_id: String,
    pub(super) resource_id: String,
    pub(super) operation: ManagedResourceMutationOperation,
    pub(super) expected_revision: u64,
    pub(super) idempotency_key: String,
    pub(super) payload_hash: String,
    pub(super) status: String,
    pub(super) value: Option<Value>,
    pub(super) target_revision: Option<u64>,
    pub(super) vault_refs: Vec<String>,
    pub(super) now_ms: i64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(super) struct ManagedResourceMutationReceipt {
    pub(super) receipt_id: String,
    pub(super) operation: ManagedResourceMutationOperation,
    pub(super) resource_id: String,
    pub(super) resource: Option<Value>,
    pub(super) duplicate: bool,
}

#[derive(Clone, Debug)]
pub(super) struct ManagedResourceVersion {
    pub(super) revision: u64,
    pub(super) status: String,
    pub(super) tombstone: bool,
    pub(super) value: Value,
    pub(super) vault_refs: Vec<String>,
    pub(super) created_at_ms: i64,
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum ResourceRegistryError {
    NotFound,
    AlreadyExists,
    IdempotencyConflict,
    InvalidMutation(String),
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
            Self::AlreadyExists => formatter.write_str("managed resource already exists"),
            Self::IdempotencyConflict => formatter.write_str(
                "managed resource idempotency key is already bound to a different request",
            ),
            Self::InvalidMutation(detail) => formatter.write_str(detail),
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
        let policy = ensure_workspace_agent_policy_in_transaction(
            &transaction,
            tenant_id,
            project_id,
            workspace_id,
            now_ms,
        )?;
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
        let current_policy =
            query_workspace_routing_policy(&transaction, tenant_id, project_id, workspace_id)?
                .unwrap_or_else(|| json!({}));
        let policy = json!({
            "tenant_id": tenant_id,
            "project_id": project_id,
            "workspace_id": workspace_id,
            "revision": next_revision,
            "roles": roles,
            "fallbacks": fallbacks,
            "reasoning_effort": current_policy
                .get("reasoning_effort")
                .and_then(Value::as_str)
                .unwrap_or("medium"),
            "permission_mode": current_policy
                .get("permission_mode")
                .and_then(Value::as_str)
                .unwrap_or("ask"),
            "capability_version": WORKSPACE_AGENT_POLICY_CAPABILITY_VERSION,
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

    pub(super) fn patch_workspace_agent_policy(
        &self,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        mutation: &WorkspaceAgentPolicyMutation,
        now_ms: i64,
    ) -> Result<Value, ResourceRegistryError> {
        let mut connection = self.connection().map_err(ResourceRegistryError::Storage)?;
        let transaction = connection
            .transaction()
            .map_err(|error| ResourceRegistryError::Storage(error.to_string()))?;
        let policy = apply_workspace_agent_policy_mutation(
            &transaction,
            tenant_id,
            project_id,
            workspace_id,
            mutation,
            now_ms,
        )?;
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
}

#[cfg(test)]
#[path = "resource_registry_tests.rs"]
mod tests;
