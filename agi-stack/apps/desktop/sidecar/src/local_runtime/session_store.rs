use std::{
    collections::HashSet,
    path::Path,
    sync::{Arc, Mutex},
    time::Duration,
};

use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

use super::{
    authority_store::{
        artifact_status_name, insert_plan_version, insert_run, insert_run_event,
        is_recovered_unstarted_run, query_conversation, query_latest_draft_plan,
        query_plan_version, query_run, query_run_by_idempotency, recover_interrupted_runs,
        typed_rows, update_conversation_in_transaction, update_plan_version, update_run,
        ApprovePlanOutcome, BrowserActionAudit, BrowserCapabilityDecision, BrowserCapabilityGrant,
        BrowserOriginDecision, BrowserOriginGrant, BrowserSiteCredential, DesktopArtifactDelivery,
        DesktopArtifactStatus, DesktopArtifactVersion, DesktopAuthorityError,
        DesktopExecutionEnvironment, DesktopHitlRequest, DesktopHitlStatus,
        DesktopPermissionProfile, DesktopPlanStatus, DesktopPlanVersion, DesktopRun,
        DesktopRunStatus, WorkspaceToolGrant, HITL_PENDING_AUTHORITY_REVISION,
    },
    composer_context::ComposerContextItem,
    provider_usage_store::{self, ProviderUsageRecord, ProviderUsageStatistic},
    steering::{DesktopRunInput, RunInputDelivery, RunInputReference, RunInputStatus},
    tool_authority::{
        GrantConsumption, InvocationStatus, PermissionGrant, ToolInvocation, ToolInvocationRequest,
        ToolMetadata,
    },
    ConversationRunMode, LocalConversation,
};

const DESKTOP_SESSION_SCHEMA_VERSION: i64 = 25;
const INSTALLATION_ID_METADATA_KEY: &str = "installation_id";
const LOCAL_TRUSTED_SESSION_METADATA_KEY: &str = "local_trusted_session_v1";
const MAX_TIMELINE_PAGE_LIMIT: usize = 500;
const LEGACY_TASK_SESSION_RECEIPT_TABLE: &str = "desktop_new_task_sessions_v15";
const TASK_SESSION_RECEIPT_TABLE_SQL: &str = "CREATE TABLE desktop_new_task_sessions (
       user_id TEXT NOT NULL,
       tenant_id TEXT NOT NULL,
       project_id TEXT NOT NULL,
       idempotency_key TEXT NOT NULL,
       payload_hash TEXT NOT NULL,
       workspace_id TEXT NOT NULL,
       conversation_id TEXT NOT NULL UNIQUE,
       initial_message_id TEXT NOT NULL UNIQUE,
       response_json TEXT NOT NULL,
       created_at TEXT NOT NULL,
       PRIMARY KEY(user_id, tenant_id, project_id, idempotency_key),
       FOREIGN KEY(conversation_id) REFERENCES desktop_conversations(id)
     );";
const TASK_SESSION_RECEIPT_INDEX_SQL: &str =
    "CREATE INDEX IF NOT EXISTS idx_desktop_new_task_sessions_scope
       ON desktop_new_task_sessions(user_id, tenant_id, project_id, created_at);";

pub(super) struct PreparedToolInvocation {
    pub(super) invocation: ToolInvocation,
    pub(super) existing: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct DesktopArtifactContentAuthority {
    pub(super) artifact_id: String,
    pub(super) artifact_version_id: String,
    pub(super) revision: u64,
    pub(super) content_hash: String,
    pub(super) mime_type: String,
    pub(super) path: String,
}

pub(super) struct DesktopArtifactContentSaveInput<'a> {
    pub(super) expected_revision: u64,
    pub(super) observed_content_hash: &'a str,
    pub(super) content_hash: &'a str,
    pub(super) idempotency_key: &'a str,
    pub(super) request_hash: &'a str,
    pub(super) now: &'a str,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct DesktopArtifactContentSaveReceipt {
    pub(super) artifact_id: String,
    pub(super) revision: u64,
    pub(super) content_hash: String,
    pub(super) duplicate: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) enum DesktopArtifactContentSaveOutcome {
    Saved(DesktopArtifactContentSaveReceipt),
    Conflict {
        reason_code: &'static str,
        server_revision: u64,
        server_content_hash: String,
    },
}

pub(super) struct HitlResponseCommit<'a> {
    pub(super) expected_authority_revision: u64,
    pub(super) response_data: &'a Value,
    pub(super) response_actor: &'a str,
    pub(super) response_revision: Option<u64>,
    pub(super) idempotency_key: &'a str,
    pub(super) workspace_tool_grant: Option<&'a WorkspaceToolGrant>,
    pub(super) now: &'a str,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) enum HitlResponseCommitOutcome {
    Committed(DesktopHitlRequest),
    Duplicate(DesktopHitlRequest),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) enum HitlResponseCommitError {
    NotFound,
    AuthorityConflict {
        expected_revision: u64,
        authority_revision: u64,
    },
    IdempotencyConflict {
        authority_revision: u64,
    },
    AlreadyAnswered {
        authority_revision: u64,
    },
    Storage(String),
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum DesktopClientTurnClaimError {
    PayloadConflict,
    Storage(String),
}

#[derive(Debug, PartialEq)]
pub(super) enum DesktopWorkspaceCoreRequestClaim {
    Claimed,
    Duplicate(Value),
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum DesktopWorkspaceCoreRequestClaimError {
    PayloadConflict,
    Storage(String),
}

#[derive(Clone, Debug, PartialEq)]
pub(super) struct DesktopWorkspaceCoreTerminalCallback {
    pub(super) id: String,
    pub(super) run_id: String,
    pub(super) sequence: u64,
    pub(super) provider_bot_ref: String,
    pub(super) payload: Value,
    pub(super) created_at: String,
    pub(super) attempt_count: u64,
    pub(super) last_attempt_at: Option<String>,
    pub(super) last_error: Option<String>,
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum DesktopTaskSessionError {
    IdempotencyConflict,
    ScopeMismatch,
    Storage(String),
}

impl std::fmt::Display for DesktopTaskSessionError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::IdempotencyConflict => formatter
                .write_str("task session idempotency key is already bound to a different request"),
            Self::ScopeMismatch => {
                formatter.write_str("resource is outside the active workspace context")
            }
            Self::Storage(error) => formatter.write_str(error),
        }
    }
}

pub(super) struct ProjectTaskSessionInput {
    pub(super) user_id: String,
    pub(super) expected_context_revision: u64,
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) idempotency_key: String,
    pub(super) payload_hash: String,
    pub(super) workspace: Value,
    pub(super) conversation: LocalConversation,
    pub(super) initial_message: Value,
    pub(super) policy: Value,
    pub(super) capability_version: String,
    pub(super) now: String,
}

pub(super) struct ProjectTaskSessionOutcome {
    pub(super) replayed: bool,
    pub(super) workspace: Value,
    pub(super) conversation: Value,
    pub(super) initial_message: Value,
    pub(super) policy: Value,
    pub(super) capability_version: String,
}

pub(super) struct ReplayTaskSessionInput {
    pub(super) user_id: String,
    pub(super) expected_context_revision: u64,
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) idempotency_key: String,
    pub(super) payload_hash: String,
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
    installation_id: Arc<str>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) struct DesktopTimelineCursor {
    pub(super) time_us: i64,
    pub(super) counter: i64,
}

#[derive(Clone, Debug, PartialEq)]
pub(super) struct DesktopTimelinePage {
    pub(super) items: Vec<Value>,
    pub(super) has_more: bool,
    pub(super) first_cursor: Option<DesktopTimelineCursor>,
    pub(super) last_cursor: Option<DesktopTimelineCursor>,
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
    pub(super) context_items: Vec<ComposerContextItem>,
    pub(super) now: &'a str,
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

    pub(super) fn with_local_mcp_connection<T>(
        &self,
        operation: impl FnOnce(&mut Connection) -> Result<T, String>,
    ) -> Result<T, String> {
        let mut connection = self
            .connection
            .lock()
            .map_err(|_| "desktop session store lock is unavailable".to_string())?;
        operation(&mut connection)
    }

