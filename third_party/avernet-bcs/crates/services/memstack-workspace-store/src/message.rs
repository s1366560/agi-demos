//! Atomic BCS-compatible persistence for the legacy Workspace message surface.

use std::collections::{HashMap, HashSet};

use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder,
    DbTransactionStep, DbTransactionStepResult,
};
use serde_json::Value;
use thiserror::Error;

use crate::message_delivery::{
    delivery_snapshot_insert, delivery_targets_from_rows, delivery_targets_select,
};

const BCS_ENVIRONMENT: &str = "memstack";
const MESSAGE_EVENT_SEQUENCE_BASE: i64 = 1_i64 << 62;
const MAX_MESSAGE_SESSION_SEQUENCE: i64 = i64::MAX - MESSAGE_EVENT_SEQUENCE_BASE;

/// Tenant/project/workspace scope for one message operation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceMessageScope {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
}

/// One active Workspace Agent target that may receive `chat.send`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceMessageDeliveryTarget {
    pub agent_id: String,
    pub bot_uuid: String,
    pub display_name: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct WorkspaceMessageMentionTarget {
    delivery_target: WorkspaceMessageDeliveryTarget,
    is_active: bool,
}

/// Canonical structured mention resolution.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedWorkspaceMentions {
    pub mention_ids: Vec<String>,
    pub delivery_targets: Vec<WorkspaceMessageDeliveryTarget>,
}

/// Fully prepared message write owned by the application service.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceMessageWrite {
    pub scope: WorkspaceMessageScope,
    pub message_id: String,
    pub session_id: String,
    pub correlation_id: String,
    pub outbox_id: String,
    pub sender_id: String,
    pub sender_name: String,
    pub sender_is_superuser: bool,
    pub content_json: String,
    pub mentions_json: String,
    pub parent_message_id: Option<String>,
    pub metadata_json: String,
    pub idempotency_key: String,
    pub request_hash: String,
    pub created_at_ms: i64,
    pub event_payload_json: String,
    pub event_metadata_json: String,
}

/// Legacy-compatible message projection backed by `bcs_messages`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceMessageRecord {
    pub id: String,
    pub group_id: String,
    pub workspace_id: String,
    pub sender_id: String,
    pub sender_type: String,
    pub content: String,
    pub mentions: Vec<String>,
    pub parent_message_id: Option<String>,
    pub metadata: Value,
    pub created_at_ms: i64,
}

/// Committed or idempotently replayed message outcome.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceMessageWriteOutcome {
    pub group_id: String,
    pub message: WorkspaceMessageRecord,
    pub delivery_targets: Vec<WorkspaceMessageDeliveryTarget>,
    pub replayed: bool,
}

/// Message persistence and access failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceMessageStoreError {
    #[error("Workspace not found")]
    NotFound,

    #[error("Workspace access required")]
    AccessRequired,

    #[error("Workspace editor access required")]
    EditorAccessRequired,

    #[error("Workspace principal identity is unavailable")]
    IdentityUnavailable,

    #[error("Invalid workspace mention target")]
    InvalidMention,

    #[error("idempotency key was already used with a different request hash")]
    IdempotencyConflict,

    #[error("message idempotency receipt is incomplete")]
    IncompleteReceipt,

    #[error("message transaction did not satisfy its row-count contract")]
    DomainConflict,

    #[error("persisted Workspace message is invalid: {0}")]
    InvalidRecord(String),

    #[error("persisted Workspace message JSON is invalid: {0}")]
    InvalidJson(#[source] serde_json::Error),

    #[error("invalid Workspace message delivery claim: {0}")]
    InvalidDeliveryClaim(String),

    #[error("Workspace message delivery lease is no longer owned by this worker")]
    DeliveryLeaseLost,

    #[error(transparent)]
    Database(#[from] DbError),
}

/// PostgreSQL/SQLite message repository with local atomic append semantics.
pub struct WorkspaceMessageStore<'a> {
    pub(crate) db: &'a dyn DbPlugin,
    pub(crate) flavor: DbSqlFlavor,
}

