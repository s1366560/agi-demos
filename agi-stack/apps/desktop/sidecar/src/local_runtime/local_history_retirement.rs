//! Deletes retired local conversation history after cloud initialization.
//!
//! The upload queue, credential vault, checkpoint database, and any table that
//! is not on the explicit whitelist are left untouched. Cleanup is idempotent:
//! a second successful call deletes nothing further. A failed delete rolls back.

use std::fs;
use std::path::Path;

use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};

use crate::workspace_core_legacy_import::LEGACY_WORKSPACE_HISTORY_TABLES;

const TERMINAL_RUN_STATUSES: &[&str] = &["completed", "failed", "cancelled"];
const SETTLED_UPLOAD_STATES: &[&str] = &["acked", "failed"];
const SETTLED_CLAIM_STATES: &[&str] = &["failed", "finished", "completed", "cancelled"];

/// History tables only. Child tables come before parents so foreign keys can commit.
pub(crate) const LOCAL_HISTORY_TABLES: &[&str] = &[
    "desktop_artifact_content_receipts",
    "desktop_artifact_content_authorities",
    "desktop_artifact_deliveries",
    "desktop_artifact_versions",
    "desktop_search_documents_fts",
    "desktop_search_documents",
    "desktop_search_backfill",
    "desktop_tool_invocations",
    "desktop_timeline",
    "desktop_client_turns",
    "desktop_run_events",
    "desktop_run_inputs",
    "desktop_hitl_requests",
    "desktop_decisions",
    "desktop_agent_plan_tasks",
    "desktop_plan_versions",
    "desktop_artifacts",
    "desktop_checkpoint_authorities",
    "desktop_runs",
    "desktop_conversation_approval_modes",
    "desktop_conversation_llm_routes",
    "desktop_conversation_execution_selections",
    "desktop_new_task_sessions",
    "desktop_conversations",
];

pub(crate) const PRESERVED_TABLES: &[&str] = &[
    "desktop_runtime_metadata",
    "desktop_seed_migrations",
    "desktop_user_sessions",
    "desktop_users",
    "desktop_projects",
    "desktop_workspace_contexts",
    "desktop_workspace_tool_grants",
    "desktop_browser_origin_grants",
    "desktop_permission_grants",
    "desktop_llm_provider_create_receipts",
    "desktop_workspace_core_requests",
    "desktop_workspace_core_terminal_callbacks",
    "upload_outbox",
    "execution_claims",
    "application_vault_records",
];

pub(crate) fn retire_local_workspace_history(
    session: &Connection,
    data_directory: &Path,
    cloud_history_ready: bool,
) -> Result<Value, String> {
    if !cloud_history_ready {
        return Ok(deferred("cloud_history_not_ready"));
    }
    if !data_directory.is_absolute() {
        return Err("local history retirement requires an absolute data directory".to_string());
    }
    let queue_path = data_directory.join("local-run-upload.db");
    let queue_guard = lock_upload_queue(&queue_path)?;
    if let Some(reason) = queue_guard.blocked {
        return Ok(deferred(reason));
    }
    let transaction =
        rusqlite::Transaction::new_unchecked(session, rusqlite::TransactionBehavior::Immediate)
            .map_err(|error| error.to_string())?;
    if active_execution(&transaction)? {
        return Ok(deferred("active_run"));
    }
    let deleted_rows = delete_whitelisted_rows(&transaction)?;
    transaction.commit().map_err(|error| error.to_string())?;
    Ok(json!({"status": "retired", "reason": null, "deleted_rows": deleted_rows}))
}

struct QueueGuard {
    connection: Option<Connection>,
    blocked: Option<&'static str>,
}

impl Drop for QueueGuard {
    fn drop(&mut self) {
        if let Some(connection) = self.connection.as_ref() {
            let _ = connection.execute_batch("ROLLBACK");
        }
    }
}

fn deferred(reason: &'static str) -> Value {
    json!({
        "status": "deferred",
        "reason": reason,
        "deleted_rows": 0,
    })
}

fn absent_queue() -> QueueGuard {
    QueueGuard {
        connection: None,
        blocked: None,
    }
}

fn blocked_queue(reason: &'static str) -> QueueGuard {
    QueueGuard {
        connection: None,
        blocked: Some(reason),
    }
}

