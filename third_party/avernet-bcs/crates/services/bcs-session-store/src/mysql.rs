//! MySQL-backed `SessionRepoPort` implementation via `bcs-db-api`.
//!
//! Task 8a: helpers + `create` + `get` + `belongs_to_group`.
//! Task 8b: `complete_if_running`, `reactivate`, `update_callback_status`, `update_title`.
//! Task 8c: `list_by_group`, `latest_running`, `count_running_service`,
//!           `list_running_service`, `add_participant`, `remove_participant`,
//!           `update_participant_mode`, `list_group_ids_by_session_participant`.

use std::sync::Arc;

use async_trait::async_trait;
use bcs_db_api::{
    DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder, DbValue, db_get_column,
    db_get_column_opt,
};
use tracing::info;

use bcs_service_api::core::session::{can_reactivate, new_session_id, validate_session_id};
use bcs_service_api::port::repo::{NewSessionParams, SessionRepoPort};
use bcs_service_api::{
    GroupSessionMetricCount, GroupSessionMetricsSnapshotPort, Participant, ParticipantMode,
    ServiceError, ServiceResult, Session, SessionKind, SessionStatus,
};

// ---------------------------------------------------------------------------
// Public type
// ---------------------------------------------------------------------------

/// MySQL-backed session repository.
#[derive(Clone)]
pub struct MySqlSessionStore {
    db: Arc<dyn DbPlugin>,
    env: String,
    flavor: DbSqlFlavor,
}

impl MySqlSessionStore {
    pub fn new(db: Arc<dyn DbPlugin>, env: String) -> Self {
        Self {
            db,
            env,
            flavor: DbSqlFlavor::Mysql,
        }
    }

    pub fn sqlite(db: Arc<dyn DbPlugin>, env: String) -> Self {
        Self {
            db,
            env,
            flavor: DbSqlFlavor::Sqlite,
        }
    }

    pub fn postgres(db: Arc<dyn DbPlugin>, env: String) -> Self {
        Self {
            db,
            env,
            flavor: DbSqlFlavor::Postgres,
        }
    }

    /// Build the SELECT column list including flavor-aware timestamp expressions.
    fn select_cols(&self) -> &'static str {
        match self.flavor {
            DbSqlFlavor::Mysql => {
                "session_id, group_id, session_title, group_version, env, status, \
                 session_kind, caller_id, input, output, error_message, callback_status, \
                 caller_principal, activation_count, created_by, participants, completed_at, meta, \
                 current_msg_seq, participant_join_seq, \
                 (UNIX_TIMESTAMP(gmt_create))*1000 AS gmt_create_ms, \
                 (UNIX_TIMESTAMP(gmt_modified))*1000 AS gmt_modified_ms"
            }
            DbSqlFlavor::Sqlite => {
                "session_id, group_id, session_title, group_version, env, status, \
                 session_kind, caller_id, input, output, error_message, callback_status, \
                 caller_principal, activation_count, created_by, participants, completed_at, meta, \
                 current_msg_seq, participant_join_seq, \
                 (CAST(strftime('%s',gmt_create) AS INTEGER))*1000 AS gmt_create_ms, \
                 (CAST(strftime('%s',gmt_modified) AS INTEGER))*1000 AS gmt_modified_ms"
            }
            DbSqlFlavor::Postgres => {
                "session_id, group_id, session_title, group_version, env, status, \
                 session_kind, caller_id, input, output, error_message, callback_status, \
                 caller_principal, activation_count, created_by, participants, completed_at, meta, \
                 current_msg_seq, participant_join_seq, \
                 (CAST(EXTRACT(EPOCH FROM gmt_create) AS BIGINT))*1000 AS gmt_create_ms, \
                 (CAST(EXTRACT(EPOCH FROM gmt_modified) AS BIGINT))*1000 AS gmt_modified_ms"
            }
        }
    }

    /// Build the prefixed SELECT column list (table alias `s.`) for JOIN queries.
    fn select_cols_prefixed(&self) -> &'static str {
        match self.flavor {
            DbSqlFlavor::Mysql => {
                "s.session_id, s.group_id, s.session_title, s.group_version, s.env, \
                 s.status, s.session_kind, s.caller_id, s.input, s.output, s.error_message, \
                 s.callback_status, s.caller_principal, s.activation_count, s.created_by, \
                 s.participants, s.completed_at, s.meta, s.current_msg_seq, \
                 s.participant_join_seq, (UNIX_TIMESTAMP(s.gmt_create))*1000 AS gmt_create_ms, \
                 (UNIX_TIMESTAMP(s.gmt_modified))*1000 AS gmt_modified_ms"
            }
            DbSqlFlavor::Sqlite => {
                "s.session_id, s.group_id, s.session_title, s.group_version, s.env, \
                 s.status, s.session_kind, s.caller_id, s.input, s.output, s.error_message, \
                 s.callback_status, s.caller_principal, s.activation_count, s.created_by, \
                 s.participants, s.completed_at, s.meta, s.current_msg_seq, \
                 s.participant_join_seq, \
                 (CAST(strftime('%s',s.gmt_create) AS INTEGER))*1000 AS gmt_create_ms, \
                 (CAST(strftime('%s',s.gmt_modified) AS INTEGER))*1000 AS gmt_modified_ms"
            }
            DbSqlFlavor::Postgres => {
                "s.session_id, s.group_id, s.session_title, s.group_version, s.env, \
                 s.status, s.session_kind, s.caller_id, s.input, s.output, s.error_message, \
                 s.callback_status, s.caller_principal, s.activation_count, s.created_by, \
                 s.participants, s.completed_at, s.meta, s.current_msg_seq, \
                 s.participant_join_seq, \
                 (CAST(EXTRACT(EPOCH FROM s.gmt_create) AS BIGINT))*1000 AS gmt_create_ms, \
                 (CAST(EXTRACT(EPOCH FROM s.gmt_modified) AS BIGINT))*1000 AS gmt_modified_ms"
            }
        }
    }

    fn session_by_id_statement(&self, session_id: &str) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static("SELECT ")
            .push_static(self.select_cols())
            .push_static(" FROM bcs_group_sessions WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .push_static(" LIMIT 1")
            .build()
    }

    /// Internal: execute the INSERT and return the constructed Session on success.
    /// Writes both the main session row and the `bcs_session_participants`
    /// side-table rows in a single transaction.
    async fn insert_session(
        &self,
        session_id: String,
        group_id: String,
        params: NewSessionParams,
        now: u64,
    ) -> ServiceResult<Session> {
        use bcs_db_api::DbTransactionStep;

        let session_kind = params.session_kind;
        let initial_cb = initial_callback_status(session_kind);
        let participants_json = serde_json::to_string(&params.participants).map_err(|e| {
            ServiceError::SessionInvalidParams(format!("participants serialize: {e}"))
        })?;

        // Build the return value before the DB call so we don't need to re-query.
        let session_value = Session {
            id: session_id.clone(),
            group_id: group_id.clone(),
            session_title: params.session_title.clone(),
            env: Some(self.env.clone()),
            status: SessionStatus::Running,
            session_kind,
            participants: params.participants.clone(),
            group_version: params.group_version,
            caller_id: params.caller_id.clone(),
            input: params.input.clone(),
            output: None,
            error_message: None,
            callback_status: initial_cb.clone(),
            activation_count: 1,
            caller_principal: params.caller_principal.clone(),
            created_by: params.created_by.clone(),
            meta: params.meta.clone(),
            current_msg_seq: 0,
            participant_join_seq: None,
            created_at: now,
            updated_at: now,
            completed_at: None,
            collected_at: None,
        };

        let kind_str = kind_to_string(session_kind);
        let input_value = json_to_db_value(&params.input);
        let meta_value = json_to_db_value(&params.meta);
        let group_version_value = match params.group_version {
            Some(v) => DbValue::I64(i64::from(v)),
            None => DbValue::Null,
        };

        let env = self.env.clone();
        let participants_for_side_table = params.participants.clone();

        let insert = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO bcs_group_sessions \
                 (session_id, group_id, session_title, env, status, session_kind, group_version, \
                  caller_id, input, caller_principal, activation_count, callback_status, created_by, \
                  participants, completed_at, meta, current_msg_seq, participant_join_seq) VALUES (",
            )
            .bind(session_id.as_str())
            .push_static(", ")
            .bind(group_id.as_str())
            .push_static(", ")
            .bind(params.session_title.as_deref())
            .push_static(", ")
            .bind(env.as_str())
            .push_static(", ")
            .bind("running")
            .push_static(", ")
            .bind(kind_str)
            .push_static(", ")
            .bind(group_version_value)
            .push_static(", ")
            .bind(params.caller_id.as_deref())
            .push_static(", ")
            .bind(input_value)
            .push_static(", ")
            .bind(params.caller_principal.as_deref())
            .push_static(", 1, ")
            .bind(initial_cb.as_deref())
            .push_static(", ")
            .bind(params.created_by.as_deref())
            .push_static(", ")
            .bind(participants_json.as_str())
            .push_static(", NULL, ")
            .bind(meta_value)
            .push_static(", 0, NULL)")
            .build();
        let mut steps: Vec<DbTransactionStep> = vec![DbTransactionStep::Execute(insert)];

        // Same-transaction write to bcs_session_participants side table
        // so list_by_group JOIN queries can find participants set at creation.
        if let Some(statement) = build_session_participants_insert_sql(
            self.flavor,
            &session_id,
            &group_id,
            &env,
            &participants_for_side_table,
        ) {
            steps.push(DbTransactionStep::Execute(statement));
        }

        self.db
            .transaction(steps)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session insert: {e}")))?;

        Ok(session_value)
    }
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