impl<'a> WorkspaceMessageStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Require a scoped Workspace and the requested membership level.
    ///
    /// # Errors
    ///
    /// Returns a stable not-found or access error, or preserves a database failure.
    pub async fn require_access(
        &self,
        scope: &WorkspaceMessageScope,
        user_id: &str,
        is_superuser: bool,
        require_editor: bool,
    ) -> Result<(), WorkspaceMessageStoreError> {
        let rows = self.db.query(workspace_exists(self.flavor, scope)).await?;
        if rows.is_empty() {
            return Err(WorkspaceMessageStoreError::NotFound);
        }
        if is_superuser {
            return Ok(());
        }
        let rows = self
            .db
            .query(member_role(self.flavor, scope, user_id))
            .await?;
        let Some(row) = rows.first() else {
            return Err(WorkspaceMessageStoreError::AccessRequired);
        };
        if require_editor {
            let role = required_string(row, "role")?;
            if !matches!(role.as_str(), "owner" | "editor" | "admin") {
                return Err(WorkspaceMessageStoreError::EditorAccessRequired);
            }
        }
        Ok(())
    }

    /// Read the sender email from the scoped principal projection.
    ///
    /// # Errors
    ///
    /// Returns `IdentityUnavailable` when the mirrored identity is missing.
    pub async fn sender_email(
        &self,
        scope: &WorkspaceMessageScope,
        user_id: &str,
    ) -> Result<String, WorkspaceMessageStoreError> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT email FROM workspace_principal_identities WHERE tenant_id = ")
            .bind(scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(scope.workspace_id.as_str())
            .push_static(" AND user_id = ")
            .bind(user_id)
            .push_static(" AND is_active = TRUE LIMIT 1")
            .build();
        let rows = self.db.query(statement).await?;
        let row = rows
            .first()
            .ok_or(WorkspaceMessageStoreError::IdentityUnavailable)?;
        required_string(row, "email")
    }

    /// Resolve structured member/Agent mentions without text heuristics.
    ///
    /// # Errors
    ///
    /// Returns `InvalidMention` when any non-blank target is outside the Workspace roster.
    pub async fn resolve_mentions(
        &self,
        scope: &WorkspaceMessageScope,
        requested: &[String],
    ) -> Result<ResolvedWorkspaceMentions, WorkspaceMessageStoreError> {
        let requested = requested
            .iter()
            .map(|value| value.trim())
            .filter(|value| !value.is_empty())
            .collect::<Vec<_>>();
        if requested.is_empty() {
            return Ok(ResolvedWorkspaceMentions {
                mention_ids: Vec::new(),
                delivery_targets: Vec::new(),
            });
        }

        let agent_rows = self.db.query(agent_targets(self.flavor, scope)).await?;
        let agents = agent_rows
            .iter()
            .map(agent_target_from_row)
            .collect::<Result<Vec<_>, _>>()?;
        if requested
            .iter()
            .any(|mention| mention.eq_ignore_ascii_case("all"))
        {
            let selected_agents = agents.into_iter().take(100).collect::<Vec<_>>();
            let mention_ids = selected_agents
                .iter()
                .map(|target| target.delivery_target.agent_id.clone())
                .collect();
            let delivery_targets = selected_agents
                .into_iter()
                .filter(|target| target.is_active)
                .map(|target| target.delivery_target)
                .collect();
            return Ok(ResolvedWorkspaceMentions {
                mention_ids,
                delivery_targets,
            });
        }

        let member_rows = self.db.query(member_targets(self.flavor, scope)).await?;
        let member_ids = member_rows
            .iter()
            .map(|row| required_string(row, "user_id"))
            .collect::<Result<HashSet<_>, _>>()?;
        let agent_by_id = agents
            .into_iter()
            .map(|target| (target.delivery_target.agent_id.clone(), target))
            .collect::<HashMap<_, _>>();
        let mut mention_ids = Vec::with_capacity(requested.len());
        let mut delivery_targets = Vec::new();
        let mut seen = HashSet::with_capacity(requested.len());
        for mention in requested {
            let valid = member_ids.contains(mention) || agent_by_id.contains_key(mention);
            if !valid {
                return Err(WorkspaceMessageStoreError::InvalidMention);
            }
            if seen.insert(mention) {
                mention_ids.push(mention.to_string());
                if let Some(target) = agent_by_id.get(mention)
                    && target.is_active
                {
                    delivery_targets.push(target.delivery_target.clone());
                }
            }
        }
        Ok(ResolvedWorkspaceMentions {
            mention_ids,
            delivery_targets,
        })
    }

    /// Atomically append one BCS message, correlation, and durable Workspace event.
    ///
    /// # Errors
    ///
    /// Returns stable access, mention, idempotency, domain, or infrastructure errors.
    pub async fn create(
        &self,
        write: &WorkspaceMessageWrite,
    ) -> Result<WorkspaceMessageWriteOutcome, WorkspaceMessageStoreError> {
        let mentions = serde_json::from_str::<Vec<String>>(&write.mentions_json)
            .map_err(WorkspaceMessageStoreError::InvalidJson)?;
        if let Some(outcome) = self.read_replay(write).await? {
            return Ok(outcome);
        }

        let steps = message_write_steps(self.flavor, write, &mentions)?;
        let results = match self.db.transaction(steps).await {
            Ok(results) => results,
            Err(error) => {
                if error.is_duplicate_key()
                    && let Some(outcome) = self.read_replay(write).await?
                {
                    return Ok(outcome);
                }
                return Err(classify_write_error(error));
            }
        };
        let Some(DbTransactionStepResult::Rows(target_rows)) = results.last() else {
            return Err(WorkspaceMessageStoreError::InvalidRecord(
                "final transaction result is not a delivery target query".to_string(),
            ));
        };
        let Some(message_result_index) = results.len().checked_sub(2) else {
            return Err(WorkspaceMessageStoreError::InvalidRecord(
                "message transaction result is incomplete".to_string(),
            ));
        };
        let Some(DbTransactionStepResult::Rows(message_rows)) = results.get(message_result_index)
        else {
            return Err(WorkspaceMessageStoreError::InvalidRecord(
                "penultimate transaction result is not a message query".to_string(),
            ));
        };
        let row = message_rows.first().ok_or_else(|| {
            WorkspaceMessageStoreError::InvalidRecord(
                "message transaction query returned no message".to_string(),
            )
        })?;
        let message = message_from_row(row)?;
        Ok(WorkspaceMessageWriteOutcome {
            group_id: message.group_id.clone(),
            delivery_targets: delivery_targets_from_rows(target_rows)?,
            message,
            replayed: false,
        })
    }

    /// List oldest-first messages with legacy `before` cursor behavior.
    ///
    /// # Errors
    ///
    /// Returns an access, database, or persisted-record error.
    pub async fn list(
        &self,
        scope: &WorkspaceMessageScope,
        user_id: &str,
        is_superuser: bool,
        limit: i64,
        before: Option<&str>,
    ) -> Result<Vec<WorkspaceMessageRecord>, WorkspaceMessageStoreError> {
        self.require_access(scope, user_id, is_superuser, false)
            .await?;
        let rows = self
            .db
            .query(list_messages(self.flavor, scope, limit, before))
            .await?;
        rows.iter().map(message_from_row).collect()
    }

    /// List oldest-first messages mentioning one exact structured target.
    ///
    /// # Errors
    ///
    /// Returns an access, database, or persisted-record error.
    pub async fn mentions(
        &self,
        scope: &WorkspaceMessageScope,
        user_id: &str,
        is_superuser: bool,
        target_id: &str,
        limit: i64,
    ) -> Result<Vec<WorkspaceMessageRecord>, WorkspaceMessageStoreError> {
        self.require_access(scope, user_id, is_superuser, false)
            .await?;
        let rows = self
            .db
            .query(mention_messages(self.flavor, scope, target_id, limit))
            .await?;
        rows.iter().map(message_from_row).collect()
    }

    async fn read_replay(
        &self,
        write: &WorkspaceMessageWrite,
    ) -> Result<Option<WorkspaceMessageWriteOutcome>, WorkspaceMessageStoreError> {
        let rows = self.db.query(replay_message(self.flavor, write)).await?;
        let Some(row) = rows.first() else {
            return Ok(None);
        };
        let stored_hash = row
            .get_string("request_hash")?
            .ok_or(WorkspaceMessageStoreError::IncompleteReceipt)?;
        if stored_hash != write.request_hash {
            return Err(WorkspaceMessageStoreError::IdempotencyConflict);
        }
        let message = message_from_row(row)?;
        let target_rows = self
            .db
            .query(delivery_targets_select(
                self.flavor,
                &write.scope.workspace_id,
                &message.id,
            ))
            .await?;
        Ok(Some(WorkspaceMessageWriteOutcome {
            group_id: message.group_id.clone(),
            delivery_targets: delivery_targets_from_rows(&target_rows)?,
            message,
            replayed: true,
        }))
    }
}

