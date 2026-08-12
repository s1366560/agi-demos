//! Database-backed implementation of relation repository ports.
//!
//! This store owns the relation SQL and depends only on the driver-level
//! `bcs-db-api` contract. The composition root decides which concrete DB
//! plugin backs it.

use std::sync::Arc;

use async_trait::async_trait;
use bcs_db_api::{
    DbError, DbExecuteResult, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder,
};
pub use bcs_service_api::port::repo::RelationRepoPort;
use bcs_service_api::{EnsureOwnerEdgesResult, RelationEdge, ServiceError, ServiceResult};
use tracing::warn;

pub type RelationSqlFlavor = DbSqlFlavor;

pub mod memory;

pub use memory::MemoryRelationRepo;

/// MySQL-backed relation repository.
pub type MysqlRelationRepo = DbRelationStore;

/// SQLite-backed relation repository.
pub type SqliteRelationRepo = DbRelationStore;

pub struct DbRelationStore {
    db: Arc<dyn DbPlugin>,
    flavor: RelationSqlFlavor,
}

impl DbRelationStore {
    pub fn new(db: Arc<dyn DbPlugin>, flavor: RelationSqlFlavor) -> Self {
        Self { db, flavor }
    }

    pub fn mysql(db: Arc<dyn DbPlugin>) -> Self {
        Self::new(db, RelationSqlFlavor::Mysql)
    }

    pub fn sqlite(db: Arc<dyn DbPlugin>) -> Self {
        Self::new(db, RelationSqlFlavor::Sqlite)
    }

    pub fn postgres(db: Arc<dyn DbPlugin>) -> Self {
        Self::new(db, RelationSqlFlavor::Postgres)
    }

    pub fn flavor(&self) -> RelationSqlFlavor {
        self.flavor
    }

    async fn exec_upsert(
        &self,
        from_id: &str,
        to_id: &str,
        env: &str,
        is_creator: bool,
    ) -> ServiceResult<()> {
        self.execute(
            "upsert",
            self.upsert_statement(from_id, to_id, env, is_creator),
        )
        .await
    }

    fn upsert_statement(
        &self,
        from_id: &str,
        to_id: &str,
        env: &str,
        is_creator: bool,
    ) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO bcs_actor_relations \
                 (from_id, to_id, env, kinds, allow, deny, is_creator) VALUES (",
            )
            .bind(from_id)
            .push_static(", ")
            .bind(to_id)
            .push_static(", ")
            .bind(env)
            .push_static(", 0, 0, 0, ")
            .bind(is_creator)
            .push_static(") ")
            .push_static(self.upsert_conflict_sql())
            .build()
    }

    async fn exec_insert_friend(&self, from_id: &str, to_id: &str, env: &str) -> ServiceResult<()> {
        self.execute(
            "insert_friend",
            self.insert_friend_statement(from_id, to_id, env),
        )
        .await
    }

    fn insert_friend_statement(&self, from_id: &str, to_id: &str, env: &str) -> DbStatement {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(self.flavor.insert_or_ignore())
            .push_static(
                " INTO bcs_actor_relations \
                 (from_id, to_id, env, kinds, allow, deny, is_creator) VALUES (",
            )
            .bind(from_id)
            .push_static(", ")
            .bind(to_id)
            .push_static(", ")
            .bind(env)
            .push_static(", 0, 0, 0, ")
            .bind(false)
            .push_static(")");
        let statement = match self.flavor {
            RelationSqlFlavor::Mysql | RelationSqlFlavor::Sqlite => statement,
            RelationSqlFlavor::Postgres => statement.push_static(" ON CONFLICT DO NOTHING"),
        };
        statement.build()
    }

    async fn execute(&self, operation: &'static str, statement: DbStatement) -> ServiceResult<()> {
        self.execute_result(operation, statement).await.map(|_| ())
    }

    async fn execute_result(
        &self,
        operation: &'static str,
        statement: DbStatement,
    ) -> ServiceResult<DbExecuteResult> {
        self.db.execute(statement).await.map_err(|err| {
            warn!(operation, error = %err, "db_relation: execute failed");
            service_db_error(operation, err)
        })
    }

    fn upsert_conflict_sql(&self) -> &'static str {
        match self.flavor {
            RelationSqlFlavor::Mysql => {
                "ON DUPLICATE KEY UPDATE \
                     kinds = VALUES(kinds), \
                     allow = VALUES(allow), \
                     deny = VALUES(deny), \
                     is_creator = GREATEST(is_creator, VALUES(is_creator))"
            }
            RelationSqlFlavor::Sqlite => {
                "ON CONFLICT(from_id, to_id, env) DO UPDATE SET \
                     kinds = excluded.kinds, \
                     allow = excluded.allow, \
                     deny = excluded.deny, \
                     is_creator = MAX(bcs_actor_relations.is_creator, excluded.is_creator)"
            }
            RelationSqlFlavor::Postgres => {
                "ON CONFLICT(from_id, to_id, env) DO UPDATE SET \
                     kinds = excluded.kinds, \
                     allow = excluded.allow, \
                     deny = excluded.deny, \
                     is_creator = bcs_actor_relations.is_creator OR excluded.is_creator"
            }
        }
    }
}