    fn from_connection(mut connection: Connection) -> Result<Self, String> {
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
                 CREATE TABLE IF NOT EXISTS desktop_seed_migrations (
                   seed_id TEXT PRIMARY KEY,
                   seed_kind TEXT NOT NULL,
                   applied_at TEXT NOT NULL,
                   value_json TEXT NOT NULL
                 );
                 CREATE TABLE IF NOT EXISTS desktop_runtime_metadata (
                   key TEXT PRIMARY KEY,
                   value_text TEXT NOT NULL
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
                 CREATE TABLE IF NOT EXISTS desktop_artifact_content_authorities (
                   artifact_id TEXT PRIMARY KEY,
                   artifact_version_id TEXT NOT NULL,
                   revision INTEGER NOT NULL,
                   content_hash TEXT NOT NULL,
                   mime_type TEXT NOT NULL,
                   path TEXT NOT NULL,
                   updated_at TEXT NOT NULL,
                   FOREIGN KEY(artifact_id) REFERENCES desktop_artifacts(id)
                     ON DELETE CASCADE,
                   FOREIGN KEY(artifact_version_id) REFERENCES desktop_artifact_versions(id)
                 );
                 CREATE TABLE IF NOT EXISTS desktop_artifact_content_receipts (
                   artifact_id TEXT NOT NULL,
                   idempotency_key TEXT NOT NULL,
                   request_hash TEXT NOT NULL,
                   revision INTEGER NOT NULL,
                   content_hash TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   PRIMARY KEY(artifact_id, idempotency_key),
                   FOREIGN KEY(artifact_id) REFERENCES desktop_artifacts(id)
                     ON DELETE CASCADE
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
                 CREATE TABLE IF NOT EXISTS desktop_workspace_tool_grants (
                   id TEXT PRIMARY KEY,
                   workspace_id TEXT NOT NULL,
                   canonical_tool_name TEXT NOT NULL,
                   source_hitl_request_id TEXT NOT NULL,
                   revision INTEGER NOT NULL,
                   created_by TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   revoked_by TEXT,
                   revoked_at TEXT,
                   value_json TEXT NOT NULL
                 );
                 CREATE TABLE IF NOT EXISTS desktop_browser_origin_grants (
                   id TEXT PRIMARY KEY,
                   host TEXT NOT NULL,
                   decision TEXT NOT NULL CHECK (decision IN ('site', 'all', 'decline')),
                   source_hitl_request_id TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   revoked_at TEXT
                 );
                 CREATE TABLE IF NOT EXISTS desktop_browser_capability_grants (
                   id TEXT PRIMARY KEY,
                   host TEXT NOT NULL,
                   capability TEXT NOT NULL,
                   decision TEXT NOT NULL CHECK (decision IN ('site', 'decline')),
                   source_hitl_request_id TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   revoked_at TEXT
                 );
                 CREATE TABLE IF NOT EXISTS desktop_browser_site_credentials (
                   id TEXT PRIMARY KEY,
                   origin TEXT NOT NULL,
                   username TEXT NOT NULL,
                   credential_ref TEXT NOT NULL UNIQUE,
                   created_at TEXT NOT NULL,
                   revoked_at TEXT
                 );
                 CREATE TABLE IF NOT EXISTS desktop_browser_action_audit (
                   id INTEGER PRIMARY KEY,
                   run_id TEXT,
                   tool_name TEXT NOT NULL,
                   origin TEXT,
                   target_summary TEXT NOT NULL,
                   outcome TEXT NOT NULL,
                   latency_ms INTEGER NOT NULL,
                   created_at INTEGER NOT NULL
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
                 CREATE TABLE IF NOT EXISTS desktop_workspace_core_requests (
                   request_id TEXT PRIMARY KEY,
                   channel TEXT NOT NULL,
                   request_hash TEXT NOT NULL,
                   response_json TEXT NOT NULL,
                   created_at TEXT NOT NULL
                 );
                 CREATE TABLE IF NOT EXISTS desktop_workspace_core_terminal_callbacks (
                   id TEXT PRIMARY KEY,
                   run_id TEXT NOT NULL,
                   sequence INTEGER NOT NULL CHECK (sequence >= 0),
                   provider_bot_ref TEXT NOT NULL,
                   payload_json TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   delivered_at TEXT,
                   attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
                   last_attempt_at TEXT,
                   last_error TEXT,
                   UNIQUE(run_id, sequence)
                 );
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
                 CREATE INDEX IF NOT EXISTS idx_desktop_workspace_tool_grants_active
                   ON desktop_workspace_tool_grants(
                     workspace_id, canonical_tool_name, revoked_at, created_at DESC
                   );
                 CREATE INDEX IF NOT EXISTS idx_desktop_browser_origin_grants_host
                   ON desktop_browser_origin_grants(host, revoked_at, created_at DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_browser_capability_grants_host
                   ON desktop_browser_capability_grants(
                     host, capability, revoked_at, created_at DESC
                   );
                 CREATE INDEX IF NOT EXISTS idx_desktop_browser_site_credentials_origin
                   ON desktop_browser_site_credentials(origin, revoked_at, created_at DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_browser_action_audit_created
                   ON desktop_browser_action_audit(created_at);
                 CREATE INDEX IF NOT EXISTS idx_desktop_tool_invocations_run
                   ON desktop_tool_invocations(run_id, prepared_at_ms DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_tool_invocations_status
                   ON desktop_tool_invocations(status, prepared_at_ms DESC);
                 CREATE INDEX IF NOT EXISTS idx_desktop_checkpoint_authorities_run
                   ON desktop_checkpoint_authorities(run_id);
                 CREATE INDEX IF NOT EXISTS idx_desktop_workspace_core_requests_created
                   ON desktop_workspace_core_requests(created_at);
                 CREATE INDEX IF NOT EXISTS idx_desktop_workspace_core_callbacks_pending
                   ON desktop_workspace_core_terminal_callbacks(
                     delivered_at, created_at, sequence
                   );",
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
        migrate_task_session_receipt_scope(&mut connection)?;
        let installation_id = match connection
            .query_row(
                "SELECT value_text FROM desktop_runtime_metadata WHERE key = ?1",
                params![INSTALLATION_ID_METADATA_KEY],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?
        {
            Some(value) => {
                Uuid::parse_str(&value)
                    .map_err(|_| "desktop installation id is invalid".to_string())?;
                value
            }
            None => {
                let value = Uuid::new_v4().to_string();
                connection
                    .execute(
                        "INSERT INTO desktop_runtime_metadata (key, value_text) VALUES (?1, ?2)",
                        params![INSTALLATION_ID_METADATA_KEY, value],
                    )
                    .map_err(|error| error.to_string())?;
                value
            }
        };
        super::auth_context::initialize_auth_context_schema(&connection)?;
        super::automation_store::initialize_schema(&connection)?;
        provider_usage_store::initialize_schema(&connection)?;
        super::resource_registry::initialize_resource_registry(&connection)?;
        super::search_projection::initialize_schema(&connection)?;
        connection
            .pragma_update(None, "user_version", DESKTOP_SESSION_SCHEMA_VERSION)
            .map_err(|error| error.to_string())?;
        recover_inflight_tool_invocations(&connection, chrono::Utc::now().timestamp_millis())?;
        recover_interrupted_runs(&connection, &super::now_iso())?;
        Ok(Self {
            connection: Arc::new(Mutex::new(connection)),
            installation_id: Arc::from(installation_id),
        })
    }

    pub(super) fn installation_id(&self) -> &str {
        &self.installation_id
    }

    pub(super) fn project_tenant_id(&self, project_id: &str) -> Result<Option<String>, String> {
        self.connection()?
            .query_row(
                "SELECT tenant_id FROM desktop_projects WHERE id = ?1 AND status = 'active'",
                [project_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(|error| error.to_string())
    }

    pub(super) fn claim_workspace_core_request(
        &self,
        request_id: &str,
        channel: &str,
        request_hash: &str,
        response: &Value,
        created_at: &str,
    ) -> Result<DesktopWorkspaceCoreRequestClaim, DesktopWorkspaceCoreRequestClaimError> {
        let mut connection = self
            .connection()
            .map_err(DesktopWorkspaceCoreRequestClaimError::Storage)?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(|error| DesktopWorkspaceCoreRequestClaimError::Storage(error.to_string()))?;
        let existing = transaction
            .query_row(
                "SELECT channel, request_hash, response_json
                 FROM desktop_workspace_core_requests WHERE request_id = ?1",
                [request_id],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                    ))
                },
            )
            .optional()
            .map_err(|error| DesktopWorkspaceCoreRequestClaimError::Storage(error.to_string()))?;
        if let Some((existing_channel, existing_hash, response_json)) = existing {
            if existing_channel != channel || existing_hash != request_hash {
                return Err(DesktopWorkspaceCoreRequestClaimError::PayloadConflict);
            }
            let response = serde_json::from_str(&response_json).map_err(|error| {
                DesktopWorkspaceCoreRequestClaimError::Storage(error.to_string())
            })?;
            transaction.commit().map_err(|error| {
                DesktopWorkspaceCoreRequestClaimError::Storage(error.to_string())
            })?;
            return Ok(DesktopWorkspaceCoreRequestClaim::Duplicate(response));
        }
        let response_json = serde_json::to_string(response)
            .map_err(|error| DesktopWorkspaceCoreRequestClaimError::Storage(error.to_string()))?;
        transaction
            .execute(
                "INSERT INTO desktop_workspace_core_requests(
                   request_id, channel, request_hash, response_json, created_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![request_id, channel, request_hash, response_json, created_at],
            )
            .map_err(|error| DesktopWorkspaceCoreRequestClaimError::Storage(error.to_string()))?;
        transaction
            .commit()
            .map_err(|error| DesktopWorkspaceCoreRequestClaimError::Storage(error.to_string()))?;
        Ok(DesktopWorkspaceCoreRequestClaim::Claimed)
    }

    pub(super) fn enqueue_workspace_core_terminal_callback(
        &self,
        callback: &DesktopWorkspaceCoreTerminalCallback,
    ) -> Result<(), String> {
        if callback.id.trim().is_empty()
            || callback.run_id.trim().is_empty()
            || callback.provider_bot_ref.trim().is_empty()
            || callback.attempt_count != 0
            || callback.last_attempt_at.is_some()
            || callback.last_error.is_some()
        {
            return Err("Workspace Core terminal callback is invalid".to_string());
        }
        let sequence = i64::try_from(callback.sequence)
            .map_err(|_| "Workspace Core callback sequence overflow".to_string())?;
        let payload_json =
            serde_json::to_string(&callback.payload).map_err(|error| error.to_string())?;
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(|error| error.to_string())?;
        let existing = transaction
            .query_row(
                "SELECT run_id, sequence, provider_bot_ref, payload_json, created_at
                 FROM desktop_workspace_core_terminal_callbacks WHERE id = ?1",
                [&callback.id],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, i64>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, String>(4)?,
                    ))
                },
            )
            .optional()
            .map_err(|error| error.to_string())?;
        if let Some((run_id, stored_sequence, provider_bot_ref, stored_payload, created_at)) =
            existing
        {
            if run_id != callback.run_id
                || stored_sequence != sequence
                || provider_bot_ref != callback.provider_bot_ref
                || stored_payload != payload_json
                || created_at != callback.created_at
            {
                return Err("Workspace Core terminal callback id collision".to_string());
            }
            return transaction.commit().map_err(|error| error.to_string());
        }
        transaction
            .execute(
                "INSERT INTO desktop_workspace_core_terminal_callbacks(
                   id, run_id, sequence, provider_bot_ref, payload_json, created_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![
                    callback.id,
                    callback.run_id,
                    sequence,
                    callback.provider_bot_ref,
                    payload_json,
                    callback.created_at
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())
    }

    pub(super) fn pending_workspace_core_terminal_callbacks(
        &self,
        limit: usize,
    ) -> Result<Vec<DesktopWorkspaceCoreTerminalCallback>, String> {
        if !(1..=1_000).contains(&limit) {
            return Err("Workspace Core callback query limit is invalid".to_string());
        }
        let limit = i64::try_from(limit).map_err(|error| error.to_string())?;
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT id, run_id, sequence, provider_bot_ref, payload_json, created_at,
                        attempt_count, last_attempt_at, last_error
                 FROM desktop_workspace_core_terminal_callbacks
                 WHERE delivered_at IS NULL
                 ORDER BY created_at ASC, sequence ASC, id ASC
                 LIMIT ?1",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([limit], |row| {
                let sequence = row.get::<_, i64>(2)?;
                let attempt_count = row.get::<_, i64>(6)?;
                let payload_json = row.get::<_, String>(4)?;
                let payload = serde_json::from_str(&payload_json).map_err(|error| {
                    rusqlite::Error::FromSqlConversionFailure(
                        4,
                        rusqlite::types::Type::Text,
                        Box::new(error),
                    )
                })?;
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    sequence,
                    row.get::<_, String>(3)?,
                    payload,
                    row.get::<_, String>(5)?,
                    attempt_count,
                    row.get::<_, Option<String>>(7)?,
                    row.get::<_, Option<String>>(8)?,
                ))
            })
            .map_err(|error| error.to_string())?;
        rows.map(|row| {
            let (
                id,
                run_id,
                sequence,
                provider_bot_ref,
                payload,
                created_at,
                attempt_count,
                last_attempt_at,
                last_error,
            ) = row.map_err(|error| error.to_string())?;
            Ok(DesktopWorkspaceCoreTerminalCallback {
                id,
                run_id,
                sequence: u64::try_from(sequence).map_err(|error| error.to_string())?,
                provider_bot_ref,
                payload,
                created_at,
                attempt_count: u64::try_from(attempt_count).map_err(|error| error.to_string())?,
                last_attempt_at,
                last_error,
            })
        })
        .collect()
    }

    pub(super) fn mark_workspace_core_terminal_callback_delivered(
        &self,
        callback_id: &str,
        delivered_at: &str,
    ) -> Result<(), String> {
        let connection = self.connection()?;
        let changed = connection
            .execute(
                "UPDATE desktop_workspace_core_terminal_callbacks
                 SET delivered_at = ?2, attempt_count = attempt_count + 1,
                     last_attempt_at = ?2, last_error = NULL
                 WHERE id = ?1 AND delivered_at IS NULL",
                params![callback_id, delivered_at],
            )
            .map_err(|error| error.to_string())?;
        if changed != 0
            || connection
                .query_row(
                    "SELECT 1 FROM desktop_workspace_core_terminal_callbacks WHERE id = ?1",
                    [callback_id],
                    |_| Ok(()),
                )
                .optional()
                .map_err(|error| error.to_string())?
                .is_some()
        {
            Ok(())
        } else {
            Err("Workspace Core terminal callback was not found".to_string())
        }
    }

    pub(super) fn record_workspace_core_terminal_callback_failure(
        &self,
        callback_id: &str,
        attempted_at: &str,
        error: &str,
    ) -> Result<(), String> {
        let changed = self
            .connection()?
            .execute(
                "UPDATE desktop_workspace_core_terminal_callbacks
                 SET attempt_count = attempt_count + 1, last_attempt_at = ?2, last_error = ?3
                 WHERE id = ?1 AND delivered_at IS NULL",
                params![callback_id, attempted_at, error],
            )
            .map_err(|error| error.to_string())?;
        if changed == 1 {
            Ok(())
        } else {
            Err("Workspace Core terminal callback is not pending".to_string())
        }
    }

    pub(super) fn save_local_trusted_session(&self, value: &str) -> Result<(), String> {
        if value.trim().is_empty() {
            return Err("local trusted session record is invalid".to_string());
        }
        self.connection()?
            .execute(
                "INSERT INTO desktop_runtime_metadata(key, value_text) VALUES (?1, ?2)
                 ON CONFLICT(key) DO UPDATE SET value_text = excluded.value_text",
                params![LOCAL_TRUSTED_SESSION_METADATA_KEY, value],
            )
            .map_err(|error| error.to_string())?;
        Ok(())
    }

    pub(super) fn load_local_trusted_session(&self) -> Result<Option<String>, String> {
        self.connection()?
            .query_row(
                "SELECT value_text FROM desktop_runtime_metadata WHERE key = ?1",
                params![LOCAL_TRUSTED_SESSION_METADATA_KEY],
                |row| row.get(0),
            )
            .optional()
            .map_err(|error| error.to_string())
    }

