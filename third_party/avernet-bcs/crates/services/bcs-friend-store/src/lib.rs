//! Database-backed implementation of friend repository ports.
//!
//! This store owns friend-domain SQL and depends only on the driver-level
//! `bcs-db-api` contract. The composition root decides which concrete DB
//! plugin backs it.

use std::sync::Arc;

use async_trait::async_trait;
use tracing::{debug, info, warn};

use bcs_config::resolve_env_str as resolve_env;
use bcs_db_api::{DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder, DbValue};
pub use bcs_service_api::port::repo::{FriendRepoPort, FriendRequestRepoPort};
use bcs_service_api::{
    FriendRequest, FriendRequestDirection, FriendRequestStatus, Friendship, ServiceError,
    ServiceResult,
};

pub type FriendSqlFlavor = DbSqlFlavor;

pub mod memory;

pub use memory::{MemoryFriendRepo, MemoryFriendRequestRepo};

/// MySQL-backed friendship repository.
pub type MysqlFriendRepo = DbFriendStore;

/// SQLite-backed friendship repository.
pub type SqliteFriendRepo = DbFriendStore;

/// MySQL-backed friend-request repository.
pub type MysqlFriendRequestRepo = DbFriendRequestStore;

/// SQLite-backed friend-request repository.
pub type SqliteFriendRequestRepo = DbFriendRequestStore;

/// DB-backed friend store operating on `bcs_friendships`.
pub struct DbFriendStore {
    db: Arc<dyn DbPlugin>,
    flavor: FriendSqlFlavor,
}

impl DbFriendStore {
    pub fn new(db: Arc<dyn DbPlugin>, flavor: FriendSqlFlavor) -> Self {
        Self { db, flavor }
    }

    pub fn mysql(db: Arc<dyn DbPlugin>) -> Self {
        Self::new(db, FriendSqlFlavor::Mysql)
    }

    pub fn sqlite(db: Arc<dyn DbPlugin>) -> Self {
        Self::new(db, FriendSqlFlavor::Sqlite)
    }

    pub fn postgres(db: Arc<dyn DbPlugin>) -> Self {
        Self::new(db, FriendSqlFlavor::Postgres)
    }

    fn insert_friendship_statement(&self, left: &str, right: &str, env: &str) -> DbStatement {
        let builder = match self.flavor {
            FriendSqlFlavor::Mysql => DbStatementBuilder::new(self.flavor).push_static(
                "INSERT IGNORE INTO bcs_friendships (left_bot, right_bot, env) VALUES (",
            ),
            FriendSqlFlavor::Sqlite => DbStatementBuilder::new(self.flavor).push_static(
                "INSERT OR IGNORE INTO bcs_friendships (left_bot, right_bot, env) VALUES (",
            ),
            FriendSqlFlavor::Postgres => DbStatementBuilder::new(self.flavor)
                .push_static("INSERT INTO bcs_friendships (left_bot, right_bot, env) VALUES ("),
        };
        let builder = builder
            .bind(left)
            .push_static(", ")
            .bind(right)
            .push_static(", ")
            .bind(env)
            .push_static(")");
        match self.flavor {
            FriendSqlFlavor::Postgres => builder.push_static(" ON CONFLICT DO NOTHING").build(),
            FriendSqlFlavor::Mysql | FriendSqlFlavor::Sqlite => builder.build(),
        }
    }

    async fn execute(&self, operation: &'static str, statement: DbStatement) -> ServiceResult<u64> {
        self.db
            .execute(statement)
            .await
            .map(|result| result.affected_rows)
            .map_err(|err| {
                warn!(operation, error = %err, "db_friend: execute failed");
                service_db_error(operation, err)
            })
    }

    /// Per-flavor SELECT fragment for the `gmt_create` column on
    /// `bcs_friendships`, emitted under alias `gmt_create_ts` as Unix-epoch
    /// seconds (TZ-correct in both backends). Mirrors the timestamp helpers on
    /// `DbFriendRequestStore`.
    fn select_created_at_column(&self) -> &'static str {
        match self.flavor {
            FriendSqlFlavor::Mysql => "UNIX_TIMESTAMP(gmt_create) AS gmt_create_ts",
            FriendSqlFlavor::Sqlite => {
                "CAST(strftime('%s', gmt_create) AS INTEGER) AS gmt_create_ts"
            }
            FriendSqlFlavor::Postgres => {
                "CAST(EXTRACT(EPOCH FROM gmt_create) AS BIGINT) AS gmt_create_ts"
            }
        }
    }
}