fn message_write_steps(
    flavor: DbSqlFlavor,
    write: &WorkspaceMessageWrite,
    mentions: &[String],
) -> Result<Vec<DbTransactionStep>, WorkspaceMessageStoreError> {
    let mut steps = vec![
        DbTransactionStep::query_checked(
            workspace_exists(flavor, &write.scope),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::query_checked(
            editor_access(flavor, write),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::query_checked(
            sender_identity(flavor, write),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::query_checked(
            valid_mentions(flavor, write, mentions),
            DbCountExpectation::exactly(mention_count(mentions)?),
        ),
        DbTransactionStep::Execute(session_insert(flavor, write)),
        DbTransactionStep::execute_checked(
            session_sequence_update(flavor, write),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            message_insert(flavor, write),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            outbox_insert(flavor, write),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            correlation_insert(flavor, write),
            DbCountExpectation::exactly(1),
        ),
    ];
    if let Some(snapshot) = delivery_snapshot_insert(flavor, write, mentions)? {
        steps.push(DbTransactionStep::Execute(snapshot));
    }
    steps.push(DbTransactionStep::Query(message_select(
        flavor,
        &write.message_id,
    )));
    steps.push(DbTransactionStep::Query(delivery_targets_select(
        flavor,
        &write.scope.workspace_id,
        &write.message_id,
    )));
    Ok(steps)
}

fn workspace_exists(flavor: DbSqlFlavor, scope: &WorkspaceMessageScope) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT 1 AS workspace_exists FROM workspace_profiles WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND deleted_at IS NULL LIMIT 1")
        .build()
}

fn member_role(flavor: DbSqlFlavor, scope: &WorkspaceMessageScope, user_id: &str) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT role FROM workspace_members WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND user_id = ")
        .bind(user_id)
        .push_static(" LIMIT 1")
        .build()
}

fn editor_access(flavor: DbSqlFlavor, write: &WorkspaceMessageWrite) -> DbStatement {
    if write.sender_is_superuser {
        return workspace_exists(flavor, &write.scope);
    }
    DbStatementBuilder::new(flavor)
        .push_static("SELECT 1 AS editor_access FROM workspace_members WHERE tenant_id = ")
        .bind(write.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(write.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(write.scope.workspace_id.as_str())
        .push_static(" AND user_id = ")
        .bind(write.sender_id.as_str())
        .push_static(" AND role IN ('owner', 'editor', 'admin') LIMIT 1")
        .build()
}

fn sender_identity(flavor: DbSqlFlavor, write: &WorkspaceMessageWrite) -> DbStatement {
    if write.sender_is_superuser {
        return DbStatementBuilder::new(flavor)
            .push_static("SELECT 1 AS identity_ready")
            .build();
    }
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT 1 AS identity_ready FROM workspace_principal_identities WHERE tenant_id = ",
        )
        .bind(write.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(write.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(write.scope.workspace_id.as_str())
        .push_static(" AND user_id = ")
        .bind(write.sender_id.as_str())
        .push_static(" AND email = ")
        .bind(write.sender_name.as_str())
        .push_static(" AND is_active = TRUE LIMIT 1")
        .build()
}

fn valid_mentions(
    flavor: DbSqlFlavor,
    write: &WorkspaceMessageWrite,
    mentions: &[String],
) -> DbStatement {
    if mentions.is_empty() {
        return DbStatementBuilder::new(flavor)
            .push_static("SELECT 1 AS mention_target WHERE 1 = 0")
            .build();
    }
    let mut builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT target_id FROM (SELECT agent_id AS target_id FROM workspace_agent_bindings \
             WHERE tenant_id = ",
        )
        .bind(write.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(write.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(write.scope.workspace_id.as_str())
        .push_static(" UNION SELECT user_id AS target_id FROM workspace_members WHERE tenant_id = ")
        .bind(write.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(write.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(write.scope.workspace_id.as_str())
        .push_static(") AS targets WHERE target_id IN (");
    for (index, mention) in mentions.iter().enumerate() {
        if index > 0 {
            builder = builder.push_static(", ");
        }
        builder = builder.bind(mention.as_str());
    }
    builder.push_static(")").build()
}

fn session_insert(flavor: DbSqlFlavor, write: &WorkspaceMessageWrite) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO bcs_group_sessions (session_id, group_id, env, status, session_kind, \
             caller_id, caller_principal, created_by, participants, current_msg_seq, meta) SELECT ",
        )
        .bind(write.session_id.as_str())
        .push_static(", p.group_id, 'memstack', 'running', 'chat', ")
        .bind(write.sender_id.as_str())
        .push_static(", ")
        .bind(write.sender_id.as_str())
        .push_static(", ")
        .bind(write.sender_id.as_str())
        .push_static(", '[]', 0, ")
        .bind("{\"authority\":\"memstack-workspace\"}")
        .push_static(" FROM workspace_profiles p WHERE p.tenant_id = ")
        .bind(write.scope.tenant_id.as_str())
        .push_static(" AND p.project_id = ")
        .bind(write.scope.project_id.as_str())
        .push_static(" AND p.workspace_id = ")
        .bind(write.scope.workspace_id.as_str());
    match flavor {
        DbSqlFlavor::Postgres | DbSqlFlavor::Sqlite => builder
            .push_static(" ON CONFLICT(env, session_id) DO NOTHING")
            .build(),
        DbSqlFlavor::Mysql => builder.build(),
    }
}

fn session_sequence_update(flavor: DbSqlFlavor, write: &WorkspaceMessageWrite) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE bcs_group_sessions SET current_msg_seq = current_msg_seq + 1 WHERE env = ",
        )
        .bind(BCS_ENVIRONMENT)
        .push_static(" AND session_id = ")
        .bind(write.session_id.as_str())
        .push_static(" AND current_msg_seq < ")
        .bind(MAX_MESSAGE_SESSION_SEQUENCE)
        .build()
}

fn message_insert(flavor: DbSqlFlavor, write: &WorkspaceMessageWrite) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO bcs_messages (message_id, group_id, session_id, session_seq, env, \
             sender_id, sender_type, message_type, content, client_msg_id, status, created_at, \
             run_id, workspace_id, mentions_json, parent_message_id, metadata_json, source_hash) \
             SELECT ",
        )
        .bind(write.message_id.as_str())
        .push_static(", p.group_id, ")
        .bind(write.session_id.as_str())
        .push_static(", s.current_msg_seq, 'memstack', ")
        .bind(write.sender_id.as_str())
        .push_static(", 'human', 'workspace_chat', ")
        .bind(write.content_json.as_str())
        .push_static(", ")
        .bind(write.idempotency_key.as_str())
        .push_static(", 'normal', ")
        .bind(write.created_at_ms)
        .push_static(", '', ")
        .bind(write.scope.workspace_id.as_str())
        .push_static(", ")
        .bind(write.mentions_json.as_str())
        .push_static(", ")
        .bind(write.parent_message_id.as_deref())
        .push_static(", ")
        .bind(write.metadata_json.as_str())
        .push_static(", ")
        .bind(write.request_hash.as_str())
        .push_static(" FROM workspace_profiles p JOIN bcs_group_sessions s ON s.env = 'memstack' ")
        .push_static("AND s.session_id = ")
        .bind(write.session_id.as_str())
        .push_static(" WHERE p.tenant_id = ")
        .bind(write.scope.tenant_id.as_str())
        .push_static(" AND p.project_id = ")
        .bind(write.scope.project_id.as_str())
        .push_static(" AND p.workspace_id = ")
        .bind(write.scope.workspace_id.as_str())
        .build()
}

fn outbox_insert(flavor: DbSqlFlavor, write: &WorkspaceMessageWrite) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, \
             aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, \
             metadata_json, correlation_id, idempotency_key) VALUES (",
        )
        .bind(write.outbox_id.as_str())
        .push_static(", ")
        .bind(write.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(write.scope.project_id.as_str())
        .push_static(", ")
        .bind(write.scope.workspace_id.as_str())
        .push_static(", 'workspace_message', ")
        .bind(write.message_id.as_str())
        .push_static(", 'workspace_message_created', ")
        .bind(format!("workspace:{}:events", write.scope.workspace_id))
        .push_static(", COALESCE((SELECT MAX(event_sequence) + 1 FROM workspace_outbox WHERE ")
        .push_static("workspace_id = ")
        .bind(write.scope.workspace_id.as_str())
        .push_static(" AND stream_name = ")
        .bind(format!("workspace:{}:events", write.scope.workspace_id))
        .push_static(" AND event_sequence >= ")
        .bind(MESSAGE_EVENT_SEQUENCE_BASE)
        .push_static("), ")
        .bind(MESSAGE_EVENT_SEQUENCE_BASE + 1)
        .push_static("), ")
        .bind(write.event_payload_json.as_str())
        .push_static(", ")
        .bind(write.event_metadata_json.as_str())
        .push_static(", ")
        .bind(write.correlation_id.as_str())
        .push_static(", ")
        .bind(format!("message-event:{}", write.idempotency_key))
        .push_static(")")
        .build()
}

fn correlation_insert(flavor: DbSqlFlavor, write: &WorkspaceMessageWrite) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_message_correlations (correlation_id, tenant_id, project_id, \
             workspace_id, legacy_message_id, conversation_id, bcs_session_id, bcs_message_id, \
             message_kind, is_terminal, idempotency_key, request_hash, event_outbox_id) VALUES (",
        )
        .bind(write.correlation_id.as_str())
        .push_static(", ")
        .bind(write.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(write.scope.project_id.as_str())
        .push_static(", ")
        .bind(write.scope.workspace_id.as_str())
        .push_static(", ")
        .bind(write.message_id.as_str())
        .push_static(", ")
        .bind(write.session_id.as_str())
        .push_static(", ")
        .bind(write.session_id.as_str())
        .push_static(", ")
        .bind(write.message_id.as_str())
        .push_static(", 'workspace_chat', FALSE, ")
        .bind(write.idempotency_key.as_str())
        .push_static(", ")
        .bind(write.request_hash.as_str())
        .push_static(", ")
        .bind(write.outbox_id.as_str())
        .push_static(")")
        .build()
}

pub(crate) fn message_select(flavor: DbSqlFlavor, message_id: &str) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT message_id, group_id, workspace_id, sender_id, sender_type, content, \
             mentions_json, parent_message_id, metadata_json, created_at FROM bcs_messages \
             WHERE message_id = ",
        )
        .bind(message_id)
        .push_static(" LIMIT 1")
        .build()
}

