//! MySQL-backed `MessageRepoPort` implementation via `bcs-db-api`.

use std::sync::Arc;

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatementBuilder, DbTransactionStep, db_get_column};
use tracing::{debug, info};

use bcs_domain::{
    MessageOwnerFilter, MessagePage, MessageQuery, NewMessage, PersistedMessage,
    PersistedMessageStatus, SenderType,
};
use bcs_service_api::port::repo::{MessageRepoError, MessageRepoPort};
use bcs_service_api::{ServiceError, ServiceResult};

// ---------------------------------------------------------------------------
// SQL constants
// ---------------------------------------------------------------------------

const SELECT_COLS: &str = "message_id, group_id, session_id, session_seq, env, \
    sender_id, sender_type, message_type, content, client_msg_id, status, \
    owner_bot_id, created_at, run_id";

// ---------------------------------------------------------------------------
// Public type
// ---------------------------------------------------------------------------

/// MySQL-backed message repository.
#[derive(Clone)]
pub struct MySqlMessageStore {
    db: Arc<dyn DbPlugin>,
    env: String,
    flavor: DbSqlFlavor,
}

impl MySqlMessageStore {
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

    /// Backend label for logs ("mysql" / "sqlite"), so persistence logs reflect
    /// the actual store rather than always claiming "(mysql)".
    fn backend_label(&self) -> &'static str {
        match self.flavor {
            DbSqlFlavor::Mysql => "mysql",
            DbSqlFlavor::Sqlite => "sqlite",
            DbSqlFlavor::Postgres => "postgres",
        }
    }
}

fn row_to_message(row: &bcs_db_api::DbRow) -> Result<PersistedMessage, MessageRepoError> {
    let content_str: String = db_get_column(row, "content")
        .map_err(|e| MessageRepoError::StorageError(format!("content: {}", e)))?;
    let content: serde_json::Value =
        serde_json::from_str(&content_str).unwrap_or(serde_json::Value::String(content_str));

    let sender_type_str: String = db_get_column(row, "sender_type")
        .map_err(|e| MessageRepoError::StorageError(format!("sender_type: {}", e)))?;
    let sender_type = match sender_type_str.as_str() {
        "bot" => SenderType::Bot,
        "human" => SenderType::Human,
        "system" => SenderType::System,
        other => {
            return Err(MessageRepoError::StorageError(format!(
                "unknown sender_type: {}",
                other
            )));
        }
    };

    let status_str: String = db_get_column(row, "status")
        .map_err(|e| MessageRepoError::StorageError(format!("status: {}", e)))?;
    let status = match status_str.as_str() {
        "normal" => PersistedMessageStatus::Normal,
        "recalled" => PersistedMessageStatus::Recalled,
        "deleted" => PersistedMessageStatus::Deleted,
        other => {
            return Err(MessageRepoError::StorageError(format!(
                "unknown status: {}",
                other
            )));
        }
    };

    let client_msg_id: Option<String> = row
        .get_string("client_msg_id")
        .map_err(|e| MessageRepoError::StorageError(format!("client_msg_id: {}", e)))?;
    let owner_bot_id: Option<String> = row
        .get_string("owner_bot_id")
        .map_err(|e| MessageRepoError::StorageError(format!("owner_bot_id: {}", e)))?;

    let created_at_i64: i64 = db_get_column(row, "created_at")
        .map_err(|e| MessageRepoError::StorageError(format!("created_at: {}", e)))?;

    let run_id: String = db_get_column(row, "run_id")
        .map_err(|e| MessageRepoError::StorageError(format!("run_id: {}", e)))?;

    Ok(PersistedMessage {
        message_id: db_get_column(row, "message_id")
            .map_err(|e| MessageRepoError::StorageError(format!("message_id: {}", e)))?,
        group_id: db_get_column(row, "group_id")
            .map_err(|e| MessageRepoError::StorageError(format!("group_id: {}", e)))?,
        session_id: db_get_column(row, "session_id")
            .map_err(|e| MessageRepoError::StorageError(format!("session_id: {}", e)))?,
        session_seq: db_get_column(row, "session_seq")
            .map_err(|e| MessageRepoError::StorageError(format!("session_seq: {}", e)))?,
        sender_id: db_get_column(row, "sender_id")
            .map_err(|e| MessageRepoError::StorageError(format!("sender_id: {}", e)))?,
        sender_type,
        message_type: db_get_column(row, "message_type")
            .map_err(|e| MessageRepoError::StorageError(format!("message_type: {}", e)))?,
        content,
        client_msg_id,
        owner_bot_id,
        status,
        created_at: created_at_i64 as u64,
        run_id,
    })
}