#[async_trait]
impl FriendRepoPort for DbFriendStore {
    async fn list_friends(&self, bot_id: &str) -> ServiceResult<Vec<String>> {
        let env = resolve_env();
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT left_bot, right_bot FROM bcs_friendships \
                 WHERE (left_bot = ",
            )
            .bind(bot_id)
            .push_static(" OR right_bot = ")
            .bind(bot_id)
            .push_static(") AND env = ")
            .bind(env.as_str())
            .build();
        let rows = match self.db.query(statement).await {
            Ok(rows) => rows,
            Err(err) => {
                warn!(bot_id = %bot_id, error = %err, "Failed to list friends from DB");
                return Err(service_db_error("list_friends", err));
            }
        };

        let mut friends = Vec::new();
        for row in rows {
            let left = optional_string(&row, "left_bot");
            let right = optional_string(&row, "right_bot");
            match (left, right) {
                (Some(left), Some(right)) if left == bot_id => friends.push(right),
                (Some(left), Some(right)) if right == bot_id => friends.push(left),
                _ => {}
            }
        }
        Ok(friends)
    }

    async fn are_friends(&self, bot_a: &str, bot_b: &str) -> ServiceResult<bool> {
        let (left, right) = normalize_pair(bot_a, bot_b);
        let env = resolve_env();
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT 1 FROM bcs_friendships WHERE left_bot = ")
            .bind(left.as_str())
            .push_static(" AND right_bot = ")
            .bind(right.as_str())
            .push_static(" AND env = ")
            .bind(env.as_str())
            .push_static(" LIMIT 1")
            .build();

        self
            .db
            .query(statement)
            .await
            .map(|rows| !rows.is_empty())
            .map_err(|err| {
                warn!(left_bot = %left, right_bot = %right, error = %err, "Failed to check friendship from DB");
                service_db_error("are_friends", err)
            })
    }

    async fn add_friendship(&self, bot_a: &str, bot_b: &str) -> ServiceResult<()> {
        let (left, right) = normalize_pair(bot_a, bot_b);
        let env = resolve_env();

        let affected = self
            .execute(
                "add_friendship",
                self.insert_friendship_statement(left.as_str(), right.as_str(), env.as_str()),
            )
            .await?;

        if affected == 0 {
            debug!(left_bot = %left, right_bot = %right, "Friendship already existed (DB)");
            return Ok(());
        }

        info!(left_bot = %left, right_bot = %right, "Friendship established (DB)");

        Ok(())
    }

