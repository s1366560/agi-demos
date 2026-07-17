use std::{
    collections::HashSet,
    path::Path,
    sync::{Arc, Mutex},
    time::Duration,
};

use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

use super::{
    authority_store::{
        artifact_status_name, insert_plan_version, insert_run, insert_run_event,
        is_recovered_unstarted_run, query_conversation, query_latest_draft_plan,
        query_plan_version, query_run, query_run_by_idempotency, recover_interrupted_runs,
        typed_rows, update_conversation_in_transaction, update_plan_version, update_run,
        ApprovePlanOutcome, DesktopArtifactDelivery, DesktopArtifactStatus, DesktopArtifactVersion,
        DesktopAuthorityError, DesktopExecutionEnvironment, DesktopHitlRequest, DesktopHitlStatus,
        DesktopPermissionProfile, DesktopPlanStatus, DesktopPlanVersion, DesktopRun,
        DesktopRunStatus,
    },
    steering::{DesktopRunInput, RunInputDelivery, RunInputReference, RunInputStatus},
    tool_authority::{
        GrantConsumption, InvocationStatus, PermissionGrant, ToolInvocation, ToolInvocationRequest,
        ToolMetadata,
    },
    ConversationCapabilityMode, ConversationRunMode, LocalConversation,
};

const DESKTOP_SESSION_SCHEMA_VERSION: i64 = 12;

pub(super) struct PreparedToolInvocation {
    pub(super) invocation: ToolInvocation,
    pub(super) existing: bool,
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum DesktopClientTurnClaimError {
    PayloadConflict,
    Storage(String),
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct DesktopCheckpointAuthority {
    pub(super) conversation_id: String,
    pub(super) run_id: String,
    pub(super) project_id: String,
    pub(super) plan_version_id: String,
    pub(super) request_message: String,
    pub(super) permission_profile: DesktopPermissionProfile,
    pub(super) environment: Option<DesktopExecutionEnvironment>,
    pub(super) generation_id: String,
    pub(super) predecessor_generation_id: Option<String>,
    pub(super) created_at: String,
    pub(super) updated_at: String,
}

impl DesktopCheckpointAuthority {
    fn from_run(run: &DesktopRun, now: &str, predecessor_generation_id: Option<String>) -> Self {
        Self {
            conversation_id: run.conversation_id.clone(),
            run_id: run.id.clone(),
            project_id: run.project_id.clone(),
            plan_version_id: run.plan_version_id.clone(),
            request_message: run.request_message.clone(),
            permission_profile: run.permission_profile,
            environment: run.environment.clone(),
            generation_id: format!("checkpoint-generation-{}", Uuid::new_v4()),
            predecessor_generation_id,
            created_at: now.to_string(),
            updated_at: now.to_string(),
        }
    }

    pub(super) fn matches_run(&self, run: &DesktopRun) -> bool {
        self.conversation_id == run.conversation_id
            && self.run_id == run.id
            && self.project_id == run.project_id
            && self.plan_version_id == run.plan_version_id
            && self.request_message == run.request_message
            && self.permission_profile == run.permission_profile
            && self.environment == run.environment
    }
}

#[derive(Clone)]
pub(super) struct DesktopSessionStore {
    connection: Arc<Mutex<Connection>>,
}

pub(super) struct ApprovePlanStartInput<'a> {
    pub(super) conversation_id: &'a str,
    pub(super) project_id: &'a str,
    pub(super) plan_version_id: &'a str,
    pub(super) expected_plan_version: i64,
    pub(super) idempotency_key: &'a str,
    pub(super) message_id: &'a str,
    pub(super) request_message: &'a str,
    pub(super) environment: Option<DesktopExecutionEnvironment>,
    pub(super) requested_environment_kind: super::authority_store::DesktopExecutionEnvironmentKind,
    pub(super) permission_profile: DesktopPermissionProfile,
    pub(super) now: &'a str,
}

pub(super) struct CreateRunInput<'a> {
    pub(super) run_id: &'a str,
    pub(super) expected_run_revision: u64,
    pub(super) message_id: &'a str,
    pub(super) idempotency_key: &'a str,
    pub(super) delivery: RunInputDelivery,
    pub(super) content: &'a str,
    pub(super) references: Vec<RunInputReference>,
    pub(super) now: &'a str,
}

#[derive(Clone, Debug, Serialize)]
pub(super) struct WorkspaceTaskProjection {
    pub(super) id: String,
    pub(super) workspace_id: String,
    pub(super) conversation_id: String,
    pub(super) title: String,
    pub(super) status: Option<String>,
    pub(super) priority: Option<String>,
    pub(super) order_index: i64,
    pub(super) plan_version_id: String,
    pub(super) plan_version: i64,
    pub(super) plan_status: DesktopPlanStatus,
    pub(super) run_id: Option<String>,
    pub(super) run_status: Option<DesktopRunStatus>,
    pub(super) run_revision: Option<u64>,
    pub(super) source: &'static str,
    pub(super) task: Value,
}

#[derive(Clone, Debug, Serialize)]
pub(super) struct WorkspaceConversationExecution {
    pub(super) conversation_id: String,
    pub(super) title: String,
    pub(super) capability_mode: ConversationCapabilityMode,
    pub(super) current_mode: ConversationRunMode,
    pub(super) updated_at: String,
    pub(super) plan: Option<DesktopPlanVersion>,
    pub(super) run: Option<DesktopRun>,
    pub(super) pending_hitl: Vec<DesktopHitlRequest>,
    pub(super) artifacts: Vec<DesktopArtifactVersion>,
    pub(super) delivery: Vec<DesktopArtifactDelivery>,
}

#[derive(Clone, Debug, Serialize)]
pub(super) struct WorkspaceExecutionSnapshot {
    pub(super) workspace_id: String,
    pub(super) project_id: String,
    pub(super) tasks: Vec<WorkspaceTaskProjection>,
    pub(super) conversation_plans: Vec<WorkspaceConversationExecution>,
    pub(super) plan_history: Vec<DesktopPlanVersion>,
    pub(super) run_health: Vec<DesktopRun>,
    pub(super) pending_hitl: Vec<DesktopHitlRequest>,
    pub(super) delivery: Vec<DesktopArtifactDelivery>,
    pub(super) artifact_index: Vec<DesktopArtifactVersion>,
}

#[derive(Clone, Debug, Serialize)]
pub(super) struct ConversationSessionSnapshot {
    pub(super) conversation: LocalConversation,
    pub(super) current_run: Option<DesktopRun>,
    pub(super) run_history: Vec<DesktopRun>,
    pub(super) current_plan: Option<DesktopPlanVersion>,
    pub(super) plan_history: Vec<DesktopPlanVersion>,
    pub(super) tasks: Vec<Value>,
    pub(super) pending_hitl: Vec<DesktopHitlRequest>,
    pub(super) artifact_versions: Vec<DesktopArtifactVersion>,
    pub(super) artifact_deliveries: Vec<DesktopArtifactDelivery>,
    pub(super) tool_invocations: Vec<ToolInvocation>,
}

impl DesktopSessionStore {
    pub(super) fn open(path: &Path) -> Result<Self, String> {
        let connection = Connection::open(path).map_err(|error| error.to_string())?;
        Self::from_connection(connection).map_err(|error| {
            if error.contains("database is locked") || error.contains("database is busy") {
                "desktop session store is already owned by another local runtime".to_string()
            } else {
                error
            }
        })
    }

    #[cfg(test)]
    pub(super) fn in_memory() -> Result<Self, String> {
        let connection = Connection::open_in_memory().map_err(|error| error.to_string())?;
        Self::from_connection(connection)
    }

