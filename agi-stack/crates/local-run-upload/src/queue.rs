//! Persistent outbound queue. Rows are isolated by user and device.

use std::path::Path;
use std::sync::Mutex;

use rusqlite::{params, Connection};

pub struct UploadLimits {
    pub max_bytes: i64,
    pub retention_ms: i64,
    pub max_attempts: i64,
}

pub fn production_limits() -> UploadLimits {
    UploadLimits {
        max_bytes: 64 * 1024 * 1024,
        retention_ms: 24 * 60 * 60 * 1000,
        max_attempts: 6,
    }
}

#[derive(Debug)]
pub enum QueueError {
    Full,
    Storage(String),
}

impl std::fmt::Display for QueueError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Full => formatter.write_str("UPLOAD_QUEUE_FULL"),
            Self::Storage(message) => formatter.write_str(message),
        }
    }
}

#[derive(Clone, Debug)]
pub struct OutboxItem {
    pub id: i64,
    pub kind: String,
    pub body: String,
    pub attempts: i64,
}

#[derive(Clone, Debug)]
pub struct ExecutionClaim {
    pub run_id: Option<String>,
    pub state: String,
}

pub struct UploadQueue {
    connection: Mutex<Connection>,
    limits: UploadLimits,
}

impl UploadQueue {
    pub fn open(path: &Path, limits: UploadLimits) -> Result<Self, QueueError> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| QueueError::Storage(error.to_string()))?;
        }
        let connection =
            Connection::open(path).map_err(|error| QueueError::Storage(error.to_string()))?;
        connection
            .execute_batch(
                "CREATE TABLE IF NOT EXISTS upload_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    run_key TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    body TEXT NOT NULL,
                    body_bytes INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    next_attempt_ms INTEGER NOT NULL,
                    last_error TEXT,
                    created_ms INTEGER NOT NULL,
                    updated_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_claims (
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    run_key TEXT NOT NULL,
                    run_id TEXT,
                    state TEXT NOT NULL,
                    created_ms INTEGER NOT NULL,
                    updated_ms INTEGER NOT NULL,
                    PRIMARY KEY (user_id, device_id, run_key)
                );",
            )
            .map_err(|error| QueueError::Storage(error.to_string()))?;
        Ok(Self {
            connection: Mutex::new(connection),
            limits,
        })
    }

    pub fn limits(&self) -> &UploadLimits {
        &self.limits
    }

    pub fn enqueue(
        &self,
        user_id: &str,
        device_id: &str,
        run_key: &str,
        kind: &str,
        body: &str,
        now_ms: i64,
    ) -> Result<i64, QueueError> {
        let connection = self.lock()?;
        self.purge(&connection, user_id, device_id, now_ms)?;
        let used = self.pending_bytes(&connection, user_id, device_id)?;
        let body_bytes = i64::try_from(body.len()).unwrap_or(i64::MAX);
        if used.saturating_add(body_bytes) > self.limits.max_bytes {
            return Err(QueueError::Full);
        }
        connection
            .execute(
                "INSERT INTO upload_outbox (
                    user_id, device_id, run_key, kind, body, body_bytes, state,
                    attempts, next_attempt_ms, created_ms, updated_ms
                ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'pending', 0, ?7, ?7, ?7)",
                params![user_id, device_id, run_key, kind, body, body_bytes, now_ms],
            )
            .map_err(|error| QueueError::Storage(error.to_string()))?;
        Ok(connection.last_insert_rowid())
    }

    pub fn due(
        &self,
        user_id: &str,
        device_id: &str,
        now_ms: i64,
    ) -> Result<Vec<OutboxItem>, QueueError> {
        let connection = self.lock()?;
        self.expire_pending(&connection, user_id, device_id, now_ms)?;
        let mut statement = connection
            .prepare(
                "SELECT id, kind, body, attempts FROM upload_outbox
                 WHERE user_id = ?1 AND device_id = ?2 AND state = 'pending' AND next_attempt_ms <= ?3
                 ORDER BY id ASC",
            )
            .map_err(|error| QueueError::Storage(error.to_string()))?;
        let rows = statement
            .query_map(params![user_id, device_id, now_ms], |row| {
                Ok(OutboxItem {
                    id: row.get(0)?,
                    kind: row.get(1)?,
                    body: row.get(2)?,
                    attempts: row.get(3)?,
                })
            })
            .map_err(|error| QueueError::Storage(error.to_string()))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| QueueError::Storage(error.to_string()))?;
        Ok(rows)
    }

    pub fn mark_acked(&self, id: i64, now_ms: i64) -> Result<(), QueueError> {
        self.exec(
            "UPDATE upload_outbox SET state = 'acked', updated_ms = ?2 WHERE id = ?1",
            params![id, now_ms],
        )
    }

    pub fn mark_retry(&self, id: i64, error: &str, next_attempt_ms: i64) -> Result<(), QueueError> {
        self.exec(
            "UPDATE upload_outbox
             SET attempts = attempts + 1, last_error = ?2, next_attempt_ms = ?3, updated_ms = ?3
             WHERE id = ?1",
            params![id, error, next_attempt_ms],
        )
    }

    pub fn mark_failed(&self, id: i64, error: &str, now_ms: i64) -> Result<(), QueueError> {
        self.exec(
            "UPDATE upload_outbox
             SET state = 'failed', attempts = attempts + 1, last_error = ?2, updated_ms = ?3
             WHERE id = ?1",
            params![id, error, now_ms],
        )
    }

    pub fn claim(
        &self,
        user_id: &str,
        device_id: &str,
        run_key: &str,
    ) -> Result<Option<ExecutionClaim>, QueueError> {
        let connection = self.lock()?;
        connection
            .query_row(
                "SELECT run_id, state FROM execution_claims
                 WHERE user_id = ?1 AND device_id = ?2 AND run_key = ?3",
                params![user_id, device_id, run_key],
                |row| {
                    Ok(ExecutionClaim {
                        run_id: row.get(0)?,
                        state: row.get(1)?,
                    })
                },
            )
            .map(Some)
            .or_else(|error| match error {
                rusqlite::Error::QueryReturnedNoRows => Ok(None),
                other => Err(QueueError::Storage(other.to_string())),
            })
    }

    pub fn save_claim(
        &self,
        user_id: &str,
        device_id: &str,
        run_key: &str,
        run_id: Option<&str>,
        state: &str,
        now_ms: i64,
    ) -> Result<(), QueueError> {
        let connection = self.lock()?;
        connection
            .execute(
                "INSERT INTO execution_claims (
                    user_id, device_id, run_key, run_id, state, created_ms, updated_ms
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?6)
                 ON CONFLICT(user_id, device_id, run_key) DO UPDATE SET
                    run_id = excluded.run_id,
                    state = excluded.state,
                    updated_ms = excluded.updated_ms",
                params![user_id, device_id, run_key, run_id, state, now_ms],
            )
            .map(|_| ())
            .map_err(|error| QueueError::Storage(error.to_string()))
    }

    pub fn contains_text(&self, needle: &str) -> Result<bool, QueueError> {
        let connection = self.lock()?;
        let mut statement = connection
            .prepare("SELECT body FROM upload_outbox")
            .map_err(|error| QueueError::Storage(error.to_string()))?;
        let bodies = statement
            .query_map([], |row| row.get::<_, String>(0))
            .map_err(|error| QueueError::Storage(error.to_string()))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| QueueError::Storage(error.to_string()))?;
        Ok(bodies.iter().any(|body| body.contains(needle)))
    }

    fn pending_bytes(
        &self,
        connection: &Connection,
        user_id: &str,
        device_id: &str,
    ) -> Result<i64, QueueError> {
        connection
            .query_row(
                "SELECT COALESCE(SUM(body_bytes), 0) FROM upload_outbox
                 WHERE user_id = ?1 AND device_id = ?2 AND state = 'pending'",
                params![user_id, device_id],
                |row| row.get(0),
            )
            .map_err(|error| QueueError::Storage(error.to_string()))
    }

    fn purge(
        &self,
        connection: &Connection,
        user_id: &str,
        device_id: &str,
        now_ms: i64,
    ) -> Result<(), QueueError> {
        connection
            .execute(
                "DELETE FROM upload_outbox
                 WHERE user_id = ?1 AND device_id = ?2 AND state IN ('acked', 'failed')
                   AND updated_ms <= ?3",
                params![user_id, device_id, now_ms - self.limits.retention_ms],
            )
            .map(|_| ())
            .map_err(|error| QueueError::Storage(error.to_string()))
    }

    fn expire_pending(
        &self,
        connection: &Connection,
        user_id: &str,
        device_id: &str,
        now_ms: i64,
    ) -> Result<(), QueueError> {
        connection
            .execute(
                "UPDATE upload_outbox
                 SET state = 'failed', last_error = 'UPLOAD_EXPIRED', updated_ms = ?3
                 WHERE user_id = ?1 AND device_id = ?2 AND state = 'pending' AND created_ms <= ?4",
                params![
                    user_id,
                    device_id,
                    now_ms,
                    now_ms - self.limits.retention_ms
                ],
            )
            .map(|_| ())
            .map_err(|error| QueueError::Storage(error.to_string()))
    }

    fn exec(&self, sql: &str, params: impl rusqlite::Params) -> Result<(), QueueError> {
        self.lock()?
            .execute(sql, params)
            .map(|_| ())
            .map_err(|error| QueueError::Storage(error.to_string()))
    }

    fn lock(&self) -> Result<std::sync::MutexGuard<'_, Connection>, QueueError> {
        self.connection
            .lock()
            .map_err(|_| QueueError::Storage("upload queue lock poisoned".to_string()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    fn temp_queue(max_bytes: i64) -> (UploadQueue, std::path::PathBuf) {
        static NEXT: AtomicU64 = AtomicU64::new(1);
        let path = std::env::temp_dir().join(format!(
            "local-run-upload-{}-{}.db",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = std::fs::remove_file(&path);
        let queue = UploadQueue::open(
            &path,
            UploadLimits {
                max_bytes,
                retention_ms: 24 * 60 * 60 * 1000,
                max_attempts: 3,
            },
        )
        .expect("queue");
        (queue, path)
    }

    #[test]
    fn queue_survives_reopen_and_isolates_accounts() {
        let (queue, path) = temp_queue(1024);
        queue
            .enqueue("alice", "device-a", "run-1", "events", "{\"ok\":true}", 10)
            .expect("enqueue");
        drop(queue);
        let reopened = UploadQueue::open(
            &path,
            UploadLimits {
                max_bytes: 1024,
                retention_ms: 24 * 60 * 60 * 1000,
                max_attempts: 3,
            },
        )
        .expect("reopen");
        let alice = reopened.due("alice", "device-a", 10).expect("due");
        assert_eq!(alice.len(), 1);
        assert!(reopened.due("bob", "device-a", 10).expect("bob").is_empty());
        assert!(reopened
            .due("alice", "device-b", 10)
            .expect("other device")
            .is_empty());
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn full_queue_returns_an_explicit_error() {
        let (queue, path) = temp_queue(8);
        let error = queue
            .enqueue("alice", "device-a", "run-1", "events", "0123456789", 10)
            .expect_err("full");
        assert!(matches!(error, QueueError::Full));
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn expired_pending_items_are_not_retried() {
        let (queue, path) = temp_queue(1024);
        queue
            .enqueue("alice", "device-a", "run-1", "events", "{}", 0)
            .expect("enqueue");
        let due = queue
            .due("alice", "device-a", 24 * 60 * 60 * 1000)
            .expect("due");
        assert!(due.is_empty());
        let _ = std::fs::remove_file(path);
    }
}