    async fn remove_all_friendships(&self, bot_id: &str) -> ServiceResult<usize> {
        let env = resolve_env();
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_friendships WHERE (left_bot = ")
            .bind(bot_id)
            .push_static(" OR right_bot = ")
            .bind(bot_id)
            .push_static(") AND env = ")
            .bind(env.as_str())
            .build();
        let affected = self.execute("remove_all_friendships", statement).await?;

        if affected > 0 {
            info!(bot_id = %bot_id, removed = affected, "Removed all friendships for bot (DB)");
        }

        Ok(affected as usize)
    }

    async fn list_friendships_paginated(
        &self,
        bot_id: &str,
        offset: u64,
        limit: u64,
    ) -> ServiceResult<(Vec<Friendship>, u64)> {
        let env = resolve_env();
        let ts = self.select_created_at_column();
        // The friend is the "other" column; ORDER BY the projected friend uuid
        // ascending as the tie-breaker after `gmt_create` DESC. Both flavors
        // support CASE expressions in ORDER BY.
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT left_bot, right_bot, ")
            .push_static(ts)
            .push_static(" FROM bcs_friendships WHERE (left_bot = ")
            .bind(bot_id)
            .push_static(" OR right_bot = ")
            .bind(bot_id)
            .push_static(") AND env = ")
            .bind(env.as_str())
            .push_static(" ORDER BY gmt_create DESC, CASE WHEN left_bot = ")
            .bind(bot_id)
            .push_static(" THEN right_bot ELSE left_bot END ASC LIMIT ")
            .bind(limit)
            .push_static(" OFFSET ")
            .bind(offset)
            .build();
        let rows = self.db.query(statement).await.map_err(|err| {
            warn!(bot_id = %bot_id, error = %err, "Failed to list friendships paginated from DB");
            service_db_error("list_friendships_paginated", err)
        })?;

        let mut friendships = Vec::with_capacity(rows.len());
        for row in &rows {
            let left = optional_string(row, "left_bot");
            let right = optional_string(row, "right_bot");
            match (left, right) {
                (Some(left), Some(right)) => {
                    let friend_bot_uuid = if left == bot_id { right } else { left };
                    friendships.push(Friendship {
                        bot_uuid: bot_id.to_string(),
                        friend_bot_uuid,
                        created_at: row_seconds_to_millis(row, "gmt_create_ts"),
                    });
                }
                _ => {}
            }
        }

        let count_statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT COUNT(*) AS cnt FROM bcs_friendships WHERE (left_bot = ")
            .bind(bot_id)
            .push_static(" OR right_bot = ")
            .bind(bot_id)
            .push_static(") AND env = ")
            .bind(env.as_str())
            .build();
        let count_rows = self.db.query(count_statement).await.map_err(|err| {
            warn!(bot_id = %bot_id, error = %err, "Failed to count friendships from DB");
            service_db_error("list_friendships_paginated_count", err)
        })?;
        let total = count_rows
            .first()
            .and_then(|row| match row.get("cnt") {
                Some(DbValue::I64(value)) if *value >= 0 => Some(*value as u64),
                Some(DbValue::U64(value)) => Some(*value),
                _ => None,
            })
            .unwrap_or(0);

        Ok((friendships, total))
    }

    async fn remove_friendship(&self, bot_a: &str, bot_b: &str) -> ServiceResult<bool> {
        // Pairs are stored normalized (left_bot < right_bot), one row per pair,
        // so a single equality condition removes the friendship. No env-less
        // bidirectional duplicate rows exist in this store.
        let (left, right) = normalize_pair(bot_a, bot_b);
        let env = resolve_env();
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_friendships WHERE left_bot = ")
            .bind(left.as_str())
            .push_static(" AND right_bot = ")
            .bind(right.as_str())
            .push_static(" AND env = ")
            .bind(env.as_str())
            .build();
        let affected = self.execute("remove_friendship", statement).await?;

        if affected > 0 {
            info!(left_bot = %left, right_bot = %right, "Friendship removed (DB)");
        }
        Ok(affected > 0)
    }
}

/// DB-backed friend request store operating on `bcs_friend_requests`.
pub struct DbFriendRequestStore {
    db: Arc<dyn DbPlugin>,
    flavor: FriendSqlFlavor,
}

impl DbFriendRequestStore {
    pub fn with_flavor(db: Arc<dyn DbPlugin>, flavor: FriendSqlFlavor) -> Self {
        Self { db, flavor }
    }

    pub fn mysql(db: Arc<dyn DbPlugin>) -> Self {
        Self::with_flavor(db, FriendSqlFlavor::Mysql)
    }

    pub fn sqlite(db: Arc<dyn DbPlugin>) -> Self {
        Self::with_flavor(db, FriendSqlFlavor::Sqlite)
    }

    pub fn postgres(db: Arc<dyn DbPlugin>) -> Self {
        Self::with_flavor(db, FriendSqlFlavor::Postgres)
    }

    /// Backward-compat shim. Defaults to MySQL semantics; new code should use
    /// the explicit `mysql` / `sqlite` constructors.
    pub fn new(db: Arc<dyn DbPlugin>) -> Self {
        Self::mysql(db)
    }

    /// Per-flavor SELECT fragment for `gmt_create` / `gmt_modified` columns.
    /// Always emits Unix-epoch seconds under aliases `gmt_create_ts`
    /// / `gmt_modified_ts` (TZ-correct in both backends).
    fn select_timestamp_columns(&self) -> &'static str {
        match self.flavor {
            FriendSqlFlavor::Mysql => {
                "UNIX_TIMESTAMP(gmt_create) AS gmt_create_ts, \
                 UNIX_TIMESTAMP(gmt_modified) AS gmt_modified_ts"
            }
            FriendSqlFlavor::Sqlite => {
                "CAST(strftime('%s', gmt_create) AS INTEGER) AS gmt_create_ts, \
                 CAST(strftime('%s', gmt_modified) AS INTEGER) AS gmt_modified_ts"
            }
            FriendSqlFlavor::Postgres => {
                "CAST(EXTRACT(EPOCH FROM gmt_create) AS BIGINT) AS gmt_create_ts, \
                 CAST(EXTRACT(EPOCH FROM gmt_modified) AS BIGINT) AS gmt_modified_ts"
            }
        }
    }

    /// Per-flavor SQL fragment for the `gmt_modified = <now>` SET clause.
    fn now_modified_clause(&self) -> &'static str {
        match self.flavor {
            FriendSqlFlavor::Mysql => "gmt_modified = NOW()",
            FriendSqlFlavor::Sqlite => "gmt_modified = strftime('%Y-%m-%d %H:%M:%S','now')",
            FriendSqlFlavor::Postgres => "gmt_modified = CURRENT_TIMESTAMP",
        }
    }