/// Serialize an `Option<serde_json::Value>` to a `DbValue` for SQL binding.
fn json_to_db_value(v: &Option<serde_json::Value>) -> DbValue {
    match v {
        None => DbValue::Null,
        Some(j) => DbValue::String(j.to_string()),
    }
}

/// Read a TEXT column from a row and parse it as JSON.
/// NULL or empty string → `Ok(None)`.
fn parse_json(col: &str, row: &DbRow) -> ServiceResult<Option<serde_json::Value>> {
    let raw: Option<String> = db_get_column_opt(row, col)
        .map_err(|e| ServiceError::InternalError(format!("column {col}: {e}")))?;
    match raw {
        None => Ok(None),
        Some(s) if s.is_empty() => Ok(None),
        Some(s) => serde_json::from_str(&s)
            .map(Some)
            .map_err(|e| ServiceError::InternalError(format!("parse json column {col}: {e}"))),
    }
}

/// Parse the `status` column string into `SessionStatus`.
fn parse_status(s: &str) -> ServiceResult<SessionStatus> {
    match s {
        "running" => Ok(SessionStatus::Running),
        "completed" => Ok(SessionStatus::Completed),
        other => Err(ServiceError::SessionInvalidParams(format!(
            "unknown session status: {other}"
        ))),
    }
}

/// Parse the `session_kind` column string into `SessionKind`.
fn parse_session_kind(s: &str) -> ServiceResult<SessionKind> {
    match s {
        "chat" => Ok(SessionKind::Chat),
        "service_invocation" => Ok(SessionKind::ServiceInvocation),
        other => Err(ServiceError::SessionInvalidParams(format!(
            "unknown session_kind: {other}"
        ))),
    }
}

fn participant_role_to_str(role: bcs_service_api::ParticipantRole) -> &'static str {
    match role {
        bcs_service_api::ParticipantRole::Driver => "driver",
        bcs_service_api::ParticipantRole::Consultant => "consultant",
        bcs_service_api::ParticipantRole::Manager => "manager",
        bcs_service_api::ParticipantRole::Worker => "worker",
        bcs_service_api::ParticipantRole::Observer => "observer",
    }
}

/// Build a multi-row INSERT for the `bcs_session_participants` side table.
/// Returns `None` when `participants` is empty (no rows to write).
fn build_session_participants_insert_sql(
    flavor: DbSqlFlavor,
    session_id: &str,
    group_id: &str,
    env: &str,
    participants: &[Participant],
) -> Option<DbStatement> {
    if participants.is_empty() {
        return None;
    }
    let mut statement = DbStatementBuilder::new(flavor).push_static(
        "INSERT INTO bcs_session_participants \
         (session_id, group_id, bot_uuid, role, env) VALUES ",
    );
    for (index, participant) in participants.iter().enumerate() {
        if index > 0 {
            statement = statement.push_static(", ");
        }
        statement = statement
            .push_static("(")
            .bind(session_id)
            .push_static(", ")
            .bind(group_id)
            .push_static(", ")
            .bind(participant.bot_uuid.as_str())
            .push_static(", ")
            .bind(participant_role_to_str(participant.role))
            .push_static(", ")
            .bind(env)
            .push_static(")");
    }
    Some(statement.build())
}