    pub(super) fn clear_local_trusted_session(&self) -> Result<(), String> {
        self.connection()?
            .execute(
                "DELETE FROM desktop_runtime_metadata WHERE key = ?1",
                params![LOCAL_TRUSTED_SESSION_METADATA_KEY],
            )
            .map_err(|error| error.to_string())?;
        Ok(())
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

    pub(super) fn insert_conversation(
        &self,
        conversation: &LocalConversation,
    ) -> Result<(), String> {
        let connection = self.connection()?;
        insert_conversation_record(&connection, conversation)
    }

    pub(super) fn project_task_session(
        &self,
        input: ProjectTaskSessionInput,
    ) -> Result<ProjectTaskSessionOutcome, DesktopTaskSessionError> {
        let ProjectTaskSessionInput {
            user_id,
            expected_context_revision,
            tenant_id,
            project_id,
            idempotency_key,
            payload_hash,
            workspace,
            conversation,
            initial_message,
            policy,
            capability_version,
            now,
        } = input;
        let mut connection = self
            .connection()
            .map_err(DesktopTaskSessionError::Storage)?;
        let transaction = connection
            .transaction()
            .map_err(|error| DesktopTaskSessionError::Storage(error.to_string()))?;
        validate_task_session_context(
            &transaction,
            &user_id,
            expected_context_revision,
            &tenant_id,
            &project_id,
        )?;
        if let Some(receipt) = query_task_session_receipt(
            &transaction,
            &user_id,
            &tenant_id,
            &project_id,
            &idempotency_key,
        )? {
            if receipt.payload_hash != payload_hash {
                return Err(DesktopTaskSessionError::IdempotencyConflict);
            }
            validate_task_session_receipt(&receipt, &user_id, &tenant_id, &project_id)?;
            let TaskSessionResponseSnapshot {
                workspace,
                conversation,
                initial_message,
                policy,
                capability_version,
            } = receipt.response;
            transaction
                .commit()
                .map_err(|error| DesktopTaskSessionError::Storage(error.to_string()))?;
            return Ok(ProjectTaskSessionOutcome {
                replayed: true,
                workspace,
                conversation,
                initial_message,
                policy,
                capability_version,
            });
        }

        validate_workspace_scope_value(&workspace, &tenant_id, &project_id)?;
        let workspace_id =
            required_string(&workspace, "id").map_err(DesktopTaskSessionError::Storage)?;
        if conversation.tenant_id != tenant_id
            || conversation.project_id != project_id
            || conversation.workspace_id.as_deref() != Some(workspace_id.as_str())
            || conversation.current_mode != super::ConversationRunMode::Plan
        {
            return Err(DesktopTaskSessionError::ScopeMismatch);
        }
        let initial_message_id =
            required_string(&initial_message, "id").map_err(DesktopTaskSessionError::Storage)?;
        let initial_workspace_id = required_string(&initial_message, "workspace_id")
            .map_err(DesktopTaskSessionError::Storage)?;
        let message_conversation_id = initial_message
            .get("metadata")
            .and_then(Value::as_object)
            .and_then(|metadata| metadata.get("conversation_id"))
            .and_then(Value::as_str)
            .ok_or(DesktopTaskSessionError::ScopeMismatch)?;
        if initial_workspace_id != workspace_id || message_conversation_id != conversation.id {
            return Err(DesktopTaskSessionError::ScopeMismatch);
        }
        insert_conversation_record(&transaction, &conversation)
            .map_err(DesktopTaskSessionError::Storage)?;
        let conversation_response =
            task_session_conversation_value(&conversation, &workspace, &user_id);
        let response = TaskSessionResponseSnapshot {
            workspace: workspace.clone(),
            conversation: conversation_response.clone(),
            initial_message: initial_message.clone(),
            policy: policy.clone(),
            capability_version: capability_version.clone(),
        };
        let response_json = serde_json::to_string(&response)
            .map_err(|error| DesktopTaskSessionError::Storage(error.to_string()))?;
        transaction
            .execute(
                "INSERT INTO desktop_new_task_sessions(
                   user_id, tenant_id, project_id, idempotency_key, payload_hash, workspace_id,
                   conversation_id, initial_message_id, response_json, created_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
                params![
                    user_id,
                    tenant_id,
                    project_id,
                    idempotency_key,
                    payload_hash,
                    workspace_id,
                    conversation.id,
                    initial_message_id,
                    response_json,
                    now,
                ],
            )
            .map_err(|error| DesktopTaskSessionError::Storage(error.to_string()))?;
        transaction
            .commit()
            .map_err(|error| DesktopTaskSessionError::Storage(error.to_string()))?;
        Ok(ProjectTaskSessionOutcome {
            replayed: false,
            workspace,
            conversation: conversation_response,
            initial_message,
            policy,
            capability_version,
        })
    }

    pub(super) fn replay_task_session(
        &self,
        input: ReplayTaskSessionInput,
    ) -> Result<Option<ProjectTaskSessionOutcome>, DesktopTaskSessionError> {
        let connection = self
            .connection()
            .map_err(DesktopTaskSessionError::Storage)?;
        validate_task_session_context(
            &connection,
            &input.user_id,
            input.expected_context_revision,
            &input.tenant_id,
            &input.project_id,
        )?;
        let Some(receipt) = query_task_session_receipt(
            &connection,
            &input.user_id,
            &input.tenant_id,
            &input.project_id,
            &input.idempotency_key,
        )?
        else {
            return Ok(None);
        };
        if receipt.payload_hash != input.payload_hash {
            return Err(DesktopTaskSessionError::IdempotencyConflict);
        }
        validate_task_session_receipt(
            &receipt,
            &input.user_id,
            &input.tenant_id,
            &input.project_id,
        )?;
        let TaskSessionResponseSnapshot {
            workspace,
            conversation,
            initial_message,
            policy,
            capability_version,
        } = receipt.response;
        Ok(Some(ProjectTaskSessionOutcome {
            replayed: true,
            workspace,
            conversation,
            initial_message,
            policy,
            capability_version,
        }))
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

    // Keep the legacy unpaginated store API available while HTTP consumers migrate to cursors.
    #[allow(dead_code)]
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

    pub(super) fn timeline_page(
        &self,
        conversation_id: &str,
        limit: usize,
        from: Option<DesktopTimelineCursor>,
        before: Option<DesktopTimelineCursor>,
    ) -> Result<DesktopTimelinePage, String> {
        if !(1..=MAX_TIMELINE_PAGE_LIMIT).contains(&limit) {
            return Err("timeline page limit must be between 1 and 500".to_string());
        }
        let limit = i64::try_from(limit).map_err(|error| error.to_string())?;
        let connection = self.connection()?;
        if timeline_has_cursor_collision(&connection, conversation_id)? {
            return Err("desktop timeline contains duplicate cursors".to_string());
        }
        let (mut rows, reverse) = if let Some(before) = before {
            let mut statement = connection
                .prepare(
                    "WITH timeline_rows AS (
                       SELECT position,
                              value_json,
                              COALESCE(
                                CAST(json_extract(value_json, '$.eventTimeUs') AS INTEGER),
                                CAST(json_extract(value_json, '$.event_time_us') AS INTEGER),
                                CAST(json_extract(value_json, '$.time_us') AS INTEGER),
                                position
                              ) AS cursor_time,
                              COALESCE(
                                CAST(json_extract(value_json, '$.eventCounter') AS INTEGER),
                                CAST(json_extract(value_json, '$.event_counter') AS INTEGER),
                                CAST(json_extract(value_json, '$.counter') AS INTEGER),
                                position
                              ) AS cursor_counter
                       FROM desktop_timeline
                       WHERE conversation_id = ?1
                     )
                     SELECT value_json, cursor_time, cursor_counter
                     FROM timeline_rows
                     WHERE (cursor_time, cursor_counter) < (?2, ?3)
                       AND (?4 IS NULL OR (cursor_time, cursor_counter) > (?4, ?5))
                     ORDER BY cursor_time DESC, cursor_counter DESC, position DESC
                     LIMIT ?6",
                )
                .map_err(|error| error.to_string())?;
            let from_time_us = from.map(|cursor| cursor.time_us);
            let from_counter = from.map(|cursor| cursor.counter);
            (
                timeline_page_rows(statement.query_map(
                    params![
                        conversation_id,
                        before.time_us,
                        before.counter,
                        from_time_us,
                        from_counter,
                        limit
                    ],
                    timeline_page_row,
                ))?,
                true,
            )
        } else if let Some(from) = from {
            let mut statement = connection
                .prepare(
                    "WITH timeline_rows AS (
                       SELECT position,
                              value_json,
                              COALESCE(
                                CAST(json_extract(value_json, '$.eventTimeUs') AS INTEGER),
                                CAST(json_extract(value_json, '$.event_time_us') AS INTEGER),
                                CAST(json_extract(value_json, '$.time_us') AS INTEGER),
                                position
                              ) AS cursor_time,
                              COALESCE(
                                CAST(json_extract(value_json, '$.eventCounter') AS INTEGER),
                                CAST(json_extract(value_json, '$.event_counter') AS INTEGER),
                                CAST(json_extract(value_json, '$.counter') AS INTEGER),
                                position
                              ) AS cursor_counter
                       FROM desktop_timeline
                       WHERE conversation_id = ?1
                     )
                     SELECT value_json, cursor_time, cursor_counter
                     FROM timeline_rows
                     WHERE (cursor_time, cursor_counter) > (?2, ?3)
                     ORDER BY cursor_time ASC, cursor_counter ASC, position ASC
                     LIMIT ?4",
                )
                .map_err(|error| error.to_string())?;
            (
                timeline_page_rows(statement.query_map(
                    params![conversation_id, from.time_us, from.counter, limit],
                    timeline_page_row,
                ))?,
                false,
            )
        } else {
            let mut statement = connection
                .prepare(
                    "WITH timeline_rows AS (
                       SELECT position,
                              value_json,
                              COALESCE(
                                CAST(json_extract(value_json, '$.eventTimeUs') AS INTEGER),
                                CAST(json_extract(value_json, '$.event_time_us') AS INTEGER),
                                CAST(json_extract(value_json, '$.time_us') AS INTEGER),
                                position
                              ) AS cursor_time,
                              COALESCE(
                                CAST(json_extract(value_json, '$.eventCounter') AS INTEGER),
                                CAST(json_extract(value_json, '$.event_counter') AS INTEGER),
                                CAST(json_extract(value_json, '$.counter') AS INTEGER),
                                position
                              ) AS cursor_counter
                       FROM desktop_timeline
                       WHERE conversation_id = ?1
                     )
                     SELECT value_json, cursor_time, cursor_counter
                     FROM timeline_rows
                     ORDER BY cursor_time DESC, cursor_counter DESC, position DESC
                     LIMIT ?2",
                )
                .map_err(|error| error.to_string())?;
            (
                timeline_page_rows(
                    statement.query_map(params![conversation_id, limit], timeline_page_row),
                )?,
                true,
            )
        };
        if reverse {
            rows.reverse();
        }
        let first_cursor = rows.first().map(|(_, cursor)| *cursor);
        let last_cursor = rows.last().map(|(_, cursor)| *cursor);
        let has_more = first_cursor
            .map(|cursor| timeline_has_rows_before(&connection, conversation_id, cursor))
            .transpose()?
            .unwrap_or(false);
        Ok(DesktopTimelinePage {
            items: rows.into_iter().map(|(item, _)| item).collect(),
            has_more,
            first_cursor,
            last_cursor,
        })
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

