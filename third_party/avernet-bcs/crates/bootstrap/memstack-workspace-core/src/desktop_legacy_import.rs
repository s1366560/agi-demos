//! Fail-closed import of the Sidecar-owned legacy Desktop Workspace snapshot.

use std::collections::{BTreeMap, HashSet};
use std::path::Path;

use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbRow, DbStatement, DbTransactionStep, DbValue,
    db_get_column,
};
use chrono::DateTime;
use serde::Deserialize;
use serde_json::{Map, Value, json};
use sha2::{Digest as _, Sha256};
use thiserror::Error;
use uuid::Uuid;

const SNAPSHOT_SCHEMA_VERSION: u16 = 1;
const SNAPSHOT_SOURCE: &str = "desktop-session-store";
const MIGRATION_VERSION: &str = "desktop-workspace-import-v1";
const LOCAL_USER_ID: &str = "local-user";
const LOCAL_USER_EMAIL: &str = "local@desktop";
const LOCAL_USER_DISPLAY_NAME: &str = "Local Desktop";
const BCS_ENVIRONMENT: &str = "memstack";
const PUBLIC_MESSAGE_NAMESPACE: Uuid = Uuid::from_u128(0xd1a7_7201_0556_42d9_b6f8_636f_12a8_2c3f);

/// Desktop legacy import failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum DesktopLegacyImportError {
    #[error("failed to read Desktop legacy Workspace snapshot: {0}")]
    Read(#[source] std::io::Error),
    #[error("Desktop legacy Workspace snapshot JSON is invalid: {0}")]
    Json(#[source] serde_json::Error),
    #[error("Desktop legacy Workspace snapshot is invalid: {0}")]
    InvalidSnapshot(String),
    #[error(transparent)]
    Database(#[from] DbError),
}

/// Import one immutable Sidecar snapshot into the Desktop-local BCS authority.
///
/// First import checks every target for collisions and commits all projections in one
/// transaction. A retry for the same snapshot verifies the immutable migration ledger and target
/// anchors without comparing mutable Workspace Core state to the legacy snapshot. Historical
/// messages deliberately do not create outbox rows.
///
/// # Errors
///
/// Returns a validation error for any scope/hash/relationship mismatch, a fail-closed error for
/// partial or conflicting targets, or the original database failure.
pub async fn import_legacy_workspace_snapshot(
    db: &dyn DbPlugin,
    snapshot_path: &Path,
    expected_sha256: &str,
) -> Result<(), DesktopLegacyImportError> {
    validate_sha256("snapshot", expected_sha256)?;
    if !snapshot_path.is_absolute() {
        return Err(invalid("snapshot path must be absolute"));
    }
    let encoded = tokio::fs::read(snapshot_path)
        .await
        .map_err(DesktopLegacyImportError::Read)?;
    if hex_sha256(&encoded) != expected_sha256 {
        return Err(invalid("snapshot SHA-256 mismatch"));
    }
    let raw: LegacyWorkspaceSnapshot =
        serde_json::from_slice(&encoded).map_err(DesktopLegacyImportError::Json)?;
    let import = ValidatedImport::parse(raw, expected_sha256)?;
    let ledger_rows = ledger_rows(db, &import.migration_run_id).await?;
    if ledger_rows.is_empty() {
        ensure_targets_absent(db, &import).await?;
        db.transaction(import.transaction_steps()).await?;
        verify_import(db, &import).await?;
        return Ok(());
    }
    verify_ledger(&import, &ledger_rows)?;
    verify_import_anchors(db, &import).await
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LegacyWorkspaceSnapshot {
    schema_version: u16,
    source: String,
    workspace_count: usize,
    message_count: usize,
    workspaces: Vec<LegacyWorkspaceRecord>,
    messages: Vec<LegacyWorkspaceMessageRecord>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LegacyWorkspaceRecord {
    id: String,
    project_id: String,
    value: Value,
    source_hash: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LegacyWorkspaceMessageRecord {
    id: String,
    workspace_id: String,
    position: i64,
    value: Value,
    source_hash: String,
}

struct ValidatedImport {
    migration_run_id: String,
    workspaces: Vec<WorkspaceProjection>,
    messages: Vec<MessageProjection>,
    projects: BTreeMap<(String, String), ProjectProjection>,
}

#[derive(Clone)]
struct ProjectProjection {
    tenant_id: String,
    project_id: String,
    created_at: String,
    updated_at: String,
}

struct WorkspaceProjection {
    id: String,
    tenant_id: String,
    project_id: String,
    group_id: String,
    session_id: String,
    name: String,
    description: Option<String>,
    is_archived: bool,
    metadata_json: String,
    created_at: String,
    updated_at: String,
    source_hash: String,
    target_hash: String,
    current_msg_seq: i64,
}

struct MessageProjection {
    id: String,
    workspace_id: String,
    tenant_id: String,
    project_id: String,
    group_id: String,
    session_id: String,
    position: i64,
    sender_id: String,
    sender_type: String,
    content_json: String,
    mentions_json: String,
    parent_message_id: Option<String>,
    metadata_json: String,
    conversation_id: String,
    created_at_ms: i64,
    source_hash: String,
    target_hash: String,
}

impl ValidatedImport {
    fn parse(
        raw: LegacyWorkspaceSnapshot,
        snapshot_sha256: &str,
    ) -> Result<Self, DesktopLegacyImportError> {
        if raw.schema_version != SNAPSHOT_SCHEMA_VERSION || raw.source != SNAPSHOT_SOURCE {
            return Err(invalid("unsupported schemaVersion or source"));
        }
        if raw.workspace_count != raw.workspaces.len() || raw.message_count != raw.messages.len() {
            return Err(invalid(
                "declared record counts do not match snapshot arrays",
            ));
        }
        let mut workspace_ids = HashSet::with_capacity(raw.workspaces.len());
        let mut projects = BTreeMap::new();
        let mut workspaces = Vec::with_capacity(raw.workspaces.len());
        for record in raw.workspaces {
            validate_sha256("Workspace record", &record.source_hash)?;
            verify_source_hash(
                &record.source_hash,
                &json!({
                    "id": &record.id,
                    "project_id": &record.project_id,
                    "value": &record.value,
                }),
            )?;
            if !workspace_ids.insert(record.id.clone()) {
                return Err(invalid("duplicate Workspace id"));
            }
            let mut projection = WorkspaceProjection::parse(record)?;
            let key = (projection.tenant_id.clone(), projection.project_id.clone());
            projects
                .entry(key)
                .and_modify(|project: &mut ProjectProjection| {
                    if projection.created_at < project.created_at {
                        project.created_at.clone_from(&projection.created_at);
                    }
                    if projection.updated_at > project.updated_at {
                        project.updated_at.clone_from(&projection.updated_at);
                    }
                })
                .or_insert_with(|| ProjectProjection {
                    tenant_id: projection.tenant_id.clone(),
                    project_id: projection.project_id.clone(),
                    created_at: projection.created_at.clone(),
                    updated_at: projection.updated_at.clone(),
                });
            projection.target_hash.clear();
            workspaces.push(projection);
        }
        let workspace_scopes = workspaces
            .iter()
            .map(|workspace| {
                (
                    workspace.id.clone(),
                    (
                        workspace.tenant_id.clone(),
                        workspace.project_id.clone(),
                        workspace.group_id.clone(),
                        workspace.session_id.clone(),
                    ),
                )
            })
            .collect::<BTreeMap<_, _>>();
        let mut message_ids = HashSet::with_capacity(raw.messages.len());
        let mut message_positions = HashSet::with_capacity(raw.messages.len());
        let mut messages = Vec::with_capacity(raw.messages.len());
        for record in raw.messages {
            validate_sha256("Message record", &record.source_hash)?;
            verify_source_hash(
                &record.source_hash,
                &json!({
                    "id": &record.id,
                    "workspace_id": &record.workspace_id,
                    "position": record.position,
                    "value": &record.value,
                }),
            )?;
            if !message_ids.insert(record.id.clone())
                || !message_positions.insert((record.workspace_id.clone(), record.position))
            {
                return Err(invalid("duplicate Message id or Workspace position"));
            }
            let scope = workspace_scopes
                .get(&record.workspace_id)
                .ok_or_else(|| invalid("Message references a missing Workspace"))?;
            messages.push(MessageProjection::parse(record, scope)?);
        }
        for workspace in &mut workspaces {
            workspace.current_msg_seq = messages
                .iter()
                .filter(|message| message.workspace_id == workspace.id)
                .map(|message| message.position)
                .max()
                .unwrap_or(0);
            let project = projects
                .get(&(workspace.tenant_id.clone(), workspace.project_id.clone()))
                .ok_or_else(|| invalid("Workspace project projection is missing"))?;
            workspace.target_hash = source_hash(&workspace_target_value(workspace, project))?;
        }
        for message in &mut messages {
            message.target_hash = source_hash(&message_target_value(message))?;
        }
        Ok(Self {
            migration_run_id: format!("desktop-session-store:{snapshot_sha256}"),
            workspaces,
            messages,
            projects,
        })
    }

    fn transaction_steps(&self) -> Vec<DbTransactionStep> {
        let mut steps = Vec::with_capacity(
            self.projects.len() + self.workspaces.len() * 9 + self.messages.len() * 3,
        );
        for project in self.projects.values() {
            steps.push(checked(insert_project_membership(project)));
        }
        for workspace in &self.workspaces {
            steps.extend(workspace_steps(workspace));
            steps.push(checked(ledger_insert(
                &self.migration_run_id,
                &workspace.tenant_id,
                &workspace.project_id,
                Some(&workspace.id),
                "workspace",
                &workspace.id,
                "workspace_profiles",
                &workspace.id,
                &workspace.source_hash,
                &workspace.target_hash,
            )));
        }
        for message in &self.messages {
            steps.extend(message_steps(message));
            steps.push(checked(ledger_insert(
                &self.migration_run_id,
                &message.tenant_id,
                &message.project_id,
                Some(&message.workspace_id),
                "message",
                &message.id,
                "bcs_messages",
                &message.id,
                &message.source_hash,
                &message.target_hash,
            )));
        }
        steps
    }
}

impl WorkspaceProjection {
    fn parse(record: LegacyWorkspaceRecord) -> Result<Self, DesktopLegacyImportError> {
        let object = object(&record.value, "Workspace value")?;
        require_equal(object, "id", &record.id, "Workspace id")?;
        require_equal(
            object,
            "project_id",
            &record.project_id,
            "Workspace project id",
        )?;
        let tenant_id = required_string(object, "tenant_id", "Workspace")?;
        let name = required_string(object, "name", "Workspace")?;
        let description = optional_string(object, "description", "Workspace")?;
        let _status = required_string(object, "status", "Workspace")?;
        let created_at = required_timestamp(object, "created_at", "Workspace")?.0;
        let updated_at = required_timestamp(object, "updated_at", "Workspace")?.0;
        let is_archived = optional_bool(object, "is_archived", "Workspace")?.unwrap_or(false);
        let metadata = optional_object(object, "metadata", "Workspace")?;
        let metadata_json = metadata_with_legacy(
            metadata,
            json!({
                "source": SNAPSHOT_SOURCE,
                "source_hash": &record.source_hash,
                "status": object.get("status"),
                "collaboration_mode": object.get("collaboration_mode"),
                "use_case": object.get("use_case"),
                "sandbox_code_root": object.get("sandbox_code_root"),
            }),
        )?;
        Ok(Self {
            group_id: format!("group-{}", record.id),
            session_id: workspace_session_id(&tenant_id, &record.project_id, &record.id),
            id: record.id,
            tenant_id,
            project_id: record.project_id,
            name,
            description,
            is_archived,
            metadata_json,
            created_at,
            updated_at,
            source_hash: record.source_hash,
            target_hash: String::new(),
            current_msg_seq: 0,
        })
    }
}

impl MessageProjection {
    fn parse(
        record: LegacyWorkspaceMessageRecord,
        scope: &(String, String, String, String),
    ) -> Result<Self, DesktopLegacyImportError> {
        if record.position < 1 {
            return Err(invalid("Message position must be positive"));
        }
        let object = object(&record.value, "Message value")?;
        require_equal(object, "id", &record.id, "Message id")?;
        require_equal(
            object,
            "workspace_id",
            &record.workspace_id,
            "Message Workspace id",
        )?;
        let sender_id = required_string(object, "sender_id", "Message")?;
        let sender_type = required_string(object, "sender_type", "Message")?;
        let content = required_string(object, "content", "Message")?;
        let (created_at, created_at_ms) = required_timestamp(object, "created_at", "Message")?;
        let parent_message_id = optional_string(object, "parent_message_id", "Message")?;
        let mentions = required_array_of_strings(object, "mentions", "Message")?;
        let metadata = optional_object(object, "metadata", "Message")?;
        let conversation_id = metadata
            .get("conversation_id")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or(&scope.3)
            .to_string();
        let metadata_json = metadata_with_legacy(
            metadata,
            json!({
                "source": SNAPSHOT_SOURCE,
                "source_hash": &record.source_hash,
                "created_at": created_at,
                "position": record.position,
            }),
        )?;
        Ok(Self {
            id: record.id,
            workspace_id: record.workspace_id,
            tenant_id: scope.0.clone(),
            project_id: scope.1.clone(),
            group_id: scope.2.clone(),
            session_id: scope.3.clone(),
            position: record.position,
            sender_id,
            sender_type,
            content_json: serde_json::to_string(&content)
                .map_err(DesktopLegacyImportError::Json)?,
            mentions_json: serde_json::to_string(&mentions)
                .map_err(DesktopLegacyImportError::Json)?,
            parent_message_id,
            metadata_json,
            conversation_id,
            created_at_ms,
            source_hash: record.source_hash,
            target_hash: String::new(),
        })
    }
}

fn workspace_steps(workspace: &WorkspaceProjection) -> Vec<DbTransactionStep> {
    vec![
        checked(insert_group(workspace)),
        checked(insert_profile(workspace)),
        checked(insert_member(workspace)),
        checked(insert_identity(workspace)),
        checked(insert_group_participant(workspace)),
        checked(insert_authority(workspace)),
        checked(insert_session(workspace)),
    ]
}

fn message_steps(message: &MessageProjection) -> Vec<DbTransactionStep> {
    vec![
        checked(insert_message(message)),
        checked(insert_message_correlation(message)),
    ]
}

fn checked(statement: DbStatement) -> DbTransactionStep {
    DbTransactionStep::execute_checked(statement, DbCountExpectation::exactly(1))
}

fn statement(sql: &str, params: Vec<DbValue>) -> DbStatement {
    DbStatement::with_params(sql, params)
}

fn insert_project_membership(project: &ProjectProjection) -> DbStatement {
    statement(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, \
         participant_actor_id, source_membership_id, role, permissions_json, is_active, \
         identity_authority, source_created_at, source_updated_at) VALUES (?, ?, ?, ?, ?, \
         'owner', '{}', ?, 'desktop-local', ?, ?)",
        vec![
            project.tenant_id.as_str().into(),
            project.project_id.as_str().into(),
            LOCAL_USER_ID.into(),
            LOCAL_USER_ID.into(),
            format!(
                "local-project-membership:{}:{}",
                project.tenant_id, project.project_id
            )
            .into(),
            true.into(),
            project.created_at.as_str().into(),
            project.updated_at.as_str().into(),
        ],
    )
}

fn insert_group(workspace: &WorkspaceProjection) -> DbStatement {
    statement(
        "INSERT INTO bcs_groups (group_id, label, status, driver_bot, originator, env, context, \
         created_by, visibility) VALUES (?, ?, 'active', ?, ?, ?, ?, ?, 'private')",
        vec![
            workspace.group_id.as_str().into(),
            workspace.name.as_str().into(),
            LOCAL_USER_ID.into(),
            LOCAL_USER_ID.into(),
            BCS_ENVIRONMENT.into(),
            workspace.description.as_deref().into(),
            LOCAL_USER_ID.into(),
        ],
    )
}

fn insert_profile(workspace: &WorkspaceProjection) -> DbStatement {
    statement(
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, \
         description, created_by, is_archived, metadata_json, source_hash, created_at, updated_at) \
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        vec![
            workspace.id.as_str().into(),
            workspace.tenant_id.as_str().into(),
            workspace.project_id.as_str().into(),
            workspace.group_id.as_str().into(),
            workspace.name.as_str().into(),
            workspace.description.as_deref().into(),
            LOCAL_USER_ID.into(),
            workspace.is_archived.into(),
            workspace.metadata_json.as_str().into(),
            workspace.source_hash.as_str().into(),
            workspace.created_at.as_str().into(),
            workspace.updated_at.as_str().into(),
        ],
    )
}

fn insert_member(workspace: &WorkspaceProjection) -> DbStatement {
    statement(
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, \
         participant_actor_id, role, invited_by, created_at, updated_at) \
         VALUES (?, ?, ?, ?, ?, ?, 'owner', ?, ?, ?)",
        vec![
            format!("local-membership:{}:{LOCAL_USER_ID}", workspace.id).into(),
            workspace.tenant_id.as_str().into(),
            workspace.project_id.as_str().into(),
            workspace.id.as_str().into(),
            LOCAL_USER_ID.into(),
            LOCAL_USER_ID.into(),
            LOCAL_USER_ID.into(),
            workspace.created_at.as_str().into(),
            workspace.updated_at.as_str().into(),
        ],
    )
}

fn insert_identity(workspace: &WorkspaceProjection) -> DbStatement {
    statement(
        "INSERT INTO workspace_principal_identities (tenant_id, project_id, workspace_id, \
         user_id, participant_actor_id, email, display_name, is_active, identity_authority, \
         source_created_at, source_updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, \
         'desktop-local', ?, ?)",
        vec![
            workspace.tenant_id.as_str().into(),
            workspace.project_id.as_str().into(),
            workspace.id.as_str().into(),
            LOCAL_USER_ID.into(),
            LOCAL_USER_ID.into(),
            LOCAL_USER_EMAIL.into(),
            LOCAL_USER_DISPLAY_NAME.into(),
            true.into(),
            workspace.created_at.as_str().into(),
            workspace.updated_at.as_str().into(),
        ],
    )
}

fn insert_group_participant(workspace: &WorkspaceProjection) -> DbStatement {
    statement(
        "INSERT INTO bcs_group_participants (group_id, bot_uuid, role, env, actor_kind, mode) \
         VALUES (?, ?, 'owner', ?, 'human', 'auto')",
        vec![
            workspace.group_id.as_str().into(),
            LOCAL_USER_ID.into(),
            BCS_ENVIRONMENT.into(),
        ],
    )
}

fn insert_authority(workspace: &WorkspaceProjection) -> DbStatement {
    statement(
        "INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id, revision) \
         VALUES (?, ?, ?, 1)",
        vec![
            workspace.id.as_str().into(),
            workspace.tenant_id.as_str().into(),
            workspace.project_id.as_str().into(),
        ],
    )
}

fn insert_session(workspace: &WorkspaceProjection) -> DbStatement {
    statement(
        "INSERT INTO bcs_group_sessions (session_id, group_id, env, status, session_kind, \
         session_title, caller_id, caller_principal, created_by, participants, current_msg_seq, \
         meta) VALUES (?, ?, ?, 'running', 'chat', ?, ?, ?, ?, ?, ?, ?)",
        vec![
            workspace.session_id.as_str().into(),
            workspace.group_id.as_str().into(),
            BCS_ENVIRONMENT.into(),
            workspace.name.as_str().into(),
            LOCAL_USER_ID.into(),
            LOCAL_USER_ID.into(),
            LOCAL_USER_ID.into(),
            "[\"local-user\"]".into(),
            workspace.current_msg_seq.into(),
            "{\"authority\":\"desktop-legacy-import\"}".into(),
        ],
    )
}

fn insert_message(message: &MessageProjection) -> DbStatement {
    statement(
        "INSERT INTO bcs_messages (message_id, group_id, session_id, session_seq, env, sender_id, \
         sender_type, message_type, content, status, created_at, run_id, workspace_id, \
         mentions_json, parent_message_id, metadata_json, source_hash) \
         VALUES (?, ?, ?, ?, ?, ?, ?, 'workspace_chat', ?, 'normal', ?, '', ?, ?, ?, ?, ?)",
        vec![
            message.id.as_str().into(),
            message.group_id.as_str().into(),
            message.session_id.as_str().into(),
            message.position.into(),
            BCS_ENVIRONMENT.into(),
            message.sender_id.as_str().into(),
            message.sender_type.as_str().into(),
            message.content_json.as_str().into(),
            message.created_at_ms.into(),
            message.workspace_id.as_str().into(),
            message.mentions_json.as_str().into(),
            message.parent_message_id.as_deref().into(),
            message.metadata_json.as_str().into(),
            message.source_hash.as_str().into(),
        ],
    )
}

fn insert_message_correlation(message: &MessageProjection) -> DbStatement {
    statement(
        "INSERT INTO workspace_message_correlations (correlation_id, tenant_id, project_id, \
         workspace_id, legacy_message_id, conversation_id, bcs_session_id, bcs_message_id, \
         message_kind, is_terminal) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'workspace_chat', 0)",
        vec![
            format!("legacy-correlation:{}", message.id).into(),
            message.tenant_id.as_str().into(),
            message.project_id.as_str().into(),
            message.workspace_id.as_str().into(),
            message.id.as_str().into(),
            message.conversation_id.as_str().into(),
            message.session_id.as_str().into(),
            message.id.as_str().into(),
        ],
    )
}

#[allow(clippy::too_many_arguments)]
fn ledger_insert(
    migration_run_id: &str,
    tenant_id: &str,
    project_id: &str,
    workspace_id: Option<&str>,
    entity_type: &str,
    source_id: &str,
    target_table: &str,
    target_id: &str,
    source_hash: &str,
    target_hash: &str,
) -> DbStatement {
    statement(
        "INSERT INTO workspace_migration_ledger (migration_run_id, migration_version, tenant_id, \
         project_id, workspace_id, entity_type, source_id, target_table, target_id, source_hash, \
         target_hash, status, attempt_count, migrated_at, verified_at) \
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'verified', 1, CURRENT_TIMESTAMP, \
         CURRENT_TIMESTAMP)",
        vec![
            migration_run_id.into(),
            MIGRATION_VERSION.into(),
            tenant_id.into(),
            project_id.into(),
            workspace_id.into(),
            entity_type.into(),
            source_id.into(),
            target_table.into(),
            target_id.into(),
            source_hash.into(),
            target_hash.into(),
        ],
    )
}

async fn ledger_rows(
    db: &dyn DbPlugin,
    migration_run_id: &str,
) -> Result<Vec<DbRow>, DesktopLegacyImportError> {
    Ok(db
        .query(statement(
            "SELECT migration_version, tenant_id, project_id, workspace_id, entity_type, \
             source_id, target_table, target_id, source_hash, target_hash, status \
             FROM workspace_migration_ledger WHERE migration_run_id = ? \
             ORDER BY entity_type, source_id",
            vec![migration_run_id.into()],
        ))
        .await?)
}

fn verify_ledger(import: &ValidatedImport, rows: &[DbRow]) -> Result<(), DesktopLegacyImportError> {
    let expected_count = import.workspaces.len() + import.messages.len();
    if rows.len() != expected_count {
        return Err(invalid("partial migration ledger detected"));
    }
    let expected = import
        .workspaces
        .iter()
        .map(|workspace| {
            (
                ("workspace", workspace.id.as_str()),
                (
                    workspace.tenant_id.as_str(),
                    workspace.project_id.as_str(),
                    workspace.id.as_str(),
                    "workspace_profiles",
                    workspace.source_hash.as_str(),
                    workspace.target_hash.as_str(),
                ),
            )
        })
        .chain(import.messages.iter().map(|message| {
            (
                ("message", message.id.as_str()),
                (
                    message.tenant_id.as_str(),
                    message.project_id.as_str(),
                    message.workspace_id.as_str(),
                    "bcs_messages",
                    message.source_hash.as_str(),
                    message.target_hash.as_str(),
                ),
            )
        }))
        .collect::<BTreeMap<_, _>>();
    for row in rows {
        let entity_type = db_get_column::<String>(row, "entity_type")?;
        let source_id = db_get_column::<String>(row, "source_id")?;
        let Some(expected) = expected.get(&(entity_type.as_str(), source_id.as_str())) else {
            return Err(invalid("migration ledger contains an unexpected source"));
        };
        let actual = (
            db_get_column::<String>(row, "tenant_id")?,
            db_get_column::<String>(row, "project_id")?,
            db_get_column::<String>(row, "workspace_id")?,
            db_get_column::<String>(row, "target_table")?,
            db_get_column::<String>(row, "target_id")?,
            db_get_column::<String>(row, "source_hash")?,
            db_get_column::<String>(row, "target_hash")?,
            db_get_column::<String>(row, "migration_version")?,
            db_get_column::<String>(row, "status")?,
        );
        if actual
            != (
                expected.0.to_string(),
                expected.1.to_string(),
                expected.2.to_string(),
                expected.3.to_string(),
                source_id.clone(),
                expected.4.to_string(),
                expected.5.to_string(),
                MIGRATION_VERSION.to_string(),
                "verified".to_string(),
            )
        {
            return Err(invalid("migration ledger content mismatch"));
        }
    }
    Ok(())
}

async fn ensure_targets_absent(
    db: &dyn DbPlugin,
    import: &ValidatedImport,
) -> Result<(), DesktopLegacyImportError> {
    for project in import.projects.values() {
        ensure_absent(
            db,
            "project_principal_memberships",
            statement(
                "SELECT 1 AS present FROM project_principal_memberships WHERE tenant_id = ? \
                 AND project_id = ? AND user_id = ?",
                vec![
                    project.tenant_id.as_str().into(),
                    project.project_id.as_str().into(),
                    LOCAL_USER_ID.into(),
                ],
            ),
        )
        .await?;
    }
    for workspace in &import.workspaces {
        for (target, query) in workspace_collision_queries(workspace) {
            ensure_absent(db, target, query).await?;
        }
    }
    for message in &import.messages {
        for (target, query) in message_collision_queries(message) {
            ensure_absent(db, target, query).await?;
        }
    }
    Ok(())
}

async fn ensure_absent(
    db: &dyn DbPlugin,
    target: &str,
    query: DbStatement,
) -> Result<(), DesktopLegacyImportError> {
    if !db.query(query).await?.is_empty() {
        return Err(invalid(format!("target collision in {target}")));
    }
    Ok(())
}

fn workspace_collision_queries(
    workspace: &WorkspaceProjection,
) -> Vec<(&'static str, DbStatement)> {
    vec![
        (
            "bcs_groups",
            by_value("bcs_groups", "group_id", &workspace.group_id),
        ),
        (
            "workspace_profiles",
            by_value("workspace_profiles", "workspace_id", &workspace.id),
        ),
        (
            "workspace_members",
            by_value("workspace_members", "workspace_id", &workspace.id),
        ),
        (
            "workspace_principal_identities",
            by_value(
                "workspace_principal_identities",
                "workspace_id",
                &workspace.id,
            ),
        ),
        (
            "bcs_group_participants",
            by_value("bcs_group_participants", "group_id", &workspace.group_id),
        ),
        (
            "workspace_authorities",
            by_value("workspace_authorities", "workspace_id", &workspace.id),
        ),
        (
            "bcs_group_sessions",
            by_value("bcs_group_sessions", "session_id", &workspace.session_id),
        ),
    ]
}

fn message_collision_queries(message: &MessageProjection) -> Vec<(&'static str, DbStatement)> {
    vec![
        (
            "bcs_messages",
            by_value("bcs_messages", "message_id", &message.id),
        ),
        (
            "workspace_message_correlations",
            by_value(
                "workspace_message_correlations",
                "legacy_message_id",
                &message.id,
            ),
        ),
    ]
}

fn by_value(table: &str, column: &str, value: &str) -> DbStatement {
    statement(
        &format!("SELECT 1 AS present FROM {table} WHERE {column} = ? LIMIT 1"),
        vec![value.into()],
    )
}

async fn verify_import(
    db: &dyn DbPlugin,
    import: &ValidatedImport,
) -> Result<(), DesktopLegacyImportError> {
    for project in import.projects.values() {
        verify_project_membership(db, project).await?;
    }
    for workspace in &import.workspaces {
        let project = import
            .projects
            .get(&(workspace.tenant_id.clone(), workspace.project_id.clone()))
            .ok_or_else(|| invalid("Workspace project projection is missing"))?;
        let actual = workspace_target_from_db(db, workspace, project).await?;
        if source_hash(&actual)? != workspace.target_hash {
            return Err(invalid("verified import target mismatch for Workspace"));
        }
    }
    for message in &import.messages {
        let actual = message_target_from_db(db, message).await?;
        if source_hash(&actual)? != message.target_hash {
            return Err(invalid("verified import target mismatch for Message"));
        }
    }
    Ok(())
}

async fn verify_import_anchors(
    db: &dyn DbPlugin,
    import: &ValidatedImport,
) -> Result<(), DesktopLegacyImportError> {
    for workspace in &import.workspaces {
        for (target, query) in workspace_import_anchor_queries(workspace) {
            query_one(db, query, target).await?;
        }
    }
    for message in &import.messages {
        for (target, query) in message_import_anchor_queries(message) {
            query_one(db, query, target).await?;
        }
    }
    Ok(())
}

fn workspace_import_anchor_queries(
    workspace: &WorkspaceProjection,
) -> Vec<(&'static str, DbStatement)> {
    vec![
        (
            "bcs_groups",
            statement(
                "SELECT 1 AS present FROM bcs_groups WHERE group_id = ?",
                vec![workspace.group_id.as_str().into()],
            ),
        ),
        (
            "workspace_profiles",
            statement(
                "SELECT 1 AS present FROM workspace_profiles WHERE workspace_id = ? \
                 AND tenant_id = ? AND project_id = ? AND group_id = ? AND source_hash = ?",
                vec![
                    workspace.id.as_str().into(),
                    workspace.tenant_id.as_str().into(),
                    workspace.project_id.as_str().into(),
                    workspace.group_id.as_str().into(),
                    workspace.source_hash.as_str().into(),
                ],
            ),
        ),
        (
            "workspace_authorities",
            statement(
                "SELECT 1 AS present FROM workspace_authorities WHERE workspace_id = ? \
                 AND tenant_id = ? AND project_id = ?",
                vec![
                    workspace.id.as_str().into(),
                    workspace.tenant_id.as_str().into(),
                    workspace.project_id.as_str().into(),
                ],
            ),
        ),
        (
            "bcs_group_sessions",
            statement(
                "SELECT 1 AS present FROM bcs_group_sessions WHERE session_id = ? \
                 AND group_id = ? AND env = ?",
                vec![
                    workspace.session_id.as_str().into(),
                    workspace.group_id.as_str().into(),
                    BCS_ENVIRONMENT.into(),
                ],
            ),
        ),
    ]
}

fn message_import_anchor_queries(message: &MessageProjection) -> Vec<(&'static str, DbStatement)> {
    vec![
        (
            "bcs_messages",
            statement(
                "SELECT 1 AS present FROM bcs_messages WHERE message_id = ? \
                 AND workspace_id = ? AND source_hash = ?",
                vec![
                    message.id.as_str().into(),
                    message.workspace_id.as_str().into(),
                    message.source_hash.as_str().into(),
                ],
            ),
        ),
        (
            "workspace_message_correlations",
            statement(
                "SELECT 1 AS present FROM workspace_message_correlations \
                 WHERE legacy_message_id = ? AND workspace_id = ? AND bcs_message_id = ?",
                vec![
                    message.id.as_str().into(),
                    message.workspace_id.as_str().into(),
                    message.id.as_str().into(),
                ],
            ),
        ),
    ]
}

async fn verify_project_membership(
    db: &dyn DbPlugin,
    project: &ProjectProjection,
) -> Result<(), DesktopLegacyImportError> {
    let row = query_one(
        db,
        statement(
            "SELECT tenant_id, project_id, user_id, participant_actor_id, role, is_active \
             FROM project_principal_memberships WHERE tenant_id = ? AND project_id = ? \
             AND user_id = ?",
            vec![
                project.tenant_id.as_str().into(),
                project.project_id.as_str().into(),
                LOCAL_USER_ID.into(),
            ],
        ),
        "project_principal_memberships",
    )
    .await?;
    let actual = row_value(
        &row,
        &[
            "tenant_id",
            "project_id",
            "user_id",
            "participant_actor_id",
            "role",
            "is_active",
        ],
    )?;
    let expected = json!({
        "tenant_id": project.tenant_id,
        "project_id": project.project_id,
        "user_id": LOCAL_USER_ID,
        "participant_actor_id": LOCAL_USER_ID,
        "role": "owner",
        "is_active": true,
    });
    if actual != expected {
        return Err(invalid(
            "verified import target mismatch in project_principal_memberships",
        ));
    }
    Ok(())
}

fn workspace_target_value(workspace: &WorkspaceProjection, project: &ProjectProjection) -> Value {
    json!({
        "group": {
            "group_id": workspace.group_id,
            "label": workspace.name,
            "status": "active",
            "driver_bot": LOCAL_USER_ID,
            "originator": LOCAL_USER_ID,
            "env": BCS_ENVIRONMENT,
            "context": workspace.description,
            "created_by": LOCAL_USER_ID,
            "visibility": "private",
        },
        "profile": {
            "workspace_id": workspace.id,
            "tenant_id": workspace.tenant_id,
            "project_id": workspace.project_id,
            "group_id": workspace.group_id,
            "name": workspace.name,
            "description": workspace.description,
            "created_by": LOCAL_USER_ID,
            "is_archived": workspace.is_archived,
            "metadata_json": workspace.metadata_json,
            "source_hash": workspace.source_hash,
            "created_at": workspace.created_at,
            "updated_at": workspace.updated_at,
        },
        "member": {
            "member_id": format!("local-membership:{}:{LOCAL_USER_ID}", workspace.id),
            "tenant_id": workspace.tenant_id,
            "project_id": workspace.project_id,
            "workspace_id": workspace.id,
            "user_id": LOCAL_USER_ID,
            "participant_actor_id": LOCAL_USER_ID,
            "role": "owner",
            "invited_by": LOCAL_USER_ID,
            "created_at": workspace.created_at,
            "updated_at": workspace.updated_at,
        },
        "identity": {
            "tenant_id": workspace.tenant_id,
            "project_id": workspace.project_id,
            "workspace_id": workspace.id,
            "user_id": LOCAL_USER_ID,
            "participant_actor_id": LOCAL_USER_ID,
            "email": LOCAL_USER_EMAIL,
            "display_name": LOCAL_USER_DISPLAY_NAME,
            "is_active": true,
            "identity_authority": "desktop-local",
            "source_created_at": workspace.created_at,
            "source_updated_at": workspace.updated_at,
        },
        "project_membership": project_membership_target_value(project),
        "participant": {
            "group_id": workspace.group_id,
            "bot_uuid": LOCAL_USER_ID,
            "role": "owner",
            "env": BCS_ENVIRONMENT,
            "actor_kind": "human",
            "mode": "auto",
        },
        "authority": {
            "workspace_id": workspace.id,
            "tenant_id": workspace.tenant_id,
            "project_id": workspace.project_id,
            "revision": 1,
        },
        "session": {
            "session_id": workspace.session_id,
            "group_id": workspace.group_id,
            "env": BCS_ENVIRONMENT,
            "status": "running",
            "session_kind": "chat",
            "session_title": workspace.name,
            "caller_id": LOCAL_USER_ID,
            "caller_principal": LOCAL_USER_ID,
            "created_by": LOCAL_USER_ID,
            "participants": "[\"local-user\"]",
            "current_msg_seq": workspace.current_msg_seq,
            "meta": "{\"authority\":\"desktop-legacy-import\"}",
        },
    })
}

fn project_membership_target_value(project: &ProjectProjection) -> Value {
    json!({
        "tenant_id": project.tenant_id,
        "project_id": project.project_id,
        "user_id": LOCAL_USER_ID,
        "participant_actor_id": LOCAL_USER_ID,
        "source_membership_id": format!(
            "local-project-membership:{}:{}",
            project.tenant_id, project.project_id
        ),
        "role": "owner",
        "permissions_json": "{}",
        "is_active": true,
        "identity_authority": "desktop-local",
        "source_created_at": project.created_at,
        "source_updated_at": project.updated_at,
    })
}

fn message_target_value(message: &MessageProjection) -> Value {
    json!({
        "message": {
            "message_id": message.id,
            "group_id": message.group_id,
            "session_id": message.session_id,
            "session_seq": message.position,
            "env": BCS_ENVIRONMENT,
            "sender_id": message.sender_id,
            "sender_type": message.sender_type,
            "message_type": "workspace_chat",
            "content": message.content_json,
            "status": "normal",
            "created_at": message.created_at_ms,
            "run_id": "",
            "workspace_id": message.workspace_id,
            "mentions_json": message.mentions_json,
            "parent_message_id": message.parent_message_id,
            "metadata_json": message.metadata_json,
            "source_hash": message.source_hash,
        },
        "correlation": {
            "correlation_id": format!("legacy-correlation:{}", message.id),
            "tenant_id": message.tenant_id,
            "project_id": message.project_id,
            "workspace_id": message.workspace_id,
            "legacy_message_id": message.id,
            "conversation_id": message.conversation_id,
            "bcs_session_id": message.session_id,
            "bcs_message_id": message.id,
            "message_kind": "workspace_chat",
            "is_terminal": false,
        },
    })
}

async fn workspace_target_from_db(
    db: &dyn DbPlugin,
    workspace: &WorkspaceProjection,
    project: &ProjectProjection,
) -> Result<Value, DesktopLegacyImportError> {
    let group = one(db, "bcs_groups", by_value("bcs_groups", "group_id", &workspace.group_id), "SELECT group_id, label, status, driver_bot, originator, env, context, created_by, visibility FROM bcs_groups WHERE group_id = ?", &workspace.group_id).await?;
    let profile = one(db, "workspace_profiles", by_value("workspace_profiles", "workspace_id", &workspace.id), "SELECT workspace_id, tenant_id, project_id, group_id, name, description, created_by, is_archived, metadata_json, source_hash, created_at, updated_at FROM workspace_profiles WHERE workspace_id = ?", &workspace.id).await?;
    let member = one(db, "workspace_members", by_value("workspace_members", "workspace_id", &workspace.id), "SELECT member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role, invited_by, created_at, updated_at FROM workspace_members WHERE workspace_id = ?", &workspace.id).await?;
    let identity = one(db, "workspace_principal_identities", by_value("workspace_principal_identities", "workspace_id", &workspace.id), "SELECT tenant_id, project_id, workspace_id, user_id, participant_actor_id, email, display_name, is_active, identity_authority, source_created_at, source_updated_at FROM workspace_principal_identities WHERE workspace_id = ?", &workspace.id).await?;
    let participant = query_one(db, statement("SELECT group_id, bot_uuid, role, env, actor_kind, mode FROM bcs_group_participants WHERE group_id = ? AND bot_uuid = ? AND env = ?", vec![workspace.group_id.as_str().into(), LOCAL_USER_ID.into(), BCS_ENVIRONMENT.into()]), "bcs_group_participants").await?;
    let authority = query_one(db, statement("SELECT workspace_id, tenant_id, project_id, revision FROM workspace_authorities WHERE workspace_id = ?", vec![workspace.id.as_str().into()]), "workspace_authorities").await?;
    let session = query_one(db, statement("SELECT session_id, group_id, env, status, session_kind, session_title, caller_id, caller_principal, created_by, participants, current_msg_seq, meta FROM bcs_group_sessions WHERE session_id = ? AND env = ?", vec![workspace.session_id.as_str().into(), BCS_ENVIRONMENT.into()]), "bcs_group_sessions").await?;
    Ok(json!({
        "group": row_value(&group, &["group_id", "label", "status", "driver_bot", "originator", "env", "context", "created_by", "visibility"])?,
        "profile": row_value(&profile, &["workspace_id", "tenant_id", "project_id", "group_id", "name", "description", "created_by", "is_archived", "metadata_json", "source_hash", "created_at", "updated_at"])?,
        "member": row_value(&member, &["member_id", "tenant_id", "project_id", "workspace_id", "user_id", "participant_actor_id", "role", "invited_by", "created_at", "updated_at"])?,
        "identity": row_value(&identity, &["tenant_id", "project_id", "workspace_id", "user_id", "participant_actor_id", "email", "display_name", "is_active", "identity_authority", "source_created_at", "source_updated_at"])?,
        "project_membership": project_membership_target_value(project),
        "participant": row_value(&participant, &["group_id", "bot_uuid", "role", "env", "actor_kind", "mode"])?,
        "authority": row_value(&authority, &["workspace_id", "tenant_id", "project_id", "revision"])?,
        "session": row_value(&session, &["session_id", "group_id", "env", "status", "session_kind", "session_title", "caller_id", "caller_principal", "created_by", "participants", "current_msg_seq", "meta"])?,
    }))
}

async fn message_target_from_db(
    db: &dyn DbPlugin,
    message: &MessageProjection,
) -> Result<Value, DesktopLegacyImportError> {
    let stored_message = query_one(db, statement("SELECT message_id, group_id, session_id, session_seq, env, sender_id, sender_type, message_type, content, status, created_at, run_id, workspace_id, mentions_json, parent_message_id, metadata_json, source_hash FROM bcs_messages WHERE message_id = ?", vec![message.id.as_str().into()]), "bcs_messages").await?;
    let correlation = query_one(db, statement("SELECT correlation_id, tenant_id, project_id, workspace_id, legacy_message_id, conversation_id, bcs_session_id, bcs_message_id, message_kind, is_terminal FROM workspace_message_correlations WHERE legacy_message_id = ?", vec![message.id.as_str().into()]), "workspace_message_correlations").await?;
    Ok(json!({
        "message": row_value(&stored_message, &["message_id", "group_id", "session_id", "session_seq", "env", "sender_id", "sender_type", "message_type", "content", "status", "created_at", "run_id", "workspace_id", "mentions_json", "parent_message_id", "metadata_json", "source_hash"])?,
        "correlation": row_value(&correlation, &["correlation_id", "tenant_id", "project_id", "workspace_id", "legacy_message_id", "conversation_id", "bcs_session_id", "bcs_message_id", "message_kind", "is_terminal"])?,
    }))
}

async fn one(
    db: &dyn DbPlugin,
    label: &str,
    _presence: DbStatement,
    sql: &str,
    value: &str,
) -> Result<DbRow, DesktopLegacyImportError> {
    query_one(db, statement(sql, vec![value.into()]), label).await
}

async fn query_one(
    db: &dyn DbPlugin,
    statement: DbStatement,
    label: &str,
) -> Result<DbRow, DesktopLegacyImportError> {
    let mut rows = db.query(statement).await?;
    if rows.len() != 1 {
        return Err(invalid(format!(
            "verified import target mismatch in {label}"
        )));
    }
    rows.pop()
        .ok_or_else(|| invalid(format!("verified import target mismatch in {label}")))
}

fn row_value(row: &DbRow, columns: &[&str]) -> Result<Value, DesktopLegacyImportError> {
    let mut value = Map::with_capacity(columns.len());
    for column in columns {
        let cell = row
            .get(column)
            .ok_or_else(|| invalid(format!("verified target column {column} is missing")))?;
        value.insert(
            (*column).to_string(),
            match cell {
                DbValue::Null => Value::Null,
                DbValue::String(value) => Value::String(value.clone()),
                DbValue::I64(value)
                    if matches!(*column, "is_archived" | "is_active" | "is_terminal") =>
                {
                    (*value != 0).into()
                }
                DbValue::I64(value) => (*value).into(),
                DbValue::U64(value) => (*value).into(),
                DbValue::Bool(value) => (*value).into(),
                DbValue::F64(value) => json!(value),
                DbValue::Bytes(_) => {
                    return Err(invalid(format!(
                        "verified target column {column} is binary"
                    )));
                }
            },
        );
    }
    Ok(Value::Object(value))
}

fn object<'a>(
    value: &'a Value,
    label: &str,
) -> Result<&'a Map<String, Value>, DesktopLegacyImportError> {
    value
        .as_object()
        .ok_or_else(|| invalid(format!("{label} must be an object")))
}