/// Deserialize the `participants` JSON column.
fn participants_from_json(s: &str) -> ServiceResult<Vec<Participant>> {
    serde_json::from_str(s)
        .map_err(|e| ServiceError::InternalError(format!("participants deserialize: {e}")))
}

/// Initial `callback_status` value for a new session.
fn initial_callback_status(kind: SessionKind) -> Option<String> {
    if matches!(kind, SessionKind::ServiceInvocation) {
        Some("pending".to_string())
    } else {
        None
    }
}

/// Canonical DB string for a `SessionKind`.
fn kind_to_string(kind: SessionKind) -> &'static str {
    match kind {
        SessionKind::Chat => "chat",
        SessionKind::ServiceInvocation => "service_invocation",
    }
}

/// Current time in milliseconds since UNIX epoch.
fn current_millis() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Read a u64 timestamp column (stored as UNIX_TIMESTAMP*1000 alias).
/// Falls back to i64 → u64 for backends that return signed integers.
fn column_u64(row: &DbRow, name: &str) -> u64 {
    // Try u64 first.
    if let Ok(Some(v)) = db_get_column_opt::<i64>(row, name) {
        return v.max(0) as u64;
    }
    0
}

/// Convert a full DB row (using `select_cols()`) into a `Session`.
fn row_to_session(row: &DbRow) -> ServiceResult<Session> {
    let id: String = db_get_column(row, "session_id")
        .map_err(|e| ServiceError::InternalError(format!("session_id: {e}")))?;
    let group_id: String = db_get_column(row, "group_id")
        .map_err(|e| ServiceError::InternalError(format!("group_id: {e}")))?;

    let status_raw: String = db_get_column_opt(row, "status")
        .map_err(|e| ServiceError::InternalError(format!("status: {e}")))?
        .unwrap_or_else(|| "running".to_string());
    let status = parse_status(&status_raw)?;

    let kind_raw: String = db_get_column_opt(row, "session_kind")
        .map_err(|e| ServiceError::InternalError(format!("session_kind: {e}")))?
        .unwrap_or_else(|| "chat".to_string());
    let session_kind = parse_session_kind(&kind_raw)?;

    let participants_raw: Option<String> = db_get_column_opt(row, "participants")
        .map_err(|e| ServiceError::InternalError(format!("participants: {e}")))?;
    let participants = match participants_raw.as_deref() {
        None | Some("") => Vec::new(),
        Some(s) => participants_from_json(s)?,
    };

    let activation_count: i32 = db_get_column_opt::<i32>(row, "activation_count")
        .map_err(|e| ServiceError::InternalError(format!("activation_count: {e}")))?
        .unwrap_or(1);

    let group_version: Option<i32> = db_get_column_opt(row, "group_version")
        .map_err(|e| ServiceError::InternalError(format!("group_version: {e}")))?;

    let completed_at: Option<u64> = db_get_column_opt::<i64>(row, "completed_at")
        .map_err(|e| ServiceError::InternalError(format!("completed_at: {e}")))?
        .map(|v| v.max(0) as u64);

    Ok(Session {
        id,
        group_id,
        session_title: db_get_column_opt(row, "session_title")
            .map_err(|e| ServiceError::InternalError(format!("session_title: {e}")))?,
        env: db_get_column_opt(row, "env")
            .map_err(|e| ServiceError::InternalError(format!("env: {e}")))?,
        status,
        session_kind,
        participants,
        group_version,
        caller_id: db_get_column_opt(row, "caller_id")
            .map_err(|e| ServiceError::InternalError(format!("caller_id: {e}")))?,
        input: parse_json("input", row)?,
        output: parse_json("output", row)?,
        error_message: db_get_column_opt(row, "error_message")
            .map_err(|e| ServiceError::InternalError(format!("error_message: {e}")))?,
        callback_status: db_get_column_opt(row, "callback_status")
            .map_err(|e| ServiceError::InternalError(format!("callback_status: {e}")))?,
        activation_count,
        caller_principal: db_get_column_opt(row, "caller_principal")
            .map_err(|e| ServiceError::InternalError(format!("caller_principal: {e}")))?,
        created_by: db_get_column_opt(row, "created_by")
            .map_err(|e| ServiceError::InternalError(format!("created_by: {e}")))?,
        created_at: column_u64(row, "gmt_create_ms"),
        updated_at: column_u64(row, "gmt_modified_ms"),
        completed_at,
        // `collected_at_ms` is only selected by the collected-list query; other
        // queries omit the column entirely (db_get_column_opt → Ok(None)). Be
        // tolerant of decode failures too (e.g. a fractional datetime producing
        // a DOUBLE on some backends) so a non-integer value never fails the
        // whole row — collected_at is best-effort, not load-bearing.
        collected_at: db_get_column_opt::<i64>(row, "collected_at_ms")
            .ok()
            .flatten()
            .map(|v| v.max(0) as u64),
        meta: parse_json("meta", row)?,
        current_msg_seq: db_get_column_opt::<i64>(row, "current_msg_seq")
            .map_err(|e| ServiceError::InternalError(format!("current_msg_seq: {e}")))?
            .unwrap_or(0),
        participant_join_seq: parse_json("participant_join_seq", row)?,
    })
}

#[async_trait]
impl GroupSessionMetricsSnapshotPort for MySqlSessionStore {
    async fn group_session_counts(&self) -> ServiceResult<Vec<GroupSessionMetricCount>> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT status, session_kind, COUNT(*) AS session_count \
                 FROM bcs_group_sessions WHERE env = ",
            )
            .bind(self.env.as_str())
            .push_static(" GROUP BY status, session_kind")
            .build();
        let rows = self.db.query(statement).await.map_err(|e| {
            ServiceError::InternalError(format!("group session metrics snapshot query failed: {e}"))
        })?;

        let mut counts = Vec::with_capacity(rows.len());
        for row in rows {
            let status_raw: String = db_get_column(&row, "status").map_err(|e| {
                ServiceError::InternalError(format!(
                    "group session metrics status conversion failed: {e}"
                ))
            })?;
            let session_kind_raw: String = db_get_column(&row, "session_kind").map_err(|e| {
                ServiceError::InternalError(format!(
                    "group session metrics kind conversion failed: {e}"
                ))
            })?;
            let session_count: i64 = db_get_column(&row, "session_count").map_err(|e| {
                ServiceError::InternalError(format!(
                    "group session metrics count conversion failed: {e}"
                ))
            })?;
            let count = u64::try_from(session_count).map_err(|e| {
                ServiceError::InternalError(format!("group session metrics count is invalid: {e}"))
            })?;
            if count == 0 {
                continue;
            }

            counts.push(GroupSessionMetricCount {
                status: parse_status(&status_raw)?,
                session_kind: parse_session_kind(&session_kind_raw)?,
                count,
            });
        }

        Ok(counts)
    }
}

