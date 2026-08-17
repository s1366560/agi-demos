//! SQLite persistence for desktop platform plugin snapshots.
//!
//! This module owns only durable requested/applied state. Runtime activation and
//! transport wiring remain separate so a rejected snapshot never changes the
//! active generation. Credential values are never stored here.

use rusqlite::{params, Connection, OptionalExtension};
use serde::Serialize;
use serde_json::Value;

const TABLE_SQL: &str = r#"
CREATE TABLE IF NOT EXISTS desktop_platform_plugin_snapshots (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    requested_version INTEGER NOT NULL,
    requested_nonce TEXT NOT NULL,
    requested_digest TEXT NOT NULL,
    requested_json TEXT NOT NULL,
    applied_version INTEGER NOT NULL,
    applied_digest TEXT,
    last_good_json TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'ack', 'nack')),
    error_message TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"#;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub(crate) struct PluginApplyRecord {
    pub requested_version: u64,
    pub requested_nonce: String,
    pub requested_digest: String,
    pub applied_version: u64,
    pub applied_digest: Option<String>,
    pub status: String,
    pub error_message: Option<String>,
    pub has_last_good: bool,
}

pub(crate) fn initialize_schema(connection: &Connection) -> Result<(), String> {
    connection
        .execute_batch(TABLE_SQL)
        .map(|_| ())
        .map_err(|error| error.to_string())
}

pub(crate) fn read_apply_record(
    connection: &Connection,
) -> Result<Option<PluginApplyRecord>, String> {
    connection
        .query_row(
            r#"
            SELECT requested_version, requested_nonce, requested_digest,
                   applied_version, applied_digest, last_good_json,
                   status, error_message
            FROM desktop_platform_plugin_snapshots WHERE id = 1
            "#,
            [],
            |row| {
                Ok(PluginApplyRecord {
                    requested_version: row.get::<_, i64>(0)? as u64,
                    requested_nonce: row.get(1)?,
                    requested_digest: row.get(2)?,
                    applied_version: row.get::<_, i64>(3)? as u64,
                    applied_digest: row.get(4)?,
                    status: row.get(6)?,
                    error_message: row.get(7)?,
                    has_last_good: row.get::<_, Option<String>>(5)?.is_some(),
                })
            },
        )
        .optional()
        .map_err(|error| error.to_string())
}

pub(crate) fn read_last_good(connection: &Connection) -> Result<Option<Value>, String> {
    connection
        .query_row(
            "SELECT last_good_json FROM desktop_platform_plugin_snapshots WHERE id = 1",
            [],
            |row| row.get::<_, Option<String>>(0),
        )
        .optional()
        .map_err(|error| error.to_string())
        .and_then(|raw| match raw.flatten() {
            Some(raw) => serde_json::from_str::<Value>(&raw)
                .map(Some)
                .map_err(|error| error.to_string()),
            None => Ok(None),
        })
}

pub(crate) fn record_requested(
    connection: &Connection,
    version: u64,
    nonce: &str,
    digest: &str,
    raw_snapshot: &str,
) -> Result<(), String> {
    let previous = read_apply_record(connection)?;
    connection
        .execute(
            r#"
            INSERT INTO desktop_platform_plugin_snapshots (
                id, requested_version, requested_nonce, requested_digest, requested_json,
                applied_version, applied_digest, last_good_json, status
            ) VALUES (1, ?1, ?2, ?3, ?4, ?5, ?6, ?7, 'pending')
            ON CONFLICT(id) DO UPDATE SET
                requested_version = excluded.requested_version,
                requested_nonce = excluded.requested_nonce,
                requested_digest = excluded.requested_digest,
                requested_json = excluded.requested_json,
                applied_version = excluded.applied_version,
                applied_digest = excluded.applied_digest,
                last_good_json = excluded.last_good_json,
                status = 'pending',
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            "#,
            params![
                version as i64,
                nonce,
                digest,
                raw_snapshot,
                previous.as_ref().map_or(0, |record| record.applied_version) as i64,
                previous.and_then(|record| record.applied_digest),
                read_last_good_json(connection)?
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn read_last_good_json(connection: &Connection) -> Result<Option<String>, String> {
    connection
        .query_row(
            "SELECT last_good_json FROM desktop_platform_plugin_snapshots WHERE id = 1",
            [],
            |row| row.get::<_, Option<String>>(0),
        )
        .optional()
        .map_err(|error| error.to_string())
        .map(Option::flatten)
}

pub(crate) fn record_ack(
    connection: &Connection,
    version: u64,
    digest: &str,
    raw_snapshot: &str,
) -> Result<(), String> {
    connection
        .execute(
            r#"
            UPDATE desktop_platform_plugin_snapshots
               SET applied_version = ?1, applied_digest = ?2, last_good_json = ?3,
                   status = 'ack', error_message = NULL, updated_at = CURRENT_TIMESTAMP
             WHERE id = 1
            "#,
            params![version as i64, digest, raw_snapshot],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

pub(crate) fn record_nack(connection: &Connection, error: &str) -> Result<(), String> {
    connection
        .execute(
            r#"
            UPDATE desktop_platform_plugin_snapshots
               SET status = 'nack', error_message = ?1, updated_at = CURRENT_TIMESTAMP
             WHERE id = 1
            "#,
            params![error],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn snapshot(digest: &str) -> Value {
        json!({
            "schema_version": 1,
            "profile_id": "test-profile",
            "plugins": [],
            "digest": digest
        })
    }

    #[test]
    fn requested_ack_and_nack_preserve_last_good() {
        let connection = Connection::open_in_memory().expect("plugin database");
        initialize_schema(&connection).expect("plugin schema");
        let good_digest = "a".repeat(64);
        let good = snapshot(&good_digest).to_string();

        record_requested(&connection, 2, "nonce-2", &good_digest, &good).expect("record requested");
        record_ack(&connection, 2, &good_digest, &good).expect("record ack");
        let record = read_apply_record(&connection)
            .expect("read apply record")
            .expect("apply record");
        assert_eq!(record.status, "ack");
        assert_eq!(record.applied_version, 2);
        assert_eq!(
            read_last_good(&connection).expect("last good"),
            Some(snapshot(&good_digest))
        );

        let bad_digest = "b".repeat(64);
        let bad = snapshot(&bad_digest).to_string();
        record_requested(&connection, 3, "nonce-3", &bad_digest, &bad)
            .expect("record bad requested");
        record_nack(&connection, "plugin failed").expect("record nack");
        let record = read_apply_record(&connection)
            .expect("reread apply record")
            .expect("apply record");
        assert_eq!(record.status, "nack");
        assert_eq!(record.applied_version, 2);
        assert_eq!(
            read_last_good(&connection).expect("retained last good"),
            Some(snapshot(&good_digest))
        );
    }
}