fn replay_message(flavor: DbSqlFlavor, write: &WorkspaceMessageWrite) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT m.message_id, m.group_id, m.workspace_id, m.sender_id, m.sender_type, \
             m.content, m.mentions_json, m.parent_message_id, m.metadata_json, m.created_at, \
             c.request_hash FROM workspace_message_correlations c JOIN bcs_messages m \
               ON m.message_id = c.bcs_message_id WHERE c.tenant_id = ",
        )
        .bind(write.scope.tenant_id.as_str())
        .push_static(" AND c.project_id = ")
        .bind(write.scope.project_id.as_str())
        .push_static(" AND c.workspace_id = ")
        .bind(write.scope.workspace_id.as_str())
        .push_static(" AND c.idempotency_key = ")
        .bind(write.idempotency_key.as_str())
        .push_static(" LIMIT 1")
        .build()
}

fn list_messages(
    flavor: DbSqlFlavor,
    scope: &WorkspaceMessageScope,
    limit: i64,
    before: Option<&str>,
) -> DbStatement {
    let mut builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT m.message_id, m.group_id, m.workspace_id, m.sender_id, m.sender_type, \
             m.content, m.mentions_json, m.parent_message_id, m.metadata_json, m.created_at \
             FROM bcs_messages m WHERE m.env = 'memstack' AND m.workspace_id = ",
        )
        .bind(scope.workspace_id.as_str())
        .push_static(" AND EXISTS (SELECT 1 FROM workspace_profiles p WHERE p.tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND p.project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND p.workspace_id = m.workspace_id)");
    if let Some(before) = before {
        builder = builder
            .push_static(
                " AND (NOT EXISTS (SELECT 1 FROM bcs_messages b WHERE b.env = 'memstack' \
                 AND b.workspace_id = m.workspace_id AND b.message_id = ",
            )
            .bind(before)
            .push_static(") OR m.created_at < (SELECT b.created_at FROM bcs_messages b ")
            .push_static("WHERE b.env = 'memstack' AND b.workspace_id = m.workspace_id ")
            .push_static("AND b.message_id = ")
            .bind(before)
            .push_static(") OR (m.created_at = (SELECT b.created_at FROM bcs_messages b ")
            .push_static("WHERE b.env = 'memstack' AND b.workspace_id = m.workspace_id ")
            .push_static("AND b.message_id = ")
            .bind(before)
            .push_static(") AND m.message_id < ")
            .bind(before)
            .push_static("))");
    }
    builder
        .push_static(" ORDER BY m.created_at ASC, m.message_id ASC LIMIT ")
        .bind(limit)
        .build()
}