    async fn execute(&self, operation: &'static str, statement: DbStatement) -> ServiceResult<u64> {
        self.db
            .execute(statement)
            .await
            .map(|result| result.affected_rows)
            .map_err(|err| {
                warn!(operation, error = %err, "db_friend_request: execute failed");
                service_db_error(operation, err)
            })
    }

    async fn query(
        &self,
        operation: &'static str,
        statement: DbStatement,
    ) -> ServiceResult<Vec<DbRow>> {
        self.db.query(statement).await.map_err(|err| {
            warn!(operation, error = %err, "db_friend_request: query failed");
            service_db_error(operation, err)
        })
    }

    fn parse_request(row: &DbRow) -> Option<FriendRequest> {
        let status = match optional_string(row, "status").as_deref() {
            Some("accepted") => FriendRequestStatus::Accepted,
            Some("rejected") => FriendRequestStatus::Rejected,
            _ => FriendRequestStatus::Pending,
        };

        Some(FriendRequest {
            id: optional_string(row, "request_id")?,
            from_bot: optional_string(row, "from_bot")?,
            to_bot: optional_string(row, "to_bot")?,
            status,
            created_at: row_seconds_to_millis(row, "gmt_create_ts"),
            updated_at: row_seconds_to_millis(row, "gmt_modified_ts"),
        })
    }

    fn status_to_str(status: &FriendRequestStatus) -> &'static str {
        match status {
            FriendRequestStatus::Pending => "pending",
            FriendRequestStatus::Accepted => "accepted",
            FriendRequestStatus::Rejected => "rejected",
        }
    }
}

#[async_trait]
impl FriendRequestRepoPort for DbFriendRequestStore {
    async fn find_pending_request(
        &self,
        from_bot: &str,
        to_bot: &str,
    ) -> ServiceResult<Option<FriendRequest>> {
        let env = resolve_env();
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT request_id, from_bot, to_bot, status, ")
            .push_static(self.select_timestamp_columns())
            .push_static(" FROM bcs_friend_requests WHERE from_bot = ")
            .bind(from_bot)
            .push_static(" AND to_bot = ")
            .bind(to_bot)
            .push_static(" AND status = 'pending' AND env = ")
            .bind(env.as_str())
            .push_static(" LIMIT 1")
            .build();
        let rows = self.query("find_pending_friend_request", statement).await?;

        Ok(rows.first().and_then(Self::parse_request))
    }

    async fn insert_pending_request_if_absent(
        &self,
        request: FriendRequest,
    ) -> ServiceResult<Option<FriendRequest>> {
        let env = resolve_env();
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO bcs_friend_requests \
                 (request_id, from_bot, to_bot, status, env) SELECT ",
            )
            .bind(request.id.as_str())
            .push_static(", ")
            .bind(request.from_bot.as_str())
            .push_static(", ")
            .bind(request.to_bot.as_str())
            .push_static(", 'pending', ")
            .bind(env.as_str())
            .push_static(" WHERE NOT EXISTS (SELECT 1 FROM bcs_friend_requests WHERE from_bot = ")
            .bind(request.from_bot.as_str())
            .push_static(" AND to_bot = ")
            .bind(request.to_bot.as_str())
            .push_static(" AND status = 'pending' AND env = ")
            .bind(env.as_str())
            .push_static(")")
            .build();
        let affected = self
            .execute("insert_pending_friend_request_if_absent", statement)
            .await?;

        if affected > 0 {
            info!(request_id = %request.id, from = %request.from_bot, to = %request.to_bot, "Pending friend request inserted (DB)");
            return Ok(None);
        }

