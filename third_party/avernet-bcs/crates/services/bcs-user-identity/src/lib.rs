//! Database-backed `UserIdentityRepoPort` implementation.
//!
//! Owns the `bcs_user_identities` SQL and depends only on `bcs-db-api`. The
//! composition root chooses the concrete DB plugin.

use std::sync::Arc;

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatementBuilder};
use bcs_service_api::{UserIdentity, UserIdentityRepoPort};
use tracing::warn;

pub mod memory;
pub use memory::{MemoryUserIdentityRepo, generate_user_id};

pub type MysqlUserIdentityRepo = DbUserIdentityStore;
pub type SqliteUserIdentityRepo = DbUserIdentityStore;

pub struct DbUserIdentityStore {
    db: Arc<dyn DbPlugin>,
    flavor: DbSqlFlavor,
}

impl DbUserIdentityStore {
    pub fn new(db: Arc<dyn DbPlugin>, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    pub fn mysql(db: Arc<dyn DbPlugin>) -> Self {
        Self::new(db, DbSqlFlavor::Mysql)
    }

    pub fn sqlite(db: Arc<dyn DbPlugin>) -> Self {
        Self::new(db, DbSqlFlavor::Sqlite)
    }

    pub fn postgres(db: Arc<dyn DbPlugin>) -> Self {
        Self::new(db, DbSqlFlavor::Postgres)
    }

    /// Reserved for future MySQL/SQLite UPSERT dialect branching.
    pub fn flavor(&self) -> DbSqlFlavor {
        self.flavor
    }

    async fn select_user_id(
        &self,
        auth_source: &str,
        external_user_id: &str,
        env: &str,
    ) -> Result<Option<String>, String> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT user_id FROM bcs_user_identities WHERE auth_source = ")
            .bind(auth_source)
            .push_static(" AND external_user_id = ")
            .bind(external_user_id)
            .push_static(" AND env = ")
            .bind(env)
            .build();
        let rows = self
            .db
            .query(statement)
            .await
            .map_err(|e| format!("select user_id: {e}"))?;
        match rows.first() {
            Some(row) => row
                .get_string("user_id")
                .map_err(|e| format!("read user_id: {e}")),
            None => Ok(None),
        }
    }
}

#[async_trait]
impl UserIdentityRepoPort for DbUserIdentityStore {
    async fn ensure_identity(
        &self,
        auth_source: &str,
        external_user_id: &str,
        external_user_name: Option<&str>,
        avatar: Option<&str>,
        env: &str,
    ) -> Result<String, String> {
        // Hit -> update external_user_name and avatar, return existing user_id.
        if let Some(existing) = self
            .select_user_id(auth_source, external_user_id, env)
            .await?
        {
            let update = DbStatementBuilder::new(self.flavor)
                .push_static("UPDATE bcs_user_identities SET external_user_name = ")
                .bind(external_user_name)
                .push_static(", avatar = ")
                .bind(avatar)
                .push_static(" WHERE auth_source = ")
                .bind(auth_source)
                .push_static(" AND external_user_id = ")
                .bind(external_user_id)
                .push_static(" AND env = ")
                .bind(env)
                .build();
            self.db
                .execute(update)
                .await
                .map_err(|e| format!("update identity: {e}"))?;
            return Ok(existing);
        }

        // Miss -> insert a freshly generated user_id, retry on uk_user_id clash.
        // The internal `user_name` is initialized from the external display name
        // on first creation, then left untouched on subsequent logins (the
        // UPDATE branch above only refreshes external_user_name/avatar). This
        // lets the internal display name diverge from the provider's later.
        let mut attempts = 0;
        loop {
            let user_id = generate_user_id();
            let insert = DbStatementBuilder::new(self.flavor)
                .push_static(
                    "INSERT INTO bcs_user_identities \
                     (user_id, auth_source, external_user_id, user_name, external_user_name, avatar, env) \
                     VALUES (",
                )
                .bind(user_id.as_str())
                .push_static(", ")
                .bind(auth_source)
                .push_static(", ")
                .bind(external_user_id)
                .push_static(", ")
                .bind(external_user_name)
                .push_static(", ")
                .bind(external_user_name)
                .push_static(", ")
                .bind(avatar)
                .push_static(", ")
                .bind(env)
                .push_static(")")
                .build();
            let result = self.db.execute(insert).await;
            match result {
                Ok(_) => return Ok(user_id),
                Err(e) => {
                    attempts += 1;
                    // A concurrent inserter may have created the external row, OR
                    // the random user_id collided. Re-resolve, then retry.
                    if let Some(existing) = self
                        .select_user_id(auth_source, external_user_id, env)
                        .await?
                    {
                        return Ok(existing);
                    }
                    if attempts >= 5 {
                        warn!(error = %e, "ensure_identity insert retry exhausted");
                        return Err(format!("insert identity: {e}"));
                    }
                }
            }
        }
    }

