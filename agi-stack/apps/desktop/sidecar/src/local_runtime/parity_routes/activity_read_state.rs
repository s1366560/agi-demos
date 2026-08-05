use std::collections::BTreeSet;

use chrono::{DateTime, SecondsFormat, Utc};
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use serde::{Deserialize, Serialize};

use super::super::*;

const MAX_ACTIVITY_READ_ENTRIES: usize = 500;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawActivityReadEntry {
    entry_id: String,
    entry_revision: u64,
    read_at: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "RawActivityReadEntry")]
pub(super) struct ActivityReadEntry {
    pub(super) entry_id: String,
    pub(super) entry_revision: u64,
    pub(super) read_at: String,
}

impl ActivityReadEntry {
    #[cfg(test)]
    pub(super) fn try_from_parts(
        entry_id: String,
        entry_revision: u64,
        read_at: String,
    ) -> Result<Self, String> {
        Self::try_from(RawActivityReadEntry {
            entry_id,
            entry_revision,
            read_at,
        })
    }
}

impl TryFrom<RawActivityReadEntry> for ActivityReadEntry {
    type Error = String;

    fn try_from(raw: RawActivityReadEntry) -> Result<Self, Self::Error> {
        if raw.entry_id.is_empty()
            || raw.entry_id != raw.entry_id.trim()
            || raw.entry_id.len() > 512
        {
            return Err("entry_id must be a bounded non-empty identifier".to_string());
        }
        i64::try_from(raw.entry_revision)
            .map_err(|_| "entry_revision exceeds local storage range".to_string())?;
        DateTime::parse_from_rfc3339(&raw.read_at)
            .map_err(|_| "read_at must be an RFC 3339 timestamp".to_string())?;
        Ok(Self {
            entry_id: raw.entry_id,
            entry_revision: raw.entry_revision,
            read_at: raw.read_at,
        })
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct UpdateActivityReadStateRequest {
    pub(super) expected_authority_revision: u64,
    pub(super) entries: Vec<ActivityReadEntry>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub(super) struct ActivityReadStateResponse {
    pub(super) project_id: String,
    pub(super) authority_revision: u64,
    pub(super) entries: Vec<ActivityReadEntry>,
}

#[derive(Debug)]
pub(super) enum ActivityReadStateError {
    RevisionConflict { actual: u64 },
    InvalidRequest(&'static str),
    Storage(String),
}

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new().route(
        "/api/v1/projects/:project_id/activity/read-state",
        get(get_activity_read_state).put(put_activity_read_state),
    )
}

async fn get_activity_read_state(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
) -> LocalJsonResult {
    ensure_project_scope(&authenticated, Some(&project_id))?;
    read_state(
        &state.session_store,
        &authenticated.workspace.tenant_id,
        &project_id,
        &authenticated.user.user_id,
    )
    .map(|response| Json(json!(response)))
    .map_err(activity_read_state_error)
}

async fn put_activity_read_state(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    Json(request): Json<UpdateActivityReadStateRequest>,
) -> LocalJsonResult {
    ensure_project_scope(&authenticated, Some(&project_id))?;
    if request.entries.len() > MAX_ACTIVITY_READ_ENTRIES {
        return Err(activity_read_state_error(
            ActivityReadStateError::InvalidRequest("activity entry limit exceeded"),
        ));
    }
    let requested_entry_ids = request
        .entries
        .iter()
        .map(|entry| entry.entry_id.clone())
        .collect::<BTreeSet<_>>();
    if requested_entry_ids.len() != request.entries.len() {
        return Err(activity_read_state_error(
            ActivityReadStateError::InvalidRequest("duplicate activity entry_id"),
        ));
    }
    update_state(
        &state.session_store,
        &authenticated.workspace.tenant_id,
        &project_id,
        &authenticated.user.user_id,
        request,
    )
    .map(|response| Json(json!(response)))
    .map_err(activity_read_state_error)
}

pub(super) fn initialize_schema(connection: &Connection) -> Result<(), String> {
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS desktop_activity_read_receipts (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                entry_id TEXT NOT NULL,
                entry_revision INTEGER NOT NULL CHECK(entry_revision >= 0),
                revision INTEGER NOT NULL CHECK(revision > 0),
                read_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id, user_id, entry_id)
             );
             CREATE INDEX IF NOT EXISTS idx_desktop_activity_read_receipts_scope_revision
             ON desktop_activity_read_receipts(tenant_id, project_id, user_id, revision);",
        )
        .map_err(|error| error.to_string())
}

pub(super) fn read_state(
    store: &DesktopSessionStore,
    tenant_id: &str,
    project_id: &str,
    user_id: &str,
) -> Result<ActivityReadStateResponse, ActivityReadStateError> {
    store
        .with_local_mcp_connection(|connection| {
            initialize_schema(connection)?;
            read_state_from_connection(connection, tenant_id, project_id, user_id)
        })
        .map_err(ActivityReadStateError::Storage)
}

pub(super) fn update_state(
    store: &DesktopSessionStore,
    tenant_id: &str,
    project_id: &str,
    user_id: &str,
    request: UpdateActivityReadStateRequest,
) -> Result<ActivityReadStateResponse, ActivityReadStateError> {
    if request.entries.len() > MAX_ACTIVITY_READ_ENTRIES {
        return Err(ActivityReadStateError::InvalidRequest(
            "activity entry limit exceeded",
        ));
    }
    let requested_entry_ids = request
        .entries
        .iter()
        .map(|entry| entry.entry_id.clone())
        .collect::<BTreeSet<_>>();
    if requested_entry_ids.len() != request.entries.len() {
        return Err(ActivityReadStateError::InvalidRequest(
            "duplicate activity entry_id",
        ));
    }
    i64::try_from(request.expected_authority_revision).map_err(|_| {
        ActivityReadStateError::InvalidRequest("authority revision exceeds local storage range")
    })?;

    store
        .with_local_mcp_connection(|connection| {
            initialize_schema(connection)?;
            let transaction = connection
                .transaction_with_behavior(TransactionBehavior::Immediate)
                .map_err(|error| error.to_string())?;
            let mut known_entry_statement = transaction
                .prepare(
                    "SELECT EXISTS(
                       SELECT 1
                       FROM desktop_runs AS run
                       JOIN desktop_conversations AS conversation
                         ON conversation.id = run.conversation_id
                       WHERE run.id = ?1
                         AND run.project_id = ?2
                         AND conversation.project_id = ?2
                         AND json_extract(conversation.value_json, '$.tenant_id') = ?3
                         AND run.status NOT IN ('completed', 'cancelled')
                     )",
                )
                .map_err(|error| error.to_string())?;
            for entry_id in &requested_entry_ids {
                let Some(run_id) = entry_id.strip_prefix("desktop_run:") else {
                    return Err("activity read-state unknown entry".to_string());
                };
                let known = known_entry_statement
                    .query_row(params![run_id, project_id, tenant_id], |row| {
                        row.get::<_, bool>(0)
                    })
                    .map_err(|error| error.to_string())?;
                if !known {
                    return Err("activity read-state unknown entry".to_string());
                }
            }
            drop(known_entry_statement);
            let current = read_state_from_connection(&transaction, tenant_id, project_id, user_id)?;
            if request.expected_authority_revision != current.authority_revision {
                return Err(format!(
                    "activity read-state revision conflict:{}",
                    current.authority_revision
                ));
            }
            let now = Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true);
            let mut authority_revision = current.authority_revision;
            for incoming in request.entries {
                let existing = transaction
                    .query_row(
                        "SELECT entry_revision, read_at
                         FROM desktop_activity_read_receipts
                         WHERE tenant_id = ?1 AND project_id = ?2 AND user_id = ?3
                           AND entry_id = ?4",
                        params![tenant_id, project_id, user_id, incoming.entry_id],
                        |row| Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?)),
                    )
                    .optional()
                    .map_err(|error| error.to_string())?;
                let (entry_revision, read_at, changed) = match existing {
                    Some((stored_revision, stored_read_at)) => {
                        let stored_revision =
                            u64::try_from(stored_revision).map_err(|error| error.to_string())?;
                        let entry_revision = stored_revision.max(incoming.entry_revision);
                        let stored_timestamp = parsed_timestamp(&stored_read_at)?;
                        let incoming_timestamp = parsed_timestamp(&incoming.read_at)?;
                        let read_at = if incoming_timestamp > stored_timestamp {
                            incoming.read_at.clone()
                        } else {
                            stored_read_at.clone()
                        };
                        let changed =
                            entry_revision != stored_revision || read_at != stored_read_at;
                        (entry_revision, read_at, changed)
                    }
                    None => (incoming.entry_revision, incoming.read_at.clone(), true),
                };
                if !changed {
                    continue;
                }
                authority_revision = authority_revision
                    .checked_add(1)
                    .ok_or_else(|| "activity read-state revision overflow".to_string())?;
                let stored_entry_revision =
                    i64::try_from(entry_revision).map_err(|error| error.to_string())?;
                let stored_authority_revision =
                    i64::try_from(authority_revision).map_err(|error| error.to_string())?;
                transaction
                    .execute(
                        "INSERT INTO desktop_activity_read_receipts(
                            tenant_id, project_id, user_id, entry_id, entry_revision,
                            revision, read_at, created_at, updated_at
                         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?8)
                         ON CONFLICT(tenant_id, project_id, user_id, entry_id) DO UPDATE SET
                            entry_revision = excluded.entry_revision,
                            revision = excluded.revision,
                            read_at = excluded.read_at,
                            updated_at = excluded.updated_at",
                        params![
                            tenant_id,
                            project_id,
                            user_id,
                            incoming.entry_id,
                            stored_entry_revision,
                            stored_authority_revision,
                            read_at,
                            now,
                        ],
                    )
                    .map_err(|error| error.to_string())?;
            }
            transaction.commit().map_err(|error| error.to_string())?;
            read_state_from_connection(connection, tenant_id, project_id, user_id)
        })
        .map_err(|error| {
            if error == "activity read-state unknown entry" {
                return ActivityReadStateError::InvalidRequest(
                    "activity entry_id is absent from the current My Work projection",
                );
            }
            if let Some(actual) = error
                .strip_prefix("activity read-state revision conflict:")
                .and_then(|actual| actual.parse::<u64>().ok())
            {
                return ActivityReadStateError::RevisionConflict { actual };
            }
            ActivityReadStateError::Storage(error)
        })
}