        self.find_pending_request(&request.from_bot, &request.to_bot)
            .await
    }

    async fn insert_request(&self, request: FriendRequest) -> ServiceResult<()> {
        let env = resolve_env();
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO bcs_friend_requests \
                 (request_id, from_bot, to_bot, status, env) \
                 VALUES (",
            )
            .bind(request.id.as_str())
            .push_static(", ")
            .bind(request.from_bot.as_str())
            .push_static(", ")
            .bind(request.to_bot.as_str())
            .push_static(", ")
            .bind(Self::status_to_str(&request.status))
            .push_static(", ")
            .bind(env.as_str())
            .push_static(")")
            .build();
        self.execute("insert_friend_request", statement).await?;
        info!(request_id = %request.id, from = %request.from_bot, to = %request.to_bot, "Friend request inserted (DB)");
        Ok(())
    }

    async fn update_request_status(
        &self,
        request_id: &str,
        status: FriendRequestStatus,
    ) -> ServiceResult<()> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_friend_requests SET status = ")
            .bind(Self::status_to_str(&status))
            .push_static(", ")
            .push_static(self.now_modified_clause())
            .push_static(" WHERE request_id = ")
            .bind(request_id)
            .build();
        let affected = self
            .execute("update_friend_request_status", statement)
            .await?;

        if affected == 0 {
            return Err(ServiceError::FriendRequestNotFound(request_id.to_string()));
        }
        Ok(())
    }

    async fn accept_reverse_pending_requests(
        &self,
        from_bot: &str,
        to_bot: &str,
    ) -> ServiceResult<usize> {
        let env = resolve_env();
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_friend_requests SET status = 'accepted', ")
            .push_static(self.now_modified_clause())
            .push_static(" WHERE from_bot = ")
            .bind(to_bot)
            .push_static(" AND to_bot = ")
            .bind(from_bot)
            .push_static(" AND status = 'pending' AND env = ")
            .bind(env.as_str())
            .build();
        let affected = self
            .execute("accept_reverse_friend_request", statement)
            .await?;

        if affected > 0 {
            info!(from = %to_bot, to = %from_bot, accepted = affected, "Auto-accepted reverse pending request (DB)");
        }
        Ok(affected as usize)
    }

    async fn get_request(&self, request_id: &str) -> ServiceResult<FriendRequest> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT request_id, from_bot, to_bot, status, ")
            .push_static(self.select_timestamp_columns())
            .push_static(" FROM bcs_friend_requests WHERE request_id = ")
            .bind(request_id)
            .build();
        let rows = self.query("get_friend_request", statement).await?;

        rows.first()
            .and_then(Self::parse_request)
            .ok_or_else(|| ServiceError::FriendRequestNotFound(request_id.to_string()))
    }

    async fn list_requests(
        &self,
        bot_id: &str,
        direction: FriendRequestDirection,
        status_filter: Option<FriendRequestStatus>,
    ) -> Vec<FriendRequest> {
        // Legacy contract: swallow persistence failures and return an empty
        // page. V1 callers use `try_list_requests` instead so DB failures
        // surface as 500 rather than a silent 200 empty page.
        match self
            .try_list_requests(bot_id, direction, status_filter)
            .await
        {
            Ok(rows) => rows,
            Err(err) => {
                warn!(bot_id = %bot_id, error = %err, "Failed to list friend requests from DB");
                Vec::new()
            }
        }
    }

    async fn try_list_requests(
        &self,
        bot_id: &str,
        direction: FriendRequestDirection,
        status_filter: Option<FriendRequestStatus>,
    ) -> ServiceResult<Vec<FriendRequest>> {
        let env = resolve_env();
        let ts = self.select_timestamp_columns();
        let base = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT request_id, from_bot, to_bot, status, ")
            .push_static(ts)
            .push_static(" FROM bcs_friend_requests WHERE ");
        let statement = match (&direction, &status_filter) {
            (FriendRequestDirection::Received, Some(status)) => base
                .push_static("to_bot = ")
                .bind(bot_id)
                .push_static(" AND status = ")
                .bind(Self::status_to_str(status))
                .push_static(" AND env = ")
                .bind(env.as_str()),
            (FriendRequestDirection::Received, None) => base
                .push_static("to_bot = ")
                .bind(bot_id)
                .push_static(" AND env = ")
                .bind(env.as_str()),
            (FriendRequestDirection::Sent, Some(status)) => base
                .push_static("from_bot = ")
                .bind(bot_id)
                .push_static(" AND status = ")
                .bind(Self::status_to_str(status))
                .push_static(" AND env = ")
                .bind(env.as_str()),
            (FriendRequestDirection::Sent, None) => base
                .push_static("from_bot = ")
                .bind(bot_id)
                .push_static(" AND env = ")
                .bind(env.as_str()),
            (FriendRequestDirection::All, Some(status)) => base
                .push_static("(from_bot = ")
                .bind(bot_id)
                .push_static(" OR to_bot = ")
                .bind(bot_id)
                .push_static(") AND status = ")
                .bind(Self::status_to_str(status))
                .push_static(" AND env = ")
                .bind(env.as_str()),
            (FriendRequestDirection::All, None) => base
                .push_static("(from_bot = ")
                .bind(bot_id)
                .push_static(" OR to_bot = ")
                .bind(bot_id)
                .push_static(") AND env = ")
                .bind(env.as_str()),
        }
        .push_static(" ORDER BY gmt_create DESC")
        .build();

        let rows = self.query("list_friend_requests", statement).await?;
        Ok(rows.iter().filter_map(Self::parse_request).collect())
    }

    async fn delete_pending_requests_for_bot(&self, bot_id: &str) -> ServiceResult<usize> {
        let env = resolve_env();
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_friend_requests WHERE (from_bot = ")
            .bind(bot_id)
            .push_static(" OR to_bot = ")
            .bind(bot_id)
            .push_static(") AND status = 'pending' AND env = ")
            .bind(env.as_str())
            .build();
        let affected = self
            .execute("cancel_pending_friend_requests", statement)
            .await?;

        if affected > 0 {
            info!(bot_id = %bot_id, removed = affected, "Cancelled all pending friend requests for bot (DB)");
        }
        Ok(affected as usize)
    }

    async fn insert_accepted_request_if_absent(
        &self,
        request: FriendRequest,
    ) -> ServiceResult<FriendRequest> {
        let env = resolve_env();
        // Let the engine fill `gmt_create` / `gmt_modified` via column DEFAULTs
        // (CURRENT_TIMESTAMP) so the row is timezone-correct in both flavors.
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO bcs_friend_requests \
                 (request_id, from_bot, to_bot, status, env) \
                 VALUES (",
            )
            .bind(request.id.as_str())
            .push_static(", ")
            .bind(request.from_bot.as_str())
            .push_static(", ")
            .bind(request.to_bot.as_str())
            .push_static(", 'accepted', ")
            .bind(env.as_str())
            .push_static(")")
            .build();
        self.execute("insert_accepted_request", statement).await?;

        Ok(request)
    }
}