#[async_trait]
impl MessageRepoPort for MySqlMessageStore {
    async fn append_message(&self, msg: NewMessage) -> Result<PersistedMessage, MessageRepoError> {
        let message_id = uuid::Uuid::new_v4().to_string();

        // Step 1: Idempotency check
        if let Some(ref client_msg_id) = msg.client_msg_id {
            let check_stmt = DbStatementBuilder::new(self.flavor)
                .push_static("SELECT message_id, session_seq FROM bcs_messages WHERE group_id = ")
                .bind(msg.group_id.as_str())
                .push_static(" AND session_id = ")
                .bind(msg.session_id.as_str())
                .push_static(" AND sender_id = ")
                .bind(msg.sender_id.as_str())
                .push_static(" AND client_msg_id = ")
                .bind(client_msg_id.as_str())
                .build();
            let rows = self
                .db
                .query(check_stmt)
                .await
                .map_err(|e| MessageRepoError::StorageError(e.to_string()))?;
            if let Some(row) = rows.first() {
                let existing_id: String = db_get_column(row, "message_id")
                    .map_err(|e| MessageRepoError::StorageError(format!("message_id: {}", e)))?;
                debug!(
                    message_id = %existing_id,
                    "idempotent duplicate detected, returning existing message"
                );
                // Fetch full message
                let get_stmt = DbStatementBuilder::new(self.flavor)
                    .push_static("SELECT ")
                    .push_static(SELECT_COLS)
                    .push_static(" FROM bcs_messages WHERE message_id = ")
                    .bind(existing_id)
                    .build();
                let existing = self
                    .db
                    .query(get_stmt)
                    .await
                    .map_err(|e| MessageRepoError::StorageError(e.to_string()))?;
                if let Some(row) = existing.first() {
                    return row_to_message(row);
                }
            }
        }

        // Step 2: Atomic seq allocation via transaction
        let seq_update = DbStatementBuilder::new(self.flavor)
            .push_static(
                "UPDATE bcs_group_sessions SET current_msg_seq = current_msg_seq + 1 \
                 WHERE session_id = ",
            )
            .bind(msg.session_id.as_str())
            .build();
        let seq_select = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT current_msg_seq FROM bcs_group_sessions WHERE session_id = ")
            .bind(msg.session_id.as_str())
            .build();

        let steps: Vec<DbTransactionStep> = vec![
            DbTransactionStep::Execute(seq_update),
            DbTransactionStep::Query(seq_select),
        ];

        let tx_results = self
            .db
            .transaction(steps)
            .await
            .map_err(|e| MessageRepoError::StorageError(format!("transaction: {}", e)))?;

        let session_seq: i64 = match &tx_results[1] {
            bcs_db_api::DbTransactionStepResult::Rows(rows) => {
                let row = rows
                    .first()
                    .ok_or_else(|| MessageRepoError::SessionNotFound(msg.session_id.clone()))?;
                db_get_column(row, "current_msg_seq")
                    .map_err(|e| MessageRepoError::StorageError(format!("seq: {}", e)))?
            }
            _ => {
                return Err(MessageRepoError::SessionNotFound(msg.session_id.clone()));
            }
        };

        // Step 3: INSERT the message
        let sender_type_str = match msg.sender_type {
            SenderType::Bot => "bot",
            SenderType::Human => "human",
            SenderType::System => "system",
        };
        let content_str = msg.content.to_string();

        let insert_stmt = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO bcs_messages \
                 (message_id, group_id, session_id, session_seq, env, sender_id, sender_type, \
                  message_type, content, client_msg_id, owner_bot_id, status, created_at, run_id) \
                 VALUES (",
            )
            .bind(message_id.as_str())
            .push_static(", ")
            .bind(msg.group_id.as_str())
            .push_static(", ")
            .bind(msg.session_id.as_str())
            .push_static(", ")
            .bind(session_seq)
            .push_static(", ")
            .bind(self.env.as_str())
            .push_static(", ")
            .bind(msg.sender_id.as_str())
            .push_static(", ")
            .bind(sender_type_str)
            .push_static(", ")
            .bind(msg.message_type.as_str())
            .push_static(", ")
            .bind(content_str)
            .push_static(", ")
            .bind(msg.client_msg_id.clone())
            .push_static(", ")
            .bind(msg.owner_bot_id.clone())
            .push_static(", 'normal', ")
            .bind(msg.created_at)
            .push_static(", ")
            .bind(msg.run_id.as_str())
            .push_static(")")
            .build();

        self.db
            .execute(insert_stmt)
            .await
            .map_err(|e| MessageRepoError::StorageError(format!("insert: {}", e)))?;

        info!(
            session_id = %msg.session_id,
            message_id = %message_id,
            session_seq,
            backend = %self.backend_label(),
            "message persisted"
        );

        Ok(PersistedMessage {
            message_id,
            group_id: msg.group_id,
            session_id: msg.session_id,
            session_seq,
            sender_id: msg.sender_id,
            sender_type: msg.sender_type,
            message_type: msg.message_type,
            content: msg.content,
            client_msg_id: msg.client_msg_id,
            owner_bot_id: msg.owner_bot_id,
            status: PersistedMessageStatus::Normal,
            created_at: msg.created_at,
            run_id: msg.run_id,
        })
    }