fn mention_messages(
    flavor: DbSqlFlavor,
    scope: &WorkspaceMessageScope,
    target_id: &str,
    limit: i64,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT m.message_id, m.group_id, m.workspace_id, m.sender_id, m.sender_type, \
             m.content, m.mentions_json, m.parent_message_id, m.metadata_json, m.created_at \
             FROM bcs_messages m WHERE m.env = 'memstack' AND m.workspace_id = ",
        )
        .bind(scope.workspace_id.as_str());
    let builder = match flavor {
        DbSqlFlavor::Postgres => builder
            .push_static(" AND m.mentions_json @> ")
            .bind(format!(
                "[{}]",
                serde_json::to_string(target_id).unwrap_or_default()
            )),
        DbSqlFlavor::Sqlite => builder
            .push_static(
                " AND EXISTS (SELECT 1 FROM json_each(m.mentions_json) mention_value \
                 WHERE mention_value.value = ",
            )
            .bind(target_id)
            .push_static(")"),
        DbSqlFlavor::Mysql => builder,
    };
    builder
        .push_static(" ORDER BY m.created_at ASC, m.message_id ASC LIMIT ")
        .bind(limit)
        .build()
}

fn agent_targets(flavor: DbSqlFlavor, scope: &WorkspaceMessageScope) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT agent_id, bot_uuid, display_name, is_active FROM workspace_agent_bindings \
             WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" ORDER BY created_at ASC, binding_id ASC")
        .build()
}