fn lock_upload_queue(path: &Path) -> Result<QueueGuard, String> {
    if path.file_name().and_then(|name| name.to_str()) != Some("local-run-upload.db") {
        return Err("local history retirement refused an unexpected queue path".to_string());
    }
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            return Ok(blocked_queue("upload_queue_unreadable"));
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(absent_queue()),
        Err(_) => return Ok(blocked_queue("upload_queue_unreadable")),
        Ok(_) => {}
    }
    let connection = match Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_WRITE) {
        Ok(connection) => connection,
        Err(_) => return Ok(blocked_queue("upload_queue_unreadable")),
    };
    if connection.busy_timeout(std::time::Duration::ZERO).is_err() {
        return Ok(blocked_queue("upload_queue_unreadable"));
    }
    if connection.execute_batch("BEGIN IMMEDIATE").is_err() {
        return Ok(blocked_queue("pending_upload"));
    }
    if unsettled_rows(&connection, "upload_outbox", "state", SETTLED_UPLOAD_STATES)?
        || unsettled_rows(
            &connection,
            "execution_claims",
            "state",
            SETTLED_CLAIM_STATES,
        )?
    {
        return Ok(blocked_queue("pending_upload"));
    }
    Ok(QueueGuard {
        connection: Some(connection),
        blocked: None,
    })
}

fn unsettled_rows(
    connection: &Connection,
    table: &str,
    column: &str,
    settled: &[&str],
) -> Result<bool, String> {
    if !table_exists(connection, table)? {
        return Ok(false);
    }
    let placeholders = settled.iter().map(|_| "?").collect::<Vec<_>>().join(", ");
    let sql = format!(
        "SELECT COUNT(*) FROM {table} WHERE {column} IS NULL OR {column} NOT IN ({placeholders})"
    );
    let mut statement = connection
        .prepare(&sql)
        .map_err(|error| error.to_string())?;
    let count = statement
        .query_row(rusqlite::params_from_iter(settled.iter()), |row| {
            row.get::<_, i64>(0)
        })
        .map_err(|error| error.to_string())?;
    Ok(count > 0)
}

fn active_execution(session: &Connection) -> Result<bool, String> {
    if table_exists(session, "desktop_runs")? {
        let terminal = quoted_list(TERMINAL_RUN_STATUSES)?;
        let mut statement = session
            .prepare(&format!(
                "SELECT COUNT(*) FROM desktop_runs
                 WHERE status IS NULL OR lower(status) NOT IN ({terminal})"
            ))
            .map_err(|error| error.to_string())?;
        let active = statement
            .query_row([], |row| row.get::<_, i64>(0))
            .map_err(|error| error.to_string())?;
        if active > 0 {
            return Ok(true);
        }
    }
    if table_exists(session, "desktop_checkpoint_authorities")?
        && table_exists(session, "desktop_runs")?
    {
        let terminal_for_checkpoint = quoted_list(TERMINAL_RUN_STATUSES)?;
        let mut statement = session
            .prepare(&format!(
                "SELECT COUNT(*) FROM desktop_checkpoint_authorities AS authority
                 WHERE NOT EXISTS (
                   SELECT 1 FROM desktop_runs AS run
                   WHERE run.id = authority.run_id
                     AND lower(run.status) IN ({terminal_for_checkpoint})
                 )"
            ))
            .map_err(|error| error.to_string())?;
        let orphans = statement
            .query_row([], |row| row.get::<_, i64>(0))
            .map_err(|error| error.to_string())?;
        if orphans > 0 {
            return Ok(true);
        }
    } else if table_exists(session, "desktop_checkpoint_authorities")? {
        let count = count_rows(session, "desktop_checkpoint_authorities")?;
        if count > 0 {
            return Ok(true);
        }
    }
    if table_exists(session, "desktop_workspace_core_terminal_callbacks")? {
        let mut statement = session
            .prepare(
                "SELECT COUNT(*) FROM desktop_workspace_core_terminal_callbacks
                 WHERE delivered_at IS NULL",
            )
            .map_err(|error| error.to_string())?;
        let pending = statement
            .query_row([], |row| row.get::<_, i64>(0))
            .map_err(|error| error.to_string())?;
        if pending > 0 {
            return Ok(true);
        }
    }
    Ok(false)
}

