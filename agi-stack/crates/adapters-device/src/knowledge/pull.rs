//! Atomic remote ingestion with a separate remote cursor and no local echo.

use agistack_core::knowledge::sync::pull::{KnowledgePullReceipt, KnowledgePullRepository};
use agistack_core::knowledge::sync::push::{KnowledgeSyncTarget, RemoteMemoryVersion};
use rusqlite::{Transaction, TransactionBehavior};
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;

use super::*;

#[path = "pull_apply.rs"]
mod apply;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Page {
    changes: Vec<Event>,
    next_cursor: u64,
    has_more: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Event {
    sequence: u64,
    change_id: String,
    version: Value,
}

pub(super) fn migrate(tx: &Transaction<'_>, previous: i64) -> KnowledgeResult<()> {
    if previous >= 5 {
        let count: i64 = tx
            .query_row(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN (
                'knowledge_sync_pull_cursors', 'knowledge_sync_pull_events',
                'knowledge_sync_pull_conflicts')",
                [],
                |row| row.get(0),
            )
            .map_err(storage)?;
        if count != 3 {
            return Err(KnowledgeError::Storage(
                "knowledge pull tables are missing".into(),
            ));
        }
    }
    tx.execute_batch(
        "CREATE TABLE IF NOT EXISTS knowledge_sync_pull_cursors (
            tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, cursor INTEGER NOT NULL,
            PRIMARY KEY(tenant_id, project_id)
         );
         CREATE TABLE IF NOT EXISTS knowledge_sync_pull_events (
            tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, sequence INTEGER NOT NULL,
            change_id TEXT NOT NULL, memory_id TEXT NOT NULL, version_json TEXT NOT NULL,
            PRIMARY KEY(tenant_id, project_id, sequence),
            UNIQUE(tenant_id, project_id, change_id)
         );
         CREATE INDEX IF NOT EXISTS knowledge_sync_pull_memory
            ON knowledge_sync_pull_events(tenant_id, project_id, memory_id, sequence DESC);
         CREATE TABLE IF NOT EXISTS knowledge_sync_pull_conflicts (
            tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, sequence INTEGER NOT NULL,
            memory_id TEXT NOT NULL, conflict_json TEXT NOT NULL,
            PRIMARY KEY(tenant_id, project_id, sequence)
         );
         CREATE INDEX IF NOT EXISTS knowledge_sync_pull_conflict_memory
            ON knowledge_sync_pull_conflicts(tenant_id, project_id, memory_id);",
    )
    .map_err(storage)
}

fn cursor(conn: &Connection, scope: &KnowledgeScope) -> KnowledgeResult<u64> {
    Ok(conn
        .query_row(
            "SELECT cursor FROM knowledge_sync_pull_cursors WHERE tenant_id=?1 AND project_id=?2",
            params![scope.tenant_id, scope.project_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?
        .unwrap_or(0))
}

impl SqliteKnowledgeRepository {
    /// The native transport may hold its session fence through this synchronous
    /// local transaction. This method performs no network or async operations.
    pub fn accept_pull_page_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        after: u64,
        response: Value,
    ) -> KnowledgeResult<KnowledgePullReceipt> {
        let page: Page =
            serde_json::from_value(response).map_err(|_| KnowledgeError::InvalidInput)?;
        if page.changes.len() > 500
            || page.next_cursor > i64::MAX as u64
            || (page.changes.is_empty() && page.has_more)
        {
            return Err(KnowledgeError::InvalidInput);
        }
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        super::push::check_target(&tx, scope, target, true)?;
        if cursor(&tx, scope)? != after {
            return Err(KnowledgeError::Conflict);
        }
        let mut result = KnowledgePullReceipt {
            next_cursor: after,
            applied: 0,
            conflicts: 0,
            has_more: page.has_more,
        };
        for event in page.changes {
            if event.sequence <= result.next_cursor
                || event.sequence > i64::MAX as u64
                || Uuid::parse_str(&event.change_id)
                    .map_err(|_| KnowledgeError::InvalidInput)?
                    .to_string()
                    != event.change_id
            {
                return Err(KnowledgeError::InvalidInput);
            }
            let remote: RemoteMemoryVersion = serde_json::from_value(event.version.clone())
                .map_err(|_| KnowledgeError::InvalidInput)?;
            remote.validate()?;
            apply::apply_event(&tx, scope, target, &event, &remote, &mut result)?;
            tx.execute(
                "INSERT INTO knowledge_sync_pull_events(tenant_id, project_id, sequence, change_id, memory_id, version_json)
                 VALUES(?1, ?2, ?3, ?4, ?5, ?6)",
                params![scope.tenant_id, scope.project_id, event.sequence, event.change_id, remote.memory_id, serde_json::to_string(&event.version).map_err(storage)?],
            ).map_err(storage)?;
            result.next_cursor = event.sequence;
        }
        if page.next_cursor != result.next_cursor {
            return Err(KnowledgeError::InvalidInput);
        }
        tx.execute(
            "INSERT INTO knowledge_sync_pull_cursors(tenant_id, project_id, cursor) VALUES(?1, ?2, ?3)
             ON CONFLICT(tenant_id, project_id) DO UPDATE SET cursor=excluded.cursor",
            params![scope.tenant_id, scope.project_id, result.next_cursor],
        ).map_err(storage)?;
        tx.commit().map_err(storage)?;
        Ok(result)
    }
}

#[async_trait]
impl KnowledgePullRepository for SqliteKnowledgeRepository {
    async fn pull_cursor(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
    ) -> KnowledgeResult<u64> {
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        super::push::check_target(&tx, scope, target, true)?;
        let result = cursor(&tx, scope)?;
        tx.commit().map_err(storage)?;
        Ok(result)
    }

    async fn accept_pull_page(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        after: u64,
        response: Value,
    ) -> KnowledgeResult<KnowledgePullReceipt> {
        self.accept_pull_page_durable(scope, target, after, response)
    }

    async fn pull_conflicts(
        &self,
        scope: &KnowledgeScope,
        limit: usize,
    ) -> KnowledgeResult<Vec<Value>> {
        validate(scope, "pull conflicts")?;
        if !(1..=200).contains(&limit) {
            return Err(KnowledgeError::InvalidInput);
        }
        let conn = self.conn.lock().map_err(storage)?;
        let mut statement = conn
            .prepare(
                "SELECT pc.conflict_json FROM knowledge_sync_pull_conflicts pc
             WHERE pc.tenant_id=?1 AND pc.project_id=?2
               AND NOT EXISTS (SELECT 1 FROM knowledge_sync_resolved_pull_conflicts r
                 WHERE r.tenant_id=pc.tenant_id AND r.project_id=pc.project_id AND r.sequence=pc.sequence)
             ORDER BY pc.sequence LIMIT ?3",
            )
            .map_err(storage)?;
        let rows = statement
            .query_map(
                params![scope.tenant_id, scope.project_id, limit as i64],
                |row| row.get::<_, String>(0),
            )
            .map_err(storage)?;
        rows.map(|row| serde_json::from_str(&row.map_err(storage)?).map_err(storage))
            .collect()
    }
}