fn normalize_pair(a: &str, b: &str) -> (String, String) {
    if a <= b {
        (a.to_string(), b.to_string())
    } else {
        (b.to_string(), a.to_string())
    }
}

#[cfg(test)]
fn now_millis() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn optional_string(row: &DbRow, column: &'static str) -> Option<String> {
    row.get_string(column).ok().flatten()
}

/// Read a Unix-epoch-seconds column (alias `*_ts`) and return milliseconds.
/// MySQL `UNIX_TIMESTAMP()` and SQLite `strftime('%s', ...)` both emit
/// integer seconds; anything else maps to 0.
fn row_seconds_to_millis(row: &DbRow, column: &'static str) -> u64 {
    match row.get(column) {
        Some(DbValue::I64(value)) if *value >= 0 => (*value as u64).saturating_mul(1000),
        Some(DbValue::U64(value)) => (*value).saturating_mul(1000),
        _ => 0,
    }
}

fn service_db_error(operation: &'static str, err: DbError) -> ServiceError {
    ServiceError::InternalError(format!("friend db {}: {}", operation, err))
}

#[cfg(test)]
mod tests {
    use super::*;
    use bcs_db_api::{
        DbExecuteResult, DbHealth, DbResult, DbTransactionStep, DbTransactionStepResult,
    };
    use bcs_db_local::LocalSqliteDbPlugin;
    use tokio::sync::Mutex;

    #[derive(Default)]
    struct RecordingDb {
        queried: Mutex<Vec<DbStatement>>,
    }

    #[async_trait]
    impl DbPlugin for RecordingDb {
        async fn query(&self, statement: DbStatement) -> DbResult<Vec<DbRow>> {
            self.queried.lock().await.push(statement);
            Ok(Vec::new())
        }

        async fn execute(&self, _statement: DbStatement) -> DbResult<DbExecuteResult> {
            Ok(DbExecuteResult::default())
        }

        async fn transaction(
            &self,
            _steps: Vec<DbTransactionStep>,
        ) -> DbResult<Vec<DbTransactionStepResult>> {
            Ok(Vec::new())
        }

        async fn health_check(&self) -> DbResult<DbHealth> {
            Ok(DbHealth::healthy())
        }
    }

    fn must_service<T>(result: ServiceResult<T>) -> T {
        match result {
            Ok(value) => value,
            Err(err) => panic!("expected service Ok, got {}", err),
        }
    }

    fn must_db<T>(result: DbResult<T>) -> T {
        match result {
            Ok(value) => value,
            Err(err) => panic!("expected db Ok, got {}", err),
        }
    }