    pub(super) fn plan_version_for_projection(
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
                && existing.references == input.references
                && existing.context_items == input.context_items;
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
            context_items: input.context_items,
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

    pub(super) fn current_artifact_version(
        &self,
        artifact_id: &str,
    ) -> Result<Option<DesktopArtifactVersion>, String> {
        let connection = self.connection()?;
        query_current_artifact_version(&connection, artifact_id)
    }

    pub(super) fn synchronize_artifact_content_authority(
        &self,
        version: &DesktopArtifactVersion,
        observed_content_hash: &str,
        now: &str,
    ) -> Result<DesktopArtifactContentAuthority, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let current = query_current_artifact_version(&transaction, &version.artifact_id)?
            .ok_or_else(|| "artifact not found".to_string())?;
        if current.id != version.id {
            return Err("artifact content authority changed".to_string());
        }
        let existing = query_artifact_content_authority(&transaction, &version.artifact_id)?;
        let authority = match existing {
            Some(existing)
                if existing.artifact_version_id == version.id
                    && existing.content_hash == observed_content_hash
                    && existing.mime_type == version.mime_type
                    && existing.path == version.path =>
            {
                existing
            }
            Some(existing) => DesktopArtifactContentAuthority {
                artifact_id: version.artifact_id.clone(),
                artifact_version_id: version.id.clone(),
                revision: existing
                    .revision
                    .checked_add(1)
                    .ok_or_else(|| "artifact content revision is exhausted".to_string())?,
                content_hash: observed_content_hash.to_string(),
                mime_type: version.mime_type.clone(),
                path: version.path.clone(),
            },
            None => DesktopArtifactContentAuthority {
                artifact_id: version.artifact_id.clone(),
                artifact_version_id: version.id.clone(),
                revision: 0,
                content_hash: observed_content_hash.to_string(),
                mime_type: version.mime_type.clone(),
                path: version.path.clone(),
            },
        };
        transaction
            .execute(
                "INSERT INTO desktop_artifact_content_authorities(
                   artifact_id, artifact_version_id, revision, content_hash,
                   mime_type, path, updated_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
                 ON CONFLICT(artifact_id) DO UPDATE SET
                   artifact_version_id = excluded.artifact_version_id,
                   revision = excluded.revision,
                   content_hash = excluded.content_hash,
                   mime_type = excluded.mime_type,
                   path = excluded.path,
                   updated_at = excluded.updated_at",
                params![
                    authority.artifact_id,
                    authority.artifact_version_id,
                    authority.revision as i64,
                    authority.content_hash,
                    authority.mime_type,
                    authority.path,
                    now,
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(authority)
    }

    pub(super) fn save_artifact_content<F>(
        &self,
        version: &DesktopArtifactVersion,
        input: DesktopArtifactContentSaveInput<'_>,
        write_file: F,
    ) -> Result<DesktopArtifactContentSaveOutcome, String>
    where
        F: FnOnce() -> Result<(), String>,
    {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let current = query_current_artifact_version(&transaction, &version.artifact_id)?
            .ok_or_else(|| "artifact not found".to_string())?;
        if current.id != version.id {
            return Err("artifact content authority changed".to_string());
        }
        let authority = query_artifact_content_authority(&transaction, &version.artifact_id)?
            .ok_or_else(|| "artifact content authority is not initialized".to_string())?;
        if authority.artifact_version_id != version.id
            || authority.path != version.path
            || authority.mime_type != version.mime_type
        {
            return Err("artifact content authority changed".to_string());
        }
        if let Some((request_hash, revision, content_hash)) = query_artifact_content_receipt(
            &transaction,
            &version.artifact_id,
            input.idempotency_key,
        )? {
            if request_hash == input.request_hash {
                return Ok(DesktopArtifactContentSaveOutcome::Saved(
                    DesktopArtifactContentSaveReceipt {
                        artifact_id: version.artifact_id.clone(),
                        revision,
                        content_hash,
                        duplicate: true,
                    },
                ));
            }
            return Ok(DesktopArtifactContentSaveOutcome::Conflict {
                reason_code: "artifact_content_idempotency_conflict",
                server_revision: authority.revision,
                server_content_hash: authority.content_hash,
            });
        }
        if authority.revision != input.expected_revision
            || authority.content_hash != input.observed_content_hash
        {
            return Ok(DesktopArtifactContentSaveOutcome::Conflict {
                reason_code: "artifact_content_revision_conflict",
                server_revision: authority.revision,
                server_content_hash: authority.content_hash,
            });
        }
        let next_revision = authority
            .revision
            .checked_add(1)
            .ok_or_else(|| "artifact content revision is exhausted".to_string())?;
        write_file()?;
        transaction
            .execute(
                "UPDATE desktop_artifact_content_authorities
                 SET revision = ?2, content_hash = ?3, updated_at = ?4
                 WHERE artifact_id = ?1",
                params![
                    version.artifact_id,
                    next_revision as i64,
                    input.content_hash,
                    input.now,
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "INSERT INTO desktop_artifact_content_receipts(
                   artifact_id, idempotency_key, request_hash, revision,
                   content_hash, created_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![
                    version.artifact_id,
                    input.idempotency_key,
                    input.request_hash,
                    next_revision as i64,
                    input.content_hash,
                    input.now,
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(DesktopArtifactContentSaveOutcome::Saved(
            DesktopArtifactContentSaveReceipt {
                artifact_id: version.artifact_id.clone(),
                revision: next_revision,
                content_hash: input.content_hash.to_string(),
                duplicate: false,
            },
        ))
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
            .map(|value| {
                serde_json::from_str(&value)
                    .map(normalize_hitl_request)
                    .map_err(|error| error.to_string())
            })
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
        typed_rows(statement.query_map([conversation_id], |row| row.get::<_, String>(0))).map(
            |requests: Vec<DesktopHitlRequest>| {
                requests.into_iter().map(normalize_hitl_request).collect()
            },
        )
    }

    pub(super) fn mark_hitl_responded(
        &self,
        request_id: &str,
        response: HitlResponseCommit<'_>,
    ) -> Result<HitlResponseCommitOutcome, HitlResponseCommitError> {
        let mut connection = self
            .connection()
            .map_err(HitlResponseCommitError::Storage)?;
        let transaction = connection
            .transaction()
            .map_err(|error| HitlResponseCommitError::Storage(error.to_string()))?;
        let value_json = transaction
            .query_row(
                "SELECT value_json FROM desktop_hitl_requests WHERE id = ?1",
                [request_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| HitlResponseCommitError::Storage(error.to_string()))?
            .ok_or(HitlResponseCommitError::NotFound)?;
        let mut request: DesktopHitlRequest = serde_json::from_str(&value_json)
            .map_err(|error| HitlResponseCommitError::Storage(error.to_string()))?;
        if request.status == DesktopHitlStatus::Responded
            && request.authority_revision == HITL_PENDING_AUTHORITY_REVISION
        {
            request.authority_revision = HITL_PENDING_AUTHORITY_REVISION + 1;
        }
        if request.status == DesktopHitlStatus::Responded {
            if response.expected_authority_revision.checked_add(1)
                != Some(request.authority_revision)
            {
                return Err(HitlResponseCommitError::AuthorityConflict {
                    expected_revision: response.expected_authority_revision,
                    authority_revision: request.authority_revision,
                });
            }
            if request.idempotency_key.as_deref() == Some(response.idempotency_key) {
                if request.response_data.as_ref() == Some(response.response_data) {
                    transaction
                        .commit()
                        .map_err(|error| HitlResponseCommitError::Storage(error.to_string()))?;
                    return Ok(HitlResponseCommitOutcome::Duplicate(request));
                }
                return Err(HitlResponseCommitError::IdempotencyConflict {
                    authority_revision: request.authority_revision,
                });
            }
            return Err(HitlResponseCommitError::AlreadyAnswered {
                authority_revision: request.authority_revision,
            });
        }
        if response.expected_authority_revision != request.authority_revision {
            return Err(HitlResponseCommitError::AuthorityConflict {
                expected_revision: response.expected_authority_revision,
                authority_revision: request.authority_revision,
            });
        }
        request.authority_revision =
            request.authority_revision.checked_add(1).ok_or_else(|| {
                HitlResponseCommitError::Storage("HITL authority revision overflowed".to_string())
            })?;
        request.status = DesktopHitlStatus::Responded;
        request.responded_at = Some(response.now.to_string());
        request.response_data = Some(response.response_data.clone());
        request.response_actor = Some(response.response_actor.to_string());
        request.response_revision = response.response_revision;
        request.idempotency_key = Some(response.idempotency_key.to_string());
        if let Some(grant) = response.workspace_tool_grant {
            let active_grant = transaction
                .query_row(
                    "SELECT id FROM desktop_workspace_tool_grants
                     WHERE workspace_id = ?1 AND canonical_tool_name = ?2
                       AND revoked_at IS NULL
                     ORDER BY created_at DESC LIMIT 1",
                    params![grant.workspace_id, grant.canonical_tool_name],
                    |row| row.get::<_, String>(0),
                )
                .optional()
                .map_err(|error| HitlResponseCommitError::Storage(error.to_string()))?;
            if active_grant.is_none() {
                transaction
                    .execute(
                        "INSERT INTO desktop_workspace_tool_grants(
                           id, workspace_id, canonical_tool_name, source_hitl_request_id,
                           revision, created_by, created_at, revoked_by, revoked_at, value_json
                         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, NULL, NULL, ?8)",
                        params![
                            grant.id,
                            grant.workspace_id,
                            grant.canonical_tool_name,
                            grant.source_hitl_request_id,
                            grant.revision as i64,
                            grant.created_by,
                            grant.created_at,
                            serde_json::to_string(grant).map_err(|error| {
                                HitlResponseCommitError::Storage(error.to_string())
                            })?,
                        ],
                    )
                    .map_err(|error| HitlResponseCommitError::Storage(error.to_string()))?;
            }
        }
        let updated = transaction
            .execute(
                "UPDATE desktop_hitl_requests
                 SET status = 'responded', responded_at = ?2, value_json = ?3
                 WHERE id = ?1 AND status = 'pending'",
                params![
                    request_id,
                    response.now,
                    serde_json::to_string(&request)
                        .map_err(|error| HitlResponseCommitError::Storage(error.to_string()))?,
                ],
            )
            .map_err(|error| HitlResponseCommitError::Storage(error.to_string()))?;
        if updated != 1 {
            return Err(HitlResponseCommitError::AuthorityConflict {
                expected_revision: response.expected_authority_revision,
                authority_revision: request.authority_revision,
            });
        }
        transaction
            .commit()
            .map_err(|error| HitlResponseCommitError::Storage(error.to_string()))?;
        Ok(HitlResponseCommitOutcome::Committed(request))
    }

    pub(super) fn workspace_tool_grant_active(
        &self,
        conversation_id: &str,
        canonical_tool_name: &str,
    ) -> Result<bool, String> {
        let connection = self.connection()?;
        let count = connection
            .query_row(
                "SELECT COUNT(*)
                 FROM desktop_workspace_tool_grants grant_authority
                 JOIN desktop_conversations conversation
                   ON conversation.workspace_id = grant_authority.workspace_id
                 WHERE conversation.id = ?1
                   AND grant_authority.canonical_tool_name = ?2
                   AND grant_authority.revoked_at IS NULL",
                params![conversation_id, canonical_tool_name],
                |row| row.get::<_, i64>(0),
            )
            .map_err(|error| error.to_string())?;
        Ok(count > 0)
    }

    pub(super) fn list_workspace_tool_grants(
        &self,
        workspace_id: &str,
    ) -> Result<Vec<WorkspaceToolGrant>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT value_json FROM desktop_workspace_tool_grants
                 WHERE workspace_id = ?1 AND revoked_at IS NULL
                 ORDER BY created_at DESC, id DESC",
            )
            .map_err(|error| error.to_string())?;
        typed_rows(statement.query_map([workspace_id], |row| row.get::<_, String>(0)))
    }

    pub(super) fn revoke_workspace_tool_grant(
        &self,
        workspace_id: &str,
        grant_id: &str,
        revoked_by: &str,
        revoked_at: &str,
    ) -> Result<Option<WorkspaceToolGrant>, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let value_json = transaction
            .query_row(
                "SELECT value_json FROM desktop_workspace_tool_grants
                 WHERE id = ?1 AND workspace_id = ?2 AND revoked_at IS NULL",
                params![grant_id, workspace_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        let Some(value_json) = value_json else {
            transaction.commit().map_err(|error| error.to_string())?;
            return Ok(None);
        };
        let mut grant: WorkspaceToolGrant =
            serde_json::from_str(&value_json).map_err(|error| error.to_string())?;
        grant.revision = grant.revision.saturating_add(1);
        grant.revoked_by = Some(revoked_by.to_string());
        grant.revoked_at = Some(revoked_at.to_string());
        transaction
            .execute(
                "UPDATE desktop_workspace_tool_grants
                 SET revision = ?3, revoked_by = ?4, revoked_at = ?5, value_json = ?6
                 WHERE id = ?1 AND workspace_id = ?2 AND revoked_at IS NULL",
                params![
                    grant_id,
                    workspace_id,
                    grant.revision as i64,
                    revoked_by,
                    revoked_at,
                    serde_json::to_string(&grant).map_err(|error| error.to_string())?,
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(Some(grant))
    }

    /// Insert a browser origin grant, superseding (revoking) any active row
    /// for the same host so a host has at most one active decision.
    pub(super) fn insert_browser_origin_grant(
        &self,
        grant: &BrowserOriginGrant,
    ) -> Result<(), String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "UPDATE desktop_browser_origin_grants
                 SET revoked_at = ?2 WHERE host = ?1 AND revoked_at IS NULL",
                params![grant.host, grant.created_at],
            )
            .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "INSERT INTO desktop_browser_origin_grants(
                   id, host, decision, source_hitl_request_id, created_at, revoked_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, NULL)",
                params![
                    grant.id,
                    grant.host,
                    grant.decision.as_str(),
                    grant.source_hitl_request_id,
                    grant.created_at,
                ],
            )
            .map(|_| ())
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())
    }

    pub(super) fn list_active_browser_origin_grants(
        &self,
    ) -> Result<Vec<BrowserOriginGrant>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT id, host, decision, source_hitl_request_id, created_at, revoked_at
                 FROM desktop_browser_origin_grants
                 WHERE revoked_at IS NULL
                 ORDER BY created_at DESC, id DESC",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([], browser_origin_grant_from_row)
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())
    }

    /// Active decisions relevant to `host`: the host-specific row (if any)
    /// and the global `'*'` row (if any). The caller applies the decision
    /// matrix (decline > global all > site).
    pub(super) fn active_browser_origin_decisions(
        &self,
        host: &str,
    ) -> Result<Vec<BrowserOriginGrant>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT id, host, decision, source_hitl_request_id, created_at, revoked_at
                 FROM desktop_browser_origin_grants
                 WHERE revoked_at IS NULL AND (host = ?1 OR host = '*')
                 ORDER BY created_at DESC, id DESC",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([host], browser_origin_grant_from_row)
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())
    }

    pub(super) fn revoke_browser_origin_grant(
        &self,
        grant_id: &str,
        revoked_at: &str,
    ) -> Result<Option<BrowserOriginGrant>, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let grant = transaction
            .query_row(
                "SELECT id, host, decision, source_hitl_request_id, created_at, revoked_at
                 FROM desktop_browser_origin_grants
                 WHERE id = ?1 AND revoked_at IS NULL",
                [grant_id],
                browser_origin_grant_from_row,
            )
            .optional()
            .map_err(|error| error.to_string())?;
        let Some(mut grant) = grant else {
            transaction.commit().map_err(|error| error.to_string())?;
            return Ok(None);
        };
        grant.revoked_at = Some(revoked_at.to_string());
        transaction
            .execute(
                "UPDATE desktop_browser_origin_grants
                 SET revoked_at = ?2 WHERE id = ?1 AND revoked_at IS NULL",
                params![grant_id, revoked_at],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(Some(grant))
    }

    /// Insert a browser capability grant, superseding (revoking) any active
    /// row for the same host+capability in the same transaction so a pair has
    /// at most one active decision.
    pub(super) fn insert_browser_capability_grant(
        &self,
        grant: &BrowserCapabilityGrant,
    ) -> Result<(), String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "UPDATE desktop_browser_capability_grants
                 SET revoked_at = ?3
                 WHERE host = ?1 AND capability = ?2 AND revoked_at IS NULL",
                params![grant.host, grant.capability, grant.created_at],
            )
            .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "INSERT INTO desktop_browser_capability_grants(
                   id, host, capability, decision, source_hitl_request_id, created_at, revoked_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, NULL)",
                params![
                    grant.id,
                    grant.host,
                    grant.capability,
                    grant.decision.as_str(),
                    grant.source_hitl_request_id,
                    grant.created_at,
                ],
            )
            .map(|_| ())
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())
    }

    pub(super) fn list_active_browser_capability_grants(
        &self,
    ) -> Result<Vec<BrowserCapabilityGrant>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT id, host, capability, decision, source_hitl_request_id, created_at,
                        revoked_at
                 FROM desktop_browser_capability_grants
                 WHERE revoked_at IS NULL
                 ORDER BY created_at DESC, id DESC",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([], browser_capability_grant_from_row)
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())
    }

    /// Active decisions for (host, capability). The caller applies the
    /// decision matrix (decline beats site).
    pub(super) fn active_browser_capability_decisions(
        &self,
        host: &str,
        capability: &str,
    ) -> Result<Vec<BrowserCapabilityGrant>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT id, host, capability, decision, source_hitl_request_id, created_at,
                        revoked_at
                 FROM desktop_browser_capability_grants
                 WHERE revoked_at IS NULL AND host = ?1 AND capability = ?2
                 ORDER BY created_at DESC, id DESC",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map(params![host, capability], browser_capability_grant_from_row)
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())
    }

    pub(super) fn revoke_browser_capability_grant(
        &self,
        grant_id: &str,
        revoked_at: &str,
    ) -> Result<Option<BrowserCapabilityGrant>, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let grant = transaction
            .query_row(
                "SELECT id, host, capability, decision, source_hitl_request_id, created_at,
                        revoked_at
                 FROM desktop_browser_capability_grants
                 WHERE id = ?1 AND revoked_at IS NULL",
                [grant_id],
                browser_capability_grant_from_row,
            )
            .optional()
            .map_err(|error| error.to_string())?;
        let Some(mut grant) = grant else {
            transaction.commit().map_err(|error| error.to_string())?;
            return Ok(None);
        };
        grant.revoked_at = Some(revoked_at.to_string());
        transaction
            .execute(
                "UPDATE desktop_browser_capability_grants
                 SET revoked_at = ?2 WHERE id = ?1 AND revoked_at IS NULL",
                params![grant_id, revoked_at],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(Some(grant))
    }

    /// Upsert a site-credential metadata row: any active row for the same
    /// origin+username is superseded in the same transaction. The row carries
    /// no secret material — the password lives in the application vault under
    /// `credential_ref`. The reference is deterministic per (origin,
    /// username), so the insert revives the conflicting historical row with
    /// the new identity instead of violating its UNIQUE constraint.
    pub(super) fn upsert_browser_site_credential(
        &self,
        credential: &BrowserSiteCredential,
    ) -> Result<(), String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "UPDATE desktop_browser_site_credentials
                 SET revoked_at = ?3
                 WHERE origin = ?1 AND username = ?2 AND revoked_at IS NULL",
                params![
                    credential.origin,
                    credential.username,
                    credential.created_at
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "INSERT INTO desktop_browser_site_credentials(
                   id, origin, username, credential_ref, created_at, revoked_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, NULL)
                 ON CONFLICT(credential_ref) DO UPDATE SET
                   id = excluded.id,
                   origin = excluded.origin,
                   username = excluded.username,
                   created_at = excluded.created_at,
                   revoked_at = NULL",
                params![
                    credential.id,
                    credential.origin,
                    credential.username,
                    credential.credential_ref,
                    credential.created_at,
                ],
            )
            .map(|_| ())
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())
    }

    pub(super) fn list_active_browser_site_credentials(
        &self,
    ) -> Result<Vec<BrowserSiteCredential>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT id, origin, username, credential_ref, created_at, revoked_at
                 FROM desktop_browser_site_credentials
                 WHERE revoked_at IS NULL
                 ORDER BY created_at DESC, id DESC",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([], browser_site_credential_from_row)
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())
    }

    /// The active site-credential metadata for `origin` (and `username` when
    /// given). With no username filter the newest active row wins.
    pub(super) fn active_browser_site_credential(
        &self,
        origin: &str,
        username: Option<&str>,
    ) -> Result<Option<BrowserSiteCredential>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT id, origin, username, credential_ref, created_at, revoked_at
                 FROM desktop_browser_site_credentials
                 WHERE revoked_at IS NULL AND origin = ?1
                   AND (?2 IS NULL OR username = ?2)
                 ORDER BY created_at DESC, id DESC
                 LIMIT 1",
            )
            .map_err(|error| error.to_string())?;
        statement
            .query_row(params![origin, username], browser_site_credential_from_row)
            .optional()
            .map_err(|error| error.to_string())
    }

    pub(super) fn revoke_browser_site_credential(
        &self,
        credential_id: &str,
        revoked_at: &str,
    ) -> Result<Option<BrowserSiteCredential>, String> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let credential = transaction
            .query_row(
                "SELECT id, origin, username, credential_ref, created_at, revoked_at
                 FROM desktop_browser_site_credentials
                 WHERE id = ?1 AND revoked_at IS NULL",
                [credential_id],
                browser_site_credential_from_row,
            )
            .optional()
            .map_err(|error| error.to_string())?;
        let Some(mut credential) = credential else {
            transaction.commit().map_err(|error| error.to_string())?;
            return Ok(None);
        };
        credential.revoked_at = Some(revoked_at.to_string());
        transaction
            .execute(
                "UPDATE desktop_browser_site_credentials
                 SET revoked_at = ?2 WHERE id = ?1 AND revoked_at IS NULL",
                params![credential_id, revoked_at],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(Some(credential))
    }

    /// Fire-and-forget audit sink for browser tool calls. The caller logs and
    /// swallows failures — auditing must never fail a tool call.
    #[allow(clippy::too_many_arguments)]
    pub(super) fn insert_browser_action_audit(
        &self,
        run_id: Option<&str>,
        tool_name: &str,
        origin: Option<&str>,
        target_summary: &str,
        outcome: &str,
        latency_ms: i64,
        created_at: i64,
    ) -> Result<(), String> {
        self.connection()?
            .execute(
                "INSERT INTO desktop_browser_action_audit(
                   run_id, tool_name, origin, target_summary, outcome, latency_ms, created_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    run_id,
                    tool_name,
                    origin,
                    target_summary,
                    outcome,
                    latency_ms,
                    created_at,
                ],
            )
            .map(|_| ())
            .map_err(|error| error.to_string())
    }

    /// Newest-first audit entries, capped by `limit` and optionally filtered
    /// to one origin.
    pub(super) fn list_browser_action_audit(
        &self,
        limit: u32,
        origin: Option<&str>,
    ) -> Result<Vec<BrowserActionAudit>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT id, run_id, tool_name, origin, target_summary, outcome, latency_ms,
                        created_at
                 FROM desktop_browser_action_audit
                 WHERE (?1 IS NULL OR origin = ?1)
                 ORDER BY created_at DESC, id DESC
                 LIMIT ?2",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map(params![origin, limit], browser_action_audit_from_row)
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())
    }

    /// Retention sweep: drop audit rows older than `cutoff` (epoch ms).
    pub(super) fn delete_browser_action_audit_older_than(
        &self,
        cutoff: i64,
    ) -> Result<usize, String> {
        self.connection()?
            .execute(
                "DELETE FROM desktop_browser_action_audit WHERE created_at < ?1",
                params![cutoff],
            )
            .map_err(|error| error.to_string())
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

        if grant_source == "workspace_tool_grant" {
            let active_count = transaction
                .query_row(
                    "SELECT COUNT(*)
                     FROM desktop_workspace_tool_grants grant_authority
                     JOIN desktop_conversations conversation
                       ON conversation.workspace_id = grant_authority.workspace_id
                     JOIN desktop_runs active_run
                       ON active_run.conversation_id = conversation.id
                     WHERE active_run.id = ?1
                       AND grant_authority.canonical_tool_name = ?2
                       AND grant_authority.revoked_at IS NULL",
                    params![request.run_id, request.tool_name],
                    |row| row.get::<_, i64>(0),
                )
                .map_err(|error| error.to_string())?;
            if active_count == 0 {
                return Err("workspace tool grant is no longer active".to_string());
            }
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
                return Err("cannot transition an invocation back to prepared".to_string());
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

    pub(super) fn record_llm_provider_usage(
        &self,
        usage: ProviderUsageRecord<'_>,
    ) -> Result<(), String> {
        let connection = self.connection()?;
        provider_usage_store::record(&connection, usage)
    }

    pub(super) fn llm_provider_usage_statistics(
        &self,
        provider_id: &str,
        tenant_id: &str,
    ) -> Result<Vec<ProviderUsageStatistic>, String> {
        let connection = self.connection()?;
        provider_usage_store::statistics(&connection, provider_id, tenant_id)
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

fn query_current_artifact_version(
    connection: &Connection,
    artifact_id: &str,
) -> Result<Option<DesktopArtifactVersion>, String> {
    let value_json = connection
        .query_row(
            "SELECT version.value_json
             FROM desktop_artifacts AS artifact
             JOIN desktop_artifact_versions AS version
               ON version.id = artifact.current_version_id
             WHERE artifact.id = ?1",
            [artifact_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| error.to_string())?;
    value_json
        .map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
        .transpose()
}

fn query_artifact_content_authority(
    connection: &Connection,
    artifact_id: &str,
) -> Result<Option<DesktopArtifactContentAuthority>, String> {
    let row = connection
        .query_row(
            "SELECT artifact_id, artifact_version_id, revision, content_hash, mime_type, path
             FROM desktop_artifact_content_authorities WHERE artifact_id = ?1",
            [artifact_id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, String>(5)?,
                ))
            },
        )
        .optional()
        .map_err(|error| error.to_string())?;
    row.map(
        |(artifact_id, artifact_version_id, revision, content_hash, mime_type, path)| {
            Ok(DesktopArtifactContentAuthority {
                artifact_id,
                artifact_version_id,
                revision: u64::try_from(revision)
                    .map_err(|_| "artifact content revision is invalid".to_string())?,
                content_hash,
                mime_type,
                path,
            })
        },
    )
    .transpose()
}

fn query_artifact_content_receipt(
    connection: &Connection,
    artifact_id: &str,
    idempotency_key: &str,
) -> Result<Option<(String, u64, String)>, String> {
    let row = connection
        .query_row(
            "SELECT request_hash, revision, content_hash
             FROM desktop_artifact_content_receipts
             WHERE artifact_id = ?1 AND idempotency_key = ?2",
            params![artifact_id, idempotency_key],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, i64>(1)?,
                    row.get::<_, String>(2)?,
                ))
            },
        )
        .optional()
        .map_err(|error| error.to_string())?;
    row.map(|(request_hash, revision, content_hash)| {
        Ok((
            request_hash,
            u64::try_from(revision)
                .map_err(|_| "artifact content receipt revision is invalid".to_string())?,
            content_hash,
        ))
    })
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

