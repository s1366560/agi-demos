//! MySQL-backed `SessionFileRepoPort` implementation via `bcs-db-api`.
//!
//! Parameterized SQL is emitted through `DbStatementBuilder`, preserving
//! MySQL/SQLite `?` binds and PostgreSQL `$1..$n` binds without rewriting SQL.

use std::sync::Arc;

use async_trait::async_trait;

use bcs_db_api::{
    DbPlugin, DbRow, DbSqlFlavor, DbStatementBuilder, db_get_column, db_get_column_opt,
};
use bcs_domain::{ActorKind, ActorRef, FileStatus, SessionFile};
use bcs_service_api::port::repo::{
    NewSessionFileParams, SessionFileListPage, SessionFileListParams, SessionFileRepoPort,
};
use bcs_service_api::{ServiceError, ServiceResult};

// ---------------------------------------------------------------------------
// SQL constants
// ---------------------------------------------------------------------------

/// Base SELECT columns (everything except the timestamp projections, which are
/// flavor-aware — see [`MySqlSessionFileStore::select_statement`]).
const SELECT_BASE_COLS: &str = "file_id, session_id, file_name, mime_type, size, sha256, \
    storage_backend, object_handle, status, owner_actor_kind, owner_actor_id";

// ---------------------------------------------------------------------------
// Public type
// ---------------------------------------------------------------------------

/// MySQL/SQLite-backed session file metadata repository.
///
/// `created_at`/`updated_at` are NOT stored columns — the table has only the
/// DB-managed `gmt_create`/`gmt_modified` audit timestamps. The domain fields
/// are projected from those on read (epoch seconds) in a flavor-aware way
/// (`UNIX_TIMESTAMP` on MySQL, `strftime('%s', …)` on SQLite), and `list`
/// orders by `gmt_create DESC` (newest uploads first). `json_extract` is lowercase for MySQL/SQLite
/// portability, so the dialect branches are the timestamp projection and the
/// `expires_at` JSON cast (`... AS SIGNED` on MySQL, `... AS INTEGER` on SQLite).
#[derive(Clone)]
pub struct MySqlSessionFileStore {
    db: Arc<dyn DbPlugin>,
    env: String,
    flavor: DbSqlFlavor,
}

impl MySqlSessionFileStore {
    /// MySQL-backed constructor.
    pub fn new(db: Arc<dyn DbPlugin>, env: String) -> Self {
        Self::with_flavor(db, env, DbSqlFlavor::Mysql)
    }

    /// SQLite-backed constructor (local dev via `bcs-db-local`).
    pub fn sqlite(db: Arc<dyn DbPlugin>, env: String) -> Self {
        Self::with_flavor(db, env, DbSqlFlavor::Sqlite)
    }

    /// PostgreSQL-backed constructor.
    pub fn postgres(db: Arc<dyn DbPlugin>, env: String) -> Self {
        Self::with_flavor(db, env, DbSqlFlavor::Postgres)
    }

    /// Flavor-explicit constructor (used by bootstrap, which knows `db_kind`).
    pub fn with_flavor(db: Arc<dyn DbPlugin>, env: String, flavor: DbSqlFlavor) -> Self {
        Self { db, env, flavor }
    }
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

fn now_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// Read a column as `i64` and cast to `u64`, clamping negatives to 0.
fn column_u64(row: &DbRow, name: &str) -> u64 {
    db_get_column_opt::<i64>(row, name)
        .ok()
        .flatten()
        .map(|v| v.max(0) as u64)
        .unwrap_or(0)
}

/// Parse the `status` column string into `FileStatus`.
fn parse_status(raw: &str) -> ServiceResult<FileStatus> {
    serde_json::from_value(serde_json::Value::String(raw.to_string()))
        .map_err(|e| ServiceError::InternalError(format!("parse status: {e}")))
}

/// Flavor-aware SQL cast of `object_handle->'$.expires_at'` to an integer for
/// comparison. MySQL/OceanBase only accept `CAST(... AS SIGNED)` (their `CAST`
/// has no `INTEGER` target); SQLite only accepts `CAST(... AS INTEGER)`.
fn expires_at_cast(flavor: DbSqlFlavor) -> &'static str {
    match flavor {
        DbSqlFlavor::Mysql => "CAST(json_extract(object_handle, '$.expires_at') AS SIGNED)",
        DbSqlFlavor::Sqlite => "CAST(json_extract(object_handle, '$.expires_at') AS INTEGER)",
        DbSqlFlavor::Postgres => "CAST(CAST(object_handle AS JSONB) ->> 'expires_at' AS BIGINT)",
    }
}

