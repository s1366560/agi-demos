use rusqlite::{params, OptionalExtension, Transaction, TransactionBehavior};

use super::*;

impl SqliteKnowledgeRepository {
    pub(super) fn mutate_durable(
        &self,
        scope: &KnowledgeScope,
        actor_id: &str,
        key: &str,
        mutation: MemoryMutation,
    ) -> KnowledgeResult<MemoryMutationOutcome> {
        validate(scope, actor_id)?;
        if key.trim().is_empty() {
            return Err(KnowledgeError::InvalidInput);
        }
        let request = serde_json::to_string(&mutation).map_err(storage)?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        let previous: Option<(String, String)> = tx.query_row(
            "SELECT request_json,receipt_json FROM knowledge_mutation_receipts WHERE tenant_id=?1 AND project_id=?2 AND actor_id=?3 AND idempotency_key=?4",
            params![scope.tenant_id,scope.project_id,actor_id,key],
            |row| Ok((row.get(0)?, row.get(1)?)),
        ).optional().map_err(storage)?;
        if let Some((original, receipt)) = previous {
            let original: serde_json::Value = serde_json::from_str(&original).map_err(storage)?;
            let requested: serde_json::Value = serde_json::from_str(&request).map_err(storage)?;
            if original != requested {
                return Err(KnowledgeError::IdempotencyConflict);
            }
            return Ok(MemoryMutationOutcome {
                receipt: serde_json::from_str(&receipt).map_err(storage)?,
                replayed: true,
            });
        }
        let receipt = apply(&tx, scope, mutation)?;
        tx.execute(
            "INSERT INTO knowledge_mutation_receipts(tenant_id,project_id,actor_id,idempotency_key,request_json,receipt_json) VALUES(?1,?2,?3,?4,?5,?6)",
            params![scope.tenant_id,scope.project_id,actor_id,key,request,serde_json::to_string(&receipt).map_err(storage)?],
        ).map_err(storage)?;
        tx.commit().map_err(storage)?;
        Ok(MemoryMutationOutcome {
            receipt,
            replayed: false,
        })
    }

    pub(super) fn apply_unkeyed(
        &self,
        scope: &KnowledgeScope,
        mutation: MemoryMutation,
    ) -> KnowledgeResult<MemoryChange> {
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(storage)?;
        let receipt = apply(&tx, scope, mutation)?;
        tx.commit().map_err(storage)?;
        Ok(receipt)
    }

    pub(super) fn read_changes(
        &self,
        scope: &KnowledgeScope,
        after_sequence: u64,
        limit: usize,
    ) -> KnowledgeResult<Vec<MemoryChange>> {
        validate(scope, "changes")?;
        let Ok(after) = i64::try_from(after_sequence) else {
            return Ok(Vec::new());
        };
        let conn = self.conn.lock().map_err(storage)?;
        let mut statement = conn.prepare(
            "SELECT sequence,payload,operation FROM knowledge_processing_changes WHERE tenant_id=?1 AND project_id=?2 AND sequence>?3 ORDER BY sequence ASC LIMIT ?4",
        ).map_err(storage)?;
        let rows = statement
            .query_map(
                params![
                    scope.tenant_id,
                    scope.project_id,
                    after,
                    i64::try_from(limit).unwrap_or(i64::MAX)
                ],
                |row| {
                    Ok((
                        row.get::<_, u64>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                    ))
                },
            )
            .map_err(storage)?;
        rows.map(|row| {
            let (sequence, json, operation) = row.map_err(storage)?;
            Ok(MemoryChange {
                sequence,
                memory: serde_json::from_str(&json).map_err(storage)?,
                deleted: operation == "delete",
            })
        })
        .collect()
    }
}

fn apply(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    mutation: MemoryMutation,
) -> KnowledgeResult<MemoryChange> {
    let (memory, deleted) = match mutation {
        MemoryMutation::Create { memory } => {
            validate_memory(scope, &memory, 1)?;
            let json = serde_json::to_string(&memory).map_err(storage)?;
            let inserted = tx.execute(
                "INSERT INTO knowledge_memories(tenant_id,project_id,id,revision,created_at_ms,payload) VALUES(?1,?2,?3,1,?4,?5) ON CONFLICT(tenant_id,project_id,id) DO NOTHING",
                params![scope.tenant_id,scope.project_id,memory.id,memory.created_at_ms,json],
            ).map_err(storage)?;
            if inserted == 0 {
                return Err(KnowledgeError::Conflict);
            }
            (memory, false)
        }
        MemoryMutation::Update {
            mut memory,
            expected_revision,
        } => {
            validate_memory(scope, &memory, expected_revision)?;
            memory.version = next_revision(expected_revision)?;
            let json = serde_json::to_string(&memory).map_err(storage)?;
            let updated = tx.execute(
                "UPDATE knowledge_memories SET revision=?4,payload=?5,created_at_ms=?7 WHERE tenant_id=?1 AND project_id=?2 AND id=?3 AND revision=?6 AND deleted=0",
                params![scope.tenant_id,scope.project_id,memory.id,memory.version,json,expected_revision,memory.created_at_ms],
            ).map_err(storage)?;
            if updated == 0 {
                return Err(if payload(tx, scope, &memory.id)?.is_some() {
                    KnowledgeError::Conflict
                } else {
                    KnowledgeError::NotFound
                });
            }
            (memory, false)
        }
        MemoryMutation::Delete {
            id,
            expected_revision,
        } => {
            validate(scope, &id)?;
            let revision = next_revision(expected_revision)?;
            let json = payload(tx, scope, &id)?.ok_or(KnowledgeError::NotFound)?;
            let mut memory: Memory = serde_json::from_str(&json).map_err(storage)?;
            if memory.version != expected_revision {
                return Err(KnowledgeError::Conflict);
            }
            memory.version = revision;
            tx.execute(
                "UPDATE knowledge_memories SET revision=?4,deleted=1,payload=?5 WHERE tenant_id=?1 AND project_id=?2 AND id=?3 AND revision=?6 AND deleted=0",
                params![scope.tenant_id,scope.project_id,id,revision,serde_json::to_string(&memory).map_err(storage)?,expected_revision],
            ).map_err(storage)?;
            (memory, true)
        }
    };
    tx.execute(
        "INSERT INTO knowledge_processing_changes(tenant_id,project_id,memory_id,revision,operation,payload) VALUES(?1,?2,?3,?4,?5,?6)",
        params![scope.tenant_id,scope.project_id,memory.id,memory.version,if deleted { "delete" } else { "upsert" },serde_json::to_string(&memory).map_err(storage)?],
    ).map_err(storage)?;
    let sequence = u64::try_from(tx.last_insert_rowid()).map_err(storage)?;
    Ok(MemoryChange {
        sequence,
        memory,
        deleted,
    })
}

fn next_revision(expected: u32) -> KnowledgeResult<u32> {
    expected
        .checked_add(1)
        .filter(|_| expected > 0)
        .ok_or(KnowledgeError::InvalidInput)
}