fn normalize_hitl_request(mut request: DesktopHitlRequest) -> DesktopHitlRequest {
    if request.status == DesktopHitlStatus::Responded
        && request.authority_revision == HITL_PENDING_AUTHORITY_REVISION
    {
        request.authority_revision = HITL_PENDING_AUTHORITY_REVISION + 1;
    }
    request
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

struct TaskSessionReceipt {
    user_id: String,
    #[cfg_attr(not(test), allow(dead_code))]
    payload_hash: String,
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    conversation_id: String,
    initial_message_id: String,
    response: TaskSessionResponseSnapshot,
}

#[derive(Serialize, Deserialize)]
struct TaskSessionResponseSnapshot {
    workspace: Value,
    conversation: Value,
    initial_message: Value,
    #[serde(default)]
    policy: Value,
    #[serde(default = "default_task_session_capability_version")]
    capability_version: String,
}

fn default_task_session_capability_version() -> String {
    "avernet-task-session-v1".to_string()
}

struct LegacyTaskSessionReceipt {
    idempotency_key: String,
    payload_hash: String,
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    conversation_id: String,
    initial_message_id: String,
    response_json: String,
    created_at: String,
}

struct SqliteColumnInfo {
    name: String,
    not_null: bool,
    primary_key_position: i64,
}

fn validate_task_session_context(
    connection: &Connection,
    user_id: &str,
    expected_revision: u64,
    tenant_id: &str,
    project_id: &str,
) -> Result<(), DesktopTaskSessionError> {
    let context = connection
        .query_row(
            "SELECT tenant_id, project_id, revision
             FROM desktop_workspace_contexts WHERE user_id = ?1",
            [user_id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                ))
            },
        )
        .optional()
        .map_err(|error| DesktopTaskSessionError::Storage(error.to_string()))?;
    let Some((active_tenant_id, active_project_id, active_revision)) = context else {
        return Err(DesktopTaskSessionError::ScopeMismatch);
    };
    let active_revision = u64::try_from(active_revision).map_err(|_| {
        DesktopTaskSessionError::Storage("workspace context revision is invalid".to_string())
    })?;
    if active_tenant_id != tenant_id
        || active_project_id != project_id
        || active_revision != expected_revision
    {
        return Err(DesktopTaskSessionError::ScopeMismatch);
    }
    Ok(())
}

fn migrate_task_session_receipt_scope(connection: &mut Connection) -> Result<(), String> {
    let columns = task_session_receipt_columns(connection)?;
    if columns.is_empty() {
        connection
            .execute_batch(TASK_SESSION_RECEIPT_TABLE_SQL)
            .map_err(|error| error.to_string())?;
        connection
            .execute_batch(TASK_SESSION_RECEIPT_INDEX_SQL)
            .map_err(|error| error.to_string())?;
        return Ok(());
    }

    if columns.iter().any(|column| column.name == "user_id") {
        validate_scoped_task_session_receipt_schema(&columns)?;
        connection
            .execute_batch(TASK_SESSION_RECEIPT_INDEX_SQL)
            .map_err(|error| error.to_string())?;
        return Ok(());
    }
    validate_legacy_task_session_receipt_schema(&columns)?;
    if sqlite_table_exists(connection, LEGACY_TASK_SESSION_RECEIPT_TABLE)? {
        return Err("legacy task session receipt migration table already exists".to_string());
    }

    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|error| error.to_string())?;
    transaction
        .execute_batch(
            "DROP INDEX IF EXISTS idx_desktop_new_task_sessions_scope;
             ALTER TABLE desktop_new_task_sessions
               RENAME TO desktop_new_task_sessions_v15;",
        )
        .map_err(|error| error.to_string())?;
    transaction
        .execute_batch(TASK_SESSION_RECEIPT_TABLE_SQL)
        .map_err(|error| error.to_string())?;

    let legacy_receipts = {
        let mut statement = transaction
            .prepare(
                "SELECT idempotency_key, payload_hash, tenant_id, project_id, workspace_id,
                        conversation_id, initial_message_id, response_json, created_at
                 FROM desktop_new_task_sessions_v15 ORDER BY rowid ASC",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([], |row| {
                Ok(LegacyTaskSessionReceipt {
                    idempotency_key: row.get(0)?,
                    payload_hash: row.get(1)?,
                    tenant_id: row.get(2)?,
                    project_id: row.get(3)?,
                    workspace_id: row.get(4)?,
                    conversation_id: row.get(5)?,
                    initial_message_id: row.get(6)?,
                    response_json: row.get(7)?,
                    created_at: row.get(8)?,
                })
            })
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())?
    };

    for legacy in legacy_receipts {
        let response: TaskSessionResponseSnapshot = serde_json::from_str(&legacy.response_json)
            .map_err(|_| "legacy task session receipt response is invalid".to_string())?;
        let user_id = task_session_snapshot_user(&response)
            .map_err(|_| "legacy task session receipt identity is invalid".to_string())?
            .to_string();
        let receipt = TaskSessionReceipt {
            user_id: user_id.clone(),
            payload_hash: legacy.payload_hash.clone(),
            tenant_id: legacy.tenant_id.clone(),
            project_id: legacy.project_id.clone(),
            workspace_id: legacy.workspace_id.clone(),
            conversation_id: legacy.conversation_id.clone(),
            initial_message_id: legacy.initial_message_id.clone(),
            response,
        };
        validate_task_session_receipt(&receipt, &user_id, &legacy.tenant_id, &legacy.project_id)
            .map_err(|_| "legacy task session receipt scope is invalid".to_string())?;
        transaction
            .execute(
                "INSERT INTO desktop_new_task_sessions(
                   user_id, tenant_id, project_id, idempotency_key, payload_hash, workspace_id,
                   conversation_id, initial_message_id, response_json, created_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
                params![
                    user_id,
                    legacy.tenant_id,
                    legacy.project_id,
                    legacy.idempotency_key,
                    legacy.payload_hash,
                    legacy.workspace_id,
                    legacy.conversation_id,
                    legacy.initial_message_id,
                    legacy.response_json,
                    legacy.created_at,
                ],
            )
            .map_err(|error| error.to_string())?;
    }
    transaction
        .execute_batch(
            "DROP TABLE desktop_new_task_sessions_v15;
             CREATE INDEX idx_desktop_new_task_sessions_scope
               ON desktop_new_task_sessions(user_id, tenant_id, project_id, created_at);",
        )
        .map_err(|error| error.to_string())?;
    transaction.commit().map_err(|error| error.to_string())
}