fn required_string(
    object: &Map<String, Value>,
    key: &str,
    label: &str,
) -> Result<String, DesktopLegacyImportError> {
    object
        .get(key)
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .map(str::to_string)
        .ok_or_else(|| invalid(format!("{label}.{key} must be a non-empty string")))
}

fn optional_string(
    object: &Map<String, Value>,
    key: &str,
    label: &str,
) -> Result<Option<String>, DesktopLegacyImportError> {
    match object.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        Some(_) => Err(invalid(format!("{label}.{key} must be a string or null"))),
    }
}

fn optional_bool(
    object: &Map<String, Value>,
    key: &str,
    label: &str,
) -> Result<Option<bool>, DesktopLegacyImportError> {
    match object.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Bool(value)) => Ok(Some(*value)),
        Some(Value::Number(value)) if value.as_i64().is_some() => {
            Ok(value.as_i64().map(|value| value != 0))
        }
        Some(_) => Err(invalid(format!("{label}.{key} must be a boolean"))),
    }
}

fn optional_object(
    object: &Map<String, Value>,
    key: &str,
    label: &str,
) -> Result<Map<String, Value>, DesktopLegacyImportError> {
    match object.get(key) {
        None | Some(Value::Null) => Ok(Map::new()),
        Some(Value::Object(value)) => Ok(value.clone()),
        Some(_) => Err(invalid(format!("{label}.{key} must be an object"))),
    }
}

