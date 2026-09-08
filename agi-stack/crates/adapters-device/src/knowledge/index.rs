//! Durable per-build vector truth; source visibility comes from Applied audits.
use agistack_core::knowledge::index::*;
use rusqlite::{Transaction, TransactionBehavior};
use sha2::{Digest, Sha256};

use super::*;

mod builds;
pub(super) mod configuration;
use configuration::ensure_config;
mod diagnostics;
mod leases;
mod schema;
pub(super) use schema::migrate;

type Clock<'a> = &'a dyn Fn() -> KnowledgeResult<i64>;

fn timed<T>(
    repository: &SqliteKnowledgeRepository,
    clock: Clock<'_>,
    action: impl FnOnce(&Transaction<'_>, i64) -> KnowledgeResult<(T, Option<i64>)>,
) -> KnowledgeResult<T> {
    let mut connection = repository.conn.lock().map_err(storage)?;
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let started = clock()?;
    if started < 0 {
        return Err(KnowledgeError::InvalidInput);
    }
    let (result, deadline) = action(&tx, started)?;
    let finished = clock()?;
    if finished < started || deadline.is_some_and(|deadline| finished >= deadline) {
        return Err(KnowledgeError::Conflict);
    }
    tx.commit().map_err(storage)?;
    Ok(result)
}

fn validate_build(build: &IndexBuild) -> KnowledgeResult<()> {
    validate(&build.scope, &build.build_id)?;
    let p = &build.profile;
    if p.provider_id.trim().is_empty()
        || p.model_id.trim().is_empty()
        || p.input_contract_version != 1
        || p.normalization_version != 1
        || p.credential_binding_digest.len() != 64
        || !p
            .credential_binding_digest
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
    {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(())
}

fn ensure_build(tx: &Transaction<'_>, build: &IndexBuild) -> KnowledgeResult<()> {
    validate_build(build)?;
    let profile: Option<String> = tx.query_row(
        "SELECT profile_json FROM knowledge_index_builds WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3",
        params![build.scope.tenant_id,build.scope.project_id,build.build_id], |r|r.get(0),
    ).optional().map_err(storage)?;
    let stored: IndexProfile =
        serde_json::from_str(&profile.ok_or(KnowledgeError::Conflict)?).map_err(storage)?;
    if stored != build.profile {
        return Err(KnowledgeError::Conflict);
    }
    Ok(())
}

struct CurrentInput {
    identity: IndexSource,
    text: String,
}
fn current_inputs(tx: &Transaction<'_>, build: &IndexBuild) -> KnowledgeResult<Vec<CurrentInput>> {
    super::retrieval::audited_sources(tx, &build.scope)?
        .into_iter()
        .map(|(source, audit_attempt, memory)| {
            // Unambiguous input contract: exact ordered JSON tuple, preserving all
            // characters and field boundaries. Query adapter uses its own raw query.
            let text =
                serde_json::to_string(&(1u32, memory.title, memory.content)).map_err(storage)?;
            let input_digest = format!("{:x}", Sha256::digest(text.as_bytes()));
            Ok(CurrentInput {
                identity: IndexSource {
                    source,
                    audit_attempt,
                    input_digest,
                },
                text,
            })
        })
        .collect()
}
fn current_input(
    tx: &Transaction<'_>,
    build: &IndexBuild,
    input: &IndexSource,
) -> KnowledgeResult<CurrentInput> {
    current_inputs(tx, build)?
        .into_iter()
        .find(|current| current.identity == *input)
        .ok_or(KnowledgeError::Conflict)
}

fn reconcile(tx: &Transaction<'_>, build: &IndexBuild) -> KnowledgeResult<Vec<CurrentInput>> {
    let current = current_inputs(tx, build)?;
    for input in &current {
        let source = &input.identity.source;
        tx.execute("INSERT INTO knowledge_index_jobs(tenant_id,project_id,build_id,change_sequence,memory_id,revision,audit_attempt,input_digest,state)
            VALUES(?1,?2,?3,?4,?5,?6,?7,?8,'pending') ON CONFLICT DO NOTHING",
            params![build.scope.tenant_id,build.scope.project_id,build.build_id,source.change_sequence,source.memory_id,source.revision,input.identity.audit_attempt,input.identity.input_digest]).map_err(storage)?;
    }
    Ok(current)
}

fn job(
    tx: &Transaction<'_>,
    build: &IndexBuild,
    input: &IndexSource,
) -> KnowledgeResult<Option<IndexJobStatus>> {
    let row: Option<(String,u32,Option<String>)> = tx.query_row(
        "SELECT state,attempt,failure_json FROM knowledge_index_jobs
         WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND change_sequence=?4 AND audit_attempt=?5 AND input_digest=?6
           AND memory_id=?7 AND revision=?8",
        params![build.scope.tenant_id,build.scope.project_id,build.build_id,input.source.change_sequence,input.audit_attempt,input.input_digest,input.source.memory_id,input.source.revision],
        |r|Ok((r.get(0)?,r.get(1)?,r.get(2)?)),
    ).optional().map_err(storage)?;
    row.map(|(state, attempt, failure)| {
        Ok(IndexJobStatus {
            input: input.clone(),
            state: match state.as_str() {
                "pending" => IndexJobState::Pending,
                "leased" => IndexJobState::Leased,
                "completed" => IndexJobState::Completed,
                "failed" => IndexJobState::Failed,
                _ => return Err(KnowledgeError::Conflict),
            },
            attempt,
            failure: failure
                .map(|value| serde_json::from_str(&value).map_err(storage))
                .transpose()?,
        })
    })
    .transpose()
}

fn validate_vector(build: &IndexBuild, vector: &[f32]) -> KnowledgeResult<()> {
    if vector.len() != build.profile.dimensions.get() as usize
        || vector.iter().any(|value| !value.is_finite())
        || !vector.iter().any(|value| *value != 0.0)
    {
        return Err(KnowledgeError::InvalidInput);
    }
    Ok(())
}

fn vectors(
    tx: &Transaction<'_>,
    build: &IndexBuild,
    current: &[CurrentInput],
) -> KnowledgeResult<(IndexCoverage, Vec<IndexedVector>)> {
    let mut coverage = IndexCoverage {
        current_sources: current.len(),
        completed_sources: 0,
        failed_sources: 0,
    };
    let mut output = Vec::new();
    for input in current {
        let Some(status) = job(tx, build, &input.identity)? else {
            continue;
        };
        if status.state == IndexJobState::Failed {
            coverage.failed_sources += 1;
        }
        if status.state != IndexJobState::Completed {
            continue;
        }
        let payload:Option<String> = tx.query_row("SELECT vector_json FROM knowledge_index_vectors
            WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND change_sequence=?4 AND audit_attempt=?5 AND input_digest=?6 AND index_attempt=?7",
            params![build.scope.tenant_id,build.scope.project_id,build.build_id,input.identity.source.change_sequence,input.identity.audit_attempt,input.identity.input_digest,status.attempt],|r|r.get(0)).optional().map_err(storage)?;
        let Some(payload) = payload else { continue };
        let vector: Vec<f32> = serde_json::from_str(&payload).map_err(storage)?;
        validate_vector(build, &vector)?;
        coverage.completed_sources += 1;
        output.push(IndexedVector {
            input: input.identity.clone(),
            vector,
        });
    }
    Ok((coverage, output))
}

fn processing_coverage(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    applied_sources: usize,
) -> KnowledgeResult<ProcessingCoverage> {
    let current_sources: usize = tx.query_row(
        "SELECT count(*) FROM knowledge_memories WHERE tenant_id=?1 AND project_id=?2 AND deleted=0",
        params![scope.tenant_id,scope.project_id], |row|row.get(0),
    ).map_err(storage)?;
    let failed_sources: usize = tx.query_row(
        "SELECT count(*) FROM knowledge_memories m
         JOIN knowledge_processing_changes c ON c.tenant_id=m.tenant_id AND c.project_id=m.project_id
           AND c.memory_id=m.id AND c.revision=m.revision AND c.operation='upsert' AND c.payload=m.payload
         JOIN knowledge_processing_jobs j ON j.change_sequence=c.sequence AND j.tenant_id=m.tenant_id
           AND j.project_id=m.project_id AND j.memory_id=m.id AND j.revision=m.revision AND j.state='failed'
         WHERE m.tenant_id=?1 AND m.project_id=?2 AND m.deleted=0",
        params![scope.tenant_id,scope.project_id], |row|row.get(0),
    ).map_err(storage)?;
    let pending_sources = current_sources
        .checked_sub(applied_sources)
        .and_then(|count| count.checked_sub(failed_sources))
        .ok_or(KnowledgeError::Conflict)?;
    Ok(ProcessingCoverage {
        current_sources,
        applied_sources,
        pending_sources,
        failed_sources,
    })
}