    fn from_connection(connection: Connection) -> Result<Self, String> {
        let stored_schema_version: i64 = connection
            .query_row("PRAGMA user_version", [], |row| row.get(0))
            .map_err(|error| error.to_string())?;
        if stored_schema_version > DESKTOP_SESSION_SCHEMA_VERSION {
            return Err(format!(
                "desktop session store schema version {stored_schema_version} is newer than supported schema version {DESKTOP_SESSION_SCHEMA_VERSION}"
            ));
        }
        // This database is an execution authority, not a shared read model. Keep one SQLite
        // connection in EXCLUSIVE locking mode for the store lifetime so a second desktop process
        // fails before it can recover or execute the same run concurrently.
        connection
            .busy_timeout(Duration::ZERO)
            .map_err(|error| error.to_string())?;
        connection
            .execute_batch(
                "PRAGMA foreign_keys = ON;
                 PRAGMA locking_mode = EXCLUSIVE;
                 PRAGMA journal_mode = WAL;
                 CREATE TABLE IF NOT EXISTS desktop_workspaces (
                   id TEXT PRIMARY KEY,
                   project_id TEXT NOT NULL,
                   value_json TEXT NOT NULL
                 );
                 CREATE TABLE IF NOT EXISTS desktop_seed_migrations (
                   seed_id TEXT PRIMARY KEY,
                   seed_kind TEXT NOT NULL,
                   applied_at TEXT NOT NULL,
                   value_json TEXT NOT NULL
                 );
                 CREATE TABLE IF NOT EXISTS desktop_workspace_messages (
                   id TEXT PRIMARY KEY,
                   workspace_id TEXT NOT NULL,
                   position INTEGER NOT NULL,
                   value_json TEXT NOT NULL,
                   UNIQUE(workspace_id, position)
                 );
                 CREATE TABLE IF NOT EXISTS desktop_conversations (
                   id TEXT PRIMARY KEY,
                   project_id TEXT NOT NULL,
                   workspace_id TEXT,
                   updated_at TEXT NOT NULL,
                   value_json TEXT NOT NULL
                 );
                 CREATE TABLE IF NOT EXISTS desktop_timeline (
                   id TEXT PRIMARY KEY,
                   conversation_id TEXT NOT NULL,
                   position INTEGER NOT NULL,
                   value_json TEXT NOT NULL,
                   UNIQUE(conversation_id, position)
                 );
                 CREATE TABLE IF NOT EXISTS desktop_agent_plan_tasks (
                   id TEXT PRIMARY KEY,
                   conversation_id TEXT NOT NULL,
                   position INTEGER NOT NULL,
                   value_json TEXT NOT NULL,
                   UNIQUE(conversation_id, position)
                 );
                 CREATE TABLE IF NOT EXISTS desktop_plan_versions (
                   id TEXT PRIMARY KEY,
                   conversation_id TEXT NOT NULL,
                   version INTEGER NOT NULL,
                   status TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   value_json TEXT NOT NULL,
                   UNIQUE(conversation_id, version)
                 );
                 CREATE TABLE IF NOT EXISTS desktop_runs (
                   id TEXT PRIMARY KEY,
                   conversation_id TEXT NOT NULL,
                   project_id TEXT NOT NULL,
                   plan_version_id TEXT NOT NULL,
                   idempotency_key TEXT NOT NULL UNIQUE,
                   status TEXT NOT NULL,
                   revision INTEGER NOT NULL,
                   created_at TEXT NOT NULL,
                   updated_at TEXT NOT NULL,
                   value_json TEXT NOT NULL
                 );
                 CREATE TABLE IF NOT EXISTS desktop_run_events (
                   id TEXT PRIMARY KEY,
                   run_id TEXT NOT NULL,
                   revision INTEGER NOT NULL,
                   event_type TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   value_json TEXT NOT NULL,
                   UNIQUE(run_id, revision)
                 );
                 CREATE TABLE IF NOT EXISTS desktop_client_turns (
                   conversation_id TEXT NOT NULL,
                   message_id TEXT NOT NULL,
                   payload_hash TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   PRIMARY KEY(conversation_id, message_id),
                   FOREIGN KEY(conversation_id) REFERENCES desktop_conversations(id)
                     ON DELETE CASCADE
                 );
                 CREATE TABLE IF NOT EXISTS desktop_run_inputs (
                   id TEXT PRIMARY KEY,
                   conversation_id TEXT NOT NULL,
                   run_id TEXT NOT NULL,
                   expected_run_revision INTEGER NOT NULL,
                   message_id TEXT NOT NULL,
                   idempotency_key TEXT NOT NULL UNIQUE,
                   delivery TEXT NOT NULL,
                   status TEXT NOT NULL,
                   sequence INTEGER NOT NULL,
                   created_at TEXT NOT NULL,
                   updated_at TEXT NOT NULL,
                   value_json TEXT NOT NULL,
                   UNIQUE(run_id, sequence),
                   UNIQUE(run_id, message_id)
                 );
                 CREATE TABLE IF NOT EXISTS desktop_hitl_requests (
                   id TEXT PRIMARY KEY,
                   conversation_id TEXT NOT NULL,
                   run_id TEXT,
                   status TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   responded_at TEXT,
                   value_json TEXT NOT NULL
                 );
                 CREATE TABLE IF NOT EXISTS desktop_artifacts (
                   id TEXT PRIMARY KEY,
                   conversation_id TEXT NOT NULL,
                   source_artifact_id TEXT NOT NULL,
                   current_version_id TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   updated_at TEXT NOT NULL,
                   value_json TEXT NOT NULL,
                   UNIQUE(conversation_id, source_artifact_id)
                 );
                 CREATE TABLE IF NOT EXISTS desktop_artifact_versions (
                   id TEXT PRIMARY KEY,
                   artifact_id TEXT NOT NULL,
                   conversation_id TEXT NOT NULL,
                   run_id TEXT,
                   version INTEGER NOT NULL,
                   status TEXT NOT NULL,
                   revision INTEGER NOT NULL,
                   created_at TEXT NOT NULL,
                   updated_at TEXT NOT NULL,
                   value_json TEXT NOT NULL,
                   UNIQUE(artifact_id, version)
                 );
                 CREATE TABLE IF NOT EXISTS desktop_artifact_deliveries (
                   id TEXT PRIMARY KEY,
                   artifact_version_id TEXT NOT NULL,
                   artifact_id TEXT NOT NULL,
                   conversation_id TEXT NOT NULL,
                   idempotency_key TEXT NOT NULL UNIQUE,
                   created_at TEXT NOT NULL,
                   value_json TEXT NOT NULL
                 );
                 CREATE TABLE IF NOT EXISTS desktop_decisions (
                   id TEXT PRIMARY KEY,
                   conversation_id TEXT NOT NULL,
                   plan_version_id TEXT NOT NULL,
                   run_id TEXT NOT NULL,
                   decision TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   value_json TEXT NOT NULL
                 );
                 CREATE TABLE IF NOT EXISTS desktop_permission_grants (
                   id TEXT PRIMARY KEY,
                   run_id TEXT NOT NULL,
                   plan_version_id TEXT NOT NULL,
                   run_revision INTEGER NOT NULL,
                   environment_id TEXT NOT NULL,
                   tool_name TEXT NOT NULL,
                   uses INTEGER NOT NULL,
                   use_limit INTEGER NOT NULL,
                   expires_at_ms INTEGER NOT NULL,
                   source TEXT NOT NULL,
                   created_at_ms INTEGER NOT NULL,
                   value_json TEXT NOT NULL
                 );
                 CREATE TABLE IF NOT EXISTS desktop_tool_invocations (
                   id TEXT PRIMARY KEY,
                   run_id TEXT NOT NULL,
                   plan_version_id TEXT NOT NULL,
                   run_revision INTEGER NOT NULL,
                   environment_id TEXT NOT NULL,
                   tool_name TEXT NOT NULL,
                   grant_id TEXT,
                   input_digest TEXT NOT NULL,
                   status TEXT NOT NULL,
                   prepared_at_ms INTEGER NOT NULL,
                   finished_at_ms INTEGER,
                   value_json TEXT NOT NULL
                 );
                 CREATE TABLE IF NOT EXISTS desktop_checkpoint_authorities (
                   conversation_id TEXT PRIMARY KEY,
                   run_id TEXT NOT NULL,
                   plan_version_id TEXT NOT NULL,
                   generation_id TEXT NOT NULL UNIQUE,
                   created_at TEXT NOT NULL,
                   updated_at TEXT NOT NULL,
                   value_json TEXT NOT NULL
                 );
                 CREATE INDEX IF NOT EXISTS idx_desktop_workspaces_project
                   ON desktop_workspaces(project_id);
                 CREATE INDEX IF NOT EXISTS idx_desktop_conversations_scope
                   ON desktop_conversations(project_id, workspace_id, updated_at DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_timeline_conversation
                   ON desktop_timeline(conversation_id, position);
                 CREATE INDEX IF NOT EXISTS idx_desktop_agent_plan_tasks_conversation
                   ON desktop_agent_plan_tasks(conversation_id, position);
                 CREATE INDEX IF NOT EXISTS idx_desktop_plan_versions_conversation
                   ON desktop_plan_versions(conversation_id, version DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_runs_conversation
                   ON desktop_runs(conversation_id, created_at DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_run_events_run
                   ON desktop_run_events(run_id, revision);
                 CREATE INDEX IF NOT EXISTS idx_desktop_client_turns_conversation
                   ON desktop_client_turns(conversation_id, created_at);
                 CREATE INDEX IF NOT EXISTS idx_desktop_run_inputs_run
                   ON desktop_run_inputs(run_id, sequence);
                 CREATE INDEX IF NOT EXISTS idx_desktop_run_inputs_pending
                   ON desktop_run_inputs(run_id, delivery, status, sequence);
                 CREATE INDEX IF NOT EXISTS idx_desktop_hitl_conversation
                   ON desktop_hitl_requests(conversation_id, created_at DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_artifact_versions_conversation
                   ON desktop_artifact_versions(conversation_id, created_at DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_artifact_versions_artifact
                   ON desktop_artifact_versions(artifact_id, version DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_artifact_deliveries_conversation
                   ON desktop_artifact_deliveries(conversation_id, created_at DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_permission_grants_run
                   ON desktop_permission_grants(run_id, created_at_ms DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_tool_invocations_run
                   ON desktop_tool_invocations(run_id, prepared_at_ms DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_tool_invocations_status
                   ON desktop_tool_invocations(status, prepared_at_ms DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_checkpoint_authorities_run
                   ON desktop_checkpoint_authorities(run_id);",
            )
            .map_err(|error| error.to_string())?;
        let locking_mode: String = connection
            .query_row("PRAGMA locking_mode", [], |row| row.get(0))
            .map_err(|error| error.to_string())?;
        if !locking_mode.eq_ignore_ascii_case("exclusive") {
            return Err(format!(
                "desktop session store requires exclusive SQLite ownership, got {locking_mode}"
            ));
        }
        super::auth_context::initialize_auth_context_schema(&connection)?;
        super::resource_registry::initialize_resource_registry(&connection)?;
        connection
            .pragma_update(None, "user_version", DESKTOP_SESSION_SCHEMA_VERSION)
            .map_err(|error| error.to_string())?;
        recover_inflight_tool_invocations(&connection, chrono::Utc::now().timestamp_millis())?;
        recover_interrupted_runs(&connection, &super::now_iso())?;
        Ok(Self {
            connection: Arc::new(Mutex::new(connection)),
        })
    }

    pub(super) fn ensure_workspace(&self, workspace: &Value) -> Result<(), String> {
        let id = required_string(workspace, "id")?;
        let project_id = required_string(workspace, "project_id")?;
        let value_json = serde_json::to_string(workspace).map_err(|error| error.to_string())?;
        self.connection()?
            .execute(
                "INSERT OR IGNORE INTO desktop_workspaces(id, project_id, value_json)
                 VALUES (?1, ?2, ?3)",
                params![id, project_id, value_json],
            )
            .map_err(|error| error.to_string())?;
        Ok(())
    }

    pub(super) fn ensure_local_demo_hierarchy_seed(
        &self,
        seed_id: &str,
        workspaces: &[Value],
        conversations: &[LocalConversation],
        applied_at: &str,
    ) -> Result<(), String> {
        let seed_id = seed_id.trim();
        if seed_id.is_empty() {
            return Err("local demo seed id is required".to_string());
        }
        if workspaces.is_empty() || conversations.is_empty() {
            return Err(
                "local demo hierarchy seed requires workspaces and conversations".to_string(),
            );
        }

        let mut workspace_ids = HashSet::with_capacity(workspaces.len());
        let mut workspace_manifest = Vec::with_capacity(workspaces.len());
        for workspace in workspaces {
            let id = required_string(workspace, "id")?;
            let tenant_id = required_string(workspace, "tenant_id")?;
            let project_id = required_string(workspace, "project_id")?;
            if !workspace_ids.insert(id.clone()) {
                return Err(format!("duplicate local demo workspace id: {id}"));
            }
            workspace_manifest.push(json!({
                "id": id,
                "tenant_id": tenant_id,
                "project_id": project_id,
            }));
        }

        let mut conversation_ids = HashSet::with_capacity(conversations.len());
        let mut conversation_manifest = Vec::with_capacity(conversations.len());
        for conversation in conversations {
            if !conversation_ids.insert(conversation.id.clone()) {
                return Err(format!(
                    "duplicate local demo conversation id: {}",
                    conversation.id
                ));
            }
            let workspace_id = conversation.workspace_id.as_deref().ok_or_else(|| {
                format!(
                    "local demo conversation {} requires a workspace",
                    conversation.id
                )
            })?;
            if !workspace_ids.contains(workspace_id) {
                return Err(format!(
                    "local demo conversation {} references an unseeded workspace",
                    conversation.id
                ));
            }
            conversation_manifest.push(json!({
                "id": conversation.id,
                "tenant_id": conversation.tenant_id,
                "project_id": conversation.project_id,
                "workspace_id": workspace_id,
            }));
        }

        let manifest = json!({
            "seed_id": seed_id,
            "kind": "local_demo_hierarchy",
            "workspace_scopes": workspace_manifest,
            "conversation_scopes": conversation_manifest,
        });
        let manifest_json = serde_json::to_string(&manifest).map_err(|error| error.to_string())?;
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let existing_marker = transaction
            .query_row(
                "SELECT seed_kind, value_json FROM desktop_seed_migrations WHERE seed_id = ?1",
                [seed_id],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        if let Some((seed_kind, existing_manifest)) = existing_marker.as_ref() {
            if seed_kind != "local_demo_hierarchy" || existing_manifest != &manifest_json {
                return Err(format!("local demo seed manifest conflict: {seed_id}"));
            }
        }
        let seed_already_applied = existing_marker.is_some();

        for workspace in workspaces {
            let id = required_string(workspace, "id")?;
            let expected_tenant_id = required_string(workspace, "tenant_id")?;
            let expected_project_id = required_string(workspace, "project_id")?;
            let existing = transaction
                .query_row(
                    "SELECT project_id, value_json FROM desktop_workspaces WHERE id = ?1",
                    [&id],
                    |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
                )
                .optional()
                .map_err(|error| error.to_string())?;
            if let Some((stored_project_id, stored_json)) = existing {
                let stored: Value =
                    serde_json::from_str(&stored_json).map_err(|error| error.to_string())?;
                let stored_id = required_string(&stored, "id")?;
                let stored_tenant_id = required_string(&stored, "tenant_id")?;
                let stored_value_project_id = required_string(&stored, "project_id")?;
                if stored_id != id
                    || stored_project_id != expected_project_id
                    || stored_value_project_id != expected_project_id
                    || stored_tenant_id != expected_tenant_id
                {
                    return Err(format!("local demo workspace scope conflict: {id}"));
                }
                if stored.pointer("/metadata/provenance")
                    != workspace.pointer("/metadata/provenance")
                {
                    return Err(format!("local demo workspace provenance conflict: {id}"));
                }
                continue;
            }
            if seed_already_applied {
                return Err(format!("local demo seeded workspace is missing: {id}"));
            }
            transaction
                .execute(
                    "INSERT INTO desktop_workspaces(id, project_id, value_json)
                     VALUES (?1, ?2, ?3)",
                    params![
                        id,
                        expected_project_id,
                        serde_json::to_string(workspace).map_err(|error| error.to_string())?
                    ],
                )
                .map_err(|error| error.to_string())?;
        }

        for conversation in conversations {
            let existing = transaction
                .query_row(
                    "SELECT project_id, workspace_id, value_json
                     FROM desktop_conversations WHERE id = ?1",
                    [&conversation.id],
                    |row| {
                        Ok((
                            row.get::<_, String>(0)?,
                            row.get::<_, Option<String>>(1)?,
                            row.get::<_, String>(2)?,
                        ))
                    },
                )
                .optional()
                .map_err(|error| error.to_string())?;
            if let Some((stored_project_id, stored_workspace_id, existing_json)) = existing {
                let stored: LocalConversation =
                    serde_json::from_str(&existing_json).map_err(|error| error.to_string())?;
                if stored.id != conversation.id
                    || stored.tenant_id != conversation.tenant_id
                    || stored.project_id != conversation.project_id
                    || stored.workspace_id != conversation.workspace_id
                {
                    return Err(format!(
                        "local demo conversation scope conflict: {}",
                        conversation.id
                    ));
                }
                if stored_project_id != conversation.project_id
                    || stored_workspace_id != conversation.workspace_id
                {
                    return Err(format!(
                        "local demo conversation column scope conflict: {}",
                        conversation.id
                    ));
                }
                continue;
            }
            if seed_already_applied {
                return Err(format!(
                    "local demo seeded conversation is missing: {}",
                    conversation.id
                ));
            }
            transaction
                .execute(
                    "INSERT INTO desktop_conversations(
                       id, project_id, workspace_id, updated_at, value_json
                     ) VALUES (?1, ?2, ?3, ?4, ?5)",
                    params![
                        conversation.id,
                        conversation.project_id,
                        conversation.workspace_id,
                        conversation.updated_at,
                        serde_json::to_string(conversation).map_err(|error| error.to_string())?
                    ],
                )
                .map_err(|error| error.to_string())?;
        }

        if !seed_already_applied {
            transaction
                .execute(
                    "INSERT INTO desktop_seed_migrations(
                       seed_id, seed_kind, applied_at, value_json
                     ) VALUES (?1, 'local_demo_hierarchy', ?2, ?3)",
                    params![seed_id, applied_at, manifest_json],
                )
                .map_err(|error| error.to_string())?;
        }
        transaction.commit().map_err(|error| error.to_string())
    }

    pub(super) fn ensure_local_demo_session_content_seed(
        &self,
        seed_id: &str,
        conversation_id: &str,
        timeline: &[Value],
        applied_at: &str,
    ) -> Result<(), String> {
        let seed_id = seed_id.trim();
        let conversation_id = conversation_id.trim();
        if seed_id.is_empty() {
            return Err("local demo session content seed id is required".to_string());
        }
        if conversation_id.is_empty() || timeline.is_empty() {
            return Err(
                "local demo session content seed requires a conversation and timeline".to_string(),
            );
        }

        let mut event_ids = HashSet::with_capacity(timeline.len());
        for event in timeline {
            let event_id = required_string(event, "id")?;
            let event_conversation_id = required_string(event, "conversation_id")?;
            if event_conversation_id != conversation_id {
                return Err(format!(
                    "local demo session content event scope conflict: {event_id}"
                ));
            }
            if !event_ids.insert(event_id.clone()) {
                return Err(format!(
                    "duplicate local demo session content event id: {event_id}"
                ));
            }
        }

        let manifest = json!({
            "seed_id": seed_id,
            "kind": "local_demo_session_content",
            "conversation_id": conversation_id,
            "timeline": timeline,
        });
        let manifest_json = serde_json::to_string(&manifest).map_err(|error| error.to_string())?;
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let conversation_exists = transaction
            .query_row(
                "SELECT 1 FROM desktop_conversations WHERE id = ?1",
                [conversation_id],
                |_| Ok(()),
            )
            .optional()
            .map_err(|error| error.to_string())?
            .is_some();
        if !conversation_exists {
            return Err(format!(
                "local demo session content conversation is missing: {conversation_id}"
            ));
        }

        let existing_marker = transaction
            .query_row(
                "SELECT seed_kind, value_json FROM desktop_seed_migrations WHERE seed_id = ?1",
                [seed_id],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        if let Some((seed_kind, existing_manifest)) = existing_marker.as_ref() {
            if seed_kind != "local_demo_session_content" || existing_manifest != &manifest_json {
                return Err(format!(
                    "local demo session content manifest conflict: {seed_id}"
                ));
            }
        }

        let mut matching_event_count = 0_usize;
        for event in timeline {
            let event_id = required_string(event, "id")?;
            let existing = transaction
                .query_row(
                    "SELECT conversation_id, value_json FROM desktop_timeline WHERE id = ?1",
                    [&event_id],
                    |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
                )
                .optional()
                .map_err(|error| error.to_string())?;
            let Some((stored_conversation_id, stored_json)) = existing else {
                continue;
            };
            let stored: Value =
                serde_json::from_str(&stored_json).map_err(|error| error.to_string())?;
            if stored_conversation_id != conversation_id || stored != *event {
                return Err(format!(
                    "local demo session content event conflict: {event_id}"
                ));
            }
            matching_event_count += 1;
        }

        if existing_marker.is_some() {
            if matching_event_count != timeline.len() {
                return Err(format!(
                    "local demo seeded session content is incomplete: {conversation_id}"
                ));
            }
            return transaction.commit().map_err(|error| error.to_string());
        }

        let existing_timeline_count: i64 = transaction
            .query_row(
                "SELECT COUNT(*) FROM desktop_timeline WHERE conversation_id = ?1",
                [conversation_id],
                |row| row.get(0),
            )
            .map_err(|error| error.to_string())?;
        if existing_timeline_count > 0 && matching_event_count == 0 {
            return transaction.commit().map_err(|error| error.to_string());
        }
        if matching_event_count != 0 && matching_event_count != timeline.len() {
            return Err(format!(
                "local demo seeded session content is partial: {conversation_id}"
            ));
        }

        if matching_event_count == 0 {
            let next_position: i64 = transaction
                .query_row(
                    "SELECT COALESCE(MAX(position), 0) + 1 FROM desktop_timeline
                     WHERE conversation_id = ?1",
                    [conversation_id],
                    |row| row.get(0),
                )
                .map_err(|error| error.to_string())?;
            for (position_offset, event) in timeline.iter().enumerate() {
                let position_offset = i64::try_from(position_offset)
                    .map_err(|_| "local demo session content position overflow".to_string())?;
                let position = next_position
                    .checked_add(position_offset)
                    .ok_or_else(|| "local demo session content position overflow".to_string())?;
                let event_id = required_string(event, "id")?;
                let value_json = serde_json::to_string(event).map_err(|error| error.to_string())?;
                transaction
                    .execute(
                        "INSERT INTO desktop_timeline(
                           id, conversation_id, position, value_json
                         ) VALUES (?1, ?2, ?3, ?4)",
                        params![event_id, conversation_id, position, value_json],
                    )
                    .map_err(|error| error.to_string())?;
            }
        }

        transaction
            .execute(
                "INSERT INTO desktop_seed_migrations(
                   seed_id, seed_kind, applied_at, value_json
                 ) VALUES (?1, 'local_demo_session_content', ?2, ?3)",
                params![seed_id, applied_at, manifest_json],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())
    }

    pub(super) fn insert_workspace(&self, workspace: &Value) -> Result<(), String> {
        let id = required_string(workspace, "id")?;
        let project_id = required_string(workspace, "project_id")?;
        let value_json = serde_json::to_string(workspace).map_err(|error| error.to_string())?;
        self.connection()?
            .execute(
                "INSERT INTO desktop_workspaces(id, project_id, value_json) VALUES (?1, ?2, ?3)",
                params![id, project_id, value_json],
            )
            .map_err(|error| error.to_string())?;
        Ok(())
    }

    pub(super) fn list_workspaces(&self, project_id: &str) -> Result<Vec<Value>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_workspaces
                 WHERE project_id = ?1 ORDER BY rowid ASC",
            )
            .map_err(|error| error.to_string())?;
        json_rows(statement.query_map([project_id], |row| row.get::<_, String>(0)))
    }

    pub(super) fn workspace_project_id(
        &self,
        workspace_id: &str,
    ) -> Result<Option<String>, String> {
        self.connection()?
            .query_row(
                "SELECT project_id FROM desktop_workspaces WHERE id = ?1",
                [workspace_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())
    }

    pub(super) fn workspace_tenant_id(&self, workspace_id: &str) -> Result<Option<String>, String> {
        let value_json = self
            .connection()?
            .query_row(
                "SELECT value_json FROM desktop_workspaces WHERE id = ?1",
                [workspace_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        value_json
            .map(|raw| {
                let workspace: Value =
                    serde_json::from_str(&raw).map_err(|error| error.to_string())?;
                required_string(&workspace, "tenant_id")
            })
            .transpose()
    }

    pub(super) fn workspace_name(&self, workspace_id: &str) -> Result<Option<String>, String> {
        let value_json = self
            .connection()?
            .query_row(
                "SELECT value_json FROM desktop_workspaces WHERE id = ?1",
                [workspace_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        value_json
            .map(|raw| {
                let workspace: Value =
                    serde_json::from_str(&raw).map_err(|error| error.to_string())?;
                Ok(workspace
                    .get("name")
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|name| !name.is_empty())
                    .map(str::to_string))
            })
            .transpose()
            .map(Option::flatten)
    }

    pub(super) fn workspace_execution_snapshot(
        &self,
        workspace_id: &str,
        expected_project_id: &str,
        expected_tenant_id: &str,
    ) -> Result<WorkspaceExecutionSnapshot, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let project_id = transaction
            .query_row(
                "SELECT project_id FROM desktop_workspaces WHERE id = ?1",
                [workspace_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?
            .ok_or_else(|| "workspace not found".to_string())?;
        if project_id != expected_project_id {
            return Err("workspace project mismatch".to_string());
        }

        let conversations: Vec<LocalConversation> = {
            let mut statement = transaction
                .prepare(
                    "SELECT value_json FROM desktop_conversations
                     WHERE project_id = ?1 AND workspace_id = ?2
                     ORDER BY updated_at DESC LIMIT 100",
                )
                .map_err(|error| error.to_string())?;
            typed_rows(
                statement.query_map(params![project_id, workspace_id], |row| {
                    row.get::<_, String>(0)
                }),
            )?
        };

        let mut tasks = Vec::new();
        let mut conversation_plans = Vec::with_capacity(conversations.len());
        let mut plan_history = Vec::new();
        let mut run_health = Vec::new();
        let mut pending_hitl = Vec::new();
        let mut delivery = Vec::new();
        let mut artifact_index = Vec::new();

        for conversation in conversations {
            if conversation.tenant_id != expected_tenant_id {
                return Err("workspace conversation tenant mismatch".to_string());
            }
            let plans: Vec<DesktopPlanVersion> = {
                let mut statement = transaction
                    .prepare(
                        "SELECT value_json FROM desktop_plan_versions
                         WHERE conversation_id = ?1 ORDER BY version DESC LIMIT 20",
                    )
                    .map_err(|error| error.to_string())?;
                typed_rows(statement.query_map([&conversation.id], |row| row.get::<_, String>(0)))?
            };
            let latest_plan = plans.first().cloned();
            plan_history.extend(plans);

            let latest_run: Option<DesktopRun> = transaction
                .query_row(
                    "SELECT value_json FROM desktop_runs
                     WHERE conversation_id = ?1 ORDER BY created_at DESC LIMIT 1",
                    [&conversation.id],
                    |row| row.get::<_, String>(0),
                )
                .optional()
                .map_err(|error| error.to_string())?
                .map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
                .transpose()?;
            if let Some(run) = latest_run.clone() {
                run_health.push(run);
            }

            let conversation_hitl: Vec<DesktopHitlRequest> = {
                let mut statement = transaction
                    .prepare(
                        "SELECT value_json FROM desktop_hitl_requests
                         WHERE conversation_id = ?1 AND status = 'pending'
                         ORDER BY created_at DESC, id DESC LIMIT 100",
                    )
                    .map_err(|error| error.to_string())?;
                typed_rows(statement.query_map([&conversation.id], |row| row.get::<_, String>(0)))?
            };
            pending_hitl.extend(conversation_hitl.clone());

            let conversation_artifacts: Vec<DesktopArtifactVersion> = {
                let mut statement = transaction
                    .prepare(
                        "SELECT value_json FROM desktop_artifact_versions
                         WHERE conversation_id = ?1
                         ORDER BY created_at DESC, version DESC LIMIT 100",
                    )
                    .map_err(|error| error.to_string())?;
                typed_rows(statement.query_map([&conversation.id], |row| row.get::<_, String>(0)))?
            };
            artifact_index.extend(conversation_artifacts.clone());

            let conversation_delivery: Vec<DesktopArtifactDelivery> = {
                let mut statement = transaction
                    .prepare(
                        "SELECT value_json FROM desktop_artifact_deliveries
                         WHERE conversation_id = ?1 ORDER BY created_at DESC LIMIT 100",
                    )
                    .map_err(|error| error.to_string())?;
                typed_rows(statement.query_map([&conversation.id], |row| row.get::<_, String>(0)))?
            };
            delivery.extend(conversation_delivery.clone());

            if let Some(plan) = latest_plan.as_ref() {
                let plan_run = latest_run
                    .as_ref()
                    .filter(|run| run.plan_version_id == plan.id);
                for (position, task) in plan.tasks.iter().enumerate() {
                    let Some(id) = task
                        .get("id")
                        .and_then(Value::as_str)
                        .filter(|value| !value.trim().is_empty())
                        .map(ToString::to_string)
                    else {
                        continue;
                    };
                    let title = task
                        .get("content")
                        .or_else(|| task.get("title"))
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_string();
                    tasks.push(WorkspaceTaskProjection {
                        id,
                        workspace_id: workspace_id.to_string(),
                        conversation_id: conversation.id.clone(),
                        title,
                        status: optional_string(task, "status"),
                        priority: optional_string(task, "priority"),
                        order_index: task
                            .get("order_index")
                            .and_then(Value::as_i64)
                            .unwrap_or(position as i64),
                        plan_version_id: plan.id.clone(),
                        plan_version: plan.version,
                        plan_status: plan.status,
                        run_id: plan_run.map(|run| run.id.clone()),
                        run_status: plan_run.map(|run| run.status),
                        run_revision: plan_run.map(|run| run.revision),
                        source: "agent_plan_task",
                        task: task.clone(),
                    });
                }
            }

            conversation_plans.push(WorkspaceConversationExecution {
                conversation_id: conversation.id,
                title: conversation.title,
                capability_mode: conversation.capability_mode,
                current_mode: conversation.current_mode,
                updated_at: conversation.updated_at,
                plan: latest_plan,
                run: latest_run,
                pending_hitl: conversation_hitl,
                artifacts: conversation_artifacts,
                delivery: conversation_delivery,
            });
        }

        transaction.commit().map_err(|error| error.to_string())?;
        Ok(WorkspaceExecutionSnapshot {
            workspace_id: workspace_id.to_string(),
            project_id,
            tasks,
            conversation_plans,
            plan_history,
            run_health,
            pending_hitl,
            delivery,
            artifact_index,
        })
    }

    pub(super) fn conversation_session_snapshot(
        &self,
        conversation_id: &str,
    ) -> Result<Option<ConversationSessionSnapshot>, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let Some(conversation) =
            query_conversation(&transaction, conversation_id).map_err(|error| error.to_string())?
        else {
            transaction.commit().map_err(|error| error.to_string())?;
            return Ok(None);
        };

        let run_history: Vec<DesktopRun> = {
            let mut statement = transaction
                .prepare(
                    "SELECT value_json FROM desktop_runs
                     WHERE conversation_id = ?1 ORDER BY created_at DESC, id DESC",
                )
                .map_err(|error| error.to_string())?;
            typed_rows(statement.query_map([conversation_id], |row| row.get::<_, String>(0)))?
        };
        let plan_history: Vec<DesktopPlanVersion> = {
            let mut statement = transaction
                .prepare(
                    "SELECT value_json FROM desktop_plan_versions
                     WHERE conversation_id = ?1 ORDER BY version DESC, id DESC",
                )
                .map_err(|error| error.to_string())?;
            typed_rows(statement.query_map([conversation_id], |row| row.get::<_, String>(0)))?
        };
        let pending_hitl: Vec<DesktopHitlRequest> = {
            let mut statement = transaction
                .prepare(
                    "SELECT value_json FROM desktop_hitl_requests
                     WHERE conversation_id = ?1 AND status = 'pending'
                     ORDER BY created_at DESC, id DESC",
                )
                .map_err(|error| error.to_string())?;
            typed_rows(statement.query_map([conversation_id], |row| row.get::<_, String>(0)))?
        };
        let artifact_versions: Vec<DesktopArtifactVersion> = {
            let mut statement = transaction
                .prepare(
                    "SELECT value_json FROM desktop_artifact_versions
                     WHERE conversation_id = ?1 ORDER BY created_at DESC, version DESC",
                )
                .map_err(|error| error.to_string())?;
            typed_rows(statement.query_map([conversation_id], |row| row.get::<_, String>(0)))?
        };
        let artifact_deliveries: Vec<DesktopArtifactDelivery> = {
            let mut statement = transaction
                .prepare(
                    "SELECT value_json FROM desktop_artifact_deliveries
                     WHERE conversation_id = ?1 ORDER BY created_at DESC, id DESC",
                )
                .map_err(|error| error.to_string())?;
            typed_rows(statement.query_map([conversation_id], |row| row.get::<_, String>(0)))?
        };
        let tool_invocations: Vec<ToolInvocation> = {
            let mut statement = transaction
                .prepare(
                    "SELECT invocation.value_json
                     FROM desktop_tool_invocations invocation
                     JOIN desktop_runs run ON run.id = invocation.run_id
                     WHERE run.conversation_id = ?1
                     ORDER BY invocation.prepared_at_ms ASC, invocation.id ASC",
                )
                .map_err(|error| error.to_string())?;
            typed_rows(statement.query_map([conversation_id], |row| row.get::<_, String>(0)))?
        };

        let current_run = run_history.first().cloned();
        let current_plan = plan_history.first().cloned();
        let tasks = current_plan
            .as_ref()
            .map(|plan| plan.tasks.clone())
            .unwrap_or_default();
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(Some(ConversationSessionSnapshot {
            conversation,
            current_run,
            run_history,
            current_plan,
            plan_history,
            tasks,
            pending_hitl,
            artifact_versions,
            artifact_deliveries,
            tool_invocations,
        }))
    }

    pub(super) fn append_workspace_message(
        &self,
        workspace_id: &str,
        message: &Value,
    ) -> Result<(), String> {
        let id = required_string(message, "id")?;
        let value_json = serde_json::to_string(message).map_err(|error| error.to_string())?;
        let connection = self.connection()?;
        let position: i64 = connection
            .query_row(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM desktop_workspace_messages
                 WHERE workspace_id = ?1",
                [workspace_id],
                |row| row.get(0),
            )
            .map_err(|error| error.to_string())?;
        connection
            .execute(
                "INSERT INTO desktop_workspace_messages(id, workspace_id, position, value_json)
                 VALUES (?1, ?2, ?3, ?4)",
                params![id, workspace_id, position, value_json],
            )
            .map_err(|error| error.to_string())?;
        Ok(())
    }

    pub(super) fn list_workspace_messages(&self, workspace_id: &str) -> Result<Vec<Value>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_workspace_messages
                 WHERE workspace_id = ?1 ORDER BY position ASC",
            )
            .map_err(|error| error.to_string())?;
        json_rows(statement.query_map([workspace_id], |row| row.get::<_, String>(0)))
    }

    pub(super) fn insert_conversation(
        &self,
        conversation: &LocalConversation,
    ) -> Result<(), String> {
        let value_json = serde_json::to_string(conversation).map_err(|error| error.to_string())?;
        self.connection()?
            .execute(
                "INSERT INTO desktop_conversations(
                   id, project_id, workspace_id, updated_at, value_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![
                    conversation.id,
                    conversation.project_id,
                    conversation.workspace_id,
                    conversation.updated_at,
                    value_json
                ],
            )
            .map_err(|error| error.to_string())?;
        Ok(())
    }

    pub(super) fn update_conversation(
        &self,
        conversation: &LocalConversation,
    ) -> Result<(), String> {
        let value_json = serde_json::to_string(conversation).map_err(|error| error.to_string())?;
        self.connection()?
            .execute(
                "UPDATE desktop_conversations
                 SET project_id = ?2, workspace_id = ?3, updated_at = ?4, value_json = ?5
                 WHERE id = ?1",
                params![
                    conversation.id,
                    conversation.project_id,
                    conversation.workspace_id,
                    conversation.updated_at,
                    value_json
                ],
            )
            .map_err(|error| error.to_string())?;
        Ok(())
    }

    pub(super) fn conversation(&self, id: &str) -> Result<Option<LocalConversation>, String> {
        let value_json = self
            .connection()?
            .query_row(
                "SELECT value_json FROM desktop_conversations WHERE id = ?1",
                [id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        value_json
            .map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
            .transpose()
    }

    pub(super) fn list_conversations(
        &self,
        project_id: &str,
        workspace_id: Option<&str>,
    ) -> Result<Vec<LocalConversation>, String> {
        let connection = self.connection()?;
        let (sql, workspace): (&str, Option<&str>) = match workspace_id {
            Some(workspace_id) => (
                "SELECT value_json FROM desktop_conversations
                 WHERE project_id = ?1 AND workspace_id = ?2 ORDER BY updated_at DESC",
                Some(workspace_id),
            ),
            None => (
                "SELECT value_json FROM desktop_conversations
                 WHERE project_id = ?1 ORDER BY updated_at DESC",
                None,
            ),
        };
        let mut statement = connection.prepare(sql).map_err(|error| error.to_string())?;
        let rows = if let Some(workspace_id) = workspace {
            statement
                .query_map(params![project_id, workspace_id], |row| {
                    row.get::<_, String>(0)
                })
                .map_err(|error| error.to_string())?
                .collect::<Result<Vec<_>, _>>()
                .map_err(|error| error.to_string())?
        } else {
            statement
                .query_map([project_id], |row| row.get::<_, String>(0))
                .map_err(|error| error.to_string())?
                .collect::<Result<Vec<_>, _>>()
                .map_err(|error| error.to_string())?
        };
        rows.into_iter()
            .map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
            .collect()
    }

    pub(super) fn append_timeline(
        &self,
        conversation_id: &str,
        item: &Value,
    ) -> Result<(), String> {
        let id = required_string(item, "id")?;
        let value_json = serde_json::to_string(item).map_err(|error| error.to_string())?;
        let connection = self.connection()?;
        let position: i64 = connection
            .query_row(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM desktop_timeline
                 WHERE conversation_id = ?1",
                [conversation_id],
                |row| row.get(0),
            )
            .map_err(|error| error.to_string())?;
        connection
            .execute(
                "INSERT INTO desktop_timeline(id, conversation_id, position, value_json)
                 VALUES (?1, ?2, ?3, ?4)",
                params![id, conversation_id, position, value_json],
            )
            .map_err(|error| error.to_string())?;
        Ok(())
    }

    pub(super) fn timeline(
        &self,
        conversation_id: &str,
        limit: usize,
    ) -> Result<Vec<Value>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_timeline
                 WHERE conversation_id = ?1 ORDER BY position DESC LIMIT ?2",
            )
            .map_err(|error| error.to_string())?;
        let mut values = json_rows(
            statement.query_map(params![conversation_id, limit as i64], |row| {
                row.get::<_, String>(0)
            }),
        )?;
        values.reverse();
        Ok(values)
    }

    pub(super) fn timeline_count(&self, conversation_id: &str) -> Result<usize, String> {
        self.connection()?
            .query_row(
                "SELECT COUNT(*) FROM desktop_timeline WHERE conversation_id = ?1",
                [conversation_id],
                |row| row.get::<_, i64>(0),
            )
            .map(|count| count as usize)
            .map_err(|error| error.to_string())
    }

    pub(super) fn replace_agent_plan_tasks(
        &self,
        conversation_id: &str,
        tasks: &[Value],
    ) -> Result<(), String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "DELETE FROM desktop_agent_plan_tasks WHERE conversation_id = ?1",
                [conversation_id],
            )
            .map_err(|error| error.to_string())?;
        for (position, task) in tasks.iter().enumerate() {
            let id = required_string(task, "id")?;
            let value_json = serde_json::to_string(task).map_err(|error| error.to_string())?;
            transaction
                .execute(
                    "INSERT INTO desktop_agent_plan_tasks(
                       id, conversation_id, position, value_json
                     ) VALUES (?1, ?2, ?3, ?4)",
                    params![id, conversation_id, position as i64, value_json],
                )
                .map_err(|error| error.to_string())?;
        }
        let version: i64 = transaction
            .query_row(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM desktop_plan_versions
                 WHERE conversation_id = ?1",
                [conversation_id],
                |row| row.get(0),
            )
            .map_err(|error| error.to_string())?;
        let plan = DesktopPlanVersion {
            id: format!("local-plan-version-{}", Uuid::new_v4()),
            conversation_id: conversation_id.to_string(),
            version,
            status: DesktopPlanStatus::Draft,
            tasks: tasks.to_vec(),
            created_at: tasks
                .first()
                .and_then(|task| task.get("created_at"))
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            approved_at: None,
        };
        insert_plan_version(&transaction, &plan)?;
        transaction.commit().map_err(|error| error.to_string())
    }

    pub(super) fn list_agent_plan_tasks(
        &self,
        conversation_id: &str,
    ) -> Result<Vec<Value>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_agent_plan_tasks
                 WHERE conversation_id = ?1 ORDER BY position ASC",
            )
            .map_err(|error| error.to_string())?;
        json_rows(statement.query_map([conversation_id], |row| row.get::<_, String>(0)))
    }

    pub(super) fn latest_draft_plan(
        &self,
        conversation_id: &str,
    ) -> Result<Option<DesktopPlanVersion>, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let plan = query_latest_draft_plan(&transaction, conversation_id)
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(plan)
    }

    #[cfg(test)]
    pub(super) fn plan_version(
        &self,
        plan_version_id: &str,
    ) -> Result<Option<DesktopPlanVersion>, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let plan =
            query_plan_version(&transaction, plan_version_id).map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(plan)
    }

    #[cfg(test)]
    pub(super) fn approve_plan_and_start(
        &self,
        conversation_id: &str,
        project_id: &str,
        idempotency_key: &str,
        message_id: &str,
        request_message: &str,
        now: &str,
    ) -> Result<ApprovePlanOutcome, DesktopAuthorityError> {
        let plan = match self
            .run_by_idempotency_key(idempotency_key)
            .map_err(DesktopAuthorityError::Storage)?
        {
            Some(run) => self
                .plan_version(&run.plan_version_id)
                .map_err(DesktopAuthorityError::Storage)?
                .ok_or(DesktopAuthorityError::PlanNotReady)?,
            None => self
                .latest_draft_plan(conversation_id)
                .map_err(DesktopAuthorityError::Storage)?
                .ok_or(DesktopAuthorityError::PlanNotReady)?,
        };
        self.approve_plan_and_start_in_environment(ApprovePlanStartInput {
            conversation_id,
            project_id,
            plan_version_id: &plan.id,
            expected_plan_version: plan.version,
            idempotency_key,
            message_id,
            request_message,
            environment: None,
            requested_environment_kind:
                super::authority_store::DesktopExecutionEnvironmentKind::Local,
            permission_profile: DesktopPermissionProfile::WorkspaceWrite,
            now,
        })
    }

    pub(super) fn approve_plan_and_start_in_environment(
        &self,
        input: ApprovePlanStartInput<'_>,
    ) -> Result<ApprovePlanOutcome, DesktopAuthorityError> {
        let ApprovePlanStartInput {
            conversation_id,
            project_id,
            plan_version_id,
            expected_plan_version,
            idempotency_key,
            message_id,
            request_message,
            environment,
            requested_environment_kind,
            permission_profile,
            now,
        } = input;
        let mut connection = self.connection().map_err(DesktopAuthorityError::Storage)?;
        let transaction = connection
            .transaction()
            .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))?;