#[async_trait]
impl RelationRepoPort for DbRelationStore {
    async fn upsert_edge(&self, edge: RelationEdge) -> ServiceResult<()> {
        self.exec_upsert(&edge.from_id, &edge.to_id, &edge.env, edge.is_creator)
            .await
    }

    async fn delete_edge(&self, from_id: &str, to_id: &str, env: &str) -> ServiceResult<()> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_actor_relations WHERE from_id = ")
            .bind(from_id)
            .push_static(" AND to_id = ")
            .bind(to_id)
            .push_static(" AND env = ")
            .bind(env)
            .build();
        self.execute("delete_edge", statement).await
    }

    async fn get_edge(
        &self,
        from_id: &str,
        to_id: &str,
        env: &str,
    ) -> ServiceResult<Option<RelationEdge>> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT from_id, to_id, env, kinds, allow, deny, is_creator \
                 FROM bcs_actor_relations WHERE from_id = ",
            )
            .bind(from_id)
            .push_static(" AND to_id = ")
            .bind(to_id)
            .push_static(" AND env = ")
            .bind(env)
            .push_static(" LIMIT 1")
            .build();
        let rows = self.db.query(statement).await.map_err(|err| {
            warn!(
                from_id = %from_id,
                to_id = %to_id,
                env = %env,
                error = %err,
                "db_relation: get_edge query failed"
            );
            service_db_error("get_edge", err)
        })?;

        rows.into_iter().next().map(row_to_edge).transpose()
    }

    async fn ensure_owner_edges(
        &self,
        human_id: &str,
        bot_id: &str,
        env: &str,
    ) -> ServiceResult<()> {
        self.exec_upsert(human_id, bot_id, env, true).await?;
        self.exec_insert_friend(bot_id, human_id, env).await?;
        Ok(())
    }

    async fn ensure_owner_edges_counted(
        &self,
        human_id: &str,
        bot_id: &str,
        env: &str,
    ) -> ServiceResult<EnsureOwnerEdgesResult> {
        // Business outcomes come from domain state, never backend-specific
        // affected-row conventions. This remains a read-before-write operation;
        // production PostgreSQL wiring stays blocked until the relation schema
        // provides a portable locking/revision contract for concurrent writers.
        let forward_before = self.get_edge(human_id, bot_id, env).await?;
        let reverse_before = self.get_edge(bot_id, human_id, env).await?;

        self.exec_upsert(human_id, bot_id, env, true).await?;
        self.exec_insert_friend(bot_id, human_id, env).await?;

        let mut result = EnsureOwnerEdgesResult::default();
        match forward_before {
            None => result.created += 1,
            Some(edge) if !edge.is_creator => result.upgraded += 1,
            Some(_) => {}
        }
        if reverse_before.is_none() {
            result.created += 1;
        }
        Ok(result)
    }

    async fn add_friend_edges(&self, a: &str, b: &str, env: &str) -> ServiceResult<()> {
        self.exec_insert_friend(a, b, env).await?;
        self.exec_insert_friend(b, a, env).await?;
        Ok(())
    }

    async fn remove_friend_edges(&self, a: &str, b: &str, env: &str) -> ServiceResult<()> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_actor_relations WHERE env = ")
            .bind(env)
            .push_static(" AND is_creator = ")
            .bind(false)
            .push_static(" AND ((from_id = ")
            .bind(a)
            .push_static(" AND to_id = ")
            .bind(b)
            .push_static(") OR (from_id = ")
            .bind(b)
            .push_static(" AND to_id = ")
            .bind(a)
            .push_static("))")
            .build();
        self.execute("remove_friend_edges", statement).await
    }

    async fn remove_all_friend_edges(&self, actor_id: &str, env: &str) -> ServiceResult<()> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("DELETE FROM bcs_actor_relations WHERE env = ")
            .bind(env)
            .push_static(" AND is_creator = ")
            .bind(false)
            .push_static(" AND (from_id = ")
            .bind(actor_id)
            .push_static(" OR to_id = ")
            .bind(actor_id)
            .push_static(")")
            .build();
        self.execute("remove_all_friend_edges", statement).await
    }

    async fn add_relation_edge(&self, caller: &str, target: &str, env: &str) -> ServiceResult<()> {
        self.exec_insert_friend(caller, target, env).await
    }

    async fn list_friends_via_relation(
        &self,
        actor_id: &str,
        env: &str,
    ) -> ServiceResult<Vec<String>> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT a.to_id AS peer FROM bcs_actor_relations a \
                 JOIN bcs_actor_relations b ON b.from_id = a.to_id \
                 AND b.to_id = a.from_id AND b.env = a.env AND b.is_creator = ",
            )
            .bind(false)
            .push_static(" WHERE a.from_id = ")
            .bind(actor_id)
            .push_static(" AND a.env = ")
            .bind(env)
            .push_static(" AND a.is_creator = ")
            .bind(false)
            .build();
        let rows = self
            .db
            .query(statement)
            .await
            .map_err(|err| service_db_error("list_friends_via_relation", err))?;

        let mut out = Vec::with_capacity(rows.len());
        for row in rows {
            if let Some(peer) = row
                .get_string("peer")
                .map_err(|err| service_db_error("list_friends_via_relation.peer", err))?
            {
                out.push(peer);
            }
        }
        Ok(out)
    }
}