    async fn lookup_user_id(
        &self,
        auth_source: &str,
        external_user_id: &str,
        env: &str,
    ) -> Option<String> {
        self.select_user_id(auth_source, external_user_id, env)
            .await
            .ok()
            .flatten()
    }

    async fn lookup_by_user_id(&self, user_id: &str, auth_source: &str) -> Option<String> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT external_user_id FROM bcs_user_identities WHERE user_id = ")
            .bind(user_id)
            .push_static(" AND auth_source = ")
            .bind(auth_source)
            .push_static(" LIMIT 1")
            .build();
        self.db.query(statement).await.ok().and_then(|rows| {
            rows.first()
                .and_then(|r| r.get_string("external_user_id").ok().flatten())
        })
    }

    async fn get_by_token(&self, token: &str) -> Option<UserIdentity> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT user_id, auth_source, user_name, external_user_name, avatar, env \
                 FROM bcs_user_identities WHERE token = ",
            )
            .bind(token)
            .push_static(" LIMIT 1")
            .build();
        self.db
            .query(statement)
            .await
            .ok()
            .and_then(|rows| rows.first().map(row_to_display_identity))
    }

    async fn get_by_user_id_display(&self, user_id: &str) -> Option<UserIdentity> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT user_id, auth_source, user_name, external_user_name, avatar, env \
                 FROM bcs_user_identities WHERE user_id = ",
            )
            .bind(user_id)
            .push_static(" LIMIT 1")
            .build();
        self.db
            .query(statement)
            .await
            .ok()
            .and_then(|rows| rows.first().map(row_to_display_identity))
    }

    async fn update_token(&self, user_id: &str, token: &str, expire_at: u64) -> Result<(), String> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE bcs_user_identities SET token = ")
            .bind(token)
            .push_static(", token_expire_at = ");
        let statement = match self.flavor {
            DbSqlFlavor::Mysql => statement
                .push_static("FROM_UNIXTIME(")
                .bind(expire_at)
                .push_static(")"),
            DbSqlFlavor::Sqlite => statement
                .push_static("datetime(")
                .bind(expire_at)
                .push_static(", 'unixepoch')"),
            DbSqlFlavor::Postgres => statement
                .push_static("TO_TIMESTAMP(")
                .bind(expire_at)
                .push_static(")"),
        }
        .push_static(" WHERE user_id = ")
        .bind(user_id)
        .build();
        self.db
            .execute(statement)
            .await
            .map_err(|e| format!("update_token: {e}"))?;
        Ok(())
    }
}

fn row_to_display_identity(row: &bcs_db_api::DbRow) -> UserIdentity {
    UserIdentity {
        user_id: row.get_string("user_id").ok().flatten().unwrap_or_default(),
        auth_source: row
            .get_string("auth_source")
            .ok()
            .flatten()
            .unwrap_or_default(),
        external_user_id: String::new(),
        user_name: row.get_string("user_name").ok().flatten(),
        external_user_name: row.get_string("external_user_name").ok().flatten(),
        avatar: row.get_string("avatar").ok().flatten(),
        token: None,
        token_expire_at: None,
        env: row.get_string("env").ok().flatten().unwrap_or_default(),
    }
}

#[cfg(test)]
mod tests {
    use bcs_db_api::{
        DbExecuteResult, DbHealth, DbResult, DbRow, DbStatement, DbTransactionStep,
        DbTransactionStepResult, DbValue,
    };
    use tokio::sync::Mutex;

    use super::*;

    #[derive(Default)]
    struct RecordingDb {
        executed: Mutex<Vec<DbStatement>>,
    }

    #[async_trait]
    impl DbPlugin for RecordingDb {
        async fn query(&self, _statement: DbStatement) -> DbResult<Vec<DbRow>> {
            Ok(Vec::new())
        }

        async fn execute(&self, statement: DbStatement) -> DbResult<DbExecuteResult> {
            self.executed.lock().await.push(statement);
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

    #[tokio::test]
    async fn postgres_token_update_uses_numbered_typed_binds() {
        let db = Arc::new(RecordingDb::default());
        let store = DbUserIdentityStore::postgres(db.clone());

        let result = store.update_token("user-1", "token-1", 42).await;

        assert!(result.is_ok());
        let statements = db.executed.lock().await;
        assert_eq!(statements.len(), 1);
        assert_eq!(
            statements[0].sql(),
            "UPDATE bcs_user_identities SET token = $1, token_expire_at = \
             TO_TIMESTAMP($2) WHERE user_id = $3"
        );
        assert_eq!(
            statements[0].params(),
            &[
                DbValue::from("token-1"),
                DbValue::from(42_u64),
                DbValue::from("user-1"),
            ]
        );
    }
}