fn member_targets(flavor: DbSqlFlavor, scope: &WorkspaceMessageScope) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT user_id FROM workspace_members WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .build()
}

fn mention_count(mentions: &[String]) -> Result<u64, WorkspaceMessageStoreError> {
    u64::try_from(mentions.len()).map_err(|_| {
        WorkspaceMessageStoreError::InvalidRecord(
            "mention count cannot be represented by the database contract".to_string(),
        )
    })
}

fn classify_write_error(error: DbError) -> WorkspaceMessageStoreError {
    if error.is_duplicate_key() {
        return WorkspaceMessageStoreError::DomainConflict;
    }
    if let DbError::TransactionExpectation { step_index, .. } = &error {
        return match *step_index {
            0 => WorkspaceMessageStoreError::NotFound,
            1 => WorkspaceMessageStoreError::EditorAccessRequired,
            2 => WorkspaceMessageStoreError::IdentityUnavailable,
            3 => WorkspaceMessageStoreError::InvalidMention,
            5..=8 => WorkspaceMessageStoreError::DomainConflict,
            _ => WorkspaceMessageStoreError::Database(error),
        };
    }
    WorkspaceMessageStoreError::Database(error)
}

pub(crate) fn message_from_row(
    row: &DbRow,
) -> Result<WorkspaceMessageRecord, WorkspaceMessageStoreError> {
    let content_json = required_string(row, "content")?;
    let content = serde_json::from_str::<String>(&content_json).unwrap_or(content_json);
    let mentions_json = required_string(row, "mentions_json")?;
    let mentions =
        serde_json::from_str(&mentions_json).map_err(WorkspaceMessageStoreError::InvalidJson)?;
    let metadata_json = required_string(row, "metadata_json")?;
    let metadata: Value =
        serde_json::from_str(&metadata_json).map_err(WorkspaceMessageStoreError::InvalidJson)?;
    if !metadata.is_object() {
        return Err(WorkspaceMessageStoreError::InvalidRecord(
            "metadata_json is not an object".to_string(),
        ));
    }
    Ok(WorkspaceMessageRecord {
        id: required_string(row, "message_id")?,
        group_id: required_string(row, "group_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        sender_id: required_string(row, "sender_id")?,
        sender_type: required_string(row, "sender_type")?,
        content,
        mentions,
        parent_message_id: row.get_string("parent_message_id")?,
        metadata,
        created_at_ms: required_i64(row, "created_at")?,
    })
}

fn agent_target_from_row(
    row: &DbRow,
) -> Result<WorkspaceMessageMentionTarget, WorkspaceMessageStoreError> {
    Ok(WorkspaceMessageMentionTarget {
        delivery_target: WorkspaceMessageDeliveryTarget {
            agent_id: required_string(row, "agent_id")?,
            bot_uuid: required_string(row, "bot_uuid")?,
            display_name: row.get_string("display_name")?,
        },
        is_active: row.get_bool("is_active")?.ok_or_else(|| {
            WorkspaceMessageStoreError::InvalidRecord("is_active is missing".to_string())
        })?,
    })
}

fn required_string(row: &DbRow, column: &str) -> Result<String, WorkspaceMessageStoreError> {
    row.get_string(column)?
        .ok_or_else(|| WorkspaceMessageStoreError::InvalidRecord(format!("{column} is missing")))
}

fn required_i64(row: &DbRow, column: &str) -> Result<i64, WorkspaceMessageStoreError> {
    row.get_i64(column)?
        .ok_or_else(|| WorkspaceMessageStoreError::InvalidRecord(format!("{column} is missing")))
}

#[cfg(test)]
#[path = "message_sql_tests.rs"]
mod sql_tests;