        if let Some(run) = query_run_by_idempotency(&transaction, idempotency_key)? {
            if run.conversation_id != conversation_id || run.project_id != project_id {
                return Err(DesktopAuthorityError::ProjectMismatch);
            }
            if run.plan_version_id != plan_version_id {
                return Err(DesktopAuthorityError::PlanVersionMismatch);
            }
            if run.message_id != message_id
                || run.request_message != request_message
                || run.permission_profile != permission_profile
                || run
                    .environment
                    .as_ref()
                    .map(|environment| environment.kind)
                    .unwrap_or(super::authority_store::DesktopExecutionEnvironmentKind::Local)
                    != requested_environment_kind
            {
                return Err(DesktopAuthorityError::IdempotencyConflict);
            }
            let conversation = query_conversation(&transaction, conversation_id)?
                .ok_or(DesktopAuthorityError::ConversationNotFound)?;
            let plan_version = query_plan_version(&transaction, &run.plan_version_id)?
                .ok_or(DesktopAuthorityError::PlanNotReady)?;
            if plan_version.version != expected_plan_version {
                return Err(DesktopAuthorityError::PlanVersionConflict {
                    expected: expected_plan_version,
                    actual: plan_version.version,
                });
            }
            transaction
                .commit()
                .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))?;
            return Ok(ApprovePlanOutcome {
                conversation,
                plan_version,
                run,
                created: false,
            });
        }

        let mut conversation = query_conversation(&transaction, conversation_id)?
            .ok_or(DesktopAuthorityError::ConversationNotFound)?;
        if conversation.project_id != project_id {
            return Err(DesktopAuthorityError::ProjectMismatch);
        }
        let mut plan_version = query_latest_draft_plan(&transaction, conversation_id)?
            .ok_or(DesktopAuthorityError::PlanNotReady)?;
        if plan_version.id != plan_version_id || plan_version.conversation_id != conversation_id {
            return Err(DesktopAuthorityError::PlanVersionMismatch);
        }
        if plan_version.version != expected_plan_version {
            return Err(DesktopAuthorityError::PlanVersionConflict {
                expected: expected_plan_version,
                actual: plan_version.version,
            });
        }
        if plan_version.status != DesktopPlanStatus::Draft {
            return Err(DesktopAuthorityError::PlanNotReady);
        }
        plan_version.status = DesktopPlanStatus::Approved;
        plan_version.approved_at = Some(now.to_string());
        update_plan_version(&transaction, &plan_version)?;

        conversation.current_mode = super::ConversationRunMode::Build;
        conversation.updated_at = now.to_string();
        update_conversation_in_transaction(&transaction, &conversation)?;

        let run = DesktopRun {
            id: format!("local-run-{}", Uuid::new_v4()),
            conversation_id: conversation_id.to_string(),
            project_id: project_id.to_string(),
            plan_version_id: plan_version.id.clone(),
            idempotency_key: idempotency_key.to_string(),
            message_id: message_id.to_string(),
            request_message: request_message.to_string(),
            status: DesktopRunStatus::Queued,
            revision: 1,
            created_at: now.to_string(),
            updated_at: now.to_string(),
            started_at: None,
            completed_at: None,
            last_heartbeat_at: None,
            error: None,
            environment: environment.clone(),
            permission_profile,
            authorization_snapshot: json!({
                "conversation_id": conversation_id,
                "project_id": project_id,
                "plan_version_id": plan_version.id,
                "approved_at": now,
                "mode": "build",
                "environment": environment,
                "permission_profile": permission_profile,
            }),
        };
        insert_run(&transaction, &run)?;
        insert_run_event(&transaction, &run, "queued", now)?;
        let decision = json!({
            "id": format!("local-decision-{}", Uuid::new_v4()),
            "conversation_id": conversation_id,
            "plan_version_id": plan_version.id,
            "run_id": run.id,
            "decision": "approved",
            "created_at": now,
            "authorization_snapshot": run.authorization_snapshot,
        });
        transaction
            .execute(
                "INSERT INTO desktop_decisions(
                   id, conversation_id, plan_version_id, run_id, decision, created_at, value_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    required_string(&decision, "id").map_err(DesktopAuthorityError::Storage)?,
                    conversation_id,
                    plan_version.id,
                    run.id,
                    "approved",
                    now,
                    serde_json::to_string(&decision)
                        .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))?,
                ],
            )
            .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))?;
        transaction
            .commit()
            .map_err(|error| DesktopAuthorityError::Storage(error.to_string()))?;
        Ok(ApprovePlanOutcome {
            conversation,
            plan_version,
            run,
            created: true,
        })
    }

    pub(super) fn run_by_idempotency_key(
        &self,
        idempotency_key: &str,
    ) -> Result<Option<DesktopRun>, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let run = query_run_by_idempotency(&transaction, idempotency_key)
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(run)
    }

    pub(super) fn claim_client_turn(
        &self,
        conversation_id: &str,
        message_id: &str,
        payload_hash: &str,
        now: &str,
    ) -> Result<bool, DesktopClientTurnClaimError> {
        let mut connection = self
            .connection()
            .map_err(DesktopClientTurnClaimError::Storage)?;
        let transaction = connection
            .transaction()
            .map_err(|error| DesktopClientTurnClaimError::Storage(error.to_string()))?;
        let existing = transaction
            .query_row(
                "SELECT payload_hash FROM desktop_client_turns
                 WHERE conversation_id = ?1 AND message_id = ?2",
                params![conversation_id, message_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| DesktopClientTurnClaimError::Storage(error.to_string()))?;
        if let Some(existing) = existing {
            if existing != payload_hash {
                return Err(DesktopClientTurnClaimError::PayloadConflict);
            }
            transaction
                .commit()
                .map_err(|error| DesktopClientTurnClaimError::Storage(error.to_string()))?;
            return Ok(false);
        }
        transaction
            .execute(
                "INSERT INTO desktop_client_turns(
                   conversation_id, message_id, payload_hash, created_at
                 ) VALUES (?1, ?2, ?3, ?4)",
                params![conversation_id, message_id, payload_hash, now],
            )
            .map_err(|error| DesktopClientTurnClaimError::Storage(error.to_string()))?;
        transaction
            .commit()
            .map_err(|error| DesktopClientTurnClaimError::Storage(error.to_string()))?;
        Ok(true)
    }

    pub(super) fn checkpoint_authority(
        &self,
        conversation_id: &str,
    ) -> Result<Option<DesktopCheckpointAuthority>, String> {
        let connection = self.connection()?;
        query_checkpoint_authority(&connection, conversation_id)
    }

    pub(super) fn bind_checkpoint_authority(
        &self,
        run: &DesktopRun,
        now: &str,
    ) -> Result<DesktopCheckpointAuthority, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        if let Some(existing) = query_checkpoint_authority(&transaction, &run.conversation_id)? {
            if existing.matches_run(run) {
                transaction.commit().map_err(|error| error.to_string())?;
                return Ok(existing);
            }
        }
        let authority = DesktopCheckpointAuthority::from_run(run, now, None);
        upsert_checkpoint_authority(&transaction, &authority)?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(authority)
    }

    pub(super) fn transfer_checkpoint_authority(
        &self,
        source: &DesktopRun,
        target: &DesktopRun,
        now: &str,
    ) -> Result<DesktopCheckpointAuthority, String> {
        if target.conversation_id != source.conversation_id
            || target.project_id != source.project_id
            || target.plan_version_id != source.plan_version_id
            || target.request_message != source.request_message
            || target.permission_profile != source.permission_profile
            || target
                .environment
                .as_ref()
                .and_then(|environment| environment.source_run_id.as_deref())
                != Some(source.id.as_str())
        {
            return Err("recovery fork does not preserve source checkpoint authority".to_string());
        }
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let existing = query_checkpoint_authority(&transaction, &source.conversation_id)?
            .ok_or_else(|| "source checkpoint authority is missing".to_string())?;
        if existing.matches_run(target) {
            transaction.commit().map_err(|error| error.to_string())?;
            return Ok(existing);
        }
        if !existing.matches_run(source) {
            return Err(
                "source checkpoint authority does not match the recovery source".to_string(),
            );
        }
        let authority =
            DesktopCheckpointAuthority::from_run(target, now, Some(existing.generation_id.clone()));
        upsert_checkpoint_authority(&transaction, &authority)?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(authority)
    }

    pub(super) fn clear_checkpoint_authority(
        &self,
        conversation_id: &str,
        expected_run_id: Option<&str>,
    ) -> Result<bool, String> {
        let deleted = match expected_run_id {
            Some(run_id) => self.connection()?.execute(
                "DELETE FROM desktop_checkpoint_authorities
                 WHERE conversation_id = ?1 AND run_id = ?2",
                params![conversation_id, run_id],
            ),
            None => self.connection()?.execute(
                "DELETE FROM desktop_checkpoint_authorities WHERE conversation_id = ?1",
                [conversation_id],
            ),
        }
        .map_err(|error| error.to_string())?;
        Ok(deleted > 0)
    }

    #[cfg(test)]
    pub(super) fn fork_recovery_run(
        &self,
        source_run_id: &str,
        expected_revision: u64,
        idempotency_key: &str,
        environment: DesktopExecutionEnvironment,
        now: &str,
    ) -> Result<(DesktopRun, bool), String> {
        self.fork_recovery_run_with_id(
            source_run_id,
            expected_revision,
            idempotency_key,
            &format!("local-run-{}", Uuid::new_v4()),
            environment,
            now,
        )
    }

    pub(super) fn fork_recovery_run_with_id(
        &self,
        source_run_id: &str,
        expected_revision: u64,
        idempotency_key: &str,
        run_id: &str,
        environment: DesktopExecutionEnvironment,
        now: &str,
    ) -> Result<(DesktopRun, bool), String> {
        if run_id.trim().is_empty() {
            return Err("recovery run id is required".to_string());
        }
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let source = query_run(&transaction, source_run_id)
            .map_err(|error| error.to_string())?
            .ok_or_else(|| "source run not found".to_string())?;
        if source.revision != expected_revision {
            return Err(format!(
                "run revision conflict: expected {expected_revision}, found {}",
                source.revision
            ));
        }
        if !matches!(
            source.status,
            DesktopRunStatus::Disconnected | DesktopRunStatus::Interrupted
        ) {
            return Err("only a disconnected or interrupted run can be forked".to_string());
        }
        if let Some(existing) = query_run_by_idempotency(&transaction, idempotency_key)
            .map_err(|error| error.to_string())?
        {
            if existing.conversation_id != source.conversation_id
                || existing.authorization_snapshot["source_run_id"].as_str()
                    != Some(source.id.as_str())
            {
                return Err("recovery idempotency key is already in use".to_string());
            }
            transaction.commit().map_err(|error| error.to_string())?;
            return Ok((existing, false));
        }

        let mut authorization_snapshot = source.authorization_snapshot.clone();
        authorization_snapshot["source_run_id"] = json!(source.id);
        authorization_snapshot["recovery"] = json!("fork");
        authorization_snapshot["forked_at"] = json!(now);
        authorization_snapshot["environment"] =
            serde_json::to_value(&environment).map_err(|error| error.to_string())?;
        let run = DesktopRun {
            id: run_id.to_string(),
            conversation_id: source.conversation_id.clone(),
            project_id: source.project_id.clone(),
            plan_version_id: source.plan_version_id.clone(),
            idempotency_key: idempotency_key.to_string(),
            message_id: format!("recovery-fork-{run_id}"),
            request_message: source.request_message.clone(),
            status: DesktopRunStatus::Queued,
            revision: 1,
            created_at: now.to_string(),
            updated_at: now.to_string(),
            started_at: None,
            completed_at: None,
            last_heartbeat_at: None,
            error: None,
            environment: Some(environment),
            permission_profile: source.permission_profile,
            authorization_snapshot,
        };
        insert_run(&transaction, &run).map_err(|error| error.to_string())?;
        insert_run_event(&transaction, &run, "recovery_forked", now)
            .map_err(|error| error.to_string())?;
        let decision = json!({
            "id": format!("local-decision-{}", Uuid::new_v4()),
            "conversation_id": run.conversation_id,
            "plan_version_id": run.plan_version_id,
            "run_id": run.id,
            "source_run_id": source.id,
            "decision": "recovery_forked",
            "created_at": now,
            "authorization_snapshot": run.authorization_snapshot,
        });
        transaction
            .execute(
                "INSERT INTO desktop_decisions(
                   id, conversation_id, plan_version_id, run_id, decision, created_at, value_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    required_string(&decision, "id")?,
                    run.conversation_id,
                    run.plan_version_id,
                    run.id,
                    "recovery_forked",
                    now,
                    serde_json::to_string(&decision).map_err(|error| error.to_string())?,
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok((run, true))
    }

    pub(super) fn rollback_recovery_fork(
        &self,
        source: &DesktopRun,
        forked: &DesktopRun,
        now: &str,
    ) -> Result<bool, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let Some(stored) =
            query_run(&transaction, &forked.id).map_err(|error| error.to_string())?
        else {
            transaction.commit().map_err(|error| error.to_string())?;
            return Ok(false);
        };
        if stored.status != DesktopRunStatus::Queued
            || stored.revision != 1
            || stored.conversation_id != source.conversation_id
            || stored.project_id != source.project_id
            || stored.plan_version_id != source.plan_version_id
            || stored.request_message != source.request_message
            || stored.permission_profile != source.permission_profile
            || stored.idempotency_key != forked.idempotency_key
            || stored.environment != forked.environment
            || stored.authorization_snapshot["recovery"].as_str() != Some("fork")
            || stored.authorization_snapshot["source_run_id"].as_str() != Some(source.id.as_str())
        {
            return Err("recovery fork is no longer safe to roll back".to_string());
        }
        let authority = query_checkpoint_authority(&transaction, &source.conversation_id)?
            .ok_or_else(|| {
                "checkpoint authority is missing during recovery rollback".to_string()
            })?;
        if authority.matches_run(&stored) {
            let restored = DesktopCheckpointAuthority::from_run(
                source,
                now,
                Some(authority.generation_id.clone()),
            );
            upsert_checkpoint_authority(&transaction, &restored)?;
        } else if !authority.matches_run(source) {
            return Err("checkpoint authority changed during recovery rollback".to_string());
        }
        transaction
            .execute(
                "DELETE FROM desktop_decisions WHERE run_id = ?1",
                [&stored.id],
            )
            .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "DELETE FROM desktop_run_events WHERE run_id = ?1",
                [&stored.id],
            )
            .map_err(|error| error.to_string())?;
        let deleted = transaction
            .execute(
                "DELETE FROM desktop_runs WHERE id = ?1 AND status = 'queued' AND revision = 1",
                [&stored.id],
            )
            .map_err(|error| error.to_string())?;
        if deleted != 1 {
            return Err("recovery fork changed during rollback".to_string());
        }
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(true)
    }

    pub(super) fn prepare_run_for_execution(
        &self,
        run_id: &str,
        now: &str,
    ) -> Result<Option<DesktopRun>, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let Some(mut run) = query_run(&transaction, run_id).map_err(|error| error.to_string())?
        else {
            return Ok(None);
        };
        if !matches!(
            run.status,
            DesktopRunStatus::Queued
                | DesktopRunStatus::Disconnected
                | DesktopRunStatus::Interrupted
        ) {
            return Ok(None);
        }
        let unknown_count: i64 = transaction
            .query_row(
                "SELECT COUNT(*) FROM desktop_tool_invocations
                 WHERE run_id = ?1 AND status = 'unknown_outcome'",
                [&run.id],
                |row| row.get(0),
            )
            .map_err(|error| error.to_string())?;
        if unknown_count > 0 {
            run.status = DesktopRunStatus::NeedsInput;
            run.revision += 1;
            run.updated_at = now.to_string();
            run.last_heartbeat_at = Some(now.to_string());
            run.error = Some("unknown tool outcome requires human inspection".to_string());
            update_run(&transaction, &run)?;
            insert_run_event(&transaction, &run, "unknown_outcome", now)
                .map_err(|error| error.to_string())?;
            transaction.commit().map_err(|error| error.to_string())?;
            return Ok(Some(run));
        }
        let clears_recovery_error = is_recovered_unstarted_run(&run);
        run.status = DesktopRunStatus::Running;
        run.revision += 1;
        run.updated_at = now.to_string();
        run.started_at.get_or_insert_with(|| now.to_string());
        run.last_heartbeat_at = Some(now.to_string());
        if clears_recovery_error {
            run.error = None;
        }
        update_run(&transaction, &run)?;
        insert_run_event(&transaction, &run, "running", now).map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(Some(run))
    }

    pub(super) fn transition_run(
        &self,
        run_id: &str,
        expected_revision: u64,
        status: DesktopRunStatus,
        error: Option<String>,
        now: &str,
    ) -> Result<DesktopRun, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let mut run = query_run(&transaction, run_id)
            .map_err(|error| error.to_string())?
            .ok_or_else(|| "run not found".to_string())?;
        if run.revision != expected_revision {
            return Err(format!(
                "run revision conflict: expected {expected_revision}, found {}",
                run.revision
            ));
        }
        if !run.status.can_transition_to(status) {
            return Err(format!(
                "invalid run transition: {:?} -> {status:?}",
                run.status
            ));
        }

        run.status = status;
        run.revision += 1;
        run.updated_at = now.to_string();
        run.last_heartbeat_at = Some(now.to_string());
        run.completed_at = status.is_terminal().then(|| now.to_string());
        run.error = error;
        update_run(&transaction, &run)?;
        insert_run_event(
            &transaction,
            &run,
            super::authority_store::run_status_name(status),
            now,
        )
        .map_err(|error| error.to_string())?;
        settle_queued_run_inputs_in_transaction(&transaction, &run.id, run.status, now)?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(run)
    }

    pub(super) fn reconcile_recovered_run(
        &self,
        run_id: &str,
        expected_revision: u64,
        status: DesktopRunStatus,
        error: Option<String>,
        now: &str,
    ) -> Result<DesktopRun, String> {
        if !matches!(
            status,
            DesktopRunStatus::NeedsInput
                | DesktopRunStatus::NeedsApproval
                | DesktopRunStatus::Paused
                | DesktopRunStatus::ReadyReview
                | DesktopRunStatus::Failed
                | DesktopRunStatus::Cancelled
        ) {
            return Err("checkpoint recovery target is not reconcilable".to_string());
        }
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let mut run = query_run(&transaction, run_id)
            .map_err(|error| error.to_string())?
            .ok_or_else(|| "run not found".to_string())?;
        if run.revision != expected_revision {
            return Err(format!(
                "run revision conflict: expected {expected_revision}, found {}",
                run.revision
            ));
        }
        let started_recovery = matches!(
            run.status,
            DesktopRunStatus::Disconnected | DesktopRunStatus::Interrupted
        ) && run.started_at.is_some();
        let terminalized_unstarted_launch = is_recovered_unstarted_run(&run)
            && matches!(
                status,
                DesktopRunStatus::ReadyReview
                    | DesktopRunStatus::Failed
                    | DesktopRunStatus::Cancelled
            );
        if !started_recovery && !terminalized_unstarted_launch {
            return Err("run is outside the started recovery boundary".to_string());
        }

        run.status = status;
        run.revision += 1;
        run.updated_at = now.to_string();
        run.last_heartbeat_at = Some(now.to_string());
        run.completed_at = status.is_terminal().then(|| now.to_string());
        run.error = error;
        update_run(&transaction, &run)?;
        insert_run_event(
            &transaction,
            &run,
            super::authority_store::run_status_name(status),
            now,
        )
        .map_err(|error| error.to_string())?;
        settle_queued_run_inputs_in_transaction(&transaction, &run.id, run.status, now)?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(run)
    }

    pub(super) fn transition_review_run(
        &self,
        run_id: &str,
        expected_revision: u64,
        status: DesktopRunStatus,
        action: &str,
        feedback: Option<&str>,
        now: &str,
    ) -> Result<(DesktopRun, Value), String> {
        if !matches!(
            status,
            DesktopRunStatus::Running | DesktopRunStatus::Completed
        ) {
            return Err("review decisions can only resume or complete a run".to_string());
        }
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let mut run = query_run(&transaction, run_id)
            .map_err(|error| error.to_string())?
            .ok_or_else(|| "run not found".to_string())?;
        if run.revision != expected_revision {
            return Err(format!(
                "run revision conflict: expected {expected_revision}, found {}",
                run.revision
            ));
        }
        if run.status != DesktopRunStatus::ReadyReview || !run.status.can_transition_to(status) {
            return Err(format!(
                "invalid review transition: {:?} -> {status:?}",
                run.status
            ));
        }

        run.status = status;
        run.revision += 1;
        run.updated_at = now.to_string();
        run.last_heartbeat_at = Some(now.to_string());
        run.completed_at = status.is_terminal().then(|| now.to_string());
        run.error = None;
        update_run(&transaction, &run)?;
        insert_run_event(
            &transaction,
            &run,
            super::authority_store::run_status_name(status),
            now,
        )
        .map_err(|error| error.to_string())?;

        let decision = json!({
            "id": format!("local-decision-{}", Uuid::new_v4()),
            "conversation_id": run.conversation_id,
            "plan_version_id": run.plan_version_id,
            "run_id": run.id,
            "run_revision": run.revision,
            "decision": action,
            "feedback": feedback,
            "created_at": now,
            "source": "local_user",
        });
        transaction
            .execute(
                "INSERT INTO desktop_decisions(
                   id, conversation_id, plan_version_id, run_id, decision, created_at, value_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    required_string(&decision, "id")?,
                    run.conversation_id,
                    run.plan_version_id,
                    run.id,
                    action,
                    now,
                    serde_json::to_string(&decision).map_err(|error| error.to_string())?,
                ],
            )
            .map_err(|error| error.to_string())?;
        settle_queued_run_inputs_in_transaction(&transaction, &run.id, run.status, now)?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok((run, decision))
    }

    pub(super) fn request_artifact_changes_and_resume_run(
        &self,
        artifact_version_id: &str,
        expected_artifact_revision: u64,
        run_id: &str,
        expected_run_revision: u64,
        feedback: &str,
        now: &str,
    ) -> Result<(DesktopArtifactVersion, DesktopRun, Value), String> {
        let feedback = feedback.trim();
        if feedback.is_empty() {
            return Err("artifact review feedback is required".to_string());
        }
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let mut version = query_artifact_version(&transaction, artifact_version_id)?
            .ok_or_else(|| "artifact version not found".to_string())?;
        if version.revision != expected_artifact_revision {
            return Err(format!(
                "artifact revision conflict: expected {expected_artifact_revision}, found {}",
                version.revision
            ));
        }
        if version.run_id.as_deref() != Some(run_id) || !version.status.can_review() {
            return Err("artifact version is not reviewable for this run".to_string());
        }
        let mut run = query_run(&transaction, run_id)
            .map_err(|error| error.to_string())?
            .ok_or_else(|| "run not found".to_string())?;
        if run.revision != expected_run_revision {
            return Err(format!(
                "run revision conflict: expected {expected_run_revision}, found {}",
                run.revision
            ));
        }
        if run.status != DesktopRunStatus::ReadyReview
            || !run.status.can_transition_to(DesktopRunStatus::Running)
        {
            return Err("artifact run is not ready for review".to_string());
        }

        run.status = DesktopRunStatus::Running;
        run.revision += 1;
        run.updated_at = now.to_string();
        run.last_heartbeat_at = Some(now.to_string());
        run.completed_at = None;
        run.error = None;
        update_run(&transaction, &run)?;
        insert_run_event(&transaction, &run, "running", now).map_err(|error| error.to_string())?;

        version.status = DesktopArtifactStatus::Superseded;
        version.revision += 1;
        version.updated_at = now.to_string();
        version.superseded_at = Some(now.to_string());
        version.feedback = Some(feedback.to_string());
        update_artifact_version(&transaction, &version)?;

        let decision = json!({
            "id": format!("local-decision-{}", Uuid::new_v4()),
            "conversation_id": run.conversation_id,
            "plan_version_id": run.plan_version_id,
            "run_id": run.id,
            "run_revision": run.revision,
            "artifact_id": version.artifact_id,
            "artifact_version_id": version.id,
            "artifact_revision": version.revision,
            "decision": "request_changes",
            "feedback": feedback,
            "created_at": now,
            "source": "local_user",
        });
        transaction
            .execute(
                "INSERT INTO desktop_decisions(
                   id, conversation_id, plan_version_id, run_id, decision, created_at, value_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    required_string(&decision, "id")?,
                    run.conversation_id,
                    run.plan_version_id,
                    run.id,
                    "request_changes",
                    now,
                    serde_json::to_string(&decision).map_err(|error| error.to_string())?,
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok((version, run, decision))
    }

    pub(super) fn run(&self, run_id: &str) -> Result<Option<DesktopRun>, String> {
        let connection = self.connection()?;
        query_run(&connection, run_id).map_err(|error| error.to_string())
    }

    pub(super) fn list_runs(&self, conversation_id: &str) -> Result<Vec<DesktopRun>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_runs
                 WHERE conversation_id = ?1 ORDER BY created_at DESC",
            )
            .map_err(|error| error.to_string())?;
        typed_rows(statement.query_map([conversation_id], |row| row.get::<_, String>(0)))
    }

    pub(super) fn list_recoverable_runs(&self) -> Result<Vec<DesktopRun>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT candidate.value_json
                 FROM desktop_runs AS candidate
                 WHERE candidate.status IN ('disconnected', 'interrupted')
                   AND NOT EXISTS (
                     SELECT 1
                     FROM desktop_runs AS newer
                     WHERE newer.conversation_id = candidate.conversation_id
                       AND newer.rowid > candidate.rowid
                   )
                 ORDER BY candidate.rowid ASC",
            )
            .map_err(|error| error.to_string())?;
        typed_rows(statement.query_map([], |row| row.get::<_, String>(0)))
    }

    pub(super) fn list_current_checkpoint_quarantines(
        &self,
        quarantine_error: &str,
        recoverable_error_prefix: &str,
    ) -> Result<Vec<DesktopRun>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT candidate.value_json
                 FROM desktop_runs AS candidate
                 WHERE candidate.status IN ('failed', 'disconnected')
                   AND NOT EXISTS (
                     SELECT 1
                     FROM desktop_runs AS newer
                     WHERE newer.conversation_id = candidate.conversation_id
                       AND newer.rowid > candidate.rowid
                   )
                 ORDER BY candidate.rowid ASC",
            )
            .map_err(|error| error.to_string())?;
        let runs: Vec<DesktopRun> =
            typed_rows(statement.query_map([], |row| row.get::<_, String>(0)))?;
        Ok(runs
            .into_iter()
            .filter(|run| {
                run.error.as_deref().is_some_and(|error| {
                    error == quarantine_error || error.starts_with(recoverable_error_prefix)
                })
            })
            .collect())
    }

    pub(super) fn list_project_attention_runs(
        &self,
        project_id: &str,
    ) -> Result<Vec<DesktopRun>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_runs
                 WHERE project_id = ?1
                   AND status NOT IN ('completed', 'cancelled')
                 ORDER BY updated_at DESC, created_at DESC",
            )
            .map_err(|error| error.to_string())?;
        typed_rows(statement.query_map([project_id], |row| row.get::<_, String>(0)))
    }

    pub(super) fn run_events(&self, run_id: &str) -> Result<Vec<Value>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_run_events
                 WHERE run_id = ?1 ORDER BY revision ASC",
            )
            .map_err(|error| error.to_string())?;
        json_rows(statement.query_map([run_id], |row| row.get::<_, String>(0)))
    }

    pub(super) fn create_run_input(
        &self,
        input: CreateRunInput<'_>,
    ) -> Result<(DesktopRunInput, bool), String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        if let Some(existing) = query_run_input_by_idempotency(&transaction, input.idempotency_key)?
        {
            let matches = existing.run_id == input.run_id
                && existing.expected_run_revision == input.expected_run_revision
                && existing.message_id == input.message_id
                && existing.delivery == input.delivery
                && existing.content == input.content
                && existing.references == input.references;
            if matches {
                return Ok((existing, false));
            }
            return Err("run input idempotency conflict".to_string());
        }
        let run = query_run(&transaction, input.run_id)
            .map_err(|error| error.to_string())?
            .ok_or_else(|| "run not found".to_string())?;
        if run.revision != input.expected_run_revision {
            return Err("run revision conflict".to_string());
        }
        if run.status != DesktopRunStatus::Running {
            return Err("run is not accepting input".to_string());
        }
        let content = input.content.trim();
        if content.is_empty() {
            return Err("run input content is required".to_string());
        }
        let sequence = transaction
            .query_row(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM desktop_run_inputs WHERE run_id = ?1",
                [input.run_id],
                |row| row.get::<_, u64>(0),
            )
            .map_err(|error| error.to_string())?;
        let queue_position = if input.delivery == RunInputDelivery::QueueNext {
            Some(
                transaction
                    .query_row(
                        "SELECT COUNT(*) + 1 FROM desktop_run_inputs
                         WHERE run_id = ?1 AND delivery = 'queue_next'
                           AND status IN ('queued', 'ready')",
                        [input.run_id],
                        |row| row.get::<_, u64>(0),
                    )
                    .map_err(|error| error.to_string())?,
            )
        } else {
            None
        };
        let run_input = DesktopRunInput {
            id: format!("local-run-input-{}", Uuid::new_v4()),
            conversation_id: run.conversation_id,
            run_id: run.id,
            expected_run_revision: input.expected_run_revision,
            message_id: input.message_id.to_string(),
            idempotency_key: input.idempotency_key.to_string(),
            delivery: input.delivery,
            status: if input.delivery == RunInputDelivery::SteerNow {
                RunInputStatus::PendingBoundary
            } else {
                RunInputStatus::Queued
            },
            sequence,
            queue_position,
            content: content.to_string(),
            references: input.references,
            applied_round: None,
            applied_at: None,
            promotion_idempotency_key: None,
            promoted_at: None,
            created_at: input.now.to_string(),
            updated_at: input.now.to_string(),
        };
        insert_run_input(&transaction, &run_input)?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok((run_input, true))
    }

    pub(super) fn pending_steering(&self, run_id: &str) -> Result<Option<DesktopRunInput>, String> {
        let connection = self.connection()?;
        connection
            .query_row(
                "SELECT value_json FROM desktop_run_inputs
                 WHERE run_id = ?1 AND delivery = 'steer_now' AND status = 'pending_boundary'
                 ORDER BY sequence ASC LIMIT 1",
                [run_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?
            .map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
            .transpose()
    }

    pub(super) fn acknowledge_steering(
        &self,
        input_id: &str,
        applied_round: u64,
        applied_at: &str,
    ) -> Result<DesktopRunInput, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let mut input = query_run_input(&transaction, input_id)?
            .ok_or_else(|| "run input not found".to_string())?;
        if input.status == RunInputStatus::Applied {
            return Ok(input);
        }
        if input.status != RunInputStatus::PendingBoundary {
            return Err("run input is not pending steering".to_string());
        }
        input.status = RunInputStatus::Applied;
        input.applied_round = Some(applied_round);
        input.applied_at = Some(applied_at.to_string());
        input.updated_at = applied_at.to_string();
        update_run_input(&transaction, &input)?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(input)
    }

    pub(super) fn list_run_inputs(&self, run_id: &str) -> Result<Vec<DesktopRunInput>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_run_inputs
                 WHERE run_id = ?1 ORDER BY sequence ASC",
            )
            .map_err(|error| error.to_string())?;
        typed_rows(statement.query_map([run_id], |row| row.get::<_, String>(0)))
    }

    pub(super) fn run_input(&self, input_id: &str) -> Result<Option<DesktopRunInput>, String> {
        let connection = self.connection()?;
        query_run_input(&connection, input_id)
    }

    pub(super) fn promote_queued_run_input(
        &self,
        input_id: &str,
        expected_source_run_revision: u64,
        idempotency_key: &str,
        now: &str,
    ) -> Result<(DesktopRunInput, LocalConversation, bool), String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let mut input = query_run_input(&transaction, input_id)?
            .ok_or_else(|| "run input not found".to_string())?;
        if input.status == RunInputStatus::PromotedToPlan {
            if input.promotion_idempotency_key.as_deref() == Some(idempotency_key) {
                let conversation = query_conversation(&transaction, &input.conversation_id)
                    .map_err(|error| error.to_string())?
                    .ok_or_else(|| "conversation not found".to_string())?;
                return Ok((input, conversation, false));
            }
            return Err("run input promotion idempotency conflict".to_string());
        }
        if input.delivery != RunInputDelivery::QueueNext || input.status != RunInputStatus::Ready {
            return Err("run input is not ready for plan handoff".to_string());
        }
        let run = query_run(&transaction, &input.run_id)
            .map_err(|error| error.to_string())?
            .ok_or_else(|| "run not found".to_string())?;
        if run.status != DesktopRunStatus::Completed {
            return Err("source run is not completed".to_string());
        }
        if run.revision != expected_source_run_revision {
            return Err("run revision conflict".to_string());
        }
        let mut conversation = query_conversation(&transaction, &input.conversation_id)
            .map_err(|error| error.to_string())?
            .ok_or_else(|| "conversation not found".to_string())?;
        conversation.current_mode = ConversationRunMode::Plan;
        conversation.updated_at = now.to_string();
        update_conversation_in_transaction(&transaction, &conversation)
            .map_err(|error| error.to_string())?;
        input.status = RunInputStatus::PromotedToPlan;
        input.promotion_idempotency_key = Some(idempotency_key.to_string());
        input.promoted_at = Some(now.to_string());
        input.updated_at = now.to_string();
        update_run_input(&transaction, &input)?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok((input, conversation, true))
    }

    pub(super) fn settle_queued_run_inputs(
        &self,
        run_id: &str,
        run_status: DesktopRunStatus,
        now: &str,
    ) -> Result<(), String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        settle_queued_run_inputs_in_transaction(&transaction, run_id, run_status, now)?;
        transaction.commit().map_err(|error| error.to_string())
    }

    pub(super) fn record_artifact_version(
        &self,
        conversation_id: &str,
        run_id: Option<&str>,
        output: &Value,
        now: &str,
    ) -> Result<DesktopArtifactVersion, String> {
        let source_artifact_id = required_string(output, "artifact_id")?;
        let artifact_version_id = required_string(output, "artifact_version_id")?;
        let filename = required_string(output, "filename")?;
        let path = required_string(output, "path")?;
        let relative_path = required_string(output, "relative_path")?;
        let artifact_id = format!("{conversation_id}:{source_artifact_id}");
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;

        if let Some(existing) = query_artifact_version(&transaction, &artifact_version_id)? {
            return Ok(existing);
        }
        let conversation_exists = transaction
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM desktop_conversations WHERE id = ?1)",
                [conversation_id],
                |row| row.get::<_, bool>(0),
            )
            .map_err(|error| error.to_string())?;
        if !conversation_exists {
            return Err("conversation not found".to_string());
        }

        let previous_versions = {
            let mut statement = transaction
                .prepare(
                    "SELECT value_json FROM desktop_artifact_versions
                     WHERE artifact_id = ?1 AND status IN ('draft', 'ready', 'approved')",
                )
                .map_err(|error| error.to_string())?;
            typed_rows::<_, DesktopArtifactVersion>(
                statement.query_map([&artifact_id], |row| row.get::<_, String>(0)),
            )?
        };
        for mut previous in previous_versions {
            previous.status = DesktopArtifactStatus::Superseded;
            previous.revision += 1;
            previous.updated_at = now.to_string();
            previous.superseded_at = Some(now.to_string());
            update_artifact_version(&transaction, &previous)?;
        }

        let version = transaction
            .query_row(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM desktop_artifact_versions
                 WHERE artifact_id = ?1",
                [&artifact_id],
                |row| row.get::<_, i64>(0),
            )
            .map_err(|error| error.to_string())?;
        let artifact_version = DesktopArtifactVersion {
            id: artifact_version_id,
            artifact_id: artifact_id.clone(),
            source_artifact_id: source_artifact_id.clone(),
            conversation_id: conversation_id.to_string(),
            run_id: run_id.map(ToString::to_string),
            version,
            status: DesktopArtifactStatus::Ready,
            revision: 1,
            filename: filename.clone(),
            mime_type: output
                .get("mime_type")
                .and_then(Value::as_str)
                .unwrap_or("application/octet-stream")
                .to_string(),
            path: path.clone(),
            relative_path: relative_path.clone(),
            bytes: output.get("bytes").and_then(Value::as_u64).unwrap_or(0),
            sources: output
                .get("sources")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default(),
            checks: output
                .get("checks")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default(),
            created_at: now.to_string(),
            updated_at: now.to_string(),
            approved_at: None,
            delivered_at: None,
            superseded_at: None,
            feedback: None,
        };
        transaction
            .execute(
                "INSERT INTO desktop_artifact_versions(
                   id, artifact_id, conversation_id, run_id, version, status, revision,
                   created_at, updated_at, value_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
                params![
                    artifact_version.id,
                    artifact_version.artifact_id,
                    artifact_version.conversation_id,
                    artifact_version.run_id,
                    artifact_version.version,
                    artifact_status_name(artifact_version.status),
                    artifact_version.revision as i64,
                    artifact_version.created_at,
                    artifact_version.updated_at,
                    serde_json::to_string(&artifact_version).map_err(|error| error.to_string())?,
                ],
            )
            .map_err(|error| error.to_string())?;
        let artifact = json!({
            "id": artifact_id,
            "source_artifact_id": source_artifact_id,
            "conversation_id": conversation_id,
            "name": filename,
            "current_version_id": artifact_version.id,
            "current_version": artifact_version.version,
            "created_at": now,
            "updated_at": now,
        });
        transaction
            .execute(
                "INSERT INTO desktop_artifacts(
                   id, conversation_id, source_artifact_id, current_version_id,
                   created_at, updated_at, value_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
                 ON CONFLICT(id) DO UPDATE SET
                   current_version_id = excluded.current_version_id,
                   updated_at = excluded.updated_at,
                   value_json = excluded.value_json",
                params![
                    artifact_id,
                    conversation_id,
                    source_artifact_id,
                    artifact_version.id,
                    now,
                    now,
                    serde_json::to_string(&artifact).map_err(|error| error.to_string())?,
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(artifact_version)
    }

    pub(super) fn artifact_version(
        &self,
        artifact_version_id: &str,
    ) -> Result<Option<DesktopArtifactVersion>, String> {
        let connection = self.connection()?;
        query_artifact_version(&connection, artifact_version_id)
    }

    pub(super) fn list_artifact_versions(
        &self,
        conversation_id: &str,
    ) -> Result<Vec<DesktopArtifactVersion>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_artifact_versions
                 WHERE conversation_id = ?1 ORDER BY created_at DESC, version DESC",
            )
            .map_err(|error| error.to_string())?;
        typed_rows(statement.query_map([conversation_id], |row| row.get::<_, String>(0)))
    }

    pub(super) fn review_artifact_version(
        &self,
        artifact_version_id: &str,
        expected_revision: u64,
        action: &str,
        feedback: Option<&str>,
        now: &str,
    ) -> Result<DesktopArtifactVersion, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let mut version = query_artifact_version(&transaction, artifact_version_id)?
            .ok_or_else(|| "artifact version not found".to_string())?;
        if version.revision != expected_revision {
            return Err(format!(
                "artifact revision conflict: expected {expected_revision}, found {}",
                version.revision
            ));
        }
        match action {
            "approve"
                if matches!(
                    version.status,
                    DesktopArtifactStatus::Draft | DesktopArtifactStatus::Ready
                ) =>
            {
                version.status = DesktopArtifactStatus::Approved;
                version.approved_at = Some(now.to_string());
                version.feedback = None;
            }
            "approve" if version.status == DesktopArtifactStatus::Approved => return Ok(version),
            "request_changes" if version.status.can_review() => {
                let feedback = feedback
                    .map(str::trim)
                    .filter(|value| !value.is_empty())
                    .ok_or_else(|| "artifact review feedback is required".to_string())?;
                version.status = DesktopArtifactStatus::Superseded;
                version.superseded_at = Some(now.to_string());
                version.feedback = Some(feedback.to_string());
            }
            _ => {
                return Err(format!(
                    "invalid artifact review transition: {:?} with {action}",
                    version.status
                ));
            }
        }
        version.revision += 1;
        version.updated_at = now.to_string();
        update_artifact_version(&transaction, &version)?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(version)
    }

    pub(super) fn deliver_artifact_version(
        &self,
        artifact_version_id: &str,
        expected_revision: u64,
        idempotency_key: &str,
        destination: &str,
        receipt: Value,
        now: &str,
    ) -> Result<(DesktopArtifactVersion, DesktopArtifactDelivery), String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        if let Some(delivery) =
            query_artifact_delivery_by_idempotency(&transaction, idempotency_key)?
        {
            if delivery.artifact_version_id != artifact_version_id {
                return Err("artifact delivery idempotency key is already in use".to_string());
            }
            let version = query_artifact_version(&transaction, artifact_version_id)?
                .ok_or_else(|| "artifact version not found".to_string())?;
            return Ok((version, delivery));
        }
        let mut version = query_artifact_version(&transaction, artifact_version_id)?
            .ok_or_else(|| "artifact version not found".to_string())?;
        if version.revision != expected_revision {
            return Err(format!(
                "artifact revision conflict: expected {expected_revision}, found {}",
                version.revision
            ));
        }
        if version.status != DesktopArtifactStatus::Approved {
            return Err("only an approved artifact version can be delivered".to_string());
        }
        version.status = DesktopArtifactStatus::Delivered;
        version.revision += 1;
        version.updated_at = now.to_string();
        version.delivered_at = Some(now.to_string());
        update_artifact_version(&transaction, &version)?;
        let delivery = DesktopArtifactDelivery {
            id: format!("artifact-delivery-{}", Uuid::new_v4()),
            artifact_version_id: version.id.clone(),
            artifact_id: version.artifact_id.clone(),
            conversation_id: version.conversation_id.clone(),
            run_id: version.run_id.clone(),
            destination: destination.to_string(),
            receipt,
            idempotency_key: idempotency_key.to_string(),
            created_at: now.to_string(),
        };
        transaction
            .execute(
                "INSERT INTO desktop_artifact_deliveries(
                   id, artifact_version_id, artifact_id, conversation_id,
                   idempotency_key, created_at, value_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    delivery.id,
                    delivery.artifact_version_id,
                    delivery.artifact_id,
                    delivery.conversation_id,
                    delivery.idempotency_key,
                    delivery.created_at,
                    serde_json::to_string(&delivery).map_err(|error| error.to_string())?,
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok((version, delivery))
    }

    pub(super) fn list_artifact_deliveries(
        &self,
        conversation_id: &str,
    ) -> Result<Vec<DesktopArtifactDelivery>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_artifact_deliveries
                 WHERE conversation_id = ?1 ORDER BY created_at DESC",
            )
            .map_err(|error| error.to_string())?;
        typed_rows(statement.query_map([conversation_id], |row| row.get::<_, String>(0)))
    }

    pub(super) fn insert_hitl_request(&self, request: &DesktopHitlRequest) -> Result<(), String> {
        let value_json = serde_json::to_string(request).map_err(|error| error.to_string())?;
        self.connection()?
            .execute(
                "INSERT OR IGNORE INTO desktop_hitl_requests(
                   id, conversation_id, run_id, status, created_at, responded_at, value_json
                 ) VALUES (?1, ?2, ?3, 'pending', ?4, NULL, ?5)",
                params![
                    request.id,
                    request.conversation_id,
                    request.run_id,
                    request.created_at,
                    value_json,
                ],
            )
            .map_err(|error| error.to_string())?;
        Ok(())
    }

    pub(super) fn hitl_request(
        &self,
        request_id: &str,
    ) -> Result<Option<DesktopHitlRequest>, String> {
        let value_json = self
            .connection()?
            .query_row(
                "SELECT value_json FROM desktop_hitl_requests WHERE id = ?1",
                [request_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        value_json
            .map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
            .transpose()
    }

    pub(super) fn list_hitl_requests(
        &self,
        conversation_id: &str,
    ) -> Result<Vec<DesktopHitlRequest>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_hitl_requests
                 WHERE conversation_id = ?1 ORDER BY created_at DESC, id DESC",
            )
            .map_err(|error| error.to_string())?;
        typed_rows(statement.query_map([conversation_id], |row| row.get::<_, String>(0)))
    }

    pub(super) fn mark_hitl_responded(
        &self,
        request_id: &str,
        response_data: &Value,
        response_actor: &str,
        response_revision: Option<u64>,
        idempotency_key: Option<&str>,
        now: &str,
    ) -> Result<DesktopHitlRequest, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let value_json = transaction
            .query_row(
                "SELECT value_json FROM desktop_hitl_requests WHERE id = ?1",
                [request_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?
            .ok_or_else(|| "HITL request not found".to_string())?;
        let mut request: DesktopHitlRequest =
            serde_json::from_str(&value_json).map_err(|error| error.to_string())?;
        if request.status == DesktopHitlStatus::Responded {
            return Ok(request);
        }
        request.status = DesktopHitlStatus::Responded;
        request.responded_at = Some(now.to_string());
        request.response_data = Some(response_data.clone());
        request.response_actor = Some(response_actor.to_string());
        request.response_revision = response_revision;
        request.idempotency_key = idempotency_key.map(ToString::to_string);
        transaction
            .execute(
                "UPDATE desktop_hitl_requests
                 SET status = 'responded', responded_at = ?2, value_json = ?3
                 WHERE id = ?1 AND status = 'pending'",
                params![
                    request_id,
                    now,
                    serde_json::to_string(&request).map_err(|error| error.to_string())?,
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(request)
    }

    pub(super) fn authorize_and_prepare_tool_invocation(
        &self,
        invocation_id: &str,
        request: &ToolInvocationRequest,
        metadata: &ToolMetadata,
        grant: Option<PermissionGrant>,
        grant_source: &str,
        now_ms: i64,
    ) -> Result<PreparedToolInvocation, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        if let Some(invocation) = query_tool_invocation(&transaction, invocation_id)? {
            transaction.commit().map_err(|error| error.to_string())?;
            return Ok(PreparedToolInvocation {
                invocation,
                existing: true,
            });
        }

        let run = query_run(&transaction, &request.run_id)
            .map_err(|error| error.to_string())?
            .ok_or_else(|| "run not found".to_string())?;
        if run.status != DesktopRunStatus::Running
            || run.plan_version_id != request.plan_version_id
            || run.revision != request.run_revision
            || run
                .environment
                .as_ref()
                .map(|environment| environment.id.as_str())
                != Some(request.environment_id.as_str())
        {
            return Err("tool invocation authority no longer matches the active run".to_string());
        }

        let mut grant = grant;
        let consumption: Option<GrantConsumption> = grant
            .as_mut()
            .map(|permission| permission.authorize_and_consume(request, now_ms))
            .transpose()
            .map_err(|error| error.to_string())?;
        if let Some(permission) = grant.as_ref() {
            transaction
                .execute(
                    "INSERT INTO desktop_permission_grants(
                       id, run_id, plan_version_id, run_revision, environment_id, tool_name,
                       uses, use_limit, expires_at_ms, source, created_at_ms, value_json
                     ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
                    params![
                        permission.grant_id,
                        permission.run_id,
                        permission.plan_version_id,
                        permission.run_revision as i64,
                        permission.environment_id,
                        permission.tool_name,
                        permission.uses as i64,
                        permission.use_limit as i64,
                        permission.expires_at_ms,
                        grant_source,
                        now_ms,
                        serde_json::to_string(permission).map_err(|error| error.to_string())?,
                    ],
                )
                .map_err(|error| error.to_string())?;
        }

        let invocation = ToolInvocation::prepare(
            invocation_id.to_string(),
            request,
            metadata,
            consumption.as_ref(),
            now_ms,
        )
        .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "INSERT INTO desktop_tool_invocations(
                   id, run_id, plan_version_id, run_revision, environment_id, tool_name,
                   grant_id, input_digest, status, prepared_at_ms, finished_at_ms, value_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, NULL, ?11)",
                params![
                    invocation.invocation_id,
                    invocation.run_id,
                    invocation.plan_version_id,
                    invocation.run_revision as i64,
                    invocation.environment_id,
                    invocation.tool_name,
                    invocation.grant_id,
                    invocation.input_digest,
                    invocation_status_name(invocation.status),
                    invocation.prepared_at_ms,
                    serde_json::to_string(&invocation).map_err(|error| error.to_string())?,
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(PreparedToolInvocation {
            invocation,
            existing: false,
        })
    }

    pub(super) fn transition_tool_invocation(
        &self,
        invocation_id: &str,
        status: InvocationStatus,
        now_ms: i64,
    ) -> Result<ToolInvocation, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let mut invocation = query_tool_invocation(&transaction, invocation_id)?
            .ok_or_else(|| "tool invocation not found".to_string())?;
        if invocation.status == status {
            transaction.commit().map_err(|error| error.to_string())?;
            return Ok(invocation);
        }
        match status {
            InvocationStatus::Executing => invocation.mark_executing(now_ms),
            InvocationStatus::Completed => invocation.mark_completed(now_ms),
            InvocationStatus::Failed => invocation.mark_failed(now_ms),
            InvocationStatus::UnknownOutcome => invocation.mark_unknown_outcome(now_ms),
            InvocationStatus::Prepared => {
                return Err("cannot transition an invocation back to prepared".to_string())
            }
        }
        .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "UPDATE desktop_tool_invocations
                 SET status = ?2, finished_at_ms = ?3, value_json = ?4 WHERE id = ?1",
                params![
                    invocation.invocation_id,
                    invocation_status_name(invocation.status),
                    invocation.finished_at_ms,
                    serde_json::to_string(&invocation).map_err(|error| error.to_string())?,
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(invocation)
    }

    pub(super) fn list_tool_invocations(
        &self,
        conversation_id: &str,
    ) -> Result<Vec<ToolInvocation>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT invocation.value_json
                 FROM desktop_tool_invocations invocation
                 JOIN desktop_runs run ON run.id = invocation.run_id
                 WHERE run.conversation_id = ?1
                 ORDER BY invocation.prepared_at_ms ASC, invocation.id ASC",
            )
            .map_err(|error| error.to_string())?;
        typed_rows(statement.query_map([conversation_id], |row| row.get::<_, String>(0)))
    }

    pub(super) fn connection(&self) -> Result<std::sync::MutexGuard<'_, Connection>, String> {
        self.connection
            .lock()
            .map_err(|_| "desktop session store lock poisoned".to_string())
    }
}

