//! Read-only community foundation. No migration, jobs, model invocation, or
//! runtime entry point. Keep this query independent of live/keyset retrieval.

use agistack_core::knowledge::{
    community::*,
    processing::{
        audit::{ProcessingAuditOutcome, ProcessingInvocation},
        worker::SUBMIT_PROJECTION_TOOL,
        ProcessingProjection, ProcessingSource, ProcessingState,
    },
    KnowledgeMemory,
};
use rusqlite::{params, Transaction};
use serde::Serialize;
use sha2::{Digest, Sha256};

use super::*;

// LEFT joins retain every current source, including pending/failed/unprocessed
// sources. A completed legacy projection without an applied audit is excluded
// from the graph but remains visible as an uncovered source.
const SNAPSHOT_SQL: &str = "SELECT m.id,m.revision,c.sequence,m.payload,j.state,j.attempt,
 p.projection_json,a.invocation_json,a.outcome_json,a.started_at_ms,a.finished_at_ms,a.latency_ms
 FROM knowledge_memories m
 LEFT JOIN knowledge_processing_changes c ON c.tenant_id=m.tenant_id AND c.project_id=m.project_id
  AND c.memory_id=m.id AND c.revision=m.revision AND c.payload=m.payload AND c.operation='upsert'
 LEFT JOIN knowledge_processing_jobs j ON j.tenant_id=m.tenant_id AND j.project_id=m.project_id
  AND j.memory_id=m.id AND j.revision=m.revision AND j.change_sequence=c.sequence
 LEFT JOIN knowledge_derived_projections p ON p.tenant_id=m.tenant_id AND p.project_id=m.project_id
  AND p.memory_id=m.id AND p.revision=m.revision AND p.change_sequence=c.sequence AND j.state='completed'
 LEFT JOIN knowledge_processing_audits a ON a.tenant_id=j.tenant_id AND a.project_id=j.project_id
  AND a.memory_id=j.memory_id AND a.revision=j.revision AND a.change_sequence=j.change_sequence
  AND a.attempt=j.attempt AND a.finished_at_ms IS NOT NULL AND a.latency_ms IS NOT NULL
  AND json_extract(a.outcome_json,'$.status')='applied'
 WHERE m.tenant_id=?1 AND m.project_id=?2 AND m.deleted=0 ORDER BY m.id";

fn digest(domain: &str, value: &impl Serialize) -> KnowledgeResult<String> {
    // Explicitly canonicalize nested object keys even if feature unification
    // later enables serde_json/preserve_order. Array positions remain evidence.
    let mut value = serde_json::to_value(value).map_err(storage)?;
    value.sort_all_objects();
    let mut hash = Sha256::new();
    hash.update(domain.as_bytes());
    hash.update([0]);
    hash.update(serde_json::to_vec(&value).map_err(storage)?);
    Ok(format!("{:x}", hash.finalize()))
}

fn fingerprint(snapshot: &CommunitySnapshot) -> KnowledgeResult<String> {
    digest(
        "knowledge-community-snapshot-v1",
        &(
            &snapshot.tenant_id,
            &snapshot.project_id,
            &snapshot.algorithm_version,
            snapshot.min_community_size,
            &snapshot.sources,
        ),
    )
}

fn capture(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    min_community_size: usize,
) -> KnowledgeResult<CommunitySnapshot> {
    let mut statement = tx.prepare(SNAPSHOT_SQL).map_err(storage)?;
    let mut rows = statement
        .query(params![scope.tenant_id, scope.project_id])
        .map_err(storage)?;
    let mut sources = Vec::new();
    while let Some(row) = rows.next().map_err(storage)? {
        sources.push(decode(row, scope)?);
    }
    Ok(CommunitySnapshot {
        tenant_id: scope.tenant_id.clone(),
        project_id: scope.project_id.clone(),
        algorithm_version: COMMUNITY_ALGORITHM_VERSION.into(),
        min_community_size,
        sources,
        graph_digest: String::new(),
    })
}