    async fn sqlite_db() -> Arc<LocalSqliteDbPlugin> {
        let db = must_db(LocalSqliteDbPlugin::new());
        must_db(
            db.execute(DbStatement::new(
                "CREATE TABLE bcs_friendships (
                    left_bot TEXT NOT NULL,
                    right_bot TEXT NOT NULL,
                    env TEXT NOT NULL,
                    gmt_create TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    gmt_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (left_bot, right_bot, env)
                )",
            ))
            .await,
        );
        must_db(
            db.execute(DbStatement::new(
                "CREATE TABLE bcs_friend_requests (
                    request_id TEXT PRIMARY KEY,
                    from_bot TEXT NOT NULL,
                    to_bot TEXT NOT NULL,
                    status TEXT NOT NULL,
                    env TEXT NOT NULL,
                    gmt_create TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    gmt_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )",
            ))
            .await,
        );
        Arc::new(db)
    }

    async fn sqlite_services() -> (
        Arc<DbFriendStore>,
        Arc<DbFriendRequestStore>,
        Arc<LocalSqliteDbPlugin>,
    ) {
        let db = sqlite_db().await;
        let db_plugin: Arc<dyn DbPlugin> = db.clone();
        let friend_store = Arc::new(DbFriendStore::sqlite(db_plugin.clone()));
        let request_store = Arc::new(DbFriendRequestStore::sqlite(db_plugin));
        (friend_store, request_store, db)
    }

    #[tokio::test]
    async fn sqlite_friendship_is_symmetric_and_idempotent() {
        let (friend_store, _, _) = sqlite_services().await;

        must_service(friend_store.add_friendship("bob", "alice").await);
        must_service(friend_store.add_friendship("alice", "bob").await);

        assert!(
            friend_store
                .are_friends("alice", "bob")
                .await
                .expect("are friends")
        );
        assert_eq!(
            friend_store
                .list_friends("alice")
                .await
                .expect("list friends"),
            vec!["bob".to_string()]
        );
        assert_eq!(
            must_service(friend_store.remove_all_friendships("alice").await),
            1
        );
        assert!(
            !friend_store
                .are_friends("alice", "bob")
                .await
                .expect("are friends after remove")
        );
    }

    #[tokio::test]
    async fn sqlite_friend_request_lifecycle_round_trips() {
        let (_, request_store, _) = sqlite_services().await;
        let baseline_secs = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);

        let request = FriendRequest {
            id: "request-1".to_string(),
            from_bot: "alice".to_string(),
            to_bot: "bob".to_string(),
            status: FriendRequestStatus::Pending,
            created_at: now_millis(),
            updated_at: now_millis(),
        };

        must_service(request_store.insert_request(request.clone()).await);

        // After insert, gmt_create / gmt_modified default to CURRENT_TIMESTAMP;
        // SELECT must round-trip them to non-zero millis (regression guard for
        // the parse-zero / TZ bugs that previously dropped them to 0).
        let pending = must_service(request_store.find_pending_request("alice", "bob").await)
            .expect("pending request");
        assert_eq!(pending.id, request.id);
        assert!(pending.created_at > 0, "created_at must not be 0");
        assert!(pending.updated_at > 0, "updated_at must not be 0");
        let pending_secs = pending.created_at / 1000;
        assert!(
            pending_secs + 5 >= baseline_secs && pending_secs <= baseline_secs + 5,
            "created_at {}s should be near baseline {}s",
            pending_secs,
            baseline_secs
        );

        // Sleep past SQLite's 1-second resolution so the next UPDATE produces a
        // distinguishably newer gmt_modified.
        tokio::time::sleep(std::time::Duration::from_millis(1_100)).await;

        must_service(
            request_store
                .update_request_status(&request.id, FriendRequestStatus::Accepted)
                .await,
        );
        let accepted = must_service(request_store.get_request(&request.id).await);
        assert_eq!(accepted.status, FriendRequestStatus::Accepted);
        assert_eq!(accepted.created_at, pending.created_at);
        assert!(
            accepted.updated_at > pending.updated_at,
            "updated_at must advance after status update: pending={}, accepted={}",
            pending.updated_at,
            accepted.updated_at
        );
    }

    #[tokio::test]
    async fn sqlite_friend_request_deletes_pending_only() {
        let (_, request_store, _) = sqlite_services().await;

        let accepted = FriendRequest {
            id: "accepted-request".to_string(),
            from_bot: "alice".to_string(),
            to_bot: "bob".to_string(),
            status: FriendRequestStatus::Accepted,
            created_at: now_millis(),
            updated_at: now_millis(),
        };
        let pending = FriendRequest {
            id: "pending-request".to_string(),
            from_bot: "bob".to_string(),
            to_bot: "alice".to_string(),
            status: FriendRequestStatus::Pending,
            created_at: now_millis(),
            updated_at: now_millis(),
        };

        must_service(request_store.insert_request(accepted.clone()).await);
        must_service(request_store.insert_request(pending.clone()).await);

        assert_eq!(
            must_service(request_store.delete_pending_requests_for_bot("alice").await),
            1
        );
        assert!(matches!(
            request_store.get_request(&pending.id).await,
            Err(ServiceError::FriendRequestNotFound(_))
        ));
        assert_eq!(
            must_service(request_store.get_request(&accepted.id).await).status,
            FriendRequestStatus::Accepted
        );
    }

    #[tokio::test]
    async fn sqlite_list_friendships_paginated_and_remove_friendship() {
        let (friend_store, _, _) = sqlite_services().await;

        must_service(friend_store.add_friendship("alice", "bob").await);
        must_service(friend_store.add_friendship("alice", "carol").await);

        // list_friendships_paginated: alice has 2 friends, projected symmetric.
        let (page, total) = must_service(
            friend_store
                .list_friendships_paginated("alice", 0, 10)
                .await,
        );
        assert_eq!(total, 2);
        assert_eq!(page.len(), 2);
        assert!(page.iter().all(|f| f.bot_uuid == "alice"));
        let mut friends: Vec<String> = page.iter().map(|f| f.friend_bot_uuid.clone()).collect();
        friends.sort();
        assert_eq!(friends, vec!["bob".to_string(), "carol".to_string()]);
        // created_at round-trips non-zero (DEFAULT CURRENT_TIMESTAMP → secs*1000).
        assert!(page.iter().all(|f| f.created_at > 0));

        // pagination: limit 1 → one row, total still 2.
        let (first, total) =
            must_service(friend_store.list_friendships_paginated("alice", 0, 1).await);
        assert_eq!(total, 2);
        assert_eq!(first.len(), 1);

        // offset beyond range → empty page, total still 2.
        let (empty, total) = must_service(
            friend_store
                .list_friendships_paginated("alice", 99, 10)
                .await,
        );
        assert!(empty.is_empty());
        assert_eq!(total, 2);

        // symmetric: bob sees alice as its friend.
        let (bob_page, bob_total) =
            must_service(friend_store.list_friendships_paginated("bob", 0, 10).await);
        assert_eq!(bob_total, 1);
        assert_eq!(bob_page[0].bot_uuid, "bob");
        assert_eq!(bob_page[0].friend_bot_uuid, "alice");

        // remove_friendship: first true, second false (idempotent), either
        // argument order hits the same normalized pair.
        assert!(must_service(
            friend_store.remove_friendship("alice", "bob").await
        ));
        assert!(!must_service(
            friend_store.remove_friendship("bob", "alice").await
        ));

        let (after, total) = must_service(
            friend_store
                .list_friendships_paginated("alice", 0, 10)
                .await,
        );
        assert_eq!(total, 1);
        assert_eq!(after.len(), 1);
        assert_eq!(after[0].friend_bot_uuid, "carol");

        // legacy list_friends still works (compat guard) — returns uuids only.
        let mut lf = must_service(friend_store.list_friends("alice").await);
        lf.sort();
        assert_eq!(lf, vec!["carol".to_string()]);
    }

    #[test]
    fn postgres_friendship_insert_uses_numbered_typed_binds() {
        let db: Arc<dyn DbPlugin> = Arc::new(RecordingDb::default());
        let store = DbFriendStore::postgres(db);

        let statement = store.insert_friendship_statement("alice", "bob", "prod");

        assert_eq!(
            statement.sql(),
            "INSERT INTO bcs_friendships (left_bot, right_bot, env) \
             VALUES ($1, $2, $3) ON CONFLICT DO NOTHING"
        );
        assert_eq!(
            statement.params(),
            &[
                DbValue::from("alice"),
                DbValue::from("bob"),
                DbValue::from("prod"),
            ]
        );
    }

    #[tokio::test]
    async fn postgres_friend_request_query_uses_numbered_typed_binds() {
        let db = Arc::new(RecordingDb::default());
        let store = DbFriendRequestStore::postgres(db.clone());

        let result = store.get_request("request-1").await;

        assert!(matches!(
            result,
            Err(ServiceError::FriendRequestNotFound(_))
        ));
        let statements = db.queried.lock().await;
        assert_eq!(statements.len(), 1);
        assert_eq!(
            statements[0].sql(),
            "SELECT request_id, from_bot, to_bot, status, \
             CAST(EXTRACT(EPOCH FROM gmt_create) AS BIGINT) AS gmt_create_ts, \
             CAST(EXTRACT(EPOCH FROM gmt_modified) AS BIGINT) AS gmt_modified_ts \
             FROM bcs_friend_requests WHERE request_id = $1"
        );
        assert_eq!(statements[0].params(), &[DbValue::from("request-1")]);
    }
}