impl MySqlSessionFileStore {
    /// Full SELECT column list, projecting `created_at`/`updated_at` (epoch
    /// seconds) from the DB-managed `gmt_create`/`gmt_modified` in a
    /// flavor-aware way. `UNIX_TIMESTAMP` is wrapped in `CAST(... AS SIGNED)`
    /// so MySQL's fractional-timestamp DOUBLE result decodes cleanly to i64
    /// (SQLite's `strftime('%s', …)` already yields INTEGER).
    fn select_statement(&self) -> DbStatementBuilder {
        select_statement_for(self.flavor)
    }
}

fn select_statement_for(flavor: DbSqlFlavor) -> DbStatementBuilder {
    let statement = DbStatementBuilder::new(flavor)
        .push_static("SELECT ")
        .push_static(SELECT_BASE_COLS)
        .push_static(", ");
    let statement = match flavor {
        DbSqlFlavor::Mysql => statement.push_static(
            "CAST(UNIX_TIMESTAMP(gmt_create) AS SIGNED) AS created_at, \
             CAST(UNIX_TIMESTAMP(gmt_modified) AS SIGNED) AS updated_at",
        ),
        DbSqlFlavor::Sqlite => statement.push_static(
            "CAST(strftime('%s', gmt_create) AS INTEGER) AS created_at, \
             CAST(strftime('%s', gmt_modified) AS INTEGER) AS updated_at",
        ),
        DbSqlFlavor::Postgres => statement.push_static(
            "CAST(EXTRACT(EPOCH FROM gmt_create) AS BIGINT) AS created_at, \
             CAST(EXTRACT(EPOCH FROM gmt_modified) AS BIGINT) AS updated_at",
        ),
    };
    statement.push_static(" FROM bcs_session_files")
}

/// Convert a DB row into a `SessionFile`.
fn row_to_session(row: &DbRow) -> ServiceResult<SessionFile> {
    let actor_kind_str: String = db_get_column_opt(row, "owner_actor_kind")
        .map_err(|e| ServiceError::InternalError(format!("owner_actor_kind: {e}")))?
        .unwrap_or_else(|| "Human".to_string());
    let actor_kind = match actor_kind_str.as_str() {
        "Bot" => ActorKind::Bot,
        _ => ActorKind::Human,
    };
    Ok(SessionFile {
        file_id: db_get_column(row, "file_id")
            .map_err(|e| ServiceError::InternalError(format!("file_id: {e}")))?,
        session_id: db_get_column(row, "session_id")
            .map_err(|e| ServiceError::InternalError(format!("session_id: {e}")))?,
        file_name: db_get_column(row, "file_name")
            .map_err(|e| ServiceError::InternalError(format!("file_name: {e}")))?,
        mime_type: db_get_column(row, "mime_type")
            .map_err(|e| ServiceError::InternalError(format!("mime_type: {e}")))?,
        size: column_u64(row, "size"),
        sha256: db_get_column_opt(row, "sha256")
            .map_err(|e| ServiceError::InternalError(format!("sha256: {e}")))?,
        owner: ActorRef {
            actor_kind,
            actor_id: db_get_column(row, "owner_actor_id")
                .map_err(|e| ServiceError::InternalError(format!("owner_actor_id: {e}")))?,
        },
        storage_backend: db_get_column(row, "storage_backend")
            .map_err(|e| ServiceError::InternalError(format!("storage_backend: {e}")))?,
        object_handle: db_get_column(row, "object_handle")
            .map_err(|e| ServiceError::InternalError(format!("object_handle: {e}")))?,
        status: {
            let raw: String = db_get_column(row, "status")
                .map_err(|e| ServiceError::InternalError(format!("status: {e}")))?;
            parse_status(&raw)?
        },
        created_at: column_u64(row, "created_at"),
        updated_at: column_u64(row, "updated_at"),
    })
}