// ---------------------------------------------------------------------------
// SessionRepoPort impl
// ---------------------------------------------------------------------------

#[async_trait]
impl SessionRepoPort for MySqlSessionStore {
    async fn create(&self, group_id: &str, params: NewSessionParams) -> ServiceResult<Session> {
        // Explicit id path — single attempt, no retry.
        if let Some(ref id) = params.id {
            if !validate_session_id(id, group_id) {
                return Err(ServiceError::SessionInvalidParams(format!(
                    "session_id {id} not valid for group {group_id}"
                )));
            }
            return self
                .insert_session(id.clone(), group_id.to_string(), params, current_millis())
                .await;
        }

        // Auto-generate path: up to 3 retries on uk_session_id collision.
        for _ in 0..3 {
            let id = new_session_id(group_id)
                .map_err(|error| ServiceError::SessionInvalidParams(error.to_string()))?;
            match self
                .insert_session(id, group_id.to_string(), params.clone(), current_millis())
                .await
            {
                Ok(sess) => return Ok(sess),
                Err(ServiceError::InternalError(ref msg))
                    if msg.to_ascii_lowercase().contains("duplicate")
                        || msg.contains("1062")
                        || msg.contains("UNIQUE constraint failed") =>
                {
                    // uk_session_id collision — retry with a new id.
                    continue;
                }
                Err(e) => return Err(e),
            }
        }
        Err(ServiceError::SessionInvalidParams(
            "session_id collision retry exhausted (3 attempts)".to_string(),
        ))
    }

    async fn get(&self, session_id: &str) -> Option<Session> {
        let rows = self
            .db
            .query(self.session_by_id_statement(session_id))
            .await
            .ok()?;
        let row = rows.into_iter().next()?;
        row_to_session(&row).ok()
    }

    async fn belongs_to_group(&self, session_id: &str, group_id: &str) -> bool {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT 1 AS found FROM bcs_group_sessions WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .push_static(" AND group_id = ")
            .bind(group_id)
            .push_static(" LIMIT 1")
            .build();
        self.db
            .query(statement)
            .await
            .map(|rows| !rows.is_empty())
            .unwrap_or(false)
    }