fn delete_whitelisted_rows(session: &Connection) -> Result<i64, String> {
    let mut deleted = 0_i64;
    for table in LOCAL_HISTORY_TABLES {
        if PRESERVED_TABLES.contains(table) {
            return Err(format!(
                "history whitelist overlaps preserved table {table}"
            ));
        }
        if !table_exists(session, table)? {
            continue;
        }
        session
            .execute(&format!("DELETE FROM {table}"), [])
            .map_err(|error| format!("failed to retire {table}: {error}"))?;
        deleted += i64::try_from(session.changes()).unwrap_or(i64::MAX);
    }
    for table in LEGACY_WORKSPACE_HISTORY_TABLES {
        if PRESERVED_TABLES.contains(table) {
            return Err(format!(
                "history whitelist overlaps preserved table {table}"
            ));
        }
        if !table_exists(session, table)? {
            continue;
        }
        session
            .execute(&format!("DELETE FROM {table}"), [])
            .map_err(|error| format!("failed to retire {table}: {error}"))?;
        deleted += i64::try_from(session.changes()).unwrap_or(i64::MAX);
    }
    Ok(deleted)
}

fn quoted_list(values: &[&str]) -> Result<String, String> {
    let mut parts = Vec::with_capacity(values.len());
    for value in values {
        if !value
            .chars()
            .all(|character| character.is_ascii_lowercase())
        {
            return Err("history retirement status literal is invalid".to_string());
        }
        parts.push(format!("'{value}'"));
    }
    Ok(parts.join(", "))
}

fn table_exists(connection: &Connection, name: &str) -> Result<bool, String> {
    connection
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?1",
            [name],
            |row| row.get::<_, i64>(0),
        )
        .map(|count| count > 0)
        .map_err(|error| error.to_string())
}