    async fn query_messages(&self, query: MessageQuery) -> Result<MessagePage, MessageRepoError> {
        let limit = query.limit as usize;

        let mut statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT ")
            .push_static(SELECT_COLS)
            .push_static(" FROM bcs_messages WHERE group_id = ")
            .bind(query.group_id.as_str())
            .push_static(" AND session_id = ")
            .bind(query.session_id.as_str());

        if let Some(cursor) = query.cursor {
            statement = statement.push_static(" AND created_at < ").bind(cursor);
        }

        if let Some(ref sender_id) = query.sender_id {
            statement = statement
                .push_static(" AND sender_id = ")
                .bind(sender_id.as_str());
        }

        if let Some(ref msg_type) = query.message_type {
            statement = statement
                .push_static(" AND message_type = ")
                .bind(msg_type.as_str());
        }

        match &query.owner_filter {
            MessageOwnerFilter::Any => {}
            MessageOwnerFilter::IsNull => {
                statement = statement.push_static(" AND owner_bot_id IS NULL");
            }
            MessageOwnerFilter::Eq(owner_bot_id) => {
                statement = statement
                    .push_static(" AND owner_bot_id = ")
                    .bind(owner_bot_id.as_str());
            }
            MessageOwnerFilter::PublicOrOwner(owner_bot_id) => {
                statement = statement
                    .push_static(" AND (owner_bot_id IS NULL OR owner_bot_id = ")
                    .bind(owner_bot_id.as_str())
                    .push_static(")");
            }
        }

        if let Some(ref keyword) = query.keyword {
            statement = statement
                .push_static(" AND content LIKE ")
                .bind(format!("%{}%", keyword));
        }

        if let Some((start, end)) = query.time_range {
            statement = statement
                .push_static(" AND created_at >= ")
                .bind(start)
                .push_static(" AND created_at <= ")
                .bind(end);
        }

        if let Some(visible_from) = query.visible_from_seq {
            statement = statement
                .push_static(" AND session_seq >= ")
                .bind(visible_from);
        }

        // Fetch limit+1 to detect has_more
        let fetch_limit = (limit + 1) as u64;
        let stmt = statement
            .push_static(" ORDER BY created_at DESC, session_seq DESC LIMIT ")
            .bind(fetch_limit)
            .build();
        let rows = self
            .db
            .query(stmt)
            .await
            .map_err(|e| MessageRepoError::StorageError(e.to_string()))?;

        let has_more = rows.len() > limit;
        let rows = if has_more { &rows[..limit] } else { &rows[..] };

        let mut messages = Vec::with_capacity(rows.len());
        for row in rows {
            messages.push(row_to_message(row)?);
        }

        let next_cursor = if has_more {
            messages.last().map(|m| (m.created_at, m.session_seq))
        } else {
            None
        };

        info!(
            group_id = %query.group_id,
            session_id = %query.session_id,
            count = messages.len(),
            has_more,
            backend = %self.backend_label(),
            "messages queried"
        );
        Ok(MessagePage {
            messages,
            next_cursor,
            has_more,
        })
    }