    async fn complete_if_running(
        &self,
        session_id: &str,
        output: Option<serde_json::Value>,
        error: Option<String>,
    ) -> ServiceResult<Option<Session>> {
        let now = current_millis();
        let output_value = json_to_db_value(&output);
        let error_value = DbValue::from(error.as_deref());
        let completed_at_value = i64::try_from(now)
            .map(DbValue::I64)
            .map_err(|e| ServiceError::InternalError(format!("completed_at overflow: {e}")))?;
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_group_sessions SET status = 'completed', output = ")
            .bind(output_value)
            .push_static(", error_message = ")
            .bind(error_value)
            .push_static(", completed_at = ")
            .bind(completed_at_value)
            .push_static(", ")
            .push_static(self.flavor.set_modified_now())
            .push_static(" WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .push_static(" AND status = 'running'")
            .build();

        let result = self
            .db
            .execute(statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;

        if result.affected_rows == 0 {
            // Already completed — CAS short-circuit, not an error.
            return Ok(None);
        }

        // 1+ rows updated → re-SELECT to return the new state.
        let rows = self
            .db
            .query(self.session_by_id_statement(session_id))
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;

        match rows.into_iter().next() {
            Some(row) => row_to_session(&row).map(Some),
            None => Err(ServiceError::SessionNotFound(session_id.to_string())),
        }
    }

    async fn reactivate(
        &self,
        session_id: &str,
        new_input: Option<serde_json::Value>,
    ) -> ServiceResult<Session> {
        // TODO(phase-2): wrap SELECT + check + UPDATE + re-SELECT in a DbPlugin transaction once supported.
        let rows = self
            .db
            .query(self.session_by_id_statement(session_id))
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;
        let row = rows
            .into_iter()
            .next()
            .ok_or_else(|| ServiceError::SessionNotFound(session_id.to_string()))?;
        let current = row_to_session(&row)?;

        // Validate state machine before mutating.
        can_reactivate(
            current.status,
            current.session_kind,
            current.callback_status.as_deref(),
        )
        .map_err(|msg| {
            if msg == "callback is still pending" {
                ServiceError::SessionCallbackPending(session_id.to_string())
            } else {
                ServiceError::SessionInvalidParams(format!("{session_id}: {msg}"))
            }
        })?;

        // Use new_input if provided; otherwise preserve the existing input.
        let new_input_value = match &new_input {
            Some(j) => DbValue::String(j.to_string()),
            None => match &current.input {
                Some(j) => DbValue::String(j.to_string()),
                None => DbValue::Null,
            },
        };

        let update_statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "UPDATE bcs_group_sessions SET status = 'running', output = NULL, \
                 error_message = NULL, callback_status = 'pending', input = ",
            )
            .bind(new_input_value)
            .push_static(", activation_count = activation_count + 1, completed_at = NULL, ")
            .push_static(self.flavor.set_modified_now())
            .push_static(" WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .build();
        self.db
            .execute(update_statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;

        // Re-SELECT to return the updated state.
        let rows = self
            .db
            .query(self.session_by_id_statement(session_id))
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;
        rows.into_iter()
            .next()
            .ok_or_else(|| ServiceError::SessionNotFound(session_id.to_string()))
            .and_then(|r| row_to_session(&r))
    }

    async fn update_callback_status(&self, session_id: &str, status: &str) -> ServiceResult<()> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_group_sessions SET callback_status = ")
            .bind(status)
            .push_static(", ")
            .push_static(self.flavor.set_modified_now())
            .push_static(" WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .build();
        self.db
            .execute(statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;
        Ok(())
    }

    async fn update_title(
        &self,
        session_id: &str,
        title: Option<String>,
    ) -> ServiceResult<Session> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_group_sessions SET session_title = ")
            .bind(title.as_deref())
            .push_static(", ")
            .push_static(self.flavor.set_modified_now())
            .push_static(" WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .build();
        let result = self
            .db
            .execute(statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;
        if result.affected_rows == 0 {
            return Err(ServiceError::SessionNotFound(session_id.to_string()));
        }
        let rows = self
            .db
            .query(self.session_by_id_statement(session_id))
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;
        rows.into_iter()
            .next()
            .ok_or_else(|| ServiceError::SessionNotFound(session_id.to_string()))
            .and_then(|r| row_to_session(&r))
    }

    async fn list_by_group(
        &self,
        group_id: &str,
        status: Option<SessionStatus>,
        offset: u64,
        limit: u64,
        title_contains: Option<&str>,
        participant_id: Option<&str>,
    ) -> Vec<Session> {
        match self
            .try_list_by_group(
                group_id,
                status,
                offset,
                limit,
                title_contains,
                participant_id,
            )
            .await
        {
            Ok(sessions) => sessions,
            Err(error) => {
                tracing::warn!(%error, "list_by_group query failed");
                Vec::new()
            }
        }
    }

    async fn try_list_by_group(
        &self,
        group_id: &str,
        status: Option<SessionStatus>,
        offset: u64,
        limit: u64,
        title_contains: Option<&str>,
        participant_id: Option<&str>,
    ) -> ServiceResult<Vec<Session>> {
        let mut statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT ")
            .push_static(self.select_cols_prefixed())
            .push_static(" FROM bcs_group_sessions s ");
        if participant_id.is_some() {
            statement = statement.push_static(
                "JOIN bcs_session_participants sp \
                 ON sp.env = s.env AND sp.session_id = s.session_id ",
            );
        }
        statement = statement
            .push_static("WHERE s.env = ")
            .bind(self.env.as_str())
            .push_static(" AND s.group_id = ")
            .bind(group_id);

        if let Some(s) = status {
            let status_str = match s {
                SessionStatus::Running => "running",
                SessionStatus::Completed => "completed",
            };
            statement = statement.push_static(" AND s.status = ").bind(status_str);
        }

        if let Some(q) = title_contains {
            statement = statement
                .push_static(" AND s.session_title LIKE ")
                .bind(format!("%{}%", q));
        }

        if let Some(participant_id) = participant_id {
            statement = statement
                .push_static(" AND sp.bot_uuid = ")
                .bind(participant_id);
        }
        let statement = statement
            .push_static(" ORDER BY s.gmt_create DESC, s.id DESC LIMIT ")
            .bind(limit)
            .push_static(" OFFSET ")
            .bind(offset)
            .build();

        let rows = self.db.query(statement).await.map_err(|error| {
            ServiceError::InternalError(format!("list sessions for Group '{group_id}': {error}"))
        })?;
        rows.iter().map(row_to_session).collect()
    }

    async fn latest_running(&self, group_id: &str) -> Option<Session> {
        self.list_by_group(group_id, Some(SessionStatus::Running), 0, 1, None, None)
            .await
            .into_iter()
            .next()
    }

    async fn count_running_service(&self, group_id: &str) -> u64 {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT COUNT(*) AS cnt FROM bcs_group_sessions WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND group_id = ")
            .bind(group_id)
            .push_static(" AND session_kind = 'service_invocation' AND status = 'running'")
            .build();
        let rows = match self.db.query(statement).await {
            Ok(r) => r,
            Err(_) => return 0,
        };
        rows.into_iter()
            .next()
            .and_then(|row| {
                db_get_column_opt::<i64>(&row, "cnt")
                    .ok()
                    .flatten()
                    .map(|v| v.max(0) as u64)
            })
            .unwrap_or(0)
    }

    /// Mirrors [`SessionRepoPort::try_list_by_group`] filter conditions exactly
    /// (env + group_id + optional status / title_contains / participant_id
    /// JOIN) but runs `SELECT COUNT(*)` without LIMIT/OFFSET. Used by the V1
    /// session list endpoint to compute `total`.
    ///
    /// Propagates DB failures as `ServiceResult::Err` rather than silently
    /// returning `0`, so a nonempty page never pairs with `total=0`.
    async fn count_by_group(
        &self,
        group_id: &str,
        status: Option<SessionStatus>,
        title_contains: Option<&str>,
        participant_id: Option<&str>,
    ) -> ServiceResult<u64> {
        let mut statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT COUNT(*) AS cnt FROM bcs_group_sessions s ");
        if participant_id.is_some() {
            statement = statement.push_static(
                "JOIN bcs_session_participants sp \
                 ON sp.env = s.env AND sp.session_id = s.session_id ",
            );
        }
        statement = statement
            .push_static("WHERE s.env = ")
            .bind(self.env.as_str())
            .push_static(" AND s.group_id = ")
            .bind(group_id);

        if let Some(s) = status {
            let status_str = match s {
                SessionStatus::Running => "running",
                SessionStatus::Completed => "completed",
            };
            statement = statement.push_static(" AND s.status = ").bind(status_str);
        }

        if let Some(q) = title_contains {
            statement = statement
                .push_static(" AND s.session_title LIKE ")
                .bind(format!("%{}%", q));
        }

        if let Some(participant_id) = participant_id {
            statement = statement
                .push_static(" AND sp.bot_uuid = ")
                .bind(participant_id);
        }

        let rows = self.db.query(statement.build()).await.map_err(|e| {
            ServiceError::InternalError(format!("count sessions for Group '{group_id}': {e}"))
        })?;
        let total = rows
            .into_iter()
            .next()
            .and_then(|row| {
                db_get_column_opt::<i64>(&row, "cnt")
                    .ok()
                    .flatten()
                    .map(|v| v.max(0) as u64)
            })
            .unwrap_or(0);
        Ok(total)
    }

    async fn list_running_service(&self, offset: u64, limit: u64) -> Vec<Session> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT ")
            .push_static(self.select_cols())
            .push_static(" FROM bcs_group_sessions WHERE env = ")
            .bind(self.env.as_str())
            .push_static(
                " AND session_kind = 'service_invocation' AND status = 'running' \
                 ORDER BY gmt_create ASC LIMIT ",
            )
            .bind(limit)
            .push_static(" OFFSET ")
            .bind(offset)
            .build();
        let rows = match self.db.query(statement).await {
            Ok(r) => r,
            Err(_) => return Vec::new(),
        };
        rows.iter().filter_map(|r| row_to_session(r).ok()).collect()
    }

    async fn add_participant(
        &self,
        session_id: &str,
        participant: Participant,
    ) -> ServiceResult<Session> {
        // TODO(phase-2): wrap SELECT + UPDATE + materialize INSERT in a DbPlugin transaction once supported.
        let rows = self
            .db
            .query(self.session_by_id_statement(session_id))
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;
        let row = rows
            .into_iter()
            .next()
            .ok_or_else(|| ServiceError::SessionNotFound(session_id.to_string()))?;
        let mut current = row_to_session(&row)?;

        // Idempotent: if bot already in list, return current state unchanged.
        if current
            .participants
            .iter()
            .any(|p| p.bot_uuid == participant.bot_uuid)
        {
            return Ok(current);
        }
        let group_id = current.group_id.clone();
        let bot_uuid = participant.bot_uuid.clone();
        let role_str = participant_role_to_str(participant.role);

        // Record join_seq for new-participant visible message window.
        let join_seq = current.current_msg_seq;
        let mut join_map: serde_json::Map<String, serde_json::Value> = current
            .participant_join_seq
            .as_ref()
            .and_then(|v| v.as_object())
            .cloned()
            .unwrap_or_default();
        join_map.insert(
            bot_uuid.clone(),
            serde_json::Value::Number(serde_json::Number::from(join_seq)),
        );
        let join_seq_json = serde_json::Value::Object(join_map);
        let join_seq_str = join_seq_json.to_string();
        current.participant_join_seq = Some(join_seq_json);

        current.participants.push(participant);
        current.updated_at = current_millis();
        let new_json = serde_json::to_string(&current.participants)
            .map_err(|e| ServiceError::SessionInvalidParams(format!("participants: {e}")))?;

        let update_statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_group_sessions SET participants = ")
            .bind(new_json.as_str())
            .push_static(", participant_join_seq = ")
            .bind(join_seq_str.as_str())
            .push_static(", ")
            .push_static(self.flavor.set_modified_now())
            .push_static(" WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .build();
        self.db
            .execute(update_statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;

        // Materialized side-table: upsert presence row (idempotent).
        let upsert_statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO bcs_session_participants \
                 (env, session_id, group_id, bot_uuid, role, gmt_create) VALUES (",
            )
            .bind(self.env.as_str())
            .push_static(", ")
            .bind(session_id)
            .push_static(", ")
            .bind(group_id.as_str())
            .push_static(", ")
            .bind(bot_uuid.as_str())
            .push_static(", ")
            .bind(role_str)
            .push_static(", ")
            .push_static(self.flavor.now())
            .push_static(") ");
        let upsert_statement = match self.flavor {
            DbSqlFlavor::Mysql => upsert_statement.push_static("ON DUPLICATE KEY UPDATE env=env"),
            DbSqlFlavor::Sqlite | DbSqlFlavor::Postgres => {
                upsert_statement.push_static("ON CONFLICT(env, session_id, bot_uuid) DO NOTHING")
            }
        }
        .build();
        self.db
            .execute(upsert_statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;

        info!(
            session_id = %session_id,
            bot_uuid = %bot_uuid,
            join_seq,
            "participant added with join_seq recorded"
        );
        Ok(current)
    }

    async fn remove_participant(&self, session_id: &str, bot_uuid: &str) -> ServiceResult<Session> {
        // TODO(phase-2): wrap in a DbPlugin transaction once supported.
        let rows = self
            .db
            .query(self.session_by_id_statement(session_id))
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;
        let row = rows
            .into_iter()
            .next()
            .ok_or_else(|| ServiceError::SessionNotFound(session_id.to_string()))?;
        let mut current = row_to_session(&row)?;

        let before = current.participants.len();
        current.participants.retain(|p| p.bot_uuid != bot_uuid);
        if current.participants.len() == before {
            return Err(ServiceError::SessionNotFound(format!(
                "participant {bot_uuid} not in session {session_id}"
            )));
        }
        current.updated_at = current_millis();
        let new_json = serde_json::to_string(&current.participants)
            .map_err(|e| ServiceError::SessionInvalidParams(format!("participants: {e}")))?;

        let update_statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_group_sessions SET participants = ")
            .bind(new_json.as_str())
            .push_static(", ")
            .push_static(self.flavor.set_modified_now())
            .push_static(" WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .build();
        self.db
            .execute(update_statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;

        let delete_statement = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_session_participants WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .push_static(" AND bot_uuid = ")
            .bind(bot_uuid)
            .build();
        self.db
            .execute(delete_statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;

        Ok(current)
    }

    async fn update_participant_mode(
        &self,
        session_id: &str,
        bot_uuid: &str,
        mode: ParticipantMode,
    ) -> ServiceResult<Session> {
        // TODO(phase-2): wrap in a DbPlugin transaction once supported.
        let rows = self
            .db
            .query(self.session_by_id_statement(session_id))
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;
        let row = rows
            .into_iter()
            .next()
            .ok_or_else(|| ServiceError::SessionNotFound(session_id.to_string()))?;
        let mut current = row_to_session(&row)?;

        let p = current
            .participants
            .iter_mut()
            .find(|p| p.bot_uuid == bot_uuid)
            .ok_or_else(|| {
                ServiceError::SessionNotFound(format!(
                    "participant {bot_uuid} not in session {session_id}"
                ))
            })?;
        p.mode = Some(mode);
        current.updated_at = current_millis();
        let new_json = serde_json::to_string(&current.participants)
            .map_err(|e| ServiceError::SessionInvalidParams(format!("participants: {e}")))?;

        let update_statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_group_sessions SET participants = ")
            .bind(new_json.as_str())
            .push_static(", ")
            .push_static(self.flavor.set_modified_now())
            .push_static(" WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .build();
        self.db
            .execute(update_statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;

        // bcs_session_participants tracks presence only (not mode); no side-table update needed.
        Ok(current)
    }

    async fn list_group_ids_by_session_participant(&self, bot_uuid: &str) -> Vec<String> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT DISTINCT group_id FROM bcs_session_participants WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND bot_uuid = ")
            .bind(bot_uuid)
            .build();
        let rows = match self.db.query(statement).await {
            Ok(r) => r,
            Err(_) => return Vec::new(),
        };
        rows.iter()
            .filter_map(|row| db_get_column_opt::<String>(row, "group_id").ok().flatten())
            .collect()
    }

    async fn try_list_group_ids_by_session_participant(
        &self,
        bot_uuid: &str,
    ) -> ServiceResult<Vec<String>> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT DISTINCT group_id FROM bcs_session_participants WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND bot_uuid = ")
            .bind(bot_uuid)
            .build();
        let rows = self
            .db
            .query(statement)
            .await
            .map_err(|error| ServiceError::InternalError(format!("session db: {error}")))?;

        rows.iter()
            .map(|row| {
                db_get_column::<String>(row, "group_id").map_err(|error| {
                    ServiceError::InternalError(format!("session db row: {error}"))
                })
            })
            .collect()
    }

    async fn delete(&self, session_id: &str) -> ServiceResult<bool> {
        let del_participants = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_session_participants WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .build();
        self.db
            .execute(del_participants)
            .await
            .map_err(|error| ServiceError::InternalError(format!("session db: {error}")))?;

        let del_session = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_group_sessions WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .build();
        let result = self
            .db
            .execute(del_session)
            .await
            .map_err(|error| ServiceError::InternalError(format!("session db: {error}")))?;
        Ok(result.affected_rows > 0)
    }

    async fn collect(&self, session_id: &str, bot_uuid: &str) -> ServiceResult<()> {
        // Existence check via SELECT, NOT affected_rows: the MySQL connection does
        // not set CLIENT_FOUND_ROWS (see bcs-config-api/src/mysql.rs to_mysql_url and
        // bcs-db-mysql/src/manager.rs), so mysql_async reports CHANGED rows. A repeat
        // collect (collected already 1) would yield affected_rows=0 and falsely look
        // like a non-participant. SELECTing the side-table row first lets us
        // distinguish non-participant (row absent) from already-collected (row present)
        // independent of changed-rows semantics; the subsequent unconditional UPDATE is
        // then idempotent by construction.
        let check_statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT 1 FROM bcs_session_participants WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .push_static(" AND bot_uuid = ")
            .bind(bot_uuid)
            .push_static(" LIMIT 1")
            .build();
        let rows = self
            .db
            .query(check_statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;
        if rows.is_empty() {
            return Err(ServiceError::SessionNotFound(format!(
                "participant {bot_uuid} not in session {session_id}"
            )));
        }
        // First-collect-writes-time, repeat-collect-keeps-it (idempotent), expressed
        // via the NULL-ness of collected_at itself: COALESCE writes `now` only when
        // collected_at is NULL (never collected, or cleared by a prior uncollect) and
        // preserves the existing value otherwise. This is dialect-portable: do NOT
        // rewrite as `CASE WHEN collected = 0 THEN now ...` — MySQL evaluates a single
        // UPDATE's SET left-to-right (so `collected` is already 1 by the time the CASE
        // reads it) while SQLite evaluates all SET RHS against the pre-update row, so
        // the CASE form silently never sets collected_at on MySQL while working on
        // SQLite. Relying on collected_at's own NULL-ness avoids any cross-column
        // old-value dependency.
        let update_statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_session_participants SET collected = ")
            .bind(true)
            .push_static(", collected_at = COALESCE(collected_at, ")
            .push_static(self.flavor.now())
            .push_static(") WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .push_static(" AND bot_uuid = ")
            .bind(bot_uuid)
            .build();
        self.db
            .execute(update_statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;
        Ok(())
    }

    async fn uncollect(&self, session_id: &str, bot_uuid: &str) -> ServiceResult<()> {
        // Idempotent: the only caller-facing error is session-not-found, which
        // the application layer checks via get() before calling. Here we run the
        // UPDATE regardless of whether a side-table row / collected flag exists.
        // Clearing collected_at means a later re-collect records a fresh event time.
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_session_participants SET collected = ")
            .bind(false)
            .push_static(", collected_at = NULL WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .push_static(" AND bot_uuid = ")
            .bind(bot_uuid)
            .build();
        self.db
            .execute(statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session db: {e}")))?;
        Ok(())
    }

    async fn list_collected_by_group(
        &self,
        group_id: &str,
        bot_uuid: &str,
        status: Option<SessionStatus>,
        title_contains: Option<&str>,
        offset: u64,
        limit: u64,
    ) -> Vec<Session> {
        // Collected-list-specific column list: base prefixed columns plus the
        // collect-event timestamp. We do NOT reuse select_cols_prefixed here
        // (it omits collected_at); and we CAST the timestamp to an integer so
        // MySQL's UNIX_TIMESTAMP(datetime(3)) — which returns a DOUBLE due to
        // fractional seconds — decodes cleanly to i64 instead of failing
        // row_to_session. SQLite's strftime already yields INTEGER.
        let collected_at_expr = match self.flavor {
            DbSqlFlavor::Mysql => "CAST((UNIX_TIMESTAMP(sp.collected_at))*1000 AS SIGNED)",
            DbSqlFlavor::Sqlite => "CAST(strftime('%s', sp.collected_at) AS INTEGER)*1000",
            DbSqlFlavor::Postgres => "CAST(EXTRACT(EPOCH FROM sp.collected_at) * 1000 AS BIGINT)",
        };
        let mut statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT ")
            .push_static(self.select_cols_prefixed())
            .push_static(", ")
            .push_static(collected_at_expr)
            .push_static(
                " AS collected_at_ms FROM bcs_group_sessions s \
                 JOIN bcs_session_participants sp \
                 ON sp.env = s.env AND sp.session_id = s.session_id WHERE s.env = ",
            )
            .bind(self.env.as_str())
            .push_static(" AND s.group_id = ")
            .bind(group_id)
            .push_static(" AND sp.group_id = ")
            .bind(group_id)
            .push_static(" AND sp.bot_uuid = ")
            .bind(bot_uuid)
            .push_static(" AND sp.collected = ")
            .bind(true);
        if let Some(status) = status {
            let status = match status {
                SessionStatus::Running => "running",
                SessionStatus::Completed => "completed",
            };
            statement = statement.push_static(" AND s.status = ").bind(status);
        }
        if let Some(title) = title_contains {
            statement = statement
                .push_static(" AND s.session_title LIKE ")
                .bind(format!("%{}%", title));
        }
        let statement = statement
            .push_static(" ORDER BY COALESCE(sp.collected_at, s.gmt_create) DESC, s.id DESC LIMIT ")
            .bind(limit)
            .push_static(" OFFSET ")
            .bind(offset)
            .build();

        let rows = match self.db.query(statement).await {
            Ok(r) => r,
            Err(e) => {
                tracing::warn!(error = %e, "list_collected_by_group query failed");
                return Vec::new();
            }
        };
        rows.iter().filter_map(|r| row_to_session(r).ok()).collect()
    }

    async fn collected_at_map(&self, session_ids: &[&str], bot_uuid: &str) -> Vec<(String, u64)> {
        if session_ids.is_empty() {
            return Vec::new();
        }
        // CAST the timestamp to an integer for the same reason as the
        // collected-list query: UNIX_TIMESTAMP(datetime(3)) is a DOUBLE on
        // MySQL and would not decode to i64. SQLite's strftime is already INTEGER.
        let collected_at_expr = match self.flavor {
            DbSqlFlavor::Mysql => "CAST((UNIX_TIMESTAMP(collected_at))*1000 AS SIGNED)",
            DbSqlFlavor::Sqlite => "CAST(strftime('%s', collected_at) AS INTEGER)*1000",
            DbSqlFlavor::Postgres => "CAST(EXTRACT(EPOCH FROM collected_at) * 1000 AS BIGINT)",
        };
        let mut statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT session_id, ")
            .push_static(collected_at_expr)
            .push_static(" AS collected_at_ms FROM bcs_session_participants WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND bot_uuid = ")
            .bind(bot_uuid)
            .push_static(" AND collected = ")
            .bind(true)
            .push_static(" AND session_id IN (");
        for (index, session_id) in session_ids.iter().enumerate() {
            if index > 0 {
                statement = statement.push_static(", ");
            }
            statement = statement.bind(*session_id);
        }
        let rows = match self.db.query(statement.push_static(")").build()).await {
            Ok(r) => r,
            Err(e) => {
                tracing::warn!(error = %e, "collected_at_map query failed");
                return Vec::new();
            }
        };
        rows.iter()
            .filter_map(|r| {
                let sid: String = db_get_column(r, "session_id").ok()?;
                let ts: i64 = db_get_column_opt::<i64>(r, "collected_at_ms")
                    .ok()
                    .flatten()?;
                Some((sid, ts.max(0) as u64))
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use bcs_db_api::{
        DbExecuteResult, DbHealth, DbResult, DbTransactionResultKind, DbTransactionStep,
        DbTransactionStepResult,
    };

    use super::*;

    #[derive(Default)]
    struct RecordingDb {
        queries: Mutex<Vec<DbStatement>>,
        transactions: Mutex<Vec<Vec<DbStatement>>>,
    }

    #[async_trait]
    impl DbPlugin for RecordingDb {
        async fn query(&self, statement: DbStatement) -> DbResult<Vec<DbRow>> {
            self.queries.lock().expect("queries").push(statement);
            Ok(Vec::new())
        }

        async fn execute(&self, _statement: DbStatement) -> DbResult<DbExecuteResult> {
            Ok(DbExecuteResult::default())
        }

        async fn transaction(
            &self,
            steps: Vec<DbTransactionStep>,
        ) -> DbResult<Vec<DbTransactionStepResult>> {
            let mut statements = Vec::with_capacity(steps.len());
            let mut results = Vec::with_capacity(steps.len());
            for (step_index, step) in steps.into_iter().enumerate() {
                match step {
                    DbTransactionStep::Execute(statement) => {
                        statements.push(statement);
                        results.push(DbTransactionStepResult::Executed(DbExecuteResult {
                            affected_rows: 1,
                            last_insert_id: None,
                        }));
                    }
                    DbTransactionStep::Query(statement) => {
                        statements.push(statement);
                        results.push(DbTransactionStepResult::Rows(Vec::new()));
                    }
                    DbTransactionStep::ExecuteChecked {
                        statement,
                        expected_affected_rows,
                    } => {
                        expected_affected_rows.verify(
                            step_index,
                            DbTransactionResultKind::AffectedRows,
                            1,
                        )?;
                        statements.push(statement);
                        results.push(DbTransactionStepResult::Executed(DbExecuteResult {
                            affected_rows: 1,
                            last_insert_id: None,
                        }));
                    }
                    DbTransactionStep::QueryChecked {
                        statement,
                        expected_rows,
                    } => {
                        expected_rows.verify(step_index, DbTransactionResultKind::Rows, 0)?;
                        statements.push(statement);
                        results.push(DbTransactionStepResult::Rows(Vec::new()));
                    }
                }
            }
            self.transactions
                .lock()
                .expect("transactions")
                .push(statements);
            Ok(results)
        }

        async fn health_check(&self) -> DbResult<DbHealth> {
            Ok(DbHealth::healthy())
        }
    }

    #[tokio::test]
    async fn postgres_session_create_numbers_main_and_participant_binds() {
        let db = Arc::new(RecordingDb::default());
        let repo = MySqlSessionStore::postgres(db.clone(), "tenant-a".to_string());
        let params = NewSessionParams {
            participants: vec![
                Participant::bot("alice", bcs_service_api::ParticipantRole::Driver),
                Participant::bot("bob", bcs_service_api::ParticipantRole::Consultant),
            ],
            ..Default::default()
        };

        repo.insert_session("group-1:session-1".into(), "group-1".into(), params, 1)
            .await
            .expect("insert session");

        let transactions = db.transactions.lock().expect("transactions");
        let statements = transactions.first().expect("session transaction");
        assert_eq!(statements.len(), 2);
        assert!(!statements[0].sql().contains('?'));
        assert!(statements[0].sql().contains("$14"));
        assert_eq!(statements[0].params().len(), 14);
        assert!(!statements[1].sql().contains('?'));
        assert!(statements[1].sql().contains("$10"));
        assert_eq!(statements[1].params().len(), 10);
    }

    #[tokio::test]
    async fn postgres_dynamic_session_filters_keep_contiguous_bind_numbers() {
        let db = Arc::new(RecordingDb::default());
        let repo = MySqlSessionStore::postgres(db.clone(), "tenant-a".to_string());

        let sessions = repo
            .try_list_by_group(
                "group-1",
                Some(SessionStatus::Completed),
                2,
                10,
                Some("review"),
                Some("alice"),
            )
            .await
            .expect("list sessions");

        assert!(sessions.is_empty());
        let queries = db.queries.lock().expect("queries");
        let statement = queries.first().expect("list query");
        assert!(!statement.sql().contains('?'));
        for index in 1..=7 {
            assert!(statement.sql().contains(&format!("${index}")));
        }
        assert_eq!(statement.params().len(), 7);
    }

    #[tokio::test]
    async fn postgres_collected_at_map_builds_numbered_dynamic_in_clause() {
        let db = Arc::new(RecordingDb::default());
        let repo = MySqlSessionStore::postgres(db.clone(), "tenant-a".to_string());

        let collected = repo
            .collected_at_map(&["session-1", "session-2"], "alice")
            .await;

        assert!(collected.is_empty());
        let queries = db.queries.lock().expect("queries");
        let statement = queries.first().expect("collected-at query");
        assert!(!statement.sql().contains('?'));
        assert!(statement.sql().contains("IN ($4, $5)"));
        assert_eq!(statement.params()[2], DbValue::Bool(true));
        assert_eq!(statement.params().len(), 5);
    }
}