fn task_session_receipt_columns(connection: &Connection) -> Result<Vec<SqliteColumnInfo>, String> {
    let mut statement = connection
        .prepare("PRAGMA table_info('desktop_new_task_sessions')")
        .map_err(|error| error.to_string())?;
    let rows = statement
        .query_map([], |row| {
            Ok(SqliteColumnInfo {
                name: row.get(1)?,
                not_null: row.get::<_, i64>(3)? == 1,
                primary_key_position: row.get(5)?,
            })
        })
        .map_err(|error| error.to_string())?;
    rows.collect::<Result<Vec<_>, _>>()
        .map_err(|error| error.to_string())
}

fn validate_legacy_task_session_receipt_schema(columns: &[SqliteColumnInfo]) -> Result<(), String> {
    const EXPECTED_COLUMNS: [&str; 9] = [
        "idempotency_key",
        "payload_hash",
        "tenant_id",
        "project_id",
        "workspace_id",
        "conversation_id",
        "initial_message_id",
        "response_json",
        "created_at",
    ];
    validate_task_session_receipt_columns(columns, &EXPECTED_COLUMNS)?;
    let idempotency_key = columns
        .iter()
        .find(|column| column.name == "idempotency_key")
        .ok_or_else(|| "legacy task session receipt key is missing".to_string())?;
    if idempotency_key.primary_key_position != 1
        || columns
            .iter()
            .any(|column| column.name != "idempotency_key" && !column.not_null)
    {
        return Err("legacy task session receipt primary key is invalid".to_string());
    }
    Ok(())
}

fn validate_scoped_task_session_receipt_schema(columns: &[SqliteColumnInfo]) -> Result<(), String> {
    const EXPECTED_COLUMNS: [&str; 10] = [
        "user_id",
        "tenant_id",
        "project_id",
        "idempotency_key",
        "payload_hash",
        "workspace_id",
        "conversation_id",
        "initial_message_id",
        "response_json",
        "created_at",
    ];
    validate_task_session_receipt_columns(columns, &EXPECTED_COLUMNS)?;
    if columns.iter().any(|column| !column.not_null) {
        return Err("task session receipt table schema is unsupported".to_string());
    }
    for (name, position) in [
        ("user_id", 1),
        ("tenant_id", 2),
        ("project_id", 3),
        ("idempotency_key", 4),
    ] {
        let column = columns
            .iter()
            .find(|column| column.name == name)
            .ok_or_else(|| format!("task session receipt column {name} is missing"))?;
        if column.primary_key_position != position {
            return Err(format!(
                "task session receipt primary key position for {name} is invalid"
            ));
        }
    }
    Ok(())
}

fn validate_task_session_receipt_columns(
    columns: &[SqliteColumnInfo],
    expected: &[&str],
) -> Result<(), String> {
    let actual_names: HashSet<&str> = columns.iter().map(|column| column.name.as_str()).collect();
    let expected_names: HashSet<&str> = expected.iter().copied().collect();
    if actual_names != expected_names {
        return Err("task session receipt table schema is unsupported".to_string());
    }
    Ok(())
}

fn sqlite_table_exists(connection: &Connection, table_name: &str) -> Result<bool, String> {
    connection
        .query_row(
            "SELECT EXISTS(
               SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?1
             )",
            [table_name],
            |row| row.get(0),
        )
        .map_err(|error| error.to_string())
}

fn query_task_session_receipt(
    connection: &Connection,
    user_id: &str,
    tenant_id: &str,
    project_id: &str,
    idempotency_key: &str,
) -> Result<Option<TaskSessionReceipt>, DesktopTaskSessionError> {
    let row = connection
        .query_row(
            "SELECT user_id, payload_hash, tenant_id, project_id, workspace_id, conversation_id,
                    initial_message_id, response_json
             FROM desktop_new_task_sessions
             WHERE user_id = ?1 AND tenant_id = ?2 AND project_id = ?3
               AND idempotency_key = ?4",
            params![user_id, tenant_id, project_id, idempotency_key],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, String>(5)?,
                    row.get::<_, String>(6)?,
                    row.get::<_, String>(7)?,
                ))
            },
        )
        .optional()
        .map_err(|error| DesktopTaskSessionError::Storage(error.to_string()))?;
    let Some((
        user_id,
        payload_hash,
        tenant_id,
        project_id,
        workspace_id,
        conversation_id,
        initial_message_id,
        response_json,
    )) = row
    else {
        return Ok(None);
    };
    let response = serde_json::from_str(&response_json)
        .map_err(|error| DesktopTaskSessionError::Storage(error.to_string()))?;
    Ok(Some(TaskSessionReceipt {
        user_id,
        payload_hash,
        tenant_id,
        project_id,
        workspace_id,
        conversation_id,
        initial_message_id,
        response,
    }))
}

fn validate_task_session_receipt(
    receipt: &TaskSessionReceipt,
    user_id: &str,
    tenant_id: &str,
    project_id: &str,
) -> Result<(), DesktopTaskSessionError> {
    if receipt.user_id != user_id
        || receipt.tenant_id != tenant_id
        || receipt.project_id != project_id
    {
        return Err(DesktopTaskSessionError::ScopeMismatch);
    }
    validate_workspace_scope_value(&receipt.response.workspace, tenant_id, project_id)?;
    let snapshot_user_id = task_session_snapshot_user(&receipt.response)?;
    let conversation = &receipt.response.conversation;
    let initial_message = &receipt.response.initial_message;
    if snapshot_user_id != user_id
        || required_string(&receipt.response.workspace, "id")
            .map_err(DesktopTaskSessionError::Storage)?
            != receipt.workspace_id
        || required_string(conversation, "id").map_err(DesktopTaskSessionError::Storage)?
            != receipt.conversation_id
        || required_string(conversation, "tenant_id").map_err(DesktopTaskSessionError::Storage)?
            != tenant_id
        || required_string(conversation, "project_id").map_err(DesktopTaskSessionError::Storage)?
            != project_id
        || required_string(conversation, "workspace_id")
            .map_err(DesktopTaskSessionError::Storage)?
            != receipt.workspace_id
        || required_string(conversation, "current_mode")
            .map_err(DesktopTaskSessionError::Storage)?
            != "plan"
        || required_string(initial_message, "id").map_err(DesktopTaskSessionError::Storage)?
            != receipt.initial_message_id
        || required_string(initial_message, "workspace_id")
            .map_err(DesktopTaskSessionError::Storage)?
            != receipt.workspace_id
    {
        return Err(DesktopTaskSessionError::ScopeMismatch);
    }
    Ok(())
}

fn task_session_snapshot_user(
    response: &TaskSessionResponseSnapshot,
) -> Result<String, DesktopTaskSessionError> {
    let conversation_user = required_string(&response.conversation, "user_id")
        .map_err(DesktopTaskSessionError::Storage)?;
    let message_sender = required_string(&response.initial_message, "sender_id")
        .map_err(DesktopTaskSessionError::Storage)?;
    if conversation_user != message_sender {
        return Err(DesktopTaskSessionError::ScopeMismatch);
    }
    Ok(conversation_user)
}

fn validate_workspace_scope_value(
    workspace: &Value,
    tenant_id: &str,
    project_id: &str,
) -> Result<(), DesktopTaskSessionError> {
    let workspace_tenant_id =
        required_string(workspace, "tenant_id").map_err(DesktopTaskSessionError::Storage)?;
    let workspace_project_id =
        required_string(workspace, "project_id").map_err(DesktopTaskSessionError::Storage)?;
    if workspace_tenant_id != tenant_id || workspace_project_id != project_id {
        return Err(DesktopTaskSessionError::ScopeMismatch);
    }
    Ok(())
}

fn task_session_conversation_value(
    conversation: &LocalConversation,
    workspace: &Value,
    user_id: &str,
) -> Value {
    json!({
        "id": conversation.id,
        "project_id": conversation.project_id,
        "tenant_id": conversation.tenant_id,
        "user_id": user_id,
        "title": conversation.title,
        "status": "active",
        "message_count": 1,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "summary": Value::Null,
        "agent_config": {
            "selected_agent_id": "builtin:all-access",
            "capability_mode": conversation.capability_mode,
        },
        "metadata": {
            "runtime": "local",
            "capability_mode": conversation.capability_mode,
            "run": Value::Null,
            "environment": { "kind": "local", "label": "Local runtime" },
        },
        "conversation_mode": "workspace",
        "current_mode": conversation.current_mode,
        "workspace_id": conversation.workspace_id,
        "linked_workspace_task_id": Value::Null,
        "workspace_name": workspace.get("name").and_then(Value::as_str),
        "participant_agents": ["local-agent"],
        "coordinator_agent_id": "local-agent",
        "focused_agent_id": "local-agent",
    })
}