fn count_rows(connection: &Connection, table: &str) -> Result<i64, String> {
    connection
        .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
            row.get(0)
        })
        .map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn session_with_history() -> Connection {
        let connection = Connection::open_in_memory().expect("session");
        connection
            .execute_batch(
                "CREATE TABLE desktop_conversations (id TEXT PRIMARY KEY, project_id TEXT);
                 CREATE TABLE desktop_timeline (
                   id TEXT PRIMARY KEY,
                   conversation_id TEXT,
                   position INTEGER,
                   value_json TEXT
                 );
                 CREATE TABLE desktop_runs (
                   id TEXT PRIMARY KEY,
                   conversation_id TEXT,
                   status TEXT
                 );
                 CREATE TABLE desktop_runtime_metadata (key TEXT PRIMARY KEY, value_text TEXT);
                 CREATE TABLE desktop_custom_keep (id TEXT PRIMARY KEY, note TEXT);
                 INSERT INTO desktop_conversations VALUES ('conversation-a', 'project-a');
                 INSERT INTO desktop_timeline VALUES ('item-1', 'conversation-a', 1, '{}');
                 INSERT INTO desktop_runs VALUES ('run-done', 'conversation-a', 'completed');
                 INSERT INTO desktop_runtime_metadata VALUES ('installation_id', 'device-1');
                 INSERT INTO desktop_custom_keep VALUES ('keep-1', 'unknown');",
            )
            .expect("schema");
        connection
    }

    struct TempDir(std::path::PathBuf);

    impl TempDir {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "agistack-history-retirement-{}",
                uuid::Uuid::new_v4()
            ));
            fs::create_dir(&path).expect("data dir");
            Self(path)
        }

        fn path(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn data_dir() -> TempDir {
        TempDir::new()
    }

    fn write_vault(dir: &Path) {
        let vault = dir.join("credential-vault");
        fs::create_dir(&vault).expect("vault dir");
        fs::write(vault.join("master.key"), b"master-key-bytes").expect("master key");
        fs::write(vault.join("records.db"), b"vault-records").expect("records");
        let mut notes = fs::File::create(dir.join("user-notes.txt")).expect("notes");
        notes.write_all(b"keep this file").expect("notes bytes");
    }

    fn write_queue(dir: &Path, outbox_state: &str, claim_state: &str) {
        let connection = Connection::open(dir.join("local-run-upload.db")).expect("queue");
        connection
            .execute_batch(
                "CREATE TABLE upload_outbox (
                   id INTEGER PRIMARY KEY,
                   user_id TEXT,
                   state TEXT,
                   body TEXT
                 );
                 CREATE TABLE execution_claims (
                   user_id TEXT,
                   run_key TEXT,
                   state TEXT
                 );",
            )
            .expect("queue schema");
        connection
            .execute(
                "INSERT INTO upload_outbox (user_id, state, body) VALUES ('user-b', ?1, 'event')",
                [outbox_state],
            )
            .expect("outbox");
        connection
            .execute(
                "INSERT INTO execution_claims (user_id, run_key, state) VALUES ('user-b', 'run', ?1)",
                [claim_state],
            )
            .expect("claim");
    }

    #[test]
    fn whitelist_does_not_overlap_preserved_runtime_or_vault_tables() {
        for table in LOCAL_HISTORY_TABLES {
            assert!(
                !PRESERVED_TABLES.contains(table),
                "{table} must stay outside history cleanup"
            );
        }
        assert!(PRESERVED_TABLES.contains(&"application_vault_records"));
        assert!(PRESERVED_TABLES.contains(&"upload_outbox"));
        assert!(PRESERVED_TABLES.contains(&"desktop_runtime_metadata"));
    }

    #[test]
    fn startup_does_not_import_legacy_workspace_rows() {
        let helper = include_str!("../workspace_core_helper.rs");
        let importer = include_str!("../workspace_core_legacy_import.rs");
        assert!(!helper.contains("stage_legacy_workspace_snapshot"));
        assert!(!helper.contains("read_legacy_workspace_rows"));
        assert!(!importer.contains("read_legacy_workspace_rows"));
        assert!(!importer.contains("SELECT id, project_id"));
        let production_importer = importer.split("#[cfg(test)]").next().unwrap_or(importer);
        assert!(production_importer.contains("desktop_workspace_messages"));
        assert!(production_importer.contains("desktop_workspaces"));
        let production_retirement = include_str!("local_history_retirement.rs")
            .split("#[cfg(test)]")
            .next()
            .unwrap_or("");
        assert!(!production_retirement.contains("desktop_workspace_messages"));
        assert!(!production_retirement.contains("desktop_workspaces"));
    }

    #[test]
    fn cloud_init_failure_does_not_delete_history() {
        let session = session_with_history();
        let dir = data_dir();
        let result = retire_local_workspace_history(&session, dir.path(), false).expect("deferred");
        assert_eq!(result["status"], "deferred");
        assert_eq!(result["reason"], "cloud_history_not_ready");
        assert_eq!(count_rows(&session, "desktop_timeline").expect("count"), 1);
    }

    #[test]
    fn pending_upload_for_another_account_blocks_cleanup_and_keeps_vault() {
        let session = session_with_history();
        let dir = data_dir();
        write_vault(dir.path());
        write_queue(dir.path(), "pending", "finished");
        let master_before = fs::read(dir.path().join("credential-vault/master.key")).expect("key");
        let records_before = fs::read(dir.path().join("credential-vault/records.db")).expect("db");

        let result = retire_local_workspace_history(&session, dir.path(), true).expect("deferred");

        assert_eq!(result["reason"], "pending_upload");
        assert_eq!(
            count_rows(&session, "desktop_conversations").expect("count"),
            1
        );
        assert_eq!(
            fs::read(dir.path().join("credential-vault/master.key")).expect("key"),
            master_before
        );
        assert_eq!(
            fs::read(dir.path().join("credential-vault/records.db")).expect("db"),
            records_before
        );
        let queue = Connection::open(dir.path().join("local-run-upload.db")).expect("queue");
        assert_eq!(count_rows(&queue, "upload_outbox").expect("outbox"), 1);
    }

    #[test]
    fn active_run_blocks_cleanup() {
        let session = session_with_history();
        session
            .execute(
                "INSERT INTO desktop_runs VALUES ('run-live', 'conversation-a', 'running')",
                [],
            )
            .expect("active run");
        let dir = data_dir();
        let result = retire_local_workspace_history(&session, dir.path(), true).expect("deferred");
        assert_eq!(result["reason"], "active_run");
        assert_eq!(count_rows(&session, "desktop_timeline").expect("count"), 1);
    }

    #[test]
    fn retirement_is_idempotent_and_leaves_unknown_tables_and_files() {
        let session = session_with_history();
        let dir = data_dir();
        write_vault(dir.path());
        write_queue(dir.path(), "acked", "finished");
        let notes_before = fs::read(dir.path().join("user-notes.txt")).expect("notes");
        let master_before = fs::read(dir.path().join("credential-vault/master.key")).expect("key");

        let first = retire_local_workspace_history(&session, dir.path(), true).expect("retire");
        assert_eq!(first["status"], "retired");
        assert!(first["deleted_rows"].as_i64().expect("rows") > 0);
        assert_eq!(
            count_rows(&session, "desktop_timeline").expect("timeline"),
            0
        );
        assert_eq!(
            count_rows(&session, "desktop_conversations").expect("catalog"),
            0
        );
        assert_eq!(count_rows(&session, "desktop_runs").expect("runs"), 0);
        assert_eq!(
            count_rows(&session, "desktop_runtime_metadata").expect("metadata"),
            1
        );
        assert_eq!(
            count_rows(&session, "desktop_custom_keep").expect("unknown"),
            1
        );

        let second = retire_local_workspace_history(&session, dir.path(), true).expect("again");
        assert_eq!(second["status"], "retired");
        assert_eq!(second["deleted_rows"], 0);
        assert_eq!(
            fs::read(dir.path().join("user-notes.txt")).expect("notes"),
            notes_before
        );
        assert_eq!(
            fs::read(dir.path().join("credential-vault/master.key")).expect("key"),
            master_before
        );
        assert!(!dir
            .path()
            .join("agistack-local-agent-checkpoints.db")
            .exists());
        let queue = Connection::open(dir.path().join("local-run-upload.db")).expect("queue");
        assert_eq!(count_rows(&queue, "upload_outbox").expect("outbox"), 1);
        assert_eq!(count_rows(&queue, "execution_claims").expect("claims"), 1);
    }

    #[test]
    fn fresh_install_with_no_history_tables_retires_without_creating_files() {
        let session = Connection::open_in_memory().expect("empty");
        let dir = data_dir();
        let before = fs::read_dir(dir.path()).expect("list").count();
        let result = retire_local_workspace_history(&session, dir.path(), true).expect("retire");
        assert_eq!(result["status"], "retired");
        assert_eq!(result["deleted_rows"], 0);
        assert_eq!(fs::read_dir(dir.path()).expect("list").count(), before);
    }

    #[test]
    fn failed_delete_rolls_back_and_a_later_attempt_can_finish() {
        let session = session_with_history();
        session
            .execute_batch(
                "CREATE TRIGGER refuse_conversation_delete
                 BEFORE DELETE ON desktop_conversations
                 BEGIN
                   SELECT RAISE(ABORT, 'refuse');
                 END;",
            )
            .expect("trigger");
        let dir = data_dir();
        let error = retire_local_workspace_history(&session, dir.path(), true)
            .expect_err("delete must fail closed");
        assert!(error.contains("desktop_conversations"));
        assert_eq!(
            count_rows(&session, "desktop_timeline").expect("timeline"),
            1
        );
        session
            .execute_batch("DROP TRIGGER refuse_conversation_delete")
            .expect("drop trigger");
        let result = retire_local_workspace_history(&session, dir.path(), true).expect("retry");
        assert_eq!(result["status"], "retired");
        assert_eq!(
            count_rows(&session, "desktop_timeline").expect("timeline"),
            0
        );
        assert_eq!(
            count_rows(&session, "desktop_custom_keep").expect("unknown"),
            1
        );
    }

    #[test]
    fn executing_claim_blocks_even_when_outbox_is_acked() {
        let session = session_with_history();
        let dir = data_dir();
        write_queue(dir.path(), "acked", "executing");
        let result = retire_local_workspace_history(&session, dir.path(), true).expect("deferred");
        assert_eq!(result["reason"], "pending_upload");
        assert_eq!(
            count_rows(&session, "desktop_timeline").expect("timeline"),
            1
        );
    }
}