fn required_array_of_strings(
    object: &Map<String, Value>,
    key: &str,
    label: &str,
) -> Result<Vec<String>, DesktopLegacyImportError> {
    let values = object
        .get(key)
        .and_then(Value::as_array)
        .ok_or_else(|| invalid(format!("{label}.{key} must be an array")))?;
    values
        .iter()
        .map(|value| {
            value
                .as_str()
                .map(str::to_string)
                .ok_or_else(|| invalid(format!("{label}.{key} must contain only strings")))
        })
        .collect()
}

fn require_equal(
    object: &Map<String, Value>,
    key: &str,
    expected: &str,
    label: &str,
) -> Result<(), DesktopLegacyImportError> {
    if required_string(object, key, label)? != expected {
        return Err(invalid(format!("{label} does not match record envelope")));
    }
    Ok(())
}

fn required_timestamp(
    object: &Map<String, Value>,
    key: &str,
    label: &str,
) -> Result<(String, i64), DesktopLegacyImportError> {
    let value = required_string(object, key, label)?;
    let parsed = DateTime::parse_from_rfc3339(&value)
        .map_err(|_| invalid(format!("{label}.{key} must be RFC 3339")))?;
    Ok((value, parsed.timestamp_millis()))
}

fn metadata_with_legacy(
    mut metadata: Map<String, Value>,
    legacy: Value,
) -> Result<String, DesktopLegacyImportError> {
    if metadata.contains_key("legacy_desktop") {
        return Err(invalid(
            "metadata.legacy_desktop is reserved for migration authority",
        ));
    }
    metadata.insert("legacy_desktop".to_string(), legacy);
    serde_json::to_string(&Value::Object(metadata)).map_err(DesktopLegacyImportError::Json)
}