fn insert_conversation_record(
    connection: &Connection,
    conversation: &LocalConversation,
) -> Result<(), String> {
    let value_json = serde_json::to_string(conversation).map_err(|error| error.to_string())?;
    connection
        .execute(
            "INSERT INTO desktop_conversations(
               id, project_id, workspace_id, updated_at, value_json
             ) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![
                conversation.id,
                conversation.project_id,
                conversation.workspace_id,
                conversation.updated_at,
                value_json,
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

pub(super) fn required_string(value: &Value, key: &str) -> Result<String, String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .map(ToString::to_string)
        .ok_or_else(|| format!("missing required {key}"))
}

fn browser_origin_grant_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<BrowserOriginGrant> {
    let decision: String = row.get(2)?;
    Ok(BrowserOriginGrant {
        id: row.get(0)?,
        host: row.get(1)?,
        decision: BrowserOriginDecision::from_str(&decision).map_err(|error| {
            rusqlite::Error::FromSqlConversionFailure(
                decision.len(),
                rusqlite::types::Type::Text,
                Box::new(std::io::Error::new(std::io::ErrorKind::InvalidData, error)),
            )
        })?,
        source_hitl_request_id: row.get(3)?,
        created_at: row.get(4)?,
        revoked_at: row.get(5)?,
    })
}

fn browser_capability_grant_from_row(
    row: &rusqlite::Row<'_>,
) -> rusqlite::Result<BrowserCapabilityGrant> {
    let decision: String = row.get(3)?;
    Ok(BrowserCapabilityGrant {
        id: row.get(0)?,
        host: row.get(1)?,
        capability: row.get(2)?,
        decision: BrowserCapabilityDecision::from_str(&decision).map_err(|error| {
            rusqlite::Error::FromSqlConversionFailure(
                decision.len(),
                rusqlite::types::Type::Text,
                Box::new(std::io::Error::new(std::io::ErrorKind::InvalidData, error)),
            )
        })?,
        source_hitl_request_id: row.get(4)?,
        created_at: row.get(5)?,
        revoked_at: row.get(6)?,
    })
}

fn browser_site_credential_from_row(
    row: &rusqlite::Row<'_>,
) -> rusqlite::Result<BrowserSiteCredential> {
    Ok(BrowserSiteCredential {
        id: row.get(0)?,
        origin: row.get(1)?,
        username: row.get(2)?,
        credential_ref: row.get(3)?,
        created_at: row.get(4)?,
        revoked_at: row.get(5)?,
    })
}

fn browser_action_audit_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<BrowserActionAudit> {
    Ok(BrowserActionAudit {
        id: row.get(0)?,
        run_id: row.get(1)?,
        tool_name: row.get(2)?,
        origin: row.get(3)?,
        target_summary: row.get(4)?,
        outcome: row.get(5)?,
        latency_ms: row.get(6)?,
        created_at: row.get(7)?,
    })
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

fn timeline_page_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<(String, i64, i64)> {
    Ok((row.get(0)?, row.get(1)?, row.get(2)?))
}

fn timeline_page_rows<T>(
    rows: Result<rusqlite::MappedRows<'_, T>, rusqlite::Error>,
) -> Result<Vec<(Value, DesktopTimelineCursor)>, String>
where
    T: FnMut(&rusqlite::Row<'_>) -> rusqlite::Result<(String, i64, i64)>,
{
    rows.map_err(|error| error.to_string())?
        .map(|row| {
            let (value_json, time_us, counter) = row.map_err(|error| error.to_string())?;
            let mut value: Value =
                serde_json::from_str(&value_json).map_err(|error| error.to_string())?;
            let object = value
                .as_object_mut()
                .ok_or_else(|| "desktop timeline item must be a JSON object".to_string())?;
            object.insert("eventTimeUs".to_string(), json!(time_us));
            object.insert("eventCounter".to_string(), json!(counter));
            object.insert("event_time_us".to_string(), json!(time_us));
            object.insert("event_counter".to_string(), json!(counter));
            object.insert("time_us".to_string(), json!(time_us));
            object.insert("counter".to_string(), json!(counter));
            Ok((value, DesktopTimelineCursor { time_us, counter }))
        })
        .collect()
}

fn timeline_has_rows_before(
    connection: &Connection,
    conversation_id: &str,
    cursor: DesktopTimelineCursor,
) -> Result<bool, String> {
    connection
        .query_row(
            "WITH timeline_rows AS (
               SELECT COALESCE(
                        CAST(json_extract(value_json, '$.eventTimeUs') AS INTEGER),
                        CAST(json_extract(value_json, '$.event_time_us') AS INTEGER),
                        CAST(json_extract(value_json, '$.time_us') AS INTEGER),
                        position
                      ) AS cursor_time,
                      COALESCE(
                        CAST(json_extract(value_json, '$.eventCounter') AS INTEGER),
                        CAST(json_extract(value_json, '$.event_counter') AS INTEGER),
                        CAST(json_extract(value_json, '$.counter') AS INTEGER),
                        position
                      ) AS cursor_counter
               FROM desktop_timeline
               WHERE conversation_id = ?1
             )
             SELECT EXISTS(
               SELECT 1 FROM timeline_rows
               WHERE (cursor_time, cursor_counter) < (?2, ?3)
             )",
            params![conversation_id, cursor.time_us, cursor.counter],
            |row| row.get(0),
        )
        .map_err(|error| error.to_string())
}

fn timeline_has_cursor_collision(
    connection: &Connection,
    conversation_id: &str,
) -> Result<bool, String> {
    connection
        .query_row(
            "WITH timeline_rows AS (
               SELECT COALESCE(
                        CAST(json_extract(value_json, '$.eventTimeUs') AS INTEGER),
                        CAST(json_extract(value_json, '$.event_time_us') AS INTEGER),
                        CAST(json_extract(value_json, '$.time_us') AS INTEGER),
                        position
                      ) AS cursor_time,
                      COALESCE(
                        CAST(json_extract(value_json, '$.eventCounter') AS INTEGER),
                        CAST(json_extract(value_json, '$.event_counter') AS INTEGER),
                        CAST(json_extract(value_json, '$.counter') AS INTEGER),
                        position
                      ) AS cursor_counter
               FROM desktop_timeline
               WHERE conversation_id = ?1
             )
             SELECT EXISTS(
               SELECT 1
               FROM timeline_rows
               GROUP BY cursor_time, cursor_counter
               HAVING COUNT(*) > 1
             )",
            [conversation_id],
            |row| row.get(0),
        )
        .map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn local_trusted_session_reference_survives_reopen_and_can_be_cleared() {
        let path = std::env::temp_dir().join(format!(
            "agistack-local-trusted-session-{}.db",
            Uuid::new_v4()
        ));
        let record = r#"{"version":1,"credential":"local-session-reference"}"#;

        {
            let store = DesktopSessionStore::open(&path).expect("open local session store");
            store
                .save_local_trusted_session(record)
                .expect("save local trusted session reference");
            assert_eq!(
                store
                    .load_local_trusted_session()
                    .expect("load local trusted session reference"),
                Some(record.to_string())
            );
        }

        {
            let store = DesktopSessionStore::open(&path).expect("reopen local session store");
            assert_eq!(
                store
                    .load_local_trusted_session()
                    .expect("load reopened local trusted session reference"),
                Some(record.to_string())
            );
            store
                .clear_local_trusted_session()
                .expect("clear local trusted session reference");
            store
                .clear_local_trusted_session()
                .expect("clear missing local trusted session reference");
            assert_eq!(
                store
                    .load_local_trusted_session()
                    .expect("load cleared local trusted session reference"),
                None
            );
        }

        let _ = std::fs::remove_file(path);
    }

    fn task_session_snapshot(
        user_id: &str,
        sender_id: &str,
        tenant_id: &str,
        project_id: &str,
        suffix: &str,
    ) -> TaskSessionResponseSnapshot {
        let workspace_id = format!("workspace-{suffix}");
        TaskSessionResponseSnapshot {
            workspace: json!({
                "id": workspace_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "name": format!("Workspace {suffix}"),
            }),
            conversation: json!({
                "id": format!("conversation-{suffix}"),
                "user_id": user_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "workspace_id": workspace_id,
                "title": format!("Conversation {suffix}"),
                "current_mode": "plan",
            }),
            initial_message: json!({
                "id": format!("message-{suffix}"),
                "sender_id": sender_id,
                "workspace_id": workspace_id,
                "content": format!("Objective {suffix}"),
            }),
            policy: Value::Null,
            capability_version: default_task_session_capability_version(),
        }
    }

    fn insert_scoped_task_session_receipt(
        connection: &Connection,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        suffix: &str,
    ) {
        let response = task_session_snapshot(user_id, user_id, tenant_id, project_id, suffix);
        let workspace_id = required_string(&response.workspace, "id").expect("workspace id");
        let conversation_id =
            required_string(&response.conversation, "id").expect("conversation id");
        let message_id =
            required_string(&response.initial_message, "id").expect("initial message id");
        connection
            .execute(
                "INSERT INTO desktop_conversations(
                   id, project_id, workspace_id, updated_at, value_json
                 ) VALUES (?1, ?2, ?3, '2026-07-19T00:00:00Z', ?4)",
                params![
                    conversation_id,
                    project_id,
                    workspace_id,
                    serde_json::to_string(&response.conversation).expect("conversation json")
                ],
            )
            .expect("scoped conversation");
        connection
            .execute(
                "INSERT INTO desktop_new_task_sessions(
                   user_id, tenant_id, project_id, idempotency_key, payload_hash, workspace_id,
                   conversation_id, initial_message_id, response_json, created_at
                 ) VALUES (?1, ?2, ?3, 'shared-key', ?4, ?5, ?6, ?7, ?8, ?9)",
                params![
                    user_id,
                    tenant_id,
                    project_id,
                    format!("payload-{suffix}"),
                    workspace_id,
                    conversation_id,
                    message_id,
                    serde_json::to_string(&response).expect("response json"),
                    format!("2026-07-19T00:00:0{suffix}Z"),
                ],
            )
            .expect("scoped task session receipt");
    }

    #[test]
    fn task_session_receipt_primary_key_and_lookup_are_fully_scoped() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let connection = store.connection().expect("session store connection");
        let scopes = [
            ("user-a", "tenant-a", "project-a", "1"),
            ("user-b", "tenant-a", "project-a", "2"),
            ("user-a", "tenant-b", "project-a", "3"),
            ("user-a", "tenant-a", "project-b", "4"),
        ];
        for (user_id, tenant_id, project_id, suffix) in scopes {
            insert_scoped_task_session_receipt(&connection, user_id, tenant_id, project_id, suffix);
        }

        let columns = task_session_receipt_columns(&connection).expect("task session columns");
        let primary_key: Vec<_> = columns
            .iter()
            .filter(|column| column.primary_key_position > 0)
            .map(|column| (column.name.as_str(), column.primary_key_position))
            .collect();
        assert_eq!(
            primary_key,
            vec![
                ("user_id", 1),
                ("tenant_id", 2),
                ("project_id", 3),
                ("idempotency_key", 4),
            ]
        );
        for (user_id, tenant_id, project_id, suffix) in scopes {
            let receipt = query_task_session_receipt(
                &connection,
                user_id,
                tenant_id,
                project_id,
                "shared-key",
            )
            .expect("scoped receipt query")
            .expect("scoped receipt");
            assert_eq!(receipt.payload_hash, format!("payload-{suffix}"));
            validate_task_session_receipt(&receipt, user_id, tenant_id, project_id)
                .expect("valid scoped receipt");
        }
    }

    fn timeline_item(id: &str, time_us: i64, counter: i64) -> Value {
        json!({
            "id": id,
            "type": "assistant_message",
            "eventTimeUs": time_us,
            "eventCounter": counter,
        })
    }

    fn timeline_ids(page: &DesktopTimelinePage) -> Vec<&str> {
        page.items
            .iter()
            .map(|item| item["id"].as_str().expect("timeline item id"))
            .collect()
    }

    #[test]
    fn timeline_page_uses_exclusive_tuple_cursors_and_exact_has_more() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let conversation_id = "timeline-pagination";
        for item in [
            timeline_item("event-1", 100, 0),
            timeline_item("event-2", 200, 0),
            timeline_item("event-3", 300, 0),
            timeline_item("event-4", 400, 0),
            timeline_item("event-5", 400, 1),
        ] {
            store
                .append_timeline(conversation_id, &item)
                .expect("append timeline item");
        }

        let latest = store
            .timeline_page(conversation_id, 2, None, None)
            .expect("latest timeline page");
        assert_eq!(timeline_ids(&latest), vec!["event-4", "event-5"]);
        assert!(latest.has_more);
        assert_eq!(
            latest.first_cursor,
            Some(DesktopTimelineCursor {
                time_us: 400,
                counter: 0,
            })
        );
        assert_eq!(
            latest.last_cursor,
            Some(DesktopTimelineCursor {
                time_us: 400,
                counter: 1,
            })
        );

        let middle = store
            .timeline_page(
                conversation_id,
                2,
                Some(DesktopTimelineCursor {
                    time_us: 100,
                    counter: 0,
                }),
                latest.first_cursor,
            )
            .expect("middle timeline page");
        assert_eq!(timeline_ids(&middle), vec!["event-2", "event-3"]);
        assert!(middle.has_more);

        let oldest = store
            .timeline_page(conversation_id, 2, None, middle.first_cursor)
            .expect("oldest timeline page");
        assert_eq!(timeline_ids(&oldest), vec!["event-1"]);
        assert!(!oldest.has_more);

        let forward = store
            .timeline_page(
                conversation_id,
                2,
                Some(DesktopTimelineCursor {
                    time_us: 200,
                    counter: 0,
                }),
                None,
            )
            .expect("forward timeline page");
        assert_eq!(timeline_ids(&forward), vec!["event-3", "event-4"]);
        assert!(forward.has_more);

        assert!(store.timeline_page(conversation_id, 0, None, None).is_err());
        assert!(store
            .timeline_page(conversation_id, 501, None, None)
            .is_err());
    }

    #[test]
    fn timeline_page_assigns_unique_cursors_to_legacy_items_without_counters() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let conversation_id = "timeline-legacy-cursors";
        for id in ["event-1", "event-2", "event-3"] {
            store
                .append_timeline(
                    conversation_id,
                    &json!({
                        "id": id,
                        "type": "assistant_message",
                        "eventTimeUs": 100,
                    }),
                )
                .expect("append legacy timeline item");
        }

        let latest = store
            .timeline_page(conversation_id, 2, None, None)
            .expect("latest legacy timeline page");
        assert_eq!(timeline_ids(&latest), vec!["event-2", "event-3"]);
        assert_eq!(
            latest.first_cursor,
            Some(DesktopTimelineCursor {
                time_us: 100,
                counter: 2,
            })
        );
        assert!(latest.has_more);

        let oldest = store
            .timeline_page(conversation_id, 2, None, latest.first_cursor)
            .expect("oldest legacy timeline page");
        assert_eq!(timeline_ids(&oldest), vec!["event-1"]);
        assert!(!oldest.has_more);
    }

    #[test]
    fn timeline_page_rejects_explicit_duplicate_cursor_tuples() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let conversation_id = "timeline-duplicate-cursors";
        for id in ["event-1", "event-2"] {
            store
                .append_timeline(conversation_id, &timeline_item(id, 100, 0))
                .expect("append duplicate cursor tuple");
        }

        let error = store
            .timeline_page(conversation_id, 1, None, None)
            .expect_err("duplicate cursor tuples must fail closed");
        assert!(error.contains("duplicate cursors"));
    }

    #[test]
    fn hitl_response_commit_is_revision_guarded_and_idempotent() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let request = DesktopHitlRequest {
            id: "hitl-authority".to_string(),
            conversation_id: "conversation-authority".to_string(),
            run_id: None,
            round: 1,
            kind: agistack_core::agent::types::HitlKind::Clarification,
            prompt: "Choose an answer".to_string(),
            decision: None,
            a2ui_action: None,
            status: DesktopHitlStatus::Pending,
            authority_revision: 1,
            created_at: "2026-07-20T00:00:00Z".to_string(),
            responded_at: None,
            response_data: None,
            response_actor: None,
            response_revision: None,
            idempotency_key: None,
        };
        store.insert_hitl_request(&request).expect("insert HITL");

        let committed = store
            .mark_hitl_responded(
                &request.id,
                HitlResponseCommit {
                    expected_authority_revision: 1,
                    response_data: &json!({ "answer": "approved" }),
                    response_actor: "owner",
                    response_revision: None,
                    idempotency_key: "hitl-authority:1",
                    workspace_tool_grant: None,
                    now: "2026-07-20T00:00:01Z",
                },
            )
            .expect("commit response");
        assert!(matches!(
            committed,
            HitlResponseCommitOutcome::Committed(ref request)
                if request.authority_revision == 2
        ));

        let duplicate = store
            .mark_hitl_responded(
                &request.id,
                HitlResponseCommit {
                    expected_authority_revision: 1,
                    response_data: &json!({ "answer": "approved" }),
                    response_actor: "owner",
                    response_revision: None,
                    idempotency_key: "hitl-authority:1",
                    workspace_tool_grant: None,
                    now: "2026-07-20T00:00:02Z",
                },
            )
            .expect("replay response");
        assert!(matches!(
            duplicate,
            HitlResponseCommitOutcome::Duplicate(ref request)
                if request.authority_revision == 2
        ));

        let conflict = store
            .mark_hitl_responded(
                &request.id,
                HitlResponseCommit {
                    expected_authority_revision: 1,
                    response_data: &json!({ "answer": "denied" }),
                    response_actor: "owner",
                    response_revision: None,
                    idempotency_key: "hitl-authority:1",
                    workspace_tool_grant: None,
                    now: "2026-07-20T00:00:03Z",
                },
            )
            .expect_err("changed idempotent payload");
        assert!(matches!(
            conflict,
            HitlResponseCommitError::IdempotencyConflict {
                authority_revision: 2
            }
        ));
    }

    #[test]
    fn workspace_tool_grant_is_cross_conversation_revocable_and_survives_reopen() {
        let path = std::env::temp_dir().join(format!(
            "agistack-workspace-tool-grant-{}.db",
            Uuid::new_v4()
        ));
        let grant_id;
        {
            let store = DesktopSessionStore::open(&path).expect("session store");
            let connection = store.connection().expect("connection");
            for conversation_id in ["grant-conversation-a", "grant-conversation-b"] {
                connection
                    .execute(
                        "INSERT INTO desktop_conversations(
                           id, project_id, workspace_id, updated_at, value_json
                         ) VALUES (?1, 'project', 'workspace', '2026-07-20T00:00:00Z', '{}')",
                        [conversation_id],
                    )
                    .expect("insert conversation");
            }
            drop(connection);
            let request = DesktopHitlRequest {
                id: "grant-hitl".to_string(),
                conversation_id: "grant-conversation-a".to_string(),
                run_id: None,
                round: 1,
                kind: agistack_core::agent::types::HitlKind::Permission,
                prompt: "Allow write".to_string(),
                decision: None,
                a2ui_action: None,
                status: DesktopHitlStatus::Pending,
                authority_revision: 1,
                created_at: "2026-07-20T00:00:00Z".to_string(),
                responded_at: None,
                response_data: None,
                response_actor: None,
                response_revision: None,
                idempotency_key: None,
            };
            store.insert_hitl_request(&request).expect("insert HITL");
            let grant = WorkspaceToolGrant {
                id: format!("grant-{}", Uuid::new_v4()),
                workspace_id: "workspace".to_string(),
                canonical_tool_name: "write".to_string(),
                source_hitl_request_id: request.id.clone(),
                revision: 1,
                created_by: "owner".to_string(),
                created_at: "2026-07-20T00:00:01Z".to_string(),
                revoked_by: None,
                revoked_at: None,
            };
            grant_id = grant.id.clone();
            store
                .mark_hitl_responded(
                    &request.id,
                    HitlResponseCommit {
                        expected_authority_revision: 1,
                        response_data: &json!({
                            "action": "allow_always",
                            "granted": true,
                            "scope": "workspace_tool",
                        }),
                        response_actor: "owner",
                        response_revision: None,
                        idempotency_key: "grant-hitl:1",
                        workspace_tool_grant: Some(&grant),
                        now: "2026-07-20T00:00:01Z",
                    },
                )
                .expect("persist response and grant");
            assert!(store
                .workspace_tool_grant_active("grant-conversation-b", "write")
                .expect("cross-conversation grant"));
            assert!(!store
                .workspace_tool_grant_active("grant-conversation-b", "edit")
                .expect("different tool"));
        }
        {
            let store = DesktopSessionStore::open(&path).expect("reopen session store");
            assert!(store
                .workspace_tool_grant_active("grant-conversation-b", "write")
                .expect("reopened grant"));
            let revoked = store
                .revoke_workspace_tool_grant(
                    "workspace",
                    &grant_id,
                    "owner",
                    "2026-07-20T00:00:02Z",
                )
                .expect("revoke grant")
                .expect("active grant");
            assert_eq!(revoked.revision, 2);
            assert!(!store
                .workspace_tool_grant_active("grant-conversation-b", "write")
                .expect("revoked grant"));
        }
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn browser_origin_grants_supersede_revoke_and_survive_reopen() {
        let path = std::env::temp_dir().join(format!(
            "agistack-browser-origin-grant-{}.db",
            Uuid::new_v4()
        ));
        let grant = |id: &str, host: &str, decision: BrowserOriginDecision, created_at: &str| {
            BrowserOriginGrant {
                id: id.to_string(),
                host: host.to_string(),
                decision,
                source_hitl_request_id: "hitl-1".to_string(),
                created_at: created_at.to_string(),
                revoked_at: None,
            }
        };
        {
            let store = DesktopSessionStore::open(&path).expect("session store");
            store
                .insert_browser_origin_grant(&grant(
                    "grant-1",
                    "example.com",
                    BrowserOriginDecision::Site,
                    "2026-08-07T00:00:01Z",
                ))
                .expect("insert site grant");
            store
                .insert_browser_origin_grant(&grant(
                    "grant-2",
                    "*",
                    BrowserOriginDecision::Decline,
                    "2026-08-07T00:00:02Z",
                ))
                .expect("insert global decline");
            let decisions = store
                .active_browser_origin_decisions("example.com")
                .expect("decisions for host");
            assert_eq!(decisions.len(), 2);
            let decisions = store
                .active_browser_origin_decisions("other.test")
                .expect("decisions for other host");
            assert_eq!(decisions.len(), 1);
            assert_eq!(decisions[0].host, "*");

            // A newer decision for the same host supersedes the active one.
            store
                .insert_browser_origin_grant(&grant(
                    "grant-3",
                    "example.com",
                    BrowserOriginDecision::Decline,
                    "2026-08-07T00:00:03Z",
                ))
                .expect("supersede site grant");
            let decisions = store
                .active_browser_origin_decisions("example.com")
                .expect("decisions after supersede");
            assert_eq!(decisions.len(), 2);
            assert!(
                decisions
                    .iter()
                    .filter(|grant| grant.host == "example.com")
                    .all(|grant| grant.decision == BrowserOriginDecision::Decline),
                "superseded site grant must be revoked"
            );
        }
        {
            let store = DesktopSessionStore::open(&path).expect("reopen session store");
            let active = store
                .list_active_browser_origin_grants()
                .expect("list active grants");
            assert_eq!(active.len(), 2);
            assert!(active.iter().all(|grant| grant.revoked_at.is_none()));
            let revoked = store
                .revoke_browser_origin_grant("grant-3", "2026-08-07T00:00:04Z")
                .expect("revoke grant")
                .expect("active grant");
            assert_eq!(revoked.revoked_at.as_deref(), Some("2026-08-07T00:00:04Z"));
            assert!(store
                .revoke_browser_origin_grant("grant-3", "2026-08-07T00:00:05Z")
                .expect("second revoke")
                .is_none());
            let decisions = store
                .active_browser_origin_decisions("example.com")
                .expect("decisions after revoke");
            assert_eq!(decisions.len(), 1);
            assert_eq!(decisions[0].host, "*");
        }
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn browser_capability_grants_supersede_revoke_and_survive_reopen() {
        let path = std::env::temp_dir().join(format!(
            "agistack-browser-capability-grant-{}.db",
            Uuid::new_v4()
        ));
        let grant = |id: &str,
                     host: &str,
                     capability: &str,
                     decision: BrowserCapabilityDecision,
                     created_at: &str| {
            BrowserCapabilityGrant {
                id: id.to_string(),
                host: host.to_string(),
                capability: capability.to_string(),
                decision,
                source_hitl_request_id: "hitl-1".to_string(),
                created_at: created_at.to_string(),
                revoked_at: None,
            }
        };
        {
            let store = DesktopSessionStore::open(&path).expect("session store");
            store
                .insert_browser_capability_grant(&grant(
                    "cap-1",
                    "example.com",
                    "full_cdp",
                    BrowserCapabilityDecision::Site,
                    "2026-08-09T00:00:01Z",
                ))
                .expect("insert site grant");
            store
                .insert_browser_capability_grant(&grant(
                    "cap-2",
                    "other.test",
                    "full_cdp",
                    BrowserCapabilityDecision::Decline,
                    "2026-08-09T00:00:02Z",
                ))
                .expect("insert decline");
            let decisions = store
                .active_browser_capability_decisions("example.com", "full_cdp")
                .expect("decisions for host");
            assert_eq!(decisions.len(), 1);
            assert_eq!(decisions[0].decision, BrowserCapabilityDecision::Site);
            // Capability scoping is exact: other hosts/capabilities do not leak.
            assert!(store
                .active_browser_capability_decisions("example.com", "other_capability")
                .expect("decisions for other capability")
                .is_empty());

            // A newer decision for the same host+capability supersedes the
            // active one.
            store
                .insert_browser_capability_grant(&grant(
                    "cap-3",
                    "example.com",
                    "full_cdp",
                    BrowserCapabilityDecision::Decline,
                    "2026-08-09T00:00:03Z",
                ))
                .expect("supersede site grant");
            let decisions = store
                .active_browser_capability_decisions("example.com", "full_cdp")
                .expect("decisions after supersede");
            assert_eq!(decisions.len(), 1);
            assert_eq!(decisions[0].id, "cap-3");
            assert_eq!(decisions[0].decision, BrowserCapabilityDecision::Decline);
        }
        {
            let store = DesktopSessionStore::open(&path).expect("reopen session store");
            let active = store
                .list_active_browser_capability_grants()
                .expect("list active grants");
            assert_eq!(active.len(), 2);
            assert!(active.iter().all(|grant| grant.revoked_at.is_none()));
            let revoked = store
                .revoke_browser_capability_grant("cap-3", "2026-08-09T00:00:04Z")
                .expect("revoke grant")
                .expect("active grant");
            assert_eq!(revoked.revoked_at.as_deref(), Some("2026-08-09T00:00:04Z"));
            assert!(store
                .revoke_browser_capability_grant("cap-3", "2026-08-09T00:00:05Z")
                .expect("second revoke")
                .is_none());
            assert!(store
                .active_browser_capability_decisions("example.com", "full_cdp")
                .expect("decisions after revoke")
                .is_empty());
        }
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn browser_site_credentials_upsert_lookup_and_revoke() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let credential =
            |id: &str, origin: &str, username: &str, created_at: &str| BrowserSiteCredential {
                id: id.to_string(),
                origin: origin.to_string(),
                username: username.to_string(),
                credential_ref: format!("site-credential.v1.{id}"),
                created_at: created_at.to_string(),
                revoked_at: None,
            };
        store
            .upsert_browser_site_credential(&credential(
                "cred-1",
                "example.com",
                "alice",
                "2026-08-09T00:00:01Z",
            ))
            .expect("insert credential");
        store
            .upsert_browser_site_credential(&credential(
                "cred-2",
                "example.com",
                "bob",
                "2026-08-09T00:00:02Z",
            ))
            .expect("insert second credential");
        assert_eq!(
            store
                .list_active_browser_site_credentials()
                .expect("list credentials")
                .len(),
            2
        );

        // Upserting the same origin+username supersedes the previous row.
        store
            .upsert_browser_site_credential(&credential(
                "cred-3",
                "example.com",
                "alice",
                "2026-08-09T00:00:03Z",
            ))
            .expect("upsert credential");
        let active = store
            .list_active_browser_site_credentials()
            .expect("list after upsert");
        assert_eq!(active.len(), 2);
        let lookup = store
            .active_browser_site_credential("example.com", Some("alice"))
            .expect("lookup alice")
            .expect("active alice credential");
        assert_eq!(lookup.id, "cred-3");
        // No username filter: newest active row for the origin wins.
        let lookup = store
            .active_browser_site_credential("example.com", None)
            .expect("lookup latest")
            .expect("active credential");
        assert_eq!(lookup.id, "cred-3");
        assert!(store
            .active_browser_site_credential("unknown.test", None)
            .expect("lookup unknown")
            .is_none());

        let revoked = store
            .revoke_browser_site_credential("cred-3", "2026-08-09T00:00:04Z")
            .expect("revoke credential")
            .expect("active credential");
        assert_eq!(revoked.revoked_at.as_deref(), Some("2026-08-09T00:00:04Z"));
        assert!(store
            .active_browser_site_credential("example.com", Some("alice"))
            .expect("lookup revoked")
            .is_none());
        assert!(store
            .revoke_browser_site_credential("cred-3", "2026-08-09T00:00:05Z")
            .expect("second revoke")
            .is_none());
    }

    #[test]
    fn browser_action_audit_records_filters_and_sweeps_retention() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        for (tool, origin, outcome, created_at) in [
            ("browser_navigate", Some("example.com"), "ok", 1_000_i64),
            (
                "browser_click",
                Some("example.com"),
                "consent_required",
                2_000,
            ),
            ("browser_list_tabs", None, "ok", 3_000),
            ("browser_cdp_raw", Some("other.test"), "error", 4_000),
        ] {
            store
                .insert_browser_action_audit(
                    Some("run-1"),
                    tool,
                    origin,
                    "target",
                    outcome,
                    12,
                    created_at,
                )
                .expect("insert audit");
        }
        let entries = store
            .list_browser_action_audit(500, None)
            .expect("list audit");
        assert_eq!(entries.len(), 4);
        // Newest first.
        assert_eq!(entries[0].tool_name, "browser_cdp_raw");
        assert_eq!(entries[0].outcome, "error");
        assert_eq!(entries[0].latency_ms, 12);
        assert_eq!(entries[3].tool_name, "browser_navigate");

        let filtered = store
            .list_browser_action_audit(500, Some("example.com"))
            .expect("filtered audit");
        assert_eq!(filtered.len(), 2);
        assert!(filtered
            .iter()
            .all(|entry| entry.origin.as_deref() == Some("example.com")));

        let limited = store
            .list_browser_action_audit(1, None)
            .expect("limited audit");
        assert_eq!(limited.len(), 1);
        assert_eq!(limited[0].tool_name, "browser_cdp_raw");

        let deleted = store
            .delete_browser_action_audit_older_than(2_500)
            .expect("retention sweep");
        assert_eq!(deleted, 2);
        let remaining = store
            .list_browser_action_audit(500, None)
            .expect("list after sweep");
        assert_eq!(remaining.len(), 2);
        assert!(remaining.iter().all(|entry| entry.created_at >= 2_500));
    }

    #[test]
    fn workspace_core_terminal_callback_outbox_survives_store_reopen() {
        let path = std::env::temp_dir().join(format!(
            "desktop-workspace-core-outbox-{}.db",
            Uuid::new_v4()
        ));
        let callback = DesktopWorkspaceCoreTerminalCallback {
            id: "callback-1".to_string(),
            run_id: "provider-run-1".to_string(),
            sequence: 3,
            provider_bot_ref: "builtin:all-access".to_string(),
            payload: json!({
                "run_id": "provider-run-1",
                "payload": { "state": "final" }
            }),
            created_at: "2026-08-11T00:00:00Z".to_string(),
            attempt_count: 0,
            last_attempt_at: None,
            last_error: None,
        };
        {
            let store = DesktopSessionStore::open(&path).expect("open session store");
            store
                .enqueue_workspace_core_terminal_callback(&callback)
                .expect("enqueue callback");
            store
                .record_workspace_core_terminal_callback_failure(
                    &callback.id,
                    "2026-08-11T00:00:01Z",
                    "Core unavailable",
                )
                .expect("record failed delivery");
        }
        {
            let store = DesktopSessionStore::open(&path).expect("reopen session store");
            let pending = store
                .pending_workspace_core_terminal_callbacks(10)
                .expect("pending callbacks");
            assert_eq!(pending.len(), 1);
            assert_eq!(pending[0].attempt_count, 1);
            assert_eq!(pending[0].last_error.as_deref(), Some("Core unavailable"));
            assert_eq!(pending[0].payload, callback.payload);
            store
                .mark_workspace_core_terminal_callback_delivered(
                    &callback.id,
                    "2026-08-11T00:00:02Z",
                )
                .expect("mark callback delivered");
            assert!(store
                .pending_workspace_core_terminal_callbacks(10)
                .expect("drained callbacks")
                .is_empty());
        }
        {
            let store = DesktopSessionStore::open(&path).expect("reopen delivered store");
            assert!(store
                .pending_workspace_core_terminal_callbacks(10)
                .expect("persisted delivery marker")
                .is_empty());
        }
        let _ = std::fs::remove_file(path);
    }
}