fn row_to_edge(row: DbRow) -> ServiceResult<RelationEdge> {
    Ok(RelationEdge {
        from_id: required_string(&row, "from_id")?,
        to_id: required_string(&row, "to_id")?,
        env: required_string(&row, "env")?,
        kinds: optional_u64(&row, "kinds")?,
        allow: optional_u64(&row, "allow")?,
        deny: optional_u64(&row, "deny")?,
        is_creator: row
            .get_bool("is_creator")
            .map_err(|err| service_db_error("row.is_creator", err))?
            .unwrap_or(false),
    })
}

fn required_string(row: &DbRow, column: &'static str) -> ServiceResult<String> {
    row.get_string(column)
        .map_err(|err| service_db_error(column, err))?
        .ok_or_else(|| ServiceError::InternalError(format!("missing relation column {}", column)))
}

fn optional_u64(row: &DbRow, column: &'static str) -> ServiceResult<u64> {
    Ok(row
        .get_i64(column)
        .map_err(|err| service_db_error(column, err))?
        .unwrap_or(0)
        .max(0) as u64)
}

fn service_db_error(operation: &'static str, err: DbError) -> ServiceError {
    ServiceError::InternalError(format!("relation db {}: {}", operation, err))
}

#[cfg(test)]
mod tests {
    use super::*;

    use bcs_db_api::{DbResult, DbValue};
    use bcs_db_local::LocalSqliteDbPlugin;

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