fn read_state_from_connection(
    connection: &Connection,
    tenant_id: &str,
    project_id: &str,
    user_id: &str,
) -> Result<ActivityReadStateResponse, String> {
    let authority_revision = connection
        .query_row(
            "SELECT MAX(revision) FROM desktop_activity_read_receipts
             WHERE tenant_id = ?1 AND project_id = ?2 AND user_id = ?3",
            params![tenant_id, project_id, user_id],
            |row| row.get::<_, Option<i64>>(0),
        )
        .map_err(|error| error.to_string())?
        .unwrap_or(0);
    let authority_revision =
        u64::try_from(authority_revision).map_err(|error| error.to_string())?;
    let mut statement = connection
        .prepare(
            "SELECT entry_id, entry_revision, read_at
             FROM desktop_activity_read_receipts
             WHERE tenant_id = ?1 AND project_id = ?2 AND user_id = ?3
             ORDER BY entry_id ASC",
        )
        .map_err(|error| error.to_string())?;
    let rows = statement
        .query_map(params![tenant_id, project_id, user_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, String>(2)?,
            ))
        })
        .map_err(|error| error.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| error.to_string())?;
    let entries = rows
        .into_iter()
        .map(|(entry_id, entry_revision, read_at)| {
            let entry_revision =
                u64::try_from(entry_revision).map_err(|error| error.to_string())?;
            ActivityReadEntry::try_from(RawActivityReadEntry {
                entry_id,
                entry_revision,
                read_at,
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(ActivityReadStateResponse {
        project_id: project_id.to_string(),
        authority_revision,
        entries,
    })
}

fn parsed_timestamp(value: &str) -> Result<DateTime<Utc>, String> {
    DateTime::parse_from_rfc3339(value)
        .map(|timestamp| timestamp.with_timezone(&Utc))
        .map_err(|error| error.to_string())
}

fn activity_read_state_error(error: ActivityReadStateError) -> (StatusCode, Json<Value>) {
    match error {
        ActivityReadStateError::RevisionConflict { actual } => (
            StatusCode::CONFLICT,
            Json(json!({
                "reason_code": "activity_read_state_revision_conflict",
                "detail": "activity read-state revision conflict",
                "authority_revision": actual,
            })),
        ),
        ActivityReadStateError::InvalidRequest(detail) => (
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({
                "reason_code": "local_activity_read_state_request_invalid",
                "detail": detail,
            })),
        ),
        ActivityReadStateError::Storage(error) => {
            tracing::error!(error = %error, "local activity read-state storage operation failed");
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({
                    "reason_code": "local_activity_read_state_store_error",
                    "detail": "local Activity read-state authority is temporarily unavailable",
                })),
            )
        }
    }
}
