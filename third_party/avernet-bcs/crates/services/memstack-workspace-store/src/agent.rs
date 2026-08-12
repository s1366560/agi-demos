//! Dialect-aware Workspace Agent binding and BCS Bot roster mutations.

use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatementBuilder, DbValue,
};
use memstack_workspace_service_api::WorkspaceScope;
use serde_json::Value;
use thiserror::Error;

use crate::{WorkspaceDomainMutation, WorkspaceProfileSnapshot};

/// Persisted Workspace Agent binding used for responses, events, and Bot projection.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceAgentSnapshot {
    pub binding_id: String,
    pub workspace_id: String,
    pub agent_id: String,
    pub bot_uuid: String,
    pub participant_actor_id: String,
    pub bot_name: String,
    pub display_name: Option<String>,
    pub description: Option<String>,
    pub config: Value,
    pub is_active: bool,
    pub hex_q: Option<i64>,
    pub hex_r: Option<i64>,
    pub theme_color: Option<String>,
    pub label: Option<String>,
    pub status: String,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Invalid or unavailable Workspace Agent persistence state.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceAgentStoreError {
    #[error(transparent)]
    Database(#[from] DbError),

    #[error("Workspace Agent binding is missing required data: {0}")]
    InvalidField(&'static str),

    #[error("Workspace Agent config is invalid JSON: {0}")]
    InvalidConfig(#[source] serde_json::Error),

    #[error("Workspace Agent config must be a JSON object")]
    ConfigNotObject,
}

/// Read-side and checked mutation helpers for Agent bindings and BCS roster rows.
pub struct WorkspaceAgentStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceAgentStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Read one scoped binding by external Agent identifier.
    ///
    /// # Errors
    ///
    /// Returns a database or row-decoding error.
    pub async fn read_by_agent_id(
        &self,
        scope: &WorkspaceScope,
        agent_id: &str,
    ) -> Result<Option<WorkspaceAgentSnapshot>, WorkspaceAgentStoreError> {
        let statement = self
            .binding_select(scope)
            .push_static(" AND binding.agent_id = ")
            .bind(agent_id)
            .build();
        self.read_one(statement).await
    }

    /// Read one scoped binding by legacy Workspace Agent binding identifier.
    ///
    /// # Errors
    ///
    /// Returns a database or row-decoding error.
    pub async fn read_by_binding_id(
        &self,
        scope: &WorkspaceScope,
        binding_id: &str,
    ) -> Result<Option<WorkspaceAgentSnapshot>, WorkspaceAgentStoreError> {
        let statement = self
            .binding_select(scope)
            .push_static(" AND binding.binding_id = ")
            .bind(binding_id)
            .build();
        self.read_one(statement).await
    }

    /// Build checked binding, BCS Bot, and Group Participant inserts.
    #[must_use]
    pub fn insert_mutations(
        &self,
        scope: &WorkspaceScope,
        profile: &WorkspaceProfileSnapshot,
        binding: &WorkspaceAgentSnapshot,
        bot_name: &str,
        bot_info: &str,
        persisted_at: &str,
    ) -> Vec<WorkspaceDomainMutation> {
        let mut binding_insert = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, \
                 workspace_id, agent_id, bot_uuid, participant_actor_id, display_name, \
                 description, config_json, is_active, hex_q, hex_r, theme_color, label, status, \
                 created_at, updated_at) SELECT ",
            )
            .bind(binding.binding_id.as_str())
            .push_static(", ")
            .bind(scope.tenant_id().as_str())
            .push_static(", ")
            .bind(scope.project_id().as_str())
            .push_static(", ")
            .bind(scope.workspace_id().as_str())
            .push_static(", ")
            .bind(binding.agent_id.as_str())
            .push_static(", ")
            .bind(binding.bot_uuid.as_str())
            .push_static(", ")
            .bind(binding.participant_actor_id.as_str())
            .push_static(", ")
            .bind(binding.display_name.clone())
            .push_static(", ")
            .bind(binding.description.clone())
            .push_static(", ")
            .bind(binding.config.to_string())
            .push_static(", ")
            .bind(binding.is_active)
            .push_static(", ")
            .bind(optional_i64_value(binding.hex_q))
            .push_static(", ")
            .bind(optional_i64_value(binding.hex_r))
            .push_static(", ")
            .bind(binding.theme_color.clone())
            .push_static(", ")
            .bind(binding.label.clone())
            .push_static(", ")
            .bind(binding.status.as_str())
            .push_static(", ")
            .bind(persisted_at)
            .push_static(", ")
            .bind(persisted_at)
            .push_static(" WHERE 1 = 1");
        binding_insert = self.append_hex_available(
            binding_insert,
            scope,
            binding.hex_q.zip(binding.hex_r),
            None,
        );
        let bot_insert = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO bcs_bots (bot_uuid, name, bot_info, registered_at, updated_at, env, \
                 visibility, created_by, actor_kind, status, is_deleted, agent_code, gmt_create, \
                 gmt_modified) VALUES (",
            )
            .bind(binding.bot_uuid.as_str())
            .push_static(", ")
            .bind(bot_name)
            .push_static(", ")
            .bind(bot_info)
            .push_static(", ")
            .bind(persisted_at)
            .push_static(", ")
            .bind(persisted_at)
            .push_static(", 'memstack', 'private', ")
            .bind(profile.created_by.as_str())
            .push_static(", 'bot', ")
            .bind(bot_status(binding.is_active))
            .push_static(", FALSE, ")
            .bind(binding.agent_id.as_str())
            .push_static(", ")
            .bind(persisted_at)
            .push_static(", ")
            .bind(persisted_at)
            .push_static(")")
            .build();
        let participant_insert = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO bcs_group_participants \
                 (group_id, bot_uuid, role, env, actor_kind, mode, gmt_create, gmt_modified) \
                 VALUES (",
            )
            .bind(profile.group_id.as_str())
            .push_static(", ")
            .bind(binding.participant_actor_id.as_str())
            .push_static(", 'worker', 'memstack', 'bot', 'auto', ")
            .bind(persisted_at)
            .push_static(", ")
            .bind(persisted_at)
            .push_static(")")
            .build();
        vec![
            WorkspaceDomainMutation::new(binding_insert.build(), DbCountExpectation::exactly(1)),
            WorkspaceDomainMutation::new(bot_insert, DbCountExpectation::exactly(1)),
            WorkspaceDomainMutation::new(participant_insert, DbCountExpectation::exactly(1)),
        ]
    }

    /// Build checked binding, BCS Bot, and Group Participant updates.
    #[must_use]
    pub fn update_mutations(
        &self,
        scope: &WorkspaceScope,
        profile: &WorkspaceProfileSnapshot,
        binding: &WorkspaceAgentSnapshot,
        bot_name: &str,
        bot_info: &str,
        persisted_at: &str,
    ) -> Vec<WorkspaceDomainMutation> {
        let mut binding_update = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE workspace_agent_bindings SET display_name = ")
            .bind(binding.display_name.clone())
            .push_static(", description = ")
            .bind(binding.description.clone())
            .push_static(", config_json = ")
            .bind(binding.config.to_string())
            .push_static(", is_active = ")
            .bind(binding.is_active)
            .push_static(", hex_q = ")
            .bind(optional_i64_value(binding.hex_q))
            .push_static(", hex_r = ")
            .bind(optional_i64_value(binding.hex_r))
            .push_static(", theme_color = ")
            .bind(binding.theme_color.clone())
            .push_static(", label = ")
            .bind(binding.label.clone())
            .push_static(", updated_at = ")
            .bind(persisted_at)
            .push_static(" WHERE tenant_id = ")
            .bind(scope.tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND workspace_id = ")
            .bind(scope.workspace_id().as_str())
            .push_static(" AND binding_id = ")
            .bind(binding.binding_id.as_str());
        binding_update = self.append_hex_available(
            binding_update,
            scope,
            binding.hex_q.zip(binding.hex_r),
            Some(binding.binding_id.as_str()),
        );
        let bot_update = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_bots SET name = ")
            .bind(bot_name)
            .push_static(", bot_info = ")
            .bind(bot_info)
            .push_static(", updated_at = ")
            .bind(persisted_at)
            .push_static(", status = ")
            .bind(bot_status(binding.is_active))
            .push_static(", is_deleted = FALSE, agent_code = ")
            .bind(binding.agent_id.as_str())
            .push_static(", gmt_modified = ")
            .bind(persisted_at)
            .push_static(" WHERE bot_uuid = ")
            .bind(binding.bot_uuid.as_str())
            .push_static(" AND env = 'memstack' AND actor_kind = 'bot'")
            .build();
        let participant_update = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_group_participants SET role = 'worker', gmt_modified = ")
            .bind(persisted_at)
            .push_static(" WHERE group_id = ")
            .bind(profile.group_id.as_str())
            .push_static(" AND bot_uuid = ")
            .bind(binding.participant_actor_id.as_str())
            .push_static(" AND env = 'memstack' AND actor_kind = 'bot'")
            .build();
        vec![
            WorkspaceDomainMutation::new(binding_update.build(), DbCountExpectation::exactly(1)),
            WorkspaceDomainMutation::new(bot_update, DbCountExpectation::exactly(1)),
            WorkspaceDomainMutation::new(participant_update, DbCountExpectation::exactly(1)),
        ]
    }

    /// Build checked BCS Participant, Bot, and Workspace binding removals.
    #[must_use]
    pub fn remove_mutations(
        &self,
        scope: &WorkspaceScope,
        profile: &WorkspaceProfileSnapshot,
        binding: &WorkspaceAgentSnapshot,
    ) -> Vec<WorkspaceDomainMutation> {
        let participant_delete = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_group_participants WHERE group_id = ")
            .bind(profile.group_id.as_str())
            .push_static(" AND bot_uuid = ")
            .bind(binding.participant_actor_id.as_str())
            .push_static(" AND env = 'memstack' AND actor_kind = 'bot'")
            .build();
        let bot_delete = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_bots WHERE bot_uuid = ")
            .bind(binding.bot_uuid.as_str())
            .push_static(" AND env = 'memstack' AND actor_kind = 'bot'")
            .build();
        let binding_delete = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM workspace_agent_bindings WHERE tenant_id = ")
            .bind(scope.tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND workspace_id = ")
            .bind(scope.workspace_id().as_str())
            .push_static(" AND binding_id = ")
            .bind(binding.binding_id.as_str())
            .build();
        vec![
            WorkspaceDomainMutation::new(participant_delete, DbCountExpectation::exactly(1)),
            WorkspaceDomainMutation::new(bot_delete, DbCountExpectation::exactly(1)),
            WorkspaceDomainMutation::new(binding_delete, DbCountExpectation::exactly(1)),
        ]
    }

    fn binding_select(&self, scope: &WorkspaceScope) -> DbStatementBuilder {
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT binding.binding_id, binding.workspace_id, binding.agent_id, \
                 binding.bot_uuid, binding.participant_actor_id, binding.display_name, \
                 binding.description, binding.config_json, binding.is_active, binding.hex_q, \
                 binding.hex_r, binding.theme_color, binding.label, binding.status, \
                 binding.created_at, binding.updated_at, \
                 COALESCE(bot.name, binding.agent_id) AS bot_name \
                 FROM workspace_agent_bindings binding LEFT JOIN bcs_bots bot \
                 ON bot.bot_uuid = binding.bot_uuid AND bot.env = 'memstack' \
                 WHERE binding.tenant_id = ",
            )
            .bind(scope.tenant_id().as_str())
            .push_static(" AND binding.project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND binding.workspace_id = ")
            .bind(scope.workspace_id().as_str())
    }

    async fn read_one(
        &self,
        statement: bcs_db_api::DbStatement,
    ) -> Result<Option<WorkspaceAgentSnapshot>, WorkspaceAgentStoreError> {
        let rows = self.db.query(statement).await?;
        rows.first().map(agent_from_row).transpose()
    }

    fn append_hex_available(
        &self,
        mut builder: DbStatementBuilder,
        scope: &WorkspaceScope,
        target: Option<(i64, i64)>,
        excluded_binding_id: Option<&str>,
    ) -> DbStatementBuilder {
        let Some((hex_q, hex_r)) = target else {
            return builder;
        };
        builder = builder
            .push_static(
                " AND NOT EXISTS (SELECT 1 FROM workspace_agent_bindings occupied \
                 WHERE occupied.tenant_id = ",
            )
            .bind(scope.tenant_id().as_str())
            .push_static(" AND occupied.project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND occupied.workspace_id = ")
            .bind(scope.workspace_id().as_str())
            .push_static(" AND occupied.hex_q = ")
            .bind(hex_q)
            .push_static(" AND occupied.hex_r = ")
            .bind(hex_r);
        if let Some(binding_id) = excluded_binding_id {
            builder = builder
                .push_static(" AND occupied.binding_id <> ")
                .bind(binding_id);
        }
        builder
            .push_static(
                ") AND NOT EXISTS (SELECT 1 FROM workspace_topology_nodes occupied_node \
                 WHERE occupied_node.tenant_id = ",
            )
            .bind(scope.tenant_id().as_str())
            .push_static(" AND occupied_node.project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND occupied_node.workspace_id = ")
            .bind(scope.workspace_id().as_str())
            .push_static(" AND occupied_node.hex_q = ")
            .bind(hex_q)
            .push_static(" AND occupied_node.hex_r = ")
            .bind(hex_r)
            .push_static(")")
    }
}

fn agent_from_row(row: &DbRow) -> Result<WorkspaceAgentSnapshot, WorkspaceAgentStoreError> {
    let raw_config = required_string(row, "config_json")?;
    let config = serde_json::from_str::<Value>(&raw_config)
        .map_err(WorkspaceAgentStoreError::InvalidConfig)?;
    if !config.is_object() {
        return Err(WorkspaceAgentStoreError::ConfigNotObject);
    }
    Ok(WorkspaceAgentSnapshot {
        binding_id: required_string(row, "binding_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        agent_id: required_string(row, "agent_id")?,
        bot_uuid: required_string(row, "bot_uuid")?,
        participant_actor_id: required_string(row, "participant_actor_id")?,
        bot_name: required_string(row, "bot_name")?,
        display_name: optional_string(row, "display_name")?,
        description: optional_string(row, "description")?,
        config,
        is_active: required_bool(row, "is_active")?,
        hex_q: optional_i64(row, "hex_q")?,
        hex_r: optional_i64(row, "hex_r")?,
        theme_color: optional_string(row, "theme_color")?,
        label: optional_string(row, "label")?,
        status: required_string(row, "status")?,
        created_at: required_string(row, "created_at")?,
        updated_at: optional_string(row, "updated_at")?,
    })
}

fn bot_status(is_active: bool) -> &'static str {
    if is_active { "online" } else { "offline" }
}

fn optional_i64_value(value: Option<i64>) -> DbValue {
    value.map_or(DbValue::Null, DbValue::I64)
}

fn required_string(row: &DbRow, column: &'static str) -> Result<String, WorkspaceAgentStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceAgentStoreError::InvalidField(column))
}

fn optional_string(
    row: &DbRow,
    column: &'static str,
) -> Result<Option<String>, WorkspaceAgentStoreError> {
    row.get_string(column)
        .map_err(WorkspaceAgentStoreError::from)
}

fn required_bool(row: &DbRow, column: &'static str) -> Result<bool, WorkspaceAgentStoreError> {
    row.get_bool(column)?
        .ok_or(WorkspaceAgentStoreError::InvalidField(column))
}

fn optional_i64(
    row: &DbRow,
    column: &'static str,
) -> Result<Option<i64>, WorkspaceAgentStoreError> {
    row.get_i64(column).map_err(WorkspaceAgentStoreError::from)
}