    async fn get_message_by_id(
        &self,
        _session_id: &str,
        message_id: &str,
    ) -> Result<Option<PersistedMessage>, MessageRepoError> {
        let stmt = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT ")
            .push_static(SELECT_COLS)
            .push_static(" FROM bcs_messages WHERE message_id = ")
            .bind(message_id)
            .build();
        let rows = self
            .db
            .query(stmt)
            .await
            .map_err(|e| MessageRepoError::StorageError(e.to_string()))?;
        if let Some(row) = rows.first() {
            Ok(Some(row_to_message(row)?))
        } else {
            Ok(None)
        }
    }

    async fn get_current_seq(&self, session_id: &str) -> Result<i64, MessageRepoError> {
        let stmt = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT current_msg_seq FROM bcs_group_sessions WHERE session_id = ")
            .bind(session_id)
            .build();
        let rows = self
            .db
            .query(stmt)
            .await
            .map_err(|e| MessageRepoError::StorageError(e.to_string()))?;
        if let Some(row) = rows.first() {
            let seq: i64 = db_get_column(row, "current_msg_seq")
                .map_err(|e| MessageRepoError::StorageError(format!("current_msg_seq: {}", e)))?;
            Ok(seq)
        } else {
            Ok(0)
        }
    }

    /// Direct-read session history with full visibility predicates + cursor
    /// pagination. Sort is the legacy `created_at DESC, session_seq DESC`
    /// (newest first); `before` is an exclusive composite
    /// `(created_at, session_seq)` cursor so tied `created_at` rows are not
    /// skipped at a page boundary (VYQHI). SQL uses the
    /// `created_at < ? OR (created_at = ? AND session_seq < ?)` compound
    /// predicate because SQLite (used by the conformance test harness) does
    /// not support MySQL row-constructor comparison `(a, b) < (?, ?)`.
    ///
    /// VUlao: filters reads by the store's own `env` so one env cannot leak
    /// another env's messages (matches the INSERT-time env tagging).
    async fn list_session_history(
        &self,
        session_id: &str,
        owner_filter: MessageOwnerFilter,
        visible_from_seq: Option<i64>,
        before: Option<(u64, i64)>,
        limit: u32,
    ) -> ServiceResult<MessagePage> {
        let limit = limit as usize;

        let mut statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT ")
            .push_static(SELECT_COLS)
            .push_static(" FROM bcs_messages WHERE session_id = ")
            .bind(session_id)
            .push_static(" AND env = ")
            .bind(self.env.as_str());

        match &owner_filter {
            MessageOwnerFilter::Any => {}
            MessageOwnerFilter::IsNull => {
                statement = statement.push_static(" AND owner_bot_id IS NULL");
            }
            MessageOwnerFilter::Eq(owner) => {
                statement = statement
                    .push_static(" AND owner_bot_id = ")
                    .bind(owner.as_str());
            }
            MessageOwnerFilter::PublicOrOwner(owner) => {
                statement = statement
                    .push_static(" AND (owner_bot_id IS NULL OR owner_bot_id = ")
                    .bind(owner.as_str())
                    .push_static(")");
            }
        }

        if let Some(visible_from) = visible_from_seq {
            statement = statement
                .push_static(" AND session_seq >= ")
                .bind(visible_from);
        }

        // VYQHI: composite (created_at, session_seq) strict-less bound. The
        // compound `created_at < ? OR (created_at = ? AND session_seq < ?)`
        // is equivalent to the row-constructor `(created_at, session_seq) <
        // (?, ?)` and runs on both MySQL and SQLite.
        if let Some((cursor_ts, cursor_seq)) = before {
            statement = statement
                .push_static(" AND (created_at < ")
                .bind(cursor_ts)
                .push_static(" OR (created_at = ")
                .bind(cursor_ts)
                .push_static(" AND session_seq < ")
                .bind(cursor_seq)
                .push_static("))");
        }

        // Fetch limit+1 to detect has_more.
        let fetch_limit = (limit + 1) as u64;
        let statement = statement
            .push_static(" ORDER BY created_at DESC, session_seq DESC LIMIT ")
            .bind(fetch_limit)
            .build();

        let rows =
            self.db.query(statement).await.map_err(|e| {
                ServiceError::InternalError(format!("list_session_history query: {e}"))
            })?;

        let has_more = rows.len() > limit;
        let rows = if has_more { &rows[..limit] } else { &rows[..] };

        let mut messages = Vec::with_capacity(rows.len());
        for row in rows {
            messages.push(row_to_message(row).map_err(|e| {
                ServiceError::InternalError(format!("list_session_history row: {e}"))
            })?);
        }

        let next_cursor = if has_more {
            messages.last().map(|m| (m.created_at, m.session_seq))
        } else {
            None
        };

        info!(
            session_id = %session_id,
            count = messages.len(),
            has_more,
            visible_from_seq = ?visible_from_seq,
            owner_filter = ?owner_filter,
            backend = %self.backend_label(),
            "session history listed"
        );
        Ok(MessagePage {
            messages,
            next_cursor,
            has_more,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use std::{collections::BTreeMap, sync::Arc};

    use bcs_db_api::{
        DbError, DbExecuteResult, DbHealth, DbResult, DbRow, DbStatement, DbTransactionStepResult,
        DbValue,
    };
    use tokio::sync::Mutex;

    #[derive(Default)]
    struct CapturingDb {
        executed: Mutex<Vec<DbStatement>>,
    }

    #[async_trait]
    impl DbPlugin for CapturingDb {
        async fn query(&self, _statement: DbStatement) -> DbResult<Vec<DbRow>> {
            Ok(Vec::new())
        }

        async fn execute(&self, statement: DbStatement) -> DbResult<DbExecuteResult> {
            self.executed.lock().await.push(statement);
            Ok(DbExecuteResult::default())
        }

        async fn transaction(
            &self,
            steps: Vec<DbTransactionStep>,
        ) -> DbResult<Vec<DbTransactionStepResult>> {
            if steps.len() != 2 {
                return Err(DbError::InvalidInput(format!(
                    "unexpected transaction steps: {}",
                    steps.len()
                )));
            }
            let mut row = BTreeMap::new();
            row.insert("current_msg_seq".to_string(), DbValue::from(1_i64));
            Ok(vec![
                DbTransactionStepResult::Executed(DbExecuteResult {
                    affected_rows: 1,
                    last_insert_id: None,
                }),
                DbTransactionStepResult::Rows(vec![DbRow::new(row)]),
            ])
        }

        async fn health_check(&self) -> DbResult<DbHealth> {
            Ok(DbHealth::healthy())
        }
    }

    #[tokio::test]
    async fn append_message_binds_missing_client_msg_id_as_null() {
        let db = Arc::new(CapturingDb::default());
        let store = MySqlMessageStore::new(db.clone(), "dev".to_string());

        store
            .append_message(NewMessage {
                group_id: "group-1".to_string(),
                session_id: "group-1:session".to_string(),
                sender_id: "bot-worker".to_string(),
                sender_type: SenderType::Bot,
                message_type: "chat".to_string(),
                content: serde_json::json!("hello"),
                client_msg_id: None,
                owner_bot_id: Some("bot-worker".to_string()),
                created_at: 1,
                run_id: "run-1".to_string(),
            })
            .await
            .expect("append should succeed");

        let executed = db.executed.lock().await;
        let insert = executed.first().expect("expected insert statement");
        assert_eq!(insert.params().get(9), Some(&DbValue::Null));
        assert_eq!(
            insert.params().get(10),
            Some(&DbValue::from(Some("bot-worker".to_string())))
        );
    }

    #[tokio::test]
    async fn postgres_append_uses_numbered_typed_binds() {
        let db = Arc::new(CapturingDb::default());
        let store = MySqlMessageStore::postgres(db.clone(), "dev".to_string());

        let result = store
            .append_message(NewMessage {
                group_id: "group-1".to_string(),
                session_id: "group-1:session".to_string(),
                sender_id: "bot-worker".to_string(),
                sender_type: SenderType::Bot,
                message_type: "terminal".to_string(),
                content: serde_json::json!({"status": "completed"}),
                client_msg_id: None,
                owner_bot_id: Some("bot-worker".to_string()),
                created_at: 1,
                run_id: "run-1".to_string(),
            })
            .await;

        assert!(result.is_ok());
        let executed = db.executed.lock().await;
        let insert = match executed.first() {
            Some(statement) => statement,
            None => panic!("expected insert statement"),
        };
        assert!(insert.sql().contains("VALUES ($1, $2, $3, $4, $5, $6, $7"));
        assert!(insert.sql().contains("$10, $11, 'normal', $12, $13)"));
        assert!(!insert.sql().contains('?'));
        assert_eq!(insert.params().get(9), Some(&DbValue::Null));
    }
}