fn verify_source_hash(expected: &str, value: &Value) -> Result<(), DesktopLegacyImportError> {
    if source_hash(value)? != expected {
        return Err(invalid("record source hash mismatch"));
    }
    Ok(())
}

fn source_hash(value: &Value) -> Result<String, DesktopLegacyImportError> {
    let encoded =
        serde_json::to_vec(&canonical_json(value)).map_err(DesktopLegacyImportError::Json)?;
    Ok(hex_sha256(&encoded))
}

fn canonical_json(value: &Value) -> Value {
    match value {
        Value::Object(object) => Value::Object(
            object
                .iter()
                .map(|(key, value)| (key.clone(), canonical_json(value)))
                .collect::<BTreeMap<_, _>>()
                .into_iter()
                .collect(),
        ),
        Value::Array(values) => Value::Array(values.iter().map(canonical_json).collect()),
        _ => value.clone(),
    }
}

fn workspace_session_id(tenant_id: &str, project_id: &str, workspace_id: &str) -> String {
    let material = format!("session:{tenant_id}:{project_id}:{workspace_id}:workspace-chat");
    Uuid::new_v5(&PUBLIC_MESSAGE_NAMESPACE, material.as_bytes()).to_string()
}

fn validate_sha256(label: &str, value: &str) -> Result<(), DesktopLegacyImportError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid(format!("{label} SHA-256 is invalid")));
    }
    Ok(())
}

fn hex_sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn invalid(message: impl Into<String>) -> DesktopLegacyImportError {
    DesktopLegacyImportError::InvalidSnapshot(message.into())
}