// ---------------------------------------------------------------------------
// SessionFileRepoPort impl
// ---------------------------------------------------------------------------

#[async_trait]
impl SessionFileRepoPort for MySqlSessionFileStore {
    async fn insert(&self, params: NewSessionFileParams) -> ServiceResult<SessionFile> {
        // created_at/updated_at are NOT stored columns: the table carries only
        // DB-managed gmt_create/gmt_modified. The returned row's timestamps are
        // the application now (≈ DB gmt_create); re-reads (get/list) project
        // them from gmt_*. expires_at lives inside object_handle JSON.
        let now = now_secs();
        let actor_kind_str = match params.owner.actor_kind {
            ActorKind::Bot => "Bot",
            ActorKind::Human => "Human",
        };

        let stmt = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO bcs_session_files \
                 (env, file_id, session_id, owner_actor_kind, owner_actor_id, file_name, \
                  mime_type, size, storage_backend, object_handle, status) VALUES (",
            )
            .bind(self.env.as_str())
            .push_static(", ")
            .bind(params.file_id.as_str())
            .push_static(", ")
            .bind(params.session_id.as_str())
            .push_static(", ")
            .bind(actor_kind_str)
            .push_static(", ")
            .bind(params.owner.actor_id.as_str())
            .push_static(", ")
            .bind(params.file_name.as_str())
            .push_static(", ")
            .bind(params.mime_type.as_str())
            .push_static(", ")
            .bind(params.size)
            .push_static(", ")
            .bind(params.storage_backend.as_str())
            .push_static(", ")
            .bind(params.object_handle.as_str())
            .push_static(", 'Pending')")
            .build();

        self.db
            .execute(stmt)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session file insert: {e}")))?;

        Ok(SessionFile {
            file_id: params.file_id,
            session_id: params.session_id,
            file_name: params.file_name,
            mime_type: params.mime_type,
            size: params.size,
            sha256: None,
            owner: params.owner,
            storage_backend: params.storage_backend,
            object_handle: params.object_handle,
            status: FileStatus::Pending,
            created_at: now,
            updated_at: now,
        })
    }