fn query_checkpoint_authority(
    connection: &Connection,
    conversation_id: &str,
) -> Result<Option<DesktopCheckpointAuthority>, String> {
    let value_json = connection
        .query_row(
            "SELECT value_json FROM desktop_checkpoint_authorities WHERE conversation_id = ?1",
            [conversation_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| error.to_string())?;
    value_json
        .map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
        .transpose()
}

fn upsert_checkpoint_authority(
    connection: &Connection,
    authority: &DesktopCheckpointAuthority,
) -> Result<(), String> {
    connection
        .execute(
            "INSERT INTO desktop_checkpoint_authorities(
               conversation_id, run_id, plan_version_id, generation_id,
               created_at, updated_at, value_json
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
             ON CONFLICT(conversation_id) DO UPDATE SET
               run_id = excluded.run_id,
               plan_version_id = excluded.plan_version_id,
               generation_id = excluded.generation_id,
               created_at = excluded.created_at,
               updated_at = excluded.updated_at,
               value_json = excluded.value_json",
            params![
                authority.conversation_id,
                authority.run_id,
                authority.plan_version_id,
                authority.generation_id,
                authority.created_at,
                authority.updated_at,
                serde_json::to_string(authority).map_err(|error| error.to_string())?,
            ],
        )
        .map_err(|error| error.to_string())?;
    Ok(())
}

fn settle_queued_run_inputs_in_transaction(
    connection: &Connection,
    run_id: &str,
    run_status: DesktopRunStatus,
    now: &str,
) -> Result<(), String> {
    let next_status = match run_status {
        DesktopRunStatus::Completed => RunInputStatus::Ready,
        DesktopRunStatus::Failed | DesktopRunStatus::Cancelled => RunInputStatus::Blocked,
        _ => return Ok(()),
    };
    let inputs = {
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_run_inputs
                 WHERE run_id = ?1 AND delivery = 'queue_next' AND status = 'queued'",
            )
            .map_err(|error| error.to_string())?;
        let rows: Vec<DesktopRunInput> =
            typed_rows(statement.query_map([run_id], |row| row.get::<_, String>(0)))?;
        rows
    };
    for mut input in inputs {
        input.status = next_status;
        input.updated_at = now.to_string();
        update_run_input(connection, &input)?;
    }
    Ok(())
}