fn decode(row: &rusqlite::Row<'_>, scope: &KnowledgeScope) -> KnowledgeResult<CommunitySource> {
    let source = ProcessingSource {
        tenant_id: scope.tenant_id.clone(),
        project_id: scope.project_id.clone(),
        memory_id: row.get(0).map_err(storage)?,
        revision: row.get(1).map_err(storage)?,
        change_sequence: row.get(2).map_err(storage)?,
    };
    let payload: serde_json::Value =
        serde_json::from_str(&row.get::<_, String>(3).map_err(storage)?).map_err(storage)?;
    let memory: KnowledgeMemory = serde_json::from_value(payload.clone()).map_err(storage)?;
    if memory.id != source.memory_id
        || memory.project_id != source.project_id
        || memory.version != source.revision
        || source.revision == 0
        || source.change_sequence == 0
    {
        return Err(KnowledgeError::Storage(
            "inconsistent community source".into(),
        ));
    }
    let state: Option<String> = row.get(4).map_err(storage)?;
    let processing_state: Option<ProcessingState> = state
        .map(|state| serde_json::from_value(serde_json::Value::String(state)))
        .transpose()
        .map_err(storage)?;
    let processing_attempt: Option<u32> = row.get(5).map_err(storage)?;
    let projection: Option<String> = row.get(6).map_err(storage)?;
    let invocation: Option<String> = row.get(7).map_err(storage)?;
    let outcome: Option<String> = row.get(8).map_err(storage)?;
    let audited_projection = match (projection, invocation, outcome) {
        (Some(projection), Some(invocation), Some(outcome)) => {
            let projection: ProcessingProjection =
                serde_json::from_str(&projection).map_err(storage)?;
            let invocation: ProcessingInvocation =
                serde_json::from_str(&invocation).map_err(storage)?;
            let outcome: ProcessingAuditOutcome =
                serde_json::from_str(&outcome).map_err(storage)?;
            let ProcessingAuditOutcome::Applied { submission } = &outcome else {
                return Err(KnowledgeError::Conflict);
            };
            let audit_attempt = processing_attempt.ok_or(KnowledgeError::Conflict)?;
            if !submission.validate(&source)
                || submission.projection() != projection
                || invocation.input.source != source
                || invocation.input.title != memory.title
                || invocation.input.content != memory.content
                || invocation.tool_name != SUBMIT_PROJECTION_TOOL
                || invocation.contract_version != 1
                || audit_attempt == 0
                || processing_state != Some(ProcessingState::Completed)
            {
                return Err(KnowledgeError::Storage(
                    "inconsistent community audit".into(),
                ));
            }
            Some(CommunityProjection {
                audit_attempt,
                audit_digest: digest(
                    "knowledge-community-audit-v1",
                    &(
                        &invocation,
                        &outcome,
                        audit_attempt,
                        row.get::<_, i64>(9).map_err(storage)?,
                        row.get::<_, i64>(10).map_err(storage)?,
                        row.get::<_, u64>(11).map_err(storage)?,
                    ),
                )?,
                projection,
            })
        }
        _ => None,
    };
    Ok(CommunitySource {
        source,
        payload,
        processing_state,
        processing_attempt,
        audited_projection,
    })
}

impl SqliteKnowledgeRepository {
    /// Captures sources and audited output together. Releases SQLite transaction
    /// and repository mutex before snapshot hashing, partitioning, or later agent work.
    pub fn community_snapshot_durable(
        &self,
        scope: &KnowledgeScope,
        min_community_size: usize,
    ) -> KnowledgeResult<CommunitySnapshot> {
        validate(scope, "community_snapshot")?;
        if min_community_size < 2 {
            return Err(KnowledgeError::InvalidInput);
        }
        let mut snapshot = {
            let mut conn = self.conn.lock().map_err(storage)?;
            let tx = conn.transaction().map_err(storage)?;
            let snapshot = capture(&tx, scope, min_community_size)?;
            tx.commit().map_err(storage)?;
            snapshot
        };
        snapshot.graph_digest = fingerprint(&snapshot)?;
        Ok(snapshot)
    }

    /// Pure computation after capture; does not claim live freshness or publish.
    pub fn community_candidates(
        snapshot: &CommunitySnapshot,
    ) -> KnowledgeResult<Vec<CommunityCandidate>> {
        if snapshot.graph_digest != fingerprint(snapshot)? {
            return Err(KnowledgeError::InvalidInput);
        }
        partition_snapshot(snapshot)?
            .into_iter()
            .map(|members| {
                Ok(CommunityCandidate {
                    membership_digest: digest("knowledge-community-membership-v1", &members)?,
                    members,
                })
            })
            .collect()
    }
}

#[async_trait]
impl CommunitySnapshotRepository for SqliteKnowledgeRepository {
    async fn community_snapshot(
        &self,
        scope: &KnowledgeScope,
        min_community_size: usize,
    ) -> KnowledgeResult<CommunitySnapshot> {
        self.community_snapshot_durable(scope, min_community_size)
    }
}

#[cfg(test)]
mod tests;