    async fn get(&self, session_id: &str, file_id: &str) -> ServiceResult<Option<SessionFile>> {
        let statement = self
            .select_statement()
            .push_static(" WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .push_static(" AND file_id = ")
            .bind(file_id)
            .push_static(" LIMIT 1")
            .build();
        let rows = self
            .db
            .query(statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session file get: {e}")))?;
        Ok(rows
            .into_iter()
            .next()
            .map(|r| row_to_session(&r))
            .transpose()?)
    }

    async fn get_by_file_id(&self, file_id: &str) -> ServiceResult<Option<SessionFile>> {
        let statement = self
            .select_statement()
            .push_static(" WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND file_id = ")
            .bind(file_id)
            .push_static(" LIMIT 1")
            .build();
        let rows = self.db.query(statement).await.map_err(|e| {
            ServiceError::InternalError(format!("session file get_by_file_id: {e}"))
        })?;
        Ok(rows
            .into_iter()
            .next()
            .map(|r| row_to_session(&r))
            .transpose()?)
    }

    async fn update_object_handle_and_status(
        &self,
        session_id: &str,
        file_id: &str,
        object_handle: &str,
        status: FileStatus,
        size: u64,
    ) -> ServiceResult<Option<SessionFile>> {
        let status_str = serde_json::to_string(&status)
            .map_err(|e| ServiceError::InternalError(format!("serialize status: {e}")))?;
        // The serialized form has surrounding quotes; strip them for the DB TEXT column.
        let status_str = status_str.trim_matches('"');

        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_session_files SET object_handle = ")
            .bind(object_handle)
            .push_static(", status = ")
            .bind(status_str)
            .push_static(", size = ")
            .bind(size)
            .push_static(" WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .push_static(" AND file_id = ")
            .bind(file_id)
            .build();

        self.db
            .execute(statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session file update: {e}")))?;

        // Re-SELECT to return the updated state.
        self.get(session_id, file_id).await
    }

    async fn update_status(
        &self,
        session_id: &str,
        file_id: &str,
        status: FileStatus,
    ) -> ServiceResult<Option<SessionFile>> {
        let status_str = serde_json::to_string(&status)
            .map_err(|e| ServiceError::InternalError(format!("serialize status: {e}")))?;
        let status_str = status_str.trim_matches('"');

        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_session_files SET status = ")
            .bind(status_str)
            .push_static(" WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .push_static(" AND file_id = ")
            .bind(file_id)
            .build();

        self.db
            .execute(statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session file update_status: {e}")))?;

        self.get(session_id, file_id).await
    }

    async fn delete(&self, session_id: &str, file_id: &str) -> ServiceResult<bool> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_session_files WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .push_static(" AND file_id = ")
            .bind(file_id)
            .build();
        let result = self
            .db
            .execute(statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session file delete: {e}")))?;
        Ok(result.affected_rows > 0)
    }

    async fn list(
        &self,
        session_id: &str,
        params: SessionFileListParams,
    ) -> ServiceResult<SessionFileListPage> {
        let build_filter = |statement: DbStatementBuilder| {
            statement
                .push_static(" WHERE env = ")
                .bind(self.env.as_str())
                .push_static(" AND session_id = ")
                .bind(session_id)
        };
        let mut count_statement = build_filter(
            DbStatementBuilder::new(self.flavor)
                .push_static("SELECT COUNT(*) AS cnt FROM bcs_session_files"),
        );
        let mut page_statement = build_filter(self.select_statement());

        // Optional prefix filter (file_name LIKE 'prefix%')
        if let Some(ref prefix) = params.prefix {
            let value = format!("{}%", prefix);
            count_statement = count_statement
                .push_static(" AND file_name LIKE ")
                .bind(value.clone());
            page_statement = page_statement
                .push_static(" AND file_name LIKE ")
                .bind(value);
        }

        // Optional status filter
        if let Some(ref status) = params.status {
            let status_str = serde_json::to_string(status)
                .map_err(|e| ServiceError::InternalError(format!("serialize status: {e}")))?;
            let status_str = status_str.trim_matches('"');
            count_statement = count_statement
                .push_static(" AND status = ")
                .bind(status_str);
            page_statement = page_statement
                .push_static(" AND status = ")
                .bind(status_str);
        }

        // Clamp limit to [1, 1000], defaulting to 100.
        let limit_u32 = if params.limit == 0 {
            100
        } else {
            params.limit.min(1000)
        };

        // COUNT query
        let count_rows =
            self.db.query(count_statement.build()).await.map_err(|e| {
                ServiceError::InternalError(format!("session file list count: {e}"))
            })?;
        let total = count_rows
            .first()
            .map(|r| db_get_column::<i64>(r, "cnt").unwrap_or(0) as u64)
            .unwrap_or(0);

        let page_statement = page_statement
            .push_static(" ORDER BY gmt_create DESC, file_id DESC LIMIT ")
            .bind(limit_u32)
            .push_static(" OFFSET ")
            .bind(params.offset)
            .build();

        let rows = self
            .db
            .query(page_statement)
            .await
            .map_err(|e| ServiceError::InternalError(format!("session file list: {e}")))?;

        let items: Vec<SessionFile> = rows
            .into_iter()
            .map(|r| row_to_session(&r))
            .collect::<ServiceResult<Vec<_>>>()?;

        Ok(SessionFileListPage { items, total })
    }

    async fn list_expired_pending(&self, now: u64, limit: u32) -> ServiceResult<Vec<SessionFile>> {
        // Use lowercase `json_extract` for both MySQL and SQLite portability.
        // The `expires_at` cast must be flavor-aware (see [`expires_at_cast`]):
        // MySQL/OceanBase reject `CAST(... AS INTEGER)` (only `AS SIGNED`),
        // SQLite needs `AS INTEGER`.
        let statement = self
            .select_statement()
            .push_static(" WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND status = 'Pending' AND ")
            .push_static(expires_at_cast(self.flavor))
            .push_static(" < ")
            .bind(now)
            .push_static(" LIMIT ")
            .bind(limit)
            .build();

        let rows = self.db.query(statement).await.map_err(|e| {
            ServiceError::InternalError(format!("session file list_expired_pending: {e}"))
        })?;

        rows.into_iter()
            .map(|r| row_to_session(&r))
            .collect::<ServiceResult<Vec<_>>>()
    }

    async fn delete_all_for_session(&self, session_id: &str) -> ServiceResult<Vec<SessionFile>> {
        // Step 1: SELECT all rows for the session.
        let select_statement = self
            .select_statement()
            .push_static(" WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .build();
        let rows = self.db.query(select_statement).await.map_err(|e| {
            ServiceError::InternalError(format!("session file delete_all select: {e}"))
        })?;

        let removed: Vec<SessionFile> = rows
            .into_iter()
            .map(|r| row_to_session(&r))
            .collect::<ServiceResult<Vec<_>>>()?;

        // Step 2: DELETE all rows for the session.
        let delete_statement = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_session_files WHERE env = ")
            .bind(self.env.as_str())
            .push_static(" AND session_id = ")
            .bind(session_id)
            .build();
        self.db.execute(delete_statement).await.map_err(|e| {
            ServiceError::InternalError(format!("session file delete_all delete: {e}"))
        })?;

        Ok(removed)
    }
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use bcs_db_api::DbValue;
    use bcs_domain::ActorKind;

    #[test]
    fn parse_status_decodes_serde_variants() {
        // DB stores the PascalCase variant name without JSON quoting.
        assert_eq!(parse_status("Pending").unwrap(), FileStatus::Pending);
        assert_eq!(parse_status("Ready").unwrap(), FileStatus::Ready);
        assert_eq!(parse_status("Deleting").unwrap(), FileStatus::Deleting);
        assert_eq!(parse_status("Failed").unwrap(), FileStatus::Failed);
    }

    #[test]
    fn parse_status_unknown_falls_back_to_pending() {
        // serde_json::from_value for an unknown variant will fail;
        // parse_status propagates the error (it does not fall back).
        assert!(parse_status("Unknown").is_err());
    }

    #[test]
    fn actor_kind_mapping() {
        let row = DbRow::new(
            vec![
                ("file_id".to_string(), DbValue::from("f1")),
                ("session_id".to_string(), DbValue::from("s1")),
                ("file_name".to_string(), DbValue::from("test.txt")),
                ("mime_type".to_string(), DbValue::from("text/plain")),
                ("size".to_string(), DbValue::I64(100)),
                ("sha256".to_string(), DbValue::Null),
                ("storage_backend".to_string(), DbValue::from("local")),
                ("object_handle".to_string(), DbValue::from("{}")),
                ("status".to_string(), DbValue::from("Pending")),
                ("created_at".to_string(), DbValue::I64(1000)),
                ("updated_at".to_string(), DbValue::I64(2000)),
                ("owner_actor_kind".to_string(), DbValue::from("Bot")),
                ("owner_actor_id".to_string(), DbValue::from("bot_1")),
            ]
            .into_iter()
            .collect(),
        );
        let sf = row_to_session(&row).unwrap();
        assert_eq!(sf.owner.actor_kind, ActorKind::Bot);
        assert_eq!(sf.owner.actor_id, "bot_1");
        assert_eq!(sf.size, 100);
        assert_eq!(sf.created_at, 1000);
        assert_eq!(sf.updated_at, 2000);
        assert_eq!(sf.status, FileStatus::Pending);
    }
    #[test]
    fn expires_at_cast_is_flavor_aware() {
        assert!(expires_at_cast(DbSqlFlavor::Mysql).contains("AS SIGNED"));
        assert!(!expires_at_cast(DbSqlFlavor::Mysql).contains("AS INTEGER"));
        assert!(expires_at_cast(DbSqlFlavor::Sqlite).contains("AS INTEGER"));
        assert!(expires_at_cast(DbSqlFlavor::Postgres).contains("AS JSONB"));
    }

    #[test]
    fn postgres_select_uses_numbered_binds_and_epoch_projection() {
        let statement = select_statement_for(DbSqlFlavor::Postgres)
            .push_static(" WHERE env = ")
            .bind("dev")
            .push_static(" AND file_id = ")
            .bind("file-1")
            .build();

        assert!(statement.sql().contains("EXTRACT(EPOCH FROM gmt_create)"));
        assert!(statement.sql().ends_with("WHERE env = $1 AND file_id = $2"));
        assert!(!statement.sql().contains('?'));
    }
}