    async fn sqlite_store() -> DbRelationStore {
        let db = must_db(LocalSqliteDbPlugin::new());
        must_db(
            db.execute(DbStatement::new(
                "CREATE TABLE bcs_actor_relations (
                    from_id VARCHAR(128) NOT NULL,
                    to_id VARCHAR(128) NOT NULL,
                    env VARCHAR(32) NOT NULL,
                    kinds BIGINT NOT NULL DEFAULT 0,
                    allow BIGINT NOT NULL DEFAULT 0,
                    deny BIGINT NOT NULL DEFAULT 0,
                    is_creator INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (from_id, to_id, env)
                )",
            ))
            .await,
        );
        DbRelationStore::sqlite(Arc::new(db))
    }

    fn edge(from: &str, to: &str, env: &str, is_creator: bool) -> RelationEdge {
        RelationEdge {
            from_id: from.to_string(),
            to_id: to.to_string(),
            env: env.to_string(),
            kinds: 0,
            allow: 0,
            deny: 0,
            is_creator,
        }
    }

    #[test]
    fn postgres_relation_statements_use_numbered_typed_binds() {
        let db = Arc::new(must_db(LocalSqliteDbPlugin::new()));
        let store = DbRelationStore::postgres(db);

        let upsert = store.upsert_statement("human-1", "bot-1", "dev", true);
        assert!(upsert.sql().contains("VALUES ($1, $2, $3, 0, 0, 0, $4)"));
        assert!(upsert.sql().contains("ON CONFLICT(from_id, to_id, env)"));
        assert!(
            upsert
                .sql()
                .contains("bcs_actor_relations.is_creator OR excluded.is_creator")
        );
        assert_eq!(
            upsert.params(),
            &[
                DbValue::from("human-1"),
                DbValue::from("bot-1"),
                DbValue::from("dev"),
                DbValue::from(true),
            ]
        );

        let friend = store.insert_friend_statement("bot-1", "human-1", "dev");
        assert!(friend.sql().contains("VALUES ($1, $2, $3, 0, 0, 0, $4)"));
        assert_eq!(friend.params()[3], DbValue::from(false));
        assert!(friend.sql().ends_with("ON CONFLICT DO NOTHING"));
    }

    #[tokio::test]
    async fn sqlite_upsert_does_not_downgrade_creator() {
        let store = sqlite_store().await;

        must_service(store.upsert_edge(edge("h", "b", "dev", true)).await);
        must_service(store.upsert_edge(edge("h", "b", "dev", false)).await);

        let got = must_service(store.get_edge("h", "b", "dev").await);
        match got {
            Some(edge) => assert!(edge.is_creator),
            None => panic!("expected relation edge"),
        }
    }

    #[tokio::test]
    async fn sqlite_owner_edges_count_created_and_upgraded() {
        let store = sqlite_store().await;

        let first = must_service(store.ensure_owner_edges_counted("h", "b", "dev").await);
        assert_eq!(first.created, 2);
        assert_eq!(first.upgraded, 0);

        must_service(store.upsert_edge(edge("h2", "b2", "dev", false)).await);
        let second = must_service(store.ensure_owner_edges_counted("h2", "b2", "dev").await);
        assert_eq!(second.created, 1);
        assert_eq!(second.upgraded, 1);
    }

    #[tokio::test]
    async fn sqlite_friend_listing_requires_two_non_creator_edges() {
        let store = sqlite_store().await;

        must_service(store.add_friend_edges("a", "b", "dev").await);
        must_service(store.add_relation_edge("a", "c", "dev").await);
        must_service(store.ensure_owner_edges("a", "owned-bot", "dev").await);

        let mut friends = must_service(store.list_friends_via_relation("a", "dev").await);
        friends.sort();
        assert_eq!(friends, vec!["b".to_string()]);

        let from_bot = must_service(store.list_friends_via_relation("owned-bot", "dev").await);
        assert!(from_bot.is_empty());
    }

    #[tokio::test]
    async fn sqlite_remove_friend_edges_keeps_owner_edges() {
        let store = sqlite_store().await;

        must_service(store.ensure_owner_edges("h", "b", "dev").await);
        must_service(store.remove_friend_edges("h", "b", "dev").await);

        let owner = must_service(store.get_edge("h", "b", "dev").await);
        match owner {
            Some(edge) => assert!(edge.is_creator),
            None => panic!("owner edge must survive friend removal"),
        }
        assert!(must_service(store.get_edge("b", "h", "dev").await).is_none());
    }
}