fn query_artifact_version(
    connection: &Connection,
    artifact_version_id: &str,
) -> Result<Option<DesktopArtifactVersion>, String> {
    let value_json = connection
        .query_row(
            "SELECT value_json FROM desktop_artifact_versions WHERE id = ?1",
            [artifact_version_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| error.to_string())?;
    value_json
        .map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
        .transpose()
}

fn query_run_input(
    connection: &Connection,
    input_id: &str,
) -> Result<Option<DesktopRunInput>, String> {
    let value_json = connection
        .query_row(
            "SELECT value_json FROM desktop_run_inputs WHERE id = ?1",
            [input_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| error.to_string())?;
    value_json
        .map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
        .transpose()
}

fn query_run_input_by_idempotency(
    connection: &Connection,
    idempotency_key: &str,
) -> Result<Option<DesktopRunInput>, String> {
    let value_json = connection
        .query_row(
            "SELECT value_json FROM desktop_run_inputs WHERE idempotency_key = ?1",
            [idempotency_key],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| error.to_string())?;
    value_json
        .map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
        .transpose()
}

fn insert_run_input(connection: &Connection, input: &DesktopRunInput) -> Result<(), String> {
    connection
        .execute(
            "INSERT INTO desktop_run_inputs(
               id, conversation_id, run_id, expected_run_revision, message_id,
               idempotency_key, delivery, status, sequence, created_at, updated_at, value_json
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
            params![
                input.id,
                input.conversation_id,
                input.run_id,
                input.expected_run_revision as i64,
                input.message_id,
                input.idempotency_key,
                run_input_delivery_name(input.delivery),
                run_input_status_name(input.status),
                input.sequence as i64,
                input.created_at,
                input.updated_at,
                serde_json::to_string(input).map_err(|error| error.to_string())?,
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn update_run_input(connection: &Connection, input: &DesktopRunInput) -> Result<(), String> {
    connection
        .execute(
            "UPDATE desktop_run_inputs
             SET status = ?2, updated_at = ?3, value_json = ?4 WHERE id = ?1",
            params![
                input.id,
                run_input_status_name(input.status),
                input.updated_at,
                serde_json::to_string(input).map_err(|error| error.to_string())?,
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn run_input_delivery_name(delivery: RunInputDelivery) -> &'static str {
    match delivery {
        RunInputDelivery::SteerNow => "steer_now",
        RunInputDelivery::QueueNext => "queue_next",
    }
}

fn run_input_status_name(status: RunInputStatus) -> &'static str {
    match status {
        RunInputStatus::PendingBoundary => "pending_boundary",
        RunInputStatus::Queued => "queued",
        RunInputStatus::Applied => "applied",
        RunInputStatus::Ready => "ready",
        RunInputStatus::Blocked => "blocked",
        RunInputStatus::PromotedToPlan => "promoted_to_plan",
    }
}

fn query_tool_invocation(
    connection: &Connection,
    invocation_id: &str,
) -> Result<Option<ToolInvocation>, String> {
    let value_json = connection
        .query_row(
            "SELECT value_json FROM desktop_tool_invocations WHERE id = ?1",
            [invocation_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| error.to_string())?;
    value_json
        .map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
        .transpose()
}

fn invocation_status_name(status: InvocationStatus) -> &'static str {
    match status {
        InvocationStatus::Prepared => "prepared",
        InvocationStatus::Executing => "executing",
        InvocationStatus::Completed => "completed",
        InvocationStatus::Failed => "failed",
        InvocationStatus::UnknownOutcome => "unknown_outcome",
    }
}

pub(super) fn recover_inflight_tool_invocations(
    connection: &Connection,
    now_ms: i64,
) -> Result<(), String> {
    let mut statement = connection
        .prepare("SELECT value_json FROM desktop_tool_invocations WHERE status = 'executing'")
        .map_err(|error| error.to_string())?;
    let invocations: Vec<ToolInvocation> =
        typed_rows(statement.query_map([], |row| row.get::<_, String>(0)))?;
    drop(statement);
    for mut invocation in invocations {
        invocation
            .mark_unknown_outcome(now_ms)
            .map_err(|error| error.to_string())?;
        connection
            .execute(
                "UPDATE desktop_tool_invocations
                 SET status = 'unknown_outcome', finished_at_ms = ?2, value_json = ?3
                 WHERE id = ?1",
                params![
                    invocation.invocation_id,
                    invocation.finished_at_ms,
                    serde_json::to_string(&invocation).map_err(|error| error.to_string())?,
                ],
            )
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn update_artifact_version(
    connection: &Connection,
    version: &DesktopArtifactVersion,
) -> Result<(), String> {
    connection
        .execute(
            "UPDATE desktop_artifact_versions
             SET status = ?2, revision = ?3, updated_at = ?4, value_json = ?5 WHERE id = ?1",
            params![
                version.id,
                artifact_status_name(version.status),
                version.revision as i64,
                version.updated_at,
                serde_json::to_string(version).map_err(|error| error.to_string())?,
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn query_artifact_delivery_by_idempotency(
    connection: &Connection,
    idempotency_key: &str,
) -> Result<Option<DesktopArtifactDelivery>, String> {
    let value_json = connection
        .query_row(
            "SELECT value_json FROM desktop_artifact_deliveries WHERE idempotency_key = ?1",
            [idempotency_key],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| error.to_string())?;
    value_json
        .map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
        .transpose()
}

pub(super) fn required_string(value: &Value, key: &str) -> Result<String, String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .map(ToString::to_string)
        .ok_or_else(|| format!("missing required {key}"))
}

fn optional_string(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .map(ToString::to_string)
}

fn json_rows<T>(
    rows: Result<rusqlite::MappedRows<'_, T>, rusqlite::Error>,
) -> Result<Vec<Value>, String>
where
    T: FnMut(&rusqlite::Row<'_>) -> rusqlite::Result<String>,
{
    rows.map_err(|error| error.to_string())?
        .map(|row| {
            let value = row.map_err(|error| error.to_string())?;
            serde_json::from_str(&value).map_err(|error| error.to_string())
        })
        .collect()
}
